from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from runtime.types import RuntimeStatus


class HarnessEventRefPayload(BaseModel):
    event_id: str
    event_name: str
    ts: datetime
    run_id: str | None = None


class HarnessStatusSnapshot(BaseModel):
    workspace_id: str
    chat_id: str | None
    chat_title: str | None
    workspace_health: Literal["ready", "busy", "degraded", "error"]
    active_mode: str
    run_id: str | None
    run_state: str
    runtime_status: RuntimeStatus
    execution_tasks: dict[str, int] = Field(default_factory=dict)
    approval_state: Literal["idle", "awaiting_user", "resolved"] | None
    clarification_state: Literal["idle", "awaiting_user", "resolved"] | None
    chat_turn_count: int
    chat_token_estimate: int
    last_compacted_at: datetime | None
    compaction_count: int
    doctor_warning_count: int
    last_event: HarnessEventRefPayload | None = None


_CLOSE: object = object()


class _ContextlibSuppress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return True


contextlib_suppress = _ContextlibSuppress


class StatusBroker:
    def __init__(
        self,
        initial: HarnessStatusSnapshot,
        *,
        heartbeat_seconds: float = 2.0,
        coalesce_seconds: float = 0.05,
    ) -> None:
        self._latest = initial
        self._heartbeat = heartbeat_seconds
        self._coalesce = coalesce_seconds
        self._subscribers: list[asyncio.Queue] = []
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def snapshot(self) -> HarnessStatusSnapshot:
        return self._latest

    def publish(self, snapshot: HarnessStatusSnapshot) -> None:
        if snapshot == self._latest:
            return
        self._latest = snapshot
        for q in self._subscribers:
            with _ContextlibSuppress():
                q.put_nowait(snapshot)

    async def close(self) -> None:
        self._closed = True
        for q in self._subscribers:
            with _ContextlibSuppress():
                q.put_nowait(_CLOSE)

    async def watch(self) -> AsyncIterator[HarnessStatusSnapshot]:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers.append(q)
        last_yielded = self._latest
        # Initial snapshot
        yield last_yielded
        try:
            while not self._closed:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=self._heartbeat)
                except asyncio.TimeoutError:
                    yield self._latest  # heartbeat
                    continue
                if item is _CLOSE:
                    return
                # Coalesce burst
                await asyncio.sleep(self._coalesce)
                while not q.empty():
                    item = q.get_nowait()
                    if item is _CLOSE:
                        return
                if self._latest != last_yielded:
                    last_yielded = self._latest
                    yield last_yielded
        finally:
            async with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)
