import asyncio
from datetime import UTC, datetime
from pathlib import Path

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


class EchoRuntime:
    async def status(self): return "ready"
    async def stream(self, request):
        from runtime.types import RuntimeEvent
        yield RuntimeEvent(
            type="text_delta", request_id=request.request_id, seq=0,
            text="assistant: copied transcript fragment",
        )
        yield RuntimeEvent(type="finish", request_id=request.request_id, seq=1, finish_reason="stop", usage={})


class CapturingRuntime:
    def __init__(self): self.requests = []
    async def status(self): return "ready"
    async def stream(self, request):
        self.requests.append(request)
        from runtime.types import RuntimeEvent
        yield RuntimeEvent(
            type="text_delta", request_id=request.request_id, seq=0,
            text=(
                "Summary of compacted chat:\n"
                "- Current user goal: continue the analysis.\n"
                "- Progress and facts: no durable facts yet.\n"
                "- Next steps: answer the latest user request."
            ),
        )
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


async def test_compactor_with_zero_recent_keeps_only_summary(store):
    s = await store.create_chat(workspace_id="w", title=None)
    for i in range(5):
        await store.append_message(s.chat_id, ChatMessage(
            message_id=f"m{i}", role="user" if i % 2 == 0 else "assistant", text=f"turn-{i}",
            ts=datetime.now(UTC), turn_id=None, active_mode=None, token_estimate=3,
        ))
    compactor = ChatCompactor(store=store, runtime=None, recent_turns_kept=0)

    async for _ in compactor.compact(s.chat_id, reason="user"):
        pass

    rec = await store.view_chat(s.chat_id)
    assert [m.role for m in rec.messages] == ["compacted_summary"]


async def test_compactor_replaces_transcript_echo_with_fallback_summary(store):
    s = await store.create_chat(workspace_id="w", title=None)
    await store.append_message(s.chat_id, ChatMessage(
        message_id="m0", role="assistant", text="raw assistant text",
        ts=datetime.now(UTC), turn_id=None, active_mode=None, token_estimate=3,
    ))
    compactor = ChatCompactor(store=store, runtime=EchoRuntime(), recent_turns_kept=0)

    async for _ in compactor.compact(s.chat_id, reason="user"):
        pass

    rec = await store.view_chat(s.chat_id)
    assert rec.messages[0].role == "compacted_summary"
    assert rec.messages[0].text.startswith("Summary of compacted chat:")
    assert not rec.messages[0].text.startswith("assistant:")


async def test_fallback_summary_is_dataharness_handoff_not_transcript_digest(store):
    s = await store.create_chat(workspace_id="w", title=None)
    rows = [
        ("compacted_summary", "assistant: Based on previous steps, the amount column matters."),
        ("user", "?"),
        ("user", "hello"),
        ("assistant", "Hello. I am DataHarness, an application for data analysis within this workspace."),
        ("user", "what is the relationship between my csv files"),
        (
            "assistant",
            "I inspected the schemas. data/customers.csv has customer_id, name, region, "
            "signup_date, plan. data/sales.csv has date, region, product, amount.",
        ),
        ("user", "and?"),
    ]
    for i, (role, text) in enumerate(rows):
        await store.append_message(s.chat_id, ChatMessage(
            message_id=f"m{i}", role=role, text=text,
            ts=datetime.now(UTC), turn_id=None, active_mode=None, token_estimate=3,
        ))
    compactor = ChatCompactor(store=store, runtime=None, recent_turns_kept=0)

    async for _ in compactor.compact(s.chat_id, reason="user"):
        pass

    rec = await store.view_chat(s.chat_id)
    summary = rec.messages[0].text
    assert summary.startswith("Summary of compacted chat:")
    assert "- Current user goal:" in summary
    assert "- Progress and facts:" in summary
    assert "- Data/workspace references:" in summary
    assert "- Next steps:" in summary
    assert "what is the relationship between my csv files" in summary
    assert "data/customers.csv" in summary
    assert "data/sales.csv" in summary
    assert "assistant:" not in summary
    assert "Prior summary context" not in summary
    assert "hello" not in summary.lower()
    assert "included:" not in summary


async def test_runtime_compaction_prompt_comes_from_harness_prompt_file(store):
    s = await store.create_chat(workspace_id="w", title=None)
    await store.append_message(s.chat_id, ChatMessage(
        message_id="m0", role="user", text="summarize data/sales.csv",
        ts=datetime.now(UTC), turn_id=None, active_mode=None, token_estimate=3,
    ))
    runtime = CapturingRuntime()
    compactor = ChatCompactor(store=store, runtime=runtime, recent_turns_kept=0)

    async for _ in compactor.compact(s.chat_id, reason="user"):
        pass

    system_prompt = runtime.requests[0].messages[0].content
    prompt_file = Path("src/harness/prompts/compaction.md").read_text().strip()
    assert system_prompt == prompt_file
    assert "DataHarness" in system_prompt
    assert "local-first data-analysis TUI" in system_prompt
    assert "Do not copy transcript lines" in system_prompt
    assert "Ignore greetings, test messages" in system_prompt
    assert "file paths, schemas, columns" in system_prompt
    assert "Summary of compacted chat:" in system_prompt


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
