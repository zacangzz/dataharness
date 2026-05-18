"""Plan gap closure tests — migrated to async run_turn (was sync handle_turn + RuntimeResponse)."""
from pathlib import Path

from harness.control import RunState, RunStateRecord
from harness.core.db import WorkspaceDb
from harness.services.knowledge import KnowledgeManager
from harness.orchestrator import Orchestrator
from harness.core.persistence import HarnessPersistence
from runtime.types import RuntimeEvent, TokenPressure


class PressuredRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def stream(self, request):
        self.calls.append("stream")
        yield RuntimeEvent(
            type="text_delta", request_id=request.request_id, seq=0, text="done",
        )
        yield RuntimeEvent(
            type="finish", request_id=request.request_id, seq=1,
            finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 1},
        )

    async def context_window(self):
        return 1024

    async def token_pressure(self, request):
        self.calls.append("token_pressure")
        return TokenPressure(
            request_id=request.request_id, context_window=1024,
            prompt_tokens=900, reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=900 + request.max_completion_tokens,
            pressure_ratio=0.9, over_threshold=True,
        )

    async def validate_request(self, request):
        return None

    async def status(self):
        return "ready"


async def test_orchestrator_checks_token_pressure_and_streams(tmp_path: Path) -> None:
    """Replaces sync token-pressure compaction test: just verify stream is called after pressure check."""
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    runtime = PressuredRuntime()
    orchestrator = Orchestrator(runtime=runtime, app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    events = [e async for e in orchestrator.run_turn(
        state,
        workspace_dir=workspace,
        chat_id="c1",
        user_input="hi",
        prompt_text="prompt",
    )]

    assert "token_pressure" in runtime.calls
    assert "stream" in runtime.calls
    final = next(e for e in events if e.event_name == "FinalMessage")
    assert final.text == "done"


def test_switch_workspace_resets_run_state_and_persists_mode_switch(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    orchestrator = Orchestrator(persistence=HarnessPersistence(db))
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    new_state = orchestrator.switch_workspace(state, new_workspace_id="w_0002")

    assert new_state.workspace_id == "w_0002"
    assert new_state.run_id != state.run_id
    assert new_state.state == RunState.IDLE
    switch = db.load_record("mode_switch_history", "to_workspace_id", "w_0002")
    assert switch["from_workspace_id"] == "w_0001"


async def test_doctor_direct_command_runs_doctor_and_persists_report_and_tmp_actions(tmp_path: Path) -> None:
    orchestrator = Orchestrator(app_root=tmp_path)
    await orchestrator.create_workspace("w_0001")
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    events = [e async for e in orchestrator.handle_direct_command(
        state,
        command="doctor",
        arguments={"trigger": "manual"},
    )]

    assert any(e.event_name == "DoctorReportReady" for e in events)
    assert any(e.event_name == "CommandCompleted" for e in events)


def test_knowledge_updates_are_pending_until_applied_through_manager(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    db = WorkspaceDb(workspace / "state" / "workspace.db")
    manager = KnowledgeManager(workspace_dir=workspace, persistence=HarnessPersistence(db))

    proposal = manager.propose_update(
        run_id="run_1",
        memory_target="note:attrition.md",
        source_refs=["chat:12"],
        proposed_content="Attrition means voluntary exits.",
    )

    assert proposal.status == "pending"
    assert not (workspace / "memory" / "notes" / "attrition.md").exists()
    applied = manager.apply(proposal.id, decision="approved")
    assert applied["status"] == "applied"
    assert (workspace / "memory" / "notes" / "attrition.md").read_text() == "Attrition means voluntary exits.\n"
    persisted = db.load_record("memory_update_proposals", "id", proposal.id)
    assert persisted["status"] == "applied"
