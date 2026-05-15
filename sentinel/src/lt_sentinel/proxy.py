"""Tier-aware HTTP reverse proxy in front of the 3 LT instances.

Listens on `sentinel_listen` (e.g. 127.0.0.1:8080). For every incoming request:

    upstream_port = current_tier_port  ← atomic read
    forward request to http://127.0.0.1:upstream_port

Tier change is an in-memory pointer swap. In-flight requests finish against
the old tier's LT (which is still up); new requests instantly go to the new
tier. Zero downtime, no LT process restart, no LT source change.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)


class TierAwareProxy:
    """Routes requests to whichever LT instance the current tier points to."""

    # Hop-by-hop headers per RFC 7230 §6.1 — must not be forwarded.
    HOP_BY_HOP = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }

    def __init__(
        self,
        *,
        listen_host: str,
        listen_port: int,
        get_upstream_port: Callable[[], int],
        on_request: Callable[[str, dict, web.Request], Awaitable[None]] | None = None,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self._get_upstream_port = get_upstream_port
        self._on_request = on_request
        self._session: aiohttp.ClientSession | None = None
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=180),
            auto_decompress=False,
        )

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host=self.listen_host, port=self.listen_port)
        await site.start()
        logger.info("Sentinel proxy listening on %s:%d", self.listen_host, self.listen_port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        assert self._session is not None, "Proxy not started"
        upstream_port = self._get_upstream_port()
        target_url = f"http://127.0.0.1:{upstream_port}{request.rel_url}"

        # Filter hop-by-hop headers.
        fwd_headers = {
            k: v for k, v in request.headers.items() if k.lower() not in self.HOP_BY_HOP
        }
        # Preserve Host of the upstream LT so its router doesn't reject us.
        fwd_headers["Host"] = f"127.0.0.1:{upstream_port}"

        body = await request.read()

        try:
            async with self._session.request(
                method=request.method,
                url=target_url,
                headers=fwd_headers,
                data=body,
                allow_redirects=False,
            ) as upstream:
                resp_body = await upstream.read()
                resp_headers = {
                    k: v
                    for k, v in upstream.headers.items()
                    if k.lower() not in self.HOP_BY_HOP and k.lower() != "content-length"
                }
                response = web.Response(
                    status=upstream.status,
                    headers=resp_headers,
                    body=resp_body,
                )
        except aiohttp.ClientError as exc:
            logger.warning("upstream error against :%d — %s", upstream_port, exc)
            return web.json_response(
                {"error": f"sentinel upstream error: {exc}"},
                status=502,
            )

        if self._on_request is not None:
            try:
                await self._on_request(target_url, dict(fwd_headers), request)
            except Exception:
                logger.exception("on_request hook raised")

        return response
