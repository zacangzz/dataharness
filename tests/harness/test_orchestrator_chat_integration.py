import pytest

from harness.events import ChatHistoryLoaded, ChatHistoryCompacted
from harness.exceptions import ChatNotFound
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord


class FakeRuntime:
    async def context_window(self): return 4096
    async def status(self): return "ready"
    async def validate_request(self, r): return None
    async def token_pressure(self, r):
        from runtime.types import TokenPressure
        return TokenPressure(
            request_id=r.request_id, context_window=4096,
            prompt_tokens=10, reserved_completion_tokens=r.max_completion_tokens,
            total_tokens=10 + r.max_completion_tokens, pressure_ratio=0.05, over_threshold=False,
        )
    async def stream(self, r):
        from runtime.types import RuntimeEvent
        yield RuntimeEvent(type="text_delta", request_id=r.request_id, seq=0, text="ack")
        yield RuntimeEvent(type="finish", request_id=r.request_id, seq=1, finish_reason="stop", usage={})


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=FakeRuntime(), app_root=tmp_path)


def make_state():
    return RunStateRecord(workspace_id="w1", active_agent_mode="interaction")


async def collect(agen):
    return [e async for e in agen]


async def test_first_user_message_lazy_creates_chat(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    chat_dir = tmp_path / "chats" / "w1" / summary.chat_id
    assert not chat_dir.exists()
    await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input="hi",
    ))
    assert chat_dir.exists()


async def test_run_turn_emits_chat_history_loaded_for_new_chat(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    events = await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input="hi",
    ))
    chl = next(e for e in events if e.event_name == "ChatHistoryLoaded")
    assert chl.source == "new"
    assert chl.message_count == 0


async def test_resume_chat_emits_chat_history_loaded_resumed(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input="first",
    ))
    events = await collect(orch.resume_chat(summary.chat_id))
    chl = next(e for e in events if e.event_name == "ChatHistoryLoaded")
    assert chl.source == "resumed"
    assert chl.message_count >= 2  # user + assistant


async def test_chat_history_persisted_across_runs(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    await collect(orch.run_turn(state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input="first"))
    rec = await orch.view_chat(summary.chat_id)
    assert [m.role for m in rec.messages] == ["user", "assistant"]


async def test_compact_emits_chat_history_compacted_status(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    for i in range(20):
        await collect(orch.run_turn(state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input=f"msg-{i}"))
    events = await collect(orch.compact_chat_history(summary.chat_id))
    statuses = [e.status for e in events if e.event_name == "ChatHistoryCompacted"]
    assert statuses[0] == "queued"
    assert statuses[-1] == "completed"


async def test_view_chat_unknown_raises(orch):
    with pytest.raises(ChatNotFound):
        await orch.view_chat("missing")
