import asyncio
from datetime import UTC, datetime

import pytest

from harness.chat import (
    ChatCompactor, ChatMessage, ChatRecord, ChatStore,
)


class FakeRuntime:
    def __init__(self): self.calls = 0
    async def status(self): return "ready"
    async def stream(self, request):
        self.calls += 1
        from runtime.types import RuntimeEvent
        yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0, text="SUMMARY: short")
        yield RuntimeEvent(type="finish", request_id=request.request_id, seq=1, finish_reason="stop", usage={})


@pytest.fixture
def store(tmp_path): return ChatStore(app_root=tmp_path)


async def test_compactor_writes_summary_marker(store):
    s = await store.create_chat(workspace_id="w", title=None)
    for i in range(20):
        await store.append_message(s.chat_id, ChatMessage(
            message_id=f"m{i}", role="user" if i%2==0 else "assistant", text=f"turn-{i}",
            ts=datetime.now(UTC), turn_id=None, active_mode=None, token_estimate=3,
        ))
    runtime = FakeRuntime()
    compactor = ChatCompactor(store=store, runtime=runtime, recent_turns_kept=8)
    statuses = []
    async for status in compactor.compact(s.chat_id, reason="user"):
        statuses.append(status)
    assert statuses[0] == "queued"
    assert statuses[-1] == "completed"
    rec = await store.view_chat(s.chat_id)
    assert any(m.role == "compacted_summary" for m in rec.messages)


async def test_compactor_serializes_with_runtime_lock(store):
    """Compaction must wait for runtime lock if a stream is active."""
    s = await store.create_chat(workspace_id="w", title=None)
    await store.append_message(s.chat_id, ChatMessage(
        message_id="m", role="user", text="hi", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    runtime = FakeRuntime()
    lock = asyncio.Lock()
    compactor = ChatCompactor(store=store, runtime=runtime, runtime_lock=lock, recent_turns_kept=8)
    await lock.acquire()
    seen_running = asyncio.Event()

    async def consume():
        async for st in compactor.compact(s.chat_id, reason="user"):
            if st == "running":
                seen_running.set()
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    assert not seen_running.is_set()
    lock.release()
    await asyncio.wait_for(task, timeout=2.0)
    assert seen_running.is_set()
