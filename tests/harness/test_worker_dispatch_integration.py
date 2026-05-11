"""Worker dispatch integration — plans now built via plan_analysis tool_call."""
from datetime import UTC, datetime
from pathlib import Path

from harness.command_registry import CommandContext
from harness.control import ApprovalRecord, RunStateRecord
from harness.orchestrator import Orchestrator
from worker.executor import PythonStepExecutor


_PLAN_ARGS = {
    "goal": "compare leavers to baseline",
    "steps": [
        {
            "purpose": "Compute leavers vs baseline.",
            "code": (
                "from pathlib import Path\n"
                "Path('output.txt').write_text('leavers,1\\nbaseline,0\\n')\n"
            ),
            "declared_inputs": ["data/input.csv"],
            "expected_outputs": ["output.txt"],
        }
    ],
}


async def test_orchestrator_dispatches_approved_step_contract_to_worker(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "artifacts" / "tmp").mkdir(parents=True)
    (workspace / "data" / "input.csv").write_text("value\n1\n")

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")
    orch = Orchestrator(worker=PythonStepExecutor(), app_root=tmp_path)

    handler = orch.registry.get_handler("plan_analysis")
    ctx = CommandContext(
        workspace_id="w_0001", chat_id="c1", run_id=state.run_id,
        has_pending_approval=False, has_pending_clarification=False,
    )
    paused_events = [ev async for ev in handler(ctx, _PLAN_ARGS)]

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

    resume_events = [e async for e in orch.resume_approved_step(
        workspace_dir=workspace,
        state=state,
        plan_payload=plan_event.plan,
        contract_payload={"_step_id": appr_event.step_id},
        approval=approval,
    )]

    names = [e.event_name for e in resume_events]
    assert "StepTaskSubmitted" in names
    assert "StepCompleted" in names
    completed = next(e for e in resume_events if e.event_name == "StepCompleted")
    assert completed.envelope.status.status in ("completed", "failed")
