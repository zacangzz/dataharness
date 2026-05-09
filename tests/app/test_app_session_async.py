from collections.abc import AsyncIterator

import pytest

from app.session import AppSession
from harness.events import FinalMessage, TurnStarted
from harness.exceptions import RunAlreadyActive
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord


class FakeOrchestrator:
    def __init__(self):
        self.run_calls = 0
        self._active = False

    async def run_turn(self, state, *, workspace_dir, chat_id, user_input, requested_mode=None, prompt_text=None):
        if self._active:
            raise RunAlreadyActive(run_id="x")
        self._active = True
        try:
            from datetime import UTC, datetime
            yield TurnStarted(
                ts=datetime.now(UTC), workspace_id="w", chat_id=chat_id, run_id="r",
                turn_id="t", user_message_id="u", active_mode=requested_mode or "interaction",
            )
            yield FinalMessage(
                ts=datetime.now(UTC), workspace_id="w", chat_id=chat_id, run_id="r",
                assistant_message_id="a", text="hello", usage={},
            )
        finally:
            self._active = False

    async def list_commands(self, ctx=None): return []
    async def help(self, command=None):
        from harness.command_registry import HelpResult
        return HelpResult(commands=[], not_found=False)
    async def status_snapshot(self, **kw):
        from harness.status import HarnessStatusSnapshot
        return HarnessStatusSnapshot(
            workspace_id="w", chat_id=None, chat_title=None, workspace_health="ready",
            active_mode="interaction", run_id=None, run_state="idle", runtime_status="ready",
            execution_tasks={}, approval_state="idle", clarification_state="idle",
            chat_turn_count=0, chat_token_estimate=0, last_compacted_at=None,
            compaction_count=0, doctor_warning_count=0, last_event=None,
        )


@pytest.fixture
def session(tmp_path):
    return AppSession(orchestrator=FakeOrchestrator(), app_root=tmp_path)


def make_state():
    return RunStateRecord(workspace_id="w", active_agent_mode="interaction")


def test_session_uses_orchestrator_app_root_when_not_explicit(tmp_path):
    orchestrator = Orchestrator(app_root=tmp_path)

    session = AppSession(orchestrator=orchestrator)

    assert session.app_root == tmp_path


async def test_run_user_turn_yields_app_events(session, tmp_path):
    state = make_state()
    events = [e async for e in session.run_user_turn(
        state=state, workspace_dir=tmp_path, chat_id="c", user_text="hi",
    )]
    assert events[0].event_name == "AppTurnStarted"
    assert events[-1].event_name == "AppFinalMessage"


async def test_concurrent_turn_raises_run_already_active(session, tmp_path):
    state = make_state()
    agen = session.run_user_turn(state=state, workspace_dir=tmp_path, chat_id="c", user_text="hi")
    await agen.__anext__()
    with pytest.raises(RunAlreadyActive):
        async for _ in session.run_user_turn(state=state, workspace_dir=tmp_path, chat_id="c", user_text="x"):
            pass
    async for _ in agen:
        pass


async def test_no_sync_methods(session):
    import inspect
    # No sync turn API present.
    for name in ("run_user_turn", "resume_approved_step", "resume_with_clarification",
                 "handle_direct_command", "compact_chat_history"):
        method = getattr(session, name)
        assert inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(method)
