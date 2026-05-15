"""Manages the lifecycle of the three LT processes (trust / observe / lockdown).

DESIGN.md §11.5 (revised) — all three LT instances stay up for the entire
demo. Sentinel never reloads LT; it only swaps which port traffic goes to.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from .config import SentinelConfig, TierBinding


@dataclass
class LTInstance:
    tier: str
    process: asyncio.subprocess.Process
    binding: TierBinding


@dataclass
class LTSupervisor:
    config: SentinelConfig
    instances: list[LTInstance] = field(default_factory=list)

    async def start_all(self) -> None:
        """Launch one LT process per tier; wait until each is listening."""
        # Best-effort cleanup of any orphaned LT processes from a previous
        # Sentinel run that was force-killed without graceful shutdown
        # (Windows asyncio.subprocess can't easily inherit a job object).
        self._kill_stale_lt_processes()

        for tier, binding in self.config.tier_bindings.items():
            # Clear any stale audit log so demo runs start clean.
            if binding.audit_log_path.exists():
                binding.audit_log_path.unlink()
            binding.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

            cmd = [
                str((self.config.project_root / self.config.lt_binary).resolve()),
                "serve",
                "--policy",
                str(binding.policy_yaml.resolve()),
                "--listen",
                f":{binding.listen_port}",
                "--backend",
                self.config.backend_url,
                "--audit-log",
                str(binding.audit_log_path.resolve()),
                "--no-dashboard",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.config.project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self.instances.append(LTInstance(tier=tier, process=proc, binding=binding))

        await self._wait_until_listening()

    async def _wait_until_listening(self, timeout: float = 15.0) -> None:
        """Poll each LT's listen port until it accepts a TCP connection."""
        deadline = asyncio.get_event_loop().time() + timeout
        for inst in self.instances:
            while True:
                if asyncio.get_event_loop().time() > deadline:
                    raise RuntimeError(
                        f"LT instance for tier '{inst.tier}' did not come up on port "
                        f"{inst.binding.listen_port} within {timeout}s"
                    )
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection("127.0.0.1", inst.binding.listen_port),
                        timeout=0.5,
                    )
                    writer.close()
                    with suppress(Exception):
                        await writer.wait_closed()
                    break
                except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
                    if inst.process.returncode is not None:
                        # Process died before listening — collect stderr for diagnosis.
                        stderr = b""
                        if inst.process.stderr is not None:
                            with suppress(Exception):
                                stderr = await inst.process.stderr.read()
                        raise RuntimeError(
                            f"LT instance for tier '{inst.tier}' exited early "
                            f"(code={inst.process.returncode}): {stderr.decode(errors='replace')}"
                        )
                    await asyncio.sleep(0.2)

    async def stop_all(self) -> None:
        for inst in self.instances:
            if inst.process.returncode is None:
                # On Windows, terminate sends CTRL_BREAK; on POSIX it sends SIGTERM.
                with suppress(ProcessLookupError):
                    inst.process.terminate()
        for inst in self.instances:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(inst.process.wait(), timeout=5.0)
            if inst.process.returncode is None:
                with suppress(ProcessLookupError):
                    inst.process.kill()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(inst.process.wait(), timeout=3.0)
        self.instances.clear()

    def port_for(self, tier: str) -> int:
        for inst in self.instances:
            if inst.tier == tier:
                return inst.binding.listen_port
        raise KeyError(f"No LT instance for tier '{tier}'")

    def _kill_stale_lt_processes(self) -> None:
        """Kill any lobstertrap processes that survived a force-kill of an
        earlier Sentinel parent. Best-effort; failure is non-fatal.
        """
        if sys.platform != "win32":
            return
        import subprocess as _subp  # local import; only needed for cleanup

        with suppress(Exception):
            _subp.run(
                ["taskkill", "/F", "/IM", "lobstertrap.exe"],
                stdout=_subp.DEVNULL,
                stderr=_subp.DEVNULL,
                creationflags=getattr(_subp, "CREATE_NO_WINDOW", 0),
                check=False,
            )
