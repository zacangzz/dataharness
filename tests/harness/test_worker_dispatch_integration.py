"""Worker dispatch integration for approved command-side analysis plans."""
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


async def test_derived_column_transformation_writes_summary_and_csv(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "artifacts" / "tmp").mkdir(parents=True)
    (workspace / "data" / "sales.csv").write_text("amount,units\n10,2\n9,3\n")

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")
    orch = Orchestrator(worker=PythonStepExecutor(), app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    ctx = CommandContext(
        workspace_id="w_0001", chat_id="c1", run_id=state.run_id,
        has_pending_approval=False, has_pending_clarification=False,
    )
    plan_events = [ev async for ev in handler(ctx, {
        "goal": "add revenue_per_unit to sales",
        "steps": [{
            "purpose": "Derive revenue_per_unit and save transformed sales.",
            "code": (
                "import csv\n"
                "from pathlib import Path\n"
                "rows = list(csv.DictReader(open('data/sales.csv', newline='')))\n"
                "for row in rows:\n"
                "    row['revenue_per_unit'] = str(float(row['amount']) / float(row['units']))\n"
                "with open('transformed_sales.csv', 'w', newline='') as fh:\n"
                "    writer = csv.DictWriter(fh, fieldnames=['amount', 'units', 'revenue_per_unit'])\n"
                "    writer.writeheader()\n"
                "    writer.writerows(rows)\n"
                "preview = '| amount | units | revenue_per_unit |\\n| --- | --- | --- |\\n'\n"
                "preview += '\\n'.join(f\"| {r['amount']} | {r['units']} | {r['revenue_per_unit']} |\" for r in rows[:2])\n"
                "Path('result.txt').write_text('Added revenue_per_unit.\\n\\n' + preview)\n"
                "print('wrote transformed_sales.csv')\n"
            ),
            "declared_inputs": ["data/sales.csv"],
            "expected_outputs": ["result.txt", "transformed_sales.csv"],
        }],
    })]
    plan_event = next(e for e in plan_events if e.event_name == "PlanReady")
    appr_event = next(e for e in plan_events if e.event_name == "ApprovalRequired")
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
        plan_id=plan_event.plan["id"],
        contract_payload={"_step_id": appr_event.step_id},
        approval=approval,
    )]

    completed = next(e for e in resume_events if e.event_name == "StepCompleted")
    assert completed.envelope.status.status == "completed"
    artifact_names = {Path(path).name for path in completed.envelope.artifacts}
    assert {"result.txt", "transformed_sales.csv"} <= artifact_names
    submitted = next(e for e in resume_events if e.event_name == "StepTaskSubmitted")
    transformed = workspace / "artifacts" / "tmp" / submitted.run_id / "step_1" / "transformed_sales.csv"
    assert "5.0" in transformed.read_text()
    final = next(e for e in resume_events if e.event_name == "FinalMessage")
    assert "| amount | units | revenue_per_unit |" in final.text
    assert "transformed_sales.csv" in final.text
