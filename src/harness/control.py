from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunState(StrEnum):
    IDLE = "idle"
    ROUTING = "routing"
    CLARIFYING = "clarifying"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    INSPECTING = "inspecting"
    UPDATING_MEMORY = "updating_memory"
    REVIEWING_DOCTOR = "reviewing_doctor"
    RESPONDING = "responding"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ValidationFailureKind(StrEnum):
    PARSE_FAILURE = "parse_failure"
    SCHEMA_MISMATCH = "schema_mismatch"
    DETERMINISTIC_REPAIR_CANDIDATE = "deterministic_repair_candidate"
    EXECUTION_FAILURE = "execution_failure"
    SEMANTIC_FAILURE = "semantic_failure"


class HarnessRecord(BaseModel):
    schema_version: str = "1.0"
    id: str = Field(default_factory=lambda: uuid4().hex)
    workspace_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    status: str = "active"


class RunStateRecord(HarnessRecord):
    run_id: str = Field(default_factory=lambda: f"run_{uuid4().hex}")
    state: RunState = RunState.IDLE
    active_agent_mode: str
    plan_id: str | None = None
    step_id: str | None = None
    retry_budget: int = 2
    attempt_count: int = 0
    pending_clarification_id: str | None = None
    pending_review_id: str | None = None
    latest_doctor_report_id: str | None = None


class ModeSwitchEvent(HarnessRecord):
    run_id: str
    from_mode: str
    to_mode: str
    reason: str
    requested_by: str
    accepted: bool


class ApprovalRecord(HarnessRecord):
    run_id: str
    target_type: str
    target_id: str
    approval_kind: str
    decision: str
    decided_by: str
    decided_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def timeout_cannot_approve_code_execution(self) -> "ApprovalRecord":
        if (
            self.approval_kind == "code_execution"
            and self.decision == "approved"
            and self.decided_by == "timeout"
        ):
            raise ValueError("timeout cannot approve code execution")
        return self


class PlanStep(HarnessRecord):
    plan_id: str
    step_order: int
    purpose: str
    kind: str
    declared_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class Plan(HarnessRecord):
    run_id: str
    goal: str
    steps: list[PlanStep]
    requires_code_execution: bool
    approval_status: str = "not_required"
    approval_record_id: str | None = None

    @model_validator(mode="after")
    def code_plans_start_pending_without_record(self) -> "Plan":
        if self.requires_code_execution and self.approval_record_id is None:
            self.approval_status = "pending"
        return self


class StepContract(HarnessRecord):
    run_id: str
    plan_id: str
    step_id: str
    code: str
    declared_inputs: list[str]
    workspace_paths: dict[str, str]
    permission_envelope: dict[str, object]
    expected_output_contract: dict[str, object]
    run_metadata: dict[str, object]

    @field_validator("declared_inputs")
    @classmethod
    def inputs_are_workspace_relative(cls, value: list[str]) -> list[str]:
        for path in value:
            if path.startswith("/"):
                raise ValueError("persisted input paths must be workspace-relative")
        return value


class ExecutionEnvelope(HarnessRecord):
    run_id: str
    step_id: str
    status: str
    step_result_path: str
    step_report_path: str
    stdout_path: str
    stderr_path: str
    artifact_refs: list[str]
    execution_metadata: dict[str, object]
    failure_kind: str | None = None


class StepResult(HarnessRecord):
    run_id: str
    step_id: str
    observations: list[str] = Field(default_factory=list)
    claims: list[dict[str, object]] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    metrics: dict[str, object] = Field(default_factory=dict)
    failure_summary: str | None = None


class PromptPackage(HarnessRecord):
    run_id: str
    agent_mode: str
    prompt_template_id: str
    prompt_template_version: str
    context_refs: list[str]
    token_budget: int
    reasoning_capture_policy: str


class DoctorReport(HarnessRecord):
    trigger: str
    source_findings: list[dict[str, object]] = Field(default_factory=list)
    validity_changes: list[dict[str, object]] = Field(default_factory=list)
    lineage_findings: list[dict[str, object]] = Field(default_factory=list)
    tmp_review: list[dict[str, object]] = Field(default_factory=list)
    tmp_actions: list[dict[str, object]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class TmpAction(HarnessRecord):
    doctor_report_id: str
    item_path: str
    action: str
    destination_path: str | None
    reason: str
    decision_source: str
    applied: bool = False


class ReviewProposal(HarnessRecord):
    run_id: str
    proposal_type: str
    source_refs: list[str]
    proposed_changes: dict[str, object]
    rationale: str


class MemoryUpdateProposal(HarnessRecord):
    run_id: str
    memory_target: str
    source_refs: list[str]
    proposed_content: str
    conflicts: list[str] = Field(default_factory=list)


class ValidationFailure(BaseModel):
    kind: ValidationFailureKind
    invalid_payload: dict[str, object]
    reason: str


def classify_validation_error(
    *,
    payload: dict[str, object],
    error: Exception,
    default_kind: ValidationFailureKind,
) -> ValidationFailure:
    return ValidationFailure(kind=default_kind, invalid_payload=payload, reason=str(error))


class SessionConfig(BaseModel):
    status_heartbeat_seconds: float = 2.0
    status_coalesce_seconds: float = 0.05
