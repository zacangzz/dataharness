from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from harness.control import (
    ApprovalRecord,
    ExecutionEnvelope,
    Plan,
    PlanStep,
    RunStateRecord,
    StepContract,
    ValidationFailure,
    ValidationFailureKind,
    classify_validation_error,
)


def test_run_state_record_contains_required_layer3_fields() -> None:
    record = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    assert record.schema_version == "1.0"
    assert record.state == "idle"
    assert record.retry_budget == 2
    assert record.attempt_count == 0
    assert record.pending_clarification_id is None
    assert record.pending_review_id is None
    assert record.latest_doctor_report_id is None


def test_plan_requiring_code_execution_starts_unapproved() -> None:
    step = PlanStep(
        workspace_id="w_0001",
        plan_id="plan_1",
        step_order=1,
        purpose="Compute headcount",
        kind="code",
        declared_inputs=["data/employees.csv"],
        expected_outputs=["artifacts/headcount.csv"],
    )
    plan = Plan(
        workspace_id="w_0001",
        run_id="run_1",
        goal="Analyze headcount",
        steps=[step],
        requires_code_execution=True,
    )
    assert plan.approval_status == "pending"
    assert plan.approval_record_id is None


def test_approval_record_timeout_cannot_approve_code_execution() -> None:
    with pytest.raises(ValidationError):
        ApprovalRecord(
            workspace_id="w_0001",
            run_id="run_1",
            target_type="plan",
            target_id="plan_1",
            approval_kind="code_execution",
            decision="approved",
            decided_by="timeout",
            decided_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(seconds=10),
        )


def test_step_contract_uses_workspace_relative_paths() -> None:
    contract = StepContract(
        workspace_id="w_0001",
        run_id="run_1",
        plan_id="plan_1",
        step_id="step_1",
        code="print('ok')",
        declared_inputs=["data/employees.csv"],
        workspace_paths={"tmp": "artifacts/tmp/run_1/step_1"},
        permission_envelope={"network": False, "writable_paths": ["artifacts/tmp/run_1/step_1"]},
        expected_output_contract={"required_files": ["step_result.json", "step_report.md"]},
        run_metadata={"attempt": 1},
    )
    assert contract.workspace_paths["tmp"] == "artifacts/tmp/run_1/step_1"


def test_execution_envelope_exists_on_failure_and_classifies_failure() -> None:
    envelope = ExecutionEnvelope(
        workspace_id="w_0001",
        run_id="run_1",
        step_id="step_1",
        status="failed",
        step_result_path="artifacts/tmp/run_1/step_1/step_result.json",
        step_report_path="artifacts/tmp/run_1/step_1/step_report.md",
        stdout_path="artifacts/tmp/run_1/step_1/stdout.txt",
        stderr_path="artifacts/tmp/run_1/step_1/stderr.txt",
        artifact_refs=[],
        execution_metadata={"duration_ms": 1},
        failure_kind="python_exception",
    )
    assert envelope.failure_kind == "python_exception"


def test_validation_failure_preserves_invalid_payload_and_reason() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunStateRecord(workspace_id="w_0001", state="not_a_state", active_agent_mode="interaction")
    failure = classify_validation_error(
        payload={"state": "not_a_state"},
        error=exc_info.value,
        default_kind=ValidationFailureKind.SCHEMA_MISMATCH,
    )
    assert isinstance(failure, ValidationFailure)
    assert failure.kind == ValidationFailureKind.SCHEMA_MISMATCH
    assert failure.invalid_payload == {"state": "not_a_state"}
