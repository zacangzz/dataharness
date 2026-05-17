from __future__ import annotations

from harness.control import ApprovalRecord, Plan, RunState, RunStateRecord


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"routing", "cancelled"},
    "routing": {"clarifying", "planning", "responding", "cancelled"},
    "clarifying": {"routing", "cancelled"},
    "planning": {"awaiting_approval", "responding", "failed", "cancelled"},
    "awaiting_approval": {"executing", "planning", "cancelled"},
    "executing": {"inspecting", "failed", "cancelled"},
    "inspecting": {"updating_memory", "reviewing_doctor", "responding", "planning", "failed"},
    "updating_memory": {"reviewing_doctor", "responding", "failed"},
    "reviewing_doctor": {"responding", "cancelled"},
    "responding": {"finished", "failed"},
    "finished": {"idle"},
    "failed": {"idle", "planning"},
    "cancelled": {"idle"},
}


class InvalidTransition(ValueError):
    pass


class HarnessStateMachine:
    def transition(self, state: RunStateRecord, next_state: str) -> RunStateRecord:
        allowed = ALLOWED_TRANSITIONS.get(str(state.state), set())
        if next_state not in allowed:
            raise InvalidTransition(f"{state.state} -> {next_state} not allowed")
        return state.model_copy(update={"state": RunState(next_state)})

    def can_dispatch_execution(self, plan: Plan, approval: ApprovalRecord | None) -> bool:
        if not plan.requires_code_execution:
            return True
        return bool(
            approval
            and approval.target_id == plan.id
            and approval.approval_kind == "code_execution"
            and approval.decision == "approved"
            and approval.decided_by != "timeout"
        )

    def decide_after_failure(self, state: RunStateRecord, *, failure_kind: str) -> dict[str, object]:
        if state.attempt_count < state.retry_budget and failure_kind in {
            "parse_failure",
            "schema_mismatch",
            "python_exception",
            "malformed_result_json",
        }:
            return {"action": "retry", "next_attempt_count": state.attempt_count + 1}
        return {"action": "replan", "next_attempt_count": state.attempt_count}
