"""Worker dispatch integration — migrated to async resume_approved_step (was sync dispatch_step)."""
from datetime import UTC, datetime
from pathlib import Path

from harness.control import ApprovalRecord, Plan, PlanStep, RunStateRecord, StepContract
from harness.orchestrator import Orchestrator
from worker.executor import PythonStepExecutor


async def test_orchestrator_dispatches_approved_step_contract_to_worker(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "artifacts" / "tmp").mkdir(parents=True)
    (workspace / "data" / "input.csv").write_text("value\n1\n")

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    # Use run_turn to generate plan + contract via analyst compare flow
    orch = Orchestrator(worker=PythonStepExecutor(), app_root=tmp_path)

    paused_events = [e async for e in orch.run_turn(
        state,
        workspace_dir=workspace,
        chat_id="c1",
        user_input="compare leavers to baseline",
    )]

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
