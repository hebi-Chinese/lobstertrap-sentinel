"""Async multi-file JSONL tailer for LT audit logs.

Each LT instance writes its own append-only audit log; Sentinel reads all of
them concurrently and yields entries in arrival order (per file).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


@dataclass
class AuditRecord:
    source: str  # tier name e.g. "trust" / "observe" / "lockdown"
    raw: dict


class _SingleFileTail:
    """Polls a single file for newly-appended JSONL lines."""

    def __init__(self, path: Path, source: str, poll_interval: float = 0.10) -> None:
        self.path = path
        self.source = source
        self.poll_interval = poll_interval
        self._pos = 0

    async def run(self, sink: asyncio.Queue[AuditRecord]) -> None:
        # Wait until the file exists (LT may not have written its first line yet).
        while not self.path.exists():
            await asyncio.sleep(self.poll_interval)

        # Start at end of file so we only see new entries, not the historical tail.
        self._pos = self.path.stat().st_size

        buffer = ""
        while True:
            try:
                size = self.path.stat().st_size
            except FileNotFoundError:
                await asyncio.sleep(self.poll_interval)
                continue

            if size < self._pos:
                # File was truncated/rotated — restart from start.
                self._pos = 0
                buffer = ""

            if size > self._pos:
                with self.path.open("rb") as fh:
                    fh.seek(self._pos)
                    chunk = fh.read(size - self._pos).decode("utf-8", errors="replace")
                    self._pos = fh.tell()
                buffer += chunk
                lines = buffer.split("\n")
                # Keep last (possibly partial) line in buffer.
                buffer = lines.pop()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    await sink.put(AuditRecord(source=self.source, raw=rec))

            await asyncio.sleep(self.poll_interval)


class MultiFileTail:
    """Tail several files concurrently into a single async queue."""

    def __init__(self, files: dict[str, Path], poll_interval: float = 0.10) -> None:
        self.files = files
        self.poll_interval = poll_interval

    async def stream(self) -> AsyncIterator[AuditRecord]:
        queue: asyncio.Queue[AuditRecord] = asyncio.Queue()
        tasks: list[asyncio.Task] = []
        for tier, path in self.files.items():
            # Ensure parent exists so tailer's wait-for-file loop doesn't hang.
            path.parent.mkdir(parents=True, exist_ok=True)
            tailer = _SingleFileTail(path=path, source=tier, poll_interval=self.poll_interval)
            tasks.append(asyncio.create_task(tailer.run(queue), name=f"tail-{tier}"))

        try:
            while True:
                rec = await queue.get()
                yield rec
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
