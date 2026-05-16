"""Full turn integration for the command-side `plan_analysis` approval path."""
from datetime import UTC, datetime
from pathlib import Path

from harness.command_registry import CommandContext
from harness.control import ApprovalRecord, RunStateRecord
from harness.db import WorkspaceDb
from harness.orchestrator import Orchestrator
from harness.persistence import HarnessPersistence
from worker.executor import PythonStepExecutor


_PLAN_ARGS = {
    "goal": "compare leavers by department",
    "steps": [
        {
            "purpose": "Compute leavers per department.",
            "code": (
                "from pathlib import Path\n"
                "Path('output.txt').write_text('department,leavers\\nSales,1\\n')\n"
            ),
            "declared_inputs": ["data/input.csv"],
            "expected_outputs": ["output.txt"],
        }
    ],
}


async def _dispatch_plan_analysis(orchestrator: Orchestrator, state: RunStateRecord, workspace_id: str):
    handler = orchestrator.registry.get_handler("plan_analysis")
    ctx = CommandContext(
        workspace_id=workspace_id, chat_id="c1", run_id=state.run_id,
        has_pending_approval=False, has_pending_clarification=False,
    )
    return [ev async for ev in handler(ctx, _PLAN_ARGS)]


async def test_analysis_plan_command_emits_plan_and_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "memory").mkdir(parents=True)
    (workspace / "state").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    (workspace / "data" / "input.csv").write_text("department,leavers\nSales,1\n")
    db = WorkspaceDb(workspace / "state" / "workspace.db")
    orchestrator = Orchestrator(persistence=HarnessPersistence(db), app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    events = await _dispatch_plan_analysis(orchestrator, state, "w_0001")
    names = [e.event_name for e in events]

    assert "PlanReady" in names
    assert "ApprovalRequired" in names
    plan_event = next(e for e in events if e.event_name == "PlanReady")
    assert plan_event.plan["requires_code_execution"] is True
    assert plan_event.plan["goal"] == "compare leavers by department"


async def test_approved_analysis_dispatches_worker_and_persists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "artifacts" / "tmp").mkdir(parents=True)
    (workspace / "memory").mkdir(parents=True)
    (workspace / "state").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    (workspace / "data" / "input.csv").write_text("department,leavers\nSales,1\n")
    db = WorkspaceDb(workspace / "state" / "workspace.db")
    orchestrator = Orchestrator(
        worker=PythonStepExecutor(), persistence=HarnessPersistence(db), app_root=tmp_path,
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    paused_events = await _dispatch_plan_analysis(orchestrator, state, "w_0001")
    plan_event = next(e for e in paused_events if e.event_name == "PlanReady")
    appr_event = next(e for e in paused_events if e.event_name == "ApprovalRequired")

    approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id=state.run_id,
        target_type="plan",
        target_id=plan_event.plan["id"],
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at=datetime.now(UTC),
    )

    resume_events = [e async for e in orchestrator.resume_approved_step(
        workspace_dir=workspace,
        state=state,
        plan_payload=plan_event.plan,
        contract_payload={"_step_id": appr_event.step_id},
        approval=approval,
    )]

    names = [e.event_name for e in resume_events]
    assert "StepCompleted" in names
    assert "FinalMessage" in names
    final = next(e for e in resume_events if e.event_name == "FinalMessage")
    assert "Analysis complete" in final.text
