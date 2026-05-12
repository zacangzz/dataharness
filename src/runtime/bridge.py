from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Iterator

from runtime.types import RuntimeEvent


_SENTINEL: object = object()


class SyncToAsyncBridge:
    """Bridges a blocking sync iterator of RuntimeEvent into an async iterator.

    Usage:
        bridge = SyncToAsyncBridge(lambda: llama_iterator, queue_size=64)
        async for event in bridge.stream():
            ...
        bridge.cancel()  # observed between deltas; one-token max latency
    """

    def __init__(
        self,
        iterator_factory: Callable[[], Iterator[RuntimeEvent]],
        *,
        queue_size: int = 64,
    ) -> None:
        self._factory = iterator_factory
        self._queue_size = queue_size
        self._cancel = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[object] | None = None
        self._thread: threading.Thread | None = None
        self._started = False

    def cancel(self) -> None:
        self._cancel.set()

    async def stream(self) -> AsyncIterator[RuntimeEvent]:
        if self._started:
            raise RuntimeError("bridge already consumed")
        self._started = True
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._queue_size)
        self._thread = threading.Thread(target=self._produce, name="runtime-bridge", daemon=True)
        self._thread.start()
        try:
            while True:
                item = await self._queue.get()
                if item is _SENTINEL:
                    return
                if isinstance(item, RuntimeEvent):
                    yield item
                    if item.type == "error" and item.finish_reason == "cancelled":
                        return
        finally:
            self._cancel.set()
            if self._thread is not None:
                self._thread.join(timeout=5.0)

    def _put(self, item: object) -> None:
        assert self._loop is not None
        assert self._queue is not None
        fut = asyncio.run_coroutine_threadsafe(self._queue.put(item), self._loop)
        while True:
            try:
                fut.result(timeout=0.1)
                return
            except TimeoutError:
                if self._cancel.is_set():
                    fut.cancel()
                    return

    def _produce(self) -> None:
        try:
            iterator = self._factory()
            for event in iterator:
                if self._cancel.is_set():
                    self._put(RuntimeEvent(
                        type="error",
                        request_id=event.request_id,
                        seq=event.seq,
                        finish_reason="cancelled",
                        error_code="cancelled",
                        error_message="cancelled by consumer",
                    ))
                    return
                self._put(event)
        except Exception as exc:  # noqa: BLE001
            self._put(RuntimeEvent(
                type="error",
                request_id="unknown",
                seq=-1,
                error_code="runtime_exception",
                error_message=f"{type(exc).__name__}: {exc}",
            ))
        finally:
            self._put(_SENTINEL)
