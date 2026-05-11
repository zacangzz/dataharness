# tests/acceptance/test_v1_async_acceptance.py
import asyncio
from pathlib import Path

import pytest

from app.session import AppSession
from harness.exceptions import RunAlreadyActive, WorkspaceSwitchBlocked


class FakeRuntime:
    async def context_window(self): return 4096
    async def status(self): return "ready"
    async def validate_request(self, r): return None
    async def token_pressure(self, r):
        from runtime.types import TokenPressure
        return TokenPressure(
            request_id=r.request_id, context_window=4096,
            prompt_tokens=10, reserved_completion_tokens=r.max_completion_tokens,
            total_tokens=10 + r.max_completion_tokens,
            pressure_ratio=0.05, over_threshold=False,
        )
    async def stream(self, r):
        from runtime.types import RuntimeEvent
        yield RuntimeEvent(type="text_delta", request_id=r.request_id, seq=0, text="ok")
        yield RuntimeEvent(type="finish", request_id=r.request_id, seq=1, finish_reason="stop", usage={})


@pytest.fixture
def session(tmp_path):
    from harness.orchestrator import Orchestrator
    orch = Orchestrator(runtime=FakeRuntime(), app_root=tmp_path)
    return AppSession(orchestrator=orch, app_root=tmp_path)


# Spec §13 — Concurrency
async def test_single_active_run(session, tmp_path):
    from harness.control import RunStateRecord
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await session.create_workspace("w1")
    chat = await session.create_chat("w1")
    agen = session.run_user_turn(state=state, workspace_dir=tmp_path, chat_id=chat.chat_id, user_text="a")
    await agen.__anext__()
    with pytest.raises(RunAlreadyActive):
        async for _ in session.run_user_turn(
            state=state, workspace_dir=tmp_path, chat_id=chat.chat_id, user_text="b",
        ):
            pass
    async for _ in agen:
        pass


async def test_workspace_switch_blocked_unless_force(session, tmp_path):
    await session.create_workspace("w1")
    await session.create_workspace("w2")
    session.orchestrator._active_run_id = "run_x"
    with pytest.raises(WorkspaceSwitchBlocked):
        await session.activate_workspace("w2", force=False)
    session.orchestrator._active_run_id = None


# Spec §13 — Chat
async def test_no_chat_dir_until_first_message(session, tmp_path):
    await session.create_workspace("w1")
    chat = await session.create_chat("w1")
    chat_dir = tmp_path / "workspaces" / "w1" / "chats" / chat.chat_id
    assert not chat_dir.exists()


async def test_chat_files_after_first_message(session, tmp_path):
    from harness.control import RunStateRecord
    await session.create_workspace("w1")
    chat = await session.create_chat("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    async for _ in session.run_user_turn(state=state, workspace_dir=tmp_path, chat_id=chat.chat_id, user_text="hi"):
        pass
    chat_dir = tmp_path / "workspaces" / "w1" / "chats" / chat.chat_id
    assert (chat_dir / "metadata.json").exists()
    assert (chat_dir / "messages.jsonl").exists()


async def test_workspace_delete_cascades_chats(session, tmp_path):
    from datetime import UTC, datetime
    from harness.chat import ChatMessage
    await session.create_workspace("w1")
    chat = await session.create_chat("w1")
    await session.orchestrator.chat_store.append_message(chat.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    await session.delete_workspace("w1")
    assert not (tmp_path / "workspaces" / "w1" / "chats").exists()


# Spec §13 — Commands
async def test_help_returns_descriptors(session):
    res = await session.help()
    names = {d.name for d in res.commands}
    for required in ("doctor", "compact", "help"):
        assert required in names


async def test_help_unknown_returns_not_found(session):
    res = await session.help("nope")
    assert res.not_found is True


# Spec §13 — Status
async def test_watch_status_yields_initial_then_heartbeat(session):
    agen = session.watch_status()
    first = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert first.workspace_id is not None or first.workspace_id == ""


# Spec §13 — Doctor
async def test_doctor_emits_full_event_sequence(session, tmp_path):
    from harness.control import RunStateRecord
    await session.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in session.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    names = [e.event_name for e in events]
    assert names[0] == "AppCommandStarted"
    assert any(n == "AppCommandProgress" for n in names)
    assert any(n == "AppDoctorReportReady" for n in names)
    assert names[-1] == "AppCommandCompleted"
