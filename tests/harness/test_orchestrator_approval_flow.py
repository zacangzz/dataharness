import pytest

from harness.command_registry import CommandContext
from harness.control import ApprovalRecord, RunStateRecord
from harness.orchestrator import Orchestrator


_PLAN_ARGS = {
    "goal": "compare A and B",
    "steps": [
        {
            "purpose": "Compute comparison.",
            "code": (
                "from pathlib import Path\n"
                "Path('output.txt').write_text('A,1\\nB,2\\n')\n"
            ),
            "declared_inputs": [],
            "expected_outputs": ["output.txt"],
        }
    ],
}


def make_state():
    return RunStateRecord(workspace_id="w1", active_agent_mode="analyst")


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=None, app_root=tmp_path)


async def collect(agen):
    return [ev async for ev in agen]


async def _dispatch_plan(orch: Orchestrator, state: RunStateRecord):
    handler = orch.registry.get_handler("plan_analysis")
    ctx = CommandContext(
        workspace_id="w1", chat_id="c1", run_id=state.run_id,
        has_pending_approval=False, has_pending_clarification=False,
    )
    return await collect(handler(ctx, _PLAN_ARGS))


async def test_plan_analysis_emits_planready_then_approvalrequired(orch):
    state = make_state()
    events = await _dispatch_plan(orch, state)
    names = [e.event_name for e in events]
    assert "PlanReady" in names
    assert "ApprovalRequired" in names


async def test_resume_approved_step_emits_submitted_status_completed(orch, tmp_path):
    state = make_state()
    events = await _dispatch_plan(orch, state)
    plan_event = next(e for e in events if e.event_name == "PlanReady")
    appr_event = next(e for e in events if e.event_name == "ApprovalRequired")
    approval = ApprovalRecord(
        workspace_id="w1", run_id=state.run_id, target_type="step",
        target_id=appr_event.step_id, approval_kind="code_execution",
        decision="approved", decided_by="user",
        decided_at=datetime_now(),
    )
    resume_events = await collect(orch.resume_approved_step(
        workspace_dir=tmp_path, state=state,
        plan_payload=plan_event.plan, contract_payload={"_step_id": appr_event.step_id},
        approval=approval,
    ))
    names = [e.event_name for e in resume_events]
    assert "ApprovalResolved" in names
    assert "StepTaskSubmitted" in names
    assert "StepTaskStatusChanged" in names
    assert "StepCompleted" in names
    assert "ArtifactsReady" in names


def datetime_now():
    from datetime import UTC, datetime
    return datetime.now(UTC)
