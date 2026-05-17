from datetime import UTC, datetime

import pytest

from harness.core.analysis_flow import AnalysisFlow, AnalysisPhase
from harness.core.command_registry import CommandContext
from harness.control import ApprovalRecord, RunStateRecord
from harness.orchestrator import Orchestrator


def _state():
    return RunStateRecord(workspace_id="w1", active_agent_mode="analyst")


async def _plan(orch, state, code):
    handler = orch.registry.get_handler("plan_analysis")
    ctx = CommandContext(
        workspace_id="w1", chat_id="c1", run_id=state.run_id,
        has_pending_approval=False, has_pending_clarification=False,
    )
    args = {
        "goal": "compute",
        "steps": [{
            "purpose": "p", "code": code,
            "declared_inputs": [], "expected_outputs": ["o.txt"],
        }],
    }
    return [ev async for ev in handler(ctx, args)]


def _approval(state, step_id):
    return ApprovalRecord(
        workspace_id="w1", run_id=state.run_id, target_type="step",
        target_id=step_id, approval_kind="code_execution",
        decision="approved", decided_by="user", decided_at=datetime.now(UTC),
    )


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=None, app_root=tmp_path)


async def test_command_path_creates_no_flow(orch):
    state = _state()
    await _plan(orch, state, "from pathlib import Path\nPath('o.txt').write_text('ok')\n")
    assert orch._get_flow("c1") is None


async def test_resume_drives_executing_then_done_and_drops_flow(orch, tmp_path):
    state = _state()
    events = await _plan(orch, state,
                         "from pathlib import Path\nPath('o.txt').write_text('ok')\n")
    appr = next(e for e in events if e.event_name == "ApprovalRequired")
    # Simulate the model path having registered a flow for this plan.
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id=state.run_id, workspace_id="w1",
        phase=AnalysisPhase.APPROVAL_PENDING, plan_id=appr.plan_id,
        original_request="compute",
    )

    resume = [
        ev async for ev in orch.resume_approved_step(
            workspace_dir=tmp_path, state=state, plan_id=appr.plan_id,
            contract_payload={"_step_id": appr.step_id},
            approval=_approval(state, appr.step_id),
        )
    ]

    assert "StepCompleted" in [e.event_name for e in resume]
    # Flow reached DONE and was dropped (a fresh orchestrator sees nothing).
    assert orch._get_flow("c1") is None
    orch2 = Orchestrator(runtime=None, app_root=tmp_path)
    assert orch2._get_flow("c1") is None


async def test_resume_hard_fail_sets_failed_and_drops_flow(orch, tmp_path):
    state = _state()
    events = await _plan(
        orch, state,
        "from pathlib import Path\n# writes o.txt then fails before completion\n"
        "raise RuntimeError('boom')\nPath('o.txt').write_text('x')\n",
    )
    appr = next(e for e in events if e.event_name == "ApprovalRequired")
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id=state.run_id, workspace_id="w1",
        phase=AnalysisPhase.APPROVAL_PENDING, plan_id=appr.plan_id,
    )

    resume = [
        ev async for ev in orch.resume_approved_step(
            workspace_dir=tmp_path, state=state, plan_id=appr.plan_id,
            contract_payload={"_step_id": appr.step_id},
            approval=_approval(state, appr.step_id),
        )
    ]

    assert [e for e in resume if e.event_name == "FinalMessage"]
    assert orch._get_flow("c1") is None


async def test_resume_without_flow_does_not_error(orch, tmp_path):
    """Command-path approval (no analysis flow) must still resume cleanly."""
    state = _state()
    events = await _plan(orch, state,
                         "from pathlib import Path\nPath('o.txt').write_text('ok')\n")
    appr = next(e for e in events if e.event_name == "ApprovalRequired")
    resume = [
        ev async for ev in orch.resume_approved_step(
            workspace_dir=tmp_path, state=state, plan_id=appr.plan_id,
            contract_payload={"_step_id": appr.step_id},
            approval=_approval(state, appr.step_id),
        )
    ]
    assert "StepCompleted" in [e.event_name for e in resume]
