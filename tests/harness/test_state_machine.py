from datetime import UTC, datetime

import pytest

from harness.control import ApprovalRecord, Plan, PlanStep, RunStateRecord
from harness.state_machine import HarnessStateMachine, InvalidTransition


def code_plan() -> Plan:
    step = PlanStep(
        workspace_id="w_0001",
        plan_id="plan_1",
        step_order=1,
        purpose="Compute attrition",
        kind="code",
        declared_inputs=["data/employees.csv"],
        expected_outputs=["artifacts/attrition.csv"],
    )
    return Plan(
        id="plan_1",
        workspace_id="w_0001",
        run_id="run_1",
        goal="Analyze attrition",
        steps=[step],
        requires_code_execution=True,
    )


def test_state_machine_advances_through_layer3_run_states() -> None:
    machine = HarnessStateMachine()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    routed = machine.transition(state, "routing")
    planned = machine.transition(routed, "planning")
    waiting = machine.transition(planned, "awaiting_approval")
    assert waiting.state == "awaiting_approval"


def test_state_machine_rejects_direct_execution_from_planning() -> None:
    machine = HarnessStateMachine()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction", state="planning")
    with pytest.raises(InvalidTransition):
        machine.transition(state, "executing")


def test_code_execution_requires_explicit_user_approval() -> None:
    machine = HarnessStateMachine()
    plan = code_plan()
    assert machine.can_dispatch_execution(plan, approval=None) is False
    timeout_approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id="run_1",
        target_type="plan",
        target_id="plan_1",
        approval_kind="non_execution",
        decision="approved",
        decided_by="timeout",
        decided_at=datetime.now(UTC),
    )
    assert machine.can_dispatch_execution(plan, approval=timeout_approval) is False
    user_approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id="run_1",
        target_type="plan",
        target_id="plan_1",
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at=datetime.now(UTC),
    )
    assert machine.can_dispatch_execution(plan, approval=user_approval) is True


def test_retry_decision_is_budgeted_and_visible() -> None:
    machine = HarnessStateMachine()
    state = RunStateRecord(
        workspace_id="w_0001",
        active_agent_mode="interaction",
        state="inspecting",
        retry_budget=2,
        attempt_count=1,
    )
    decision = machine.decide_after_failure(state, failure_kind="schema_mismatch")
    assert decision["action"] == "retry"
    assert decision["next_attempt_count"] == 2
    exhausted = state.model_copy(update={"attempt_count": 2})
    assert machine.decide_after_failure(exhausted, failure_kind="python_exception")["action"] == "replan"
