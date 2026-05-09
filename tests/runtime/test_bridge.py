import asyncio
import time

import pytest

from runtime.bridge import SyncToAsyncBridge
from runtime.types import RuntimeEvent


def make_iter(items):
    def gen():
        for it in items:
            yield it
    return gen


async def collect(bridge):
    out = []
    async for ev in bridge.stream():
        out.append(ev)
    return out


async def test_drains_iterator_in_order():
    items = [
        RuntimeEvent(type="text_delta", request_id="r", seq=0, text="a"),
        RuntimeEvent(type="text_delta", request_id="r", seq=1, text="b"),
        RuntimeEvent(type="finish", request_id="r", seq=2, finish_reason="stop", usage={}),
    ]
    bridge = SyncToAsyncBridge(make_iter(items), queue_size=4)
    out = await collect(bridge)
    assert [e.type for e in out] == ["text_delta", "text_delta", "finish"]


async def test_backpressure_blocks_producer_when_consumer_slow():
    produced = []

    def gen():
        for i in range(8):
            produced.append(i)
            yield RuntimeEvent(type="text_delta", request_id="r", seq=i, text=str(i))
        yield RuntimeEvent(type="finish", request_id="r", seq=8, finish_reason="stop", usage={})

    bridge = SyncToAsyncBridge(lambda: gen(), queue_size=2)
    agen = bridge.stream()
    first = await agen.__anext__()
    assert first.text == "0"
    await asyncio.sleep(0.05)
    # Producer should have been blocked at ~queue_size + 1 items.
    assert len(produced) <= 4
    rest = []
    async for ev in agen:
        rest.append(ev)
    assert rest[-1].type == "finish"


async def test_cancel_between_deltas_emits_cancelled_error():
    def slow_gen():
        for i in range(100):
            time.sleep(0.005)
            yield RuntimeEvent(type="text_delta", request_id="r", seq=i, text="x")
        yield RuntimeEvent(type="finish", request_id="r", seq=100, finish_reason="stop", usage={})

    bridge = SyncToAsyncBridge(slow_gen, queue_size=4)
    agen = bridge.stream()
    seen = 0
    async for ev in agen:
        seen += 1
        if seen == 3:
            bridge.cancel()
        if ev.type == "error":
            assert ev.finish_reason == "cancelled"
            break
    assert seen >= 3


async def test_cancel_while_producer_blocked_does_not_deadlock():
    """Producer blocked on full queue + consumer cancels → bridge exits cleanly within ~1s."""

    def slow_gen():
        for i in range(100):
            time.sleep(0.01)
            yield RuntimeEvent(type="text_delta", request_id="r", seq=i, text=str(i))
        yield RuntimeEvent(type="finish", request_id="r", seq=100, finish_reason="stop", usage={})

    bridge = SyncToAsyncBridge(slow_gen, queue_size=1)
    agen = bridge.stream()
    # Consume one item then cancel
    first = await agen.__anext__()
    assert first.type == "text_delta"
    bridge.cancel()
    # Drain remaining items until the generator closes
    try:
        async for _ in agen:
            pass
    except StopAsyncIteration:
        pass
    # Thread should exit within 1s (poll interval is 0.1s)
    assert bridge._thread is not None
    bridge._thread.join(timeout=2.0)
    assert not bridge._thread.is_alive(), "producer thread still alive — deadlock detected"


async def test_iterator_exception_surfaces_as_error_event():
    def bad():
        yield RuntimeEvent(type="text_delta", request_id="r", seq=0, text="a")
        raise RuntimeError("boom")

    bridge = SyncToAsyncBridge(bad, queue_size=4)
    out = await collect(bridge)
    assert out[-1].type == "error"
    assert out[-1].error_code == "runtime_exception"
    assert "boom" in (out[-1].error_message or "")
