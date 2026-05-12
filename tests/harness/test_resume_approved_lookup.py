"""resume_approved_step resolves the Plan from the orchestrator's cache via
plan_id, so the App layer does not have to forward the full Plan dict."""

from datetime import UTC, datetime

import pytest

from harness.command_registry import CommandContext
from harness.control import ApprovalRecord, RunStateRecord
from harness.orchestrator import Orchestrator


_PLAN_ARGS = {
    "goal": "compute",
    "steps": [
        {
            "purpose": "p",
            "code": "from pathlib import Path\nPath('o.txt').write_text('ok')\n",
            "declared_inputs": [],
            "expected_outputs": ["o.txt"],
        }
    ],
}


def _state():
    return RunStateRecord(workspace_id="w1", active_agent_mode="analyst")


async def _plan(orch, state):
    handler = orch.registry.get_handler("plan_analysis")
    ctx = CommandContext(
        workspace_id="w1", chat_id="c1", run_id=state.run_id,
        has_pending_approval=False, has_pending_clarification=False,
    )
    return [ev async for ev in handler(ctx, _PLAN_ARGS)]


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=None, app_root=tmp_path)


async def test_resume_with_plan_id_only(orch, tmp_path):
    state = _state()
    events = await _plan(orch, state)
    appr = next(e for e in events if e.event_name == "ApprovalRequired")
    approval = ApprovalRecord(
        workspace_id="w1", run_id=state.run_id, target_type="step",
        target_id=appr.step_id, approval_kind="code_execution",
        decision="approved", decided_by="user",
        decided_at=datetime.now(UTC),
    )
    # NOTE: no plan_payload — exercises the cache lookup path
    resume = [
        ev async for ev in orch.resume_approved_step(
            workspace_dir=tmp_path, state=state,
            plan_id=appr.plan_id,
            contract_payload={"_step_id": appr.step_id},
            approval=approval,
        )
    ]
    names = [e.event_name for e in resume]
    assert "ApprovalResolved" in names
    assert "StepCompleted" in names
    # cache cleaned after resume
    assert appr.plan_id not in orch._pending_plans


async def test_resume_missing_plan_id_and_no_payload_raises(orch, tmp_path):
    state = _state()
    approval = ApprovalRecord(
        workspace_id="w1", run_id=state.run_id, target_type="step",
        target_id="step_1", approval_kind="code_execution",
        decision="approved", decided_by="user",
        decided_at=datetime.now(UTC),
    )
    with pytest.raises(ValueError, match="no cached plan"):
        async for _ in orch.resume_approved_step(
            workspace_dir=tmp_path, state=state,
            plan_id="plan_run_does_not_exist",
            contract_payload={"_step_id": "step_1"},
            approval=approval,
        ):
            pass
