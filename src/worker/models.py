from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class ExecutionStatus(StrEnum):
    OK = "ok"
    EXECUTION_ERROR = "execution_error"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    CONTRACT_ERROR = "contract_error"
    SANDBOX_ERROR = "sandbox_error"


class FailureKind(StrEnum):
    OK = "ok"
    PYTHON_EXCEPTION = "python_exception"
    TIMEOUT_OR_RESOURCE_EXHAUSTION = "timeout_or_resource_exhaustion"
    MISSING_OUTPUT_FILES = "missing_output_files"
    MALFORMED_RESULT_JSON = "malformed_result_json"
    PARTIAL_ARTIFACT_GENERATION = "partial_artifact_generation"
    SANDBOX_VIOLATION = "sandbox_violation"


class ResourceLimits(BaseModel):
    timeout_seconds: int = 120
    memory_mb: int = 1024
    artifact_bytes: int = 100_000_000
    stdout_bytes: int = 5_000_000
    stderr_bytes: int = 5_000_000


class PermissionEnvelope(BaseModel):
    allowed_read_paths: list[str] = Field(default_factory=list)
    registered_artifact_paths: list[str] = Field(default_factory=list)
    allowed_write_roots: list[str] = Field(default_factory=lambda: ["artifacts/tmp"])
    allowed_packages: list[str] = Field(default_factory=list)
    allow_network: bool = False
    allow_shell: bool = False


class StepExecutionRequest(BaseModel):
    schema_version: str = "1.0"
    id: str
    workspace_id: str
    run_id: str
    plan_id: str
    step_id: str
    workspace_dir: Path
    code: str
    declared_inputs: dict[str, str]
    workspace_paths: dict[str, str]
    permission_envelope: PermissionEnvelope
    expected_output_contract: list[str] = Field(default_factory=list)
    run_metadata: dict[str, Any] = Field(default_factory=dict)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    created_at: datetime = Field(default_factory=utc_now)
    permitted_paths: list[Path] = Field(default_factory=list)
    timeout_seconds: int | None = None
    env_overrides: dict[str, str] = Field(default_factory=dict)

    def effective_timeout(self) -> int:
        return self.timeout_seconds if self.timeout_seconds is not None else self.resource_limits.timeout_seconds


class ExecutionEnvelope(BaseModel):
    schema_version: str = "1.0"
    id: str
    workspace_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    run_id: str
    step_id: str
    status: ExecutionStatus
    step_result_path: str
    step_report_path: str
    stdout_path: str
    stderr_path: str
    artifact_refs: list[str] = Field(default_factory=list)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)
    failure_kind: FailureKind
    failure_summary: str | None = None


class StepTaskHandle(BaseModel):
    task_id: str
    status: Literal["queued", "running"]
    submitted_at: datetime


class StepTaskStatus(BaseModel):
    task_id: str
    workspace_id: str
    run_id: str
    plan_id: str
    step_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "timeout"]
    started_at: datetime | None
    finished_at: datetime | None
    return_code: int | None


class StepExecutionEnvelope(BaseModel):
    task_id: str
    status: StepTaskStatus
    stdout: str
    stderr: str
    artifacts: list[Path] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
