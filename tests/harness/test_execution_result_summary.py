from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from harness.command_registry import CommandContext
from harness.control import ApprovalRecord, RunStateRecord
from harness.orchestrator import Orchestrator
from worker.models import StepTaskHandle, StepTaskStatus, StepExecutionEnvelope


class _StaticWorker:
    def __init__(self, envelope: StepExecutionEnvelope) -> None:
        self.envelope = envelope

    async def submit(self, request):
        return StepTaskHandle(
            task_id=self.envelope.task_id,
            status="queued",
            submitted_at=datetime.now(UTC),
        )

    async def get_task(self, task_id: str):
        return self.envelope.status

    async def wait(self, task_id: str):
        return self.envelope


def _status(tmp_path: Path, status: str, *, return_code: int | None = 0) -> StepTaskStatus:
    return StepTaskStatus(
        task_id="task_1",
        workspace_id="w1",
        run_id="run_test",
        plan_id="plan_test",
        step_id="step_1",
        status=status,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        return_code=return_code,
    )


def _envelope(tmp_path: Path, status: str, *, stdout: str = "", stderr: str = "", artifacts=None):
    return StepExecutionEnvelope(
        task_id="task_1",
        status=_status(tmp_path, status, return_code=0 if status == "completed" else 1),
        stdout=stdout,
        stderr=stderr,
        artifacts=artifacts or [],
        diagnostics={},
    )


async def _approved_events(tmp_path: Path, envelope: StepExecutionEnvelope):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="analyst", run_id="run_test")
    orch = Orchestrator(worker=_StaticWorker(envelope), app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    ctx = CommandContext(
        workspace_id="w1", chat_id="c1", run_id=state.run_id,
        has_pending_approval=False, has_pending_clarification=False,
    )
    plan_events = [
        ev async for ev in handler(ctx, {
            "goal": "summarize",
            "steps": [{
                "purpose": "Write summary.",
                "code": "from pathlib import Path\nPath('result.txt').write_text('ok')",
                "declared_inputs": [],
                "expected_outputs": ["result.txt"],
            }],
        })
    ]
    plan = next(e for e in plan_events if e.event_name == "PlanReady")
    approval_required = next(e for e in plan_events if e.event_name == "ApprovalRequired")
    approval = ApprovalRecord(
        workspace_id="w1",
        run_id=state.run_id,
        target_type="step",
        target_id=approval_required.step_id,
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at=datetime.now(UTC),
    )
    return [
        ev async for ev in orch.resume_approved_step(
            workspace_dir=tmp_path,
            state=state,
            plan_payload=plan.plan,
            contract_payload={"_step_id": approval_required.step_id},
            approval=approval,
        )
    ]


async def test_resume_approved_step_summarizes_successful_result_file(tmp_path: Path):
    result_file = tmp_path / "artifacts" / "tmp" / "run_test" / "step_1" / "result.txt"
    result_file.parent.mkdir(parents=True)
    result_file.write_text("Total Sales: 123.45", encoding="utf-8")
    events = await _approved_events(
        tmp_path,
        _envelope(tmp_path, "completed", artifacts=[result_file]),
    )
    final = next(e for e in events if e.event_name == "FinalMessage")
    assert final.text == (
        "Analysis complete: Total Sales: 123.45\n\n"
        f"Artifact: {result_file}"
    )


async def test_resume_approved_step_prefers_result_summary_and_cites_transformed_csv(tmp_path: Path):
    step_dir = tmp_path / "artifacts" / "tmp" / "run_test" / "step_1"
    step_dir.mkdir(parents=True)
    transformed = step_dir / "transformed_sales.csv"
    result_file = step_dir / "result.txt"
    transformed.write_text("amount,units,revenue_per_unit\n10,2,5\n", encoding="utf-8")
    result_file.write_text(
        "Added revenue_per_unit.\n\n"
        "| amount | units | revenue_per_unit |\n"
        "| --- | --- | --- |\n"
        "| 10 | 2 | 5 |",
        encoding="utf-8",
    )

    events = await _approved_events(
        tmp_path,
        _envelope(tmp_path, "completed", artifacts=[transformed, result_file]),
    )

    final = next(e for e in events if e.event_name == "FinalMessage")
    assert "Analysis complete: Added revenue_per_unit." in final.text
    assert "| amount | units | revenue_per_unit |" in final.text
    assert f"Artifact: {result_file}" in final.text
    assert f"Artifact: {transformed}" in final.text


async def test_resume_approved_step_reports_worker_failure(tmp_path: Path):
    events = await _approved_events(
        tmp_path,
        _envelope(tmp_path, "failed", stderr="package not allowed: os"),
    )
    final = next(e for e in events if e.event_name == "FinalMessage")
    assert final.text == "Analysis failed during execution: package not allowed: os"
