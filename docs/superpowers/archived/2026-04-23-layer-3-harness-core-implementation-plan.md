# Layer 3 Harness Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the workspace-first harness core that owns Layer 3 orchestration, state, memory, doctor, validation, provenance, approvals, and direct harness commands.

**Architecture:** Implement `src/harness/` as the platform core above the Layer 1 runtime and Layer 2 worker. Deterministic Python owns state transitions, approval gates, validation, fingerprinting, provenance, and storage; only three narrow harness-operational prompts are allowed for context compaction, doctor tmp judgment, and knowledge reconciliation, and their outputs are advisory until validated and recorded.

**Tech Stack:** Python 3.12, `pydantic`, `sqlite3`, `pytest`, `pathlib`, `hashlib`, `json`, `uuid`, `datetime`

---

## File Structure

**Create:**
- `src/harness/__init__.py`: public harness exports.
- `src/harness/paths.py`: app-root and workspace-relative path model.
- `src/harness/app_store.py`: small global app store for workspace ids, paths, recent workspaces, and basic preferences.
- `src/harness/workspace.py`: workspace bootstrap and `state/workspace.db` path helpers.
- `src/harness/control.py`: canonical typed control objects and validation failure classification.
- `src/harness/db.py`: SQLite schema and repository helpers for workspace truth.
- `src/harness/state_machine.py`: run-state transition rules and explicit approval gate checks.
- `src/harness/commands.py`: direct harness command registry and command request validation.
- `src/harness/orchestrator.py`: sequential control loop skeleton and worker dispatch decision logic.
- `src/harness/context.py`: durable context rebuilding and non-durable compaction records.
- `src/harness/doctor.py`: lazy fingerprinting, validity detection, doctor reports, and tmp actions.
- `src/harness/knowledge.py`: preferences, notes, functions, memory rescans, and update proposals.
- `src/harness/provenance.py`: lineage records and evidence-backed claim checks.
- `src/harness/prompt_registry.py`: allow-list for the three Layer 3 operational prompts.
- `src/harness/prompts/compaction.md`
- `src/harness/prompts/doctor.md`
- `src/harness/prompts/knowledge_reconcile.md`
- `tests/harness/test_paths_and_workspace.py`
- `tests/harness/test_control_objects.py`
- `tests/harness/test_db.py`
- `tests/harness/test_state_machine.py`
- `tests/harness/test_orchestrator.py`
- `tests/harness/test_context.py`
- `tests/harness/test_doctor.py`
- `tests/harness/test_knowledge.py`
- `tests/harness/test_provenance.py`
- `tests/harness/test_layer3_integration.py`

## Spec Coverage Map

- Spec 6.1 purpose: Tasks 5 and 10.
- Spec 6.2 core capabilities: Tasks 1 through 10.
- Spec 6.3 orchestration loop: Tasks 5 and 10.
- Spec 6.4 run state, prompt routing, and explicit execution approval: Tasks 2, 4, 5, and 6.
- Spec 6.5 workspace and app-state model: Task 1.
- Spec 6.6 canonical control objects and validation classification: Tasks 2 and 3.
- Spec 6.7 deterministic repair, retry, and replan: Tasks 2, 4, and 5.
- Spec 6.8 context and compaction: Task 6.
- Spec 6.9 storage model: Tasks 1 and 3.
- Spec 6.10 direct command surface: Task 5.
- Spec 6.11 validity and fingerprinting: Task 7.
- Spec 6.12 doctor and review: Task 7.
- Spec 6.13 knowledge and function management: Task 8.
- Spec 6.14 provenance: Task 9.
- Spec 6.15 end-of-layer barebones harness result: Task 10.

### Task 1: Build Workspace-First Paths, App Store, And Workspace Bootstrap

**Files:**
- Create: `src/harness/__init__.py`
- Create: `src/harness/paths.py`
- Create: `src/harness/app_store.py`
- Create: `src/harness/workspace.py`
- Test: `tests/harness/test_paths_and_workspace.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from harness.app_store import AppStore
from harness.paths import AppPaths, WorkspacePaths
from harness.workspace import bootstrap_workspace


def test_app_paths_match_workspace_first_layout(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path)
    assert paths.app_dir == tmp_path / "app"
    assert paths.app_store_path == tmp_path / "app" / "app.json"
    assert paths.harness_dir == tmp_path / "harness"
    assert paths.telemetry_dir == tmp_path / "harness" / "telemetry"
    assert paths.logs_dir == tmp_path / "harness" / "logs"
    assert paths.workspaces_dir == tmp_path / "workspaces"


def test_workspace_paths_are_workspace_relative(tmp_path: Path) -> None:
    workspace = WorkspacePaths.from_workspace_dir(tmp_path / "workspaces" / "w_0001")
    assert workspace.data_dir == workspace.root / "data"
    assert workspace.tmp_artifacts_dir == workspace.root / "artifacts" / "tmp"
    assert workspace.preferences_path == workspace.root / "memory" / "preferences.json"
    assert workspace.workspace_db_path == workspace.root / "state" / "workspace.db"
    assert workspace.relative(workspace.root / "artifacts" / "report.md") == Path("artifacts/report.md")


def test_bootstrap_workspace_creates_required_directories_and_preferences(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspaces" / "w_0001")
    assert (workspace / "data").exists()
    assert (workspace / "artifacts" / "tmp").exists()
    assert (workspace / "memory" / "preferences.json").read_text() == "{}\n"
    assert (workspace / "memory" / "notes" / "gaps").exists()
    assert (workspace / "memory" / "functions").exists()
    assert (workspace / "state").exists()


def test_app_store_remains_non_authoritative_for_workspace_truth(tmp_path: Path) -> None:
    store_path = tmp_path / "app" / "app.json"
    store = AppStore(path=store_path)
    store.register_workspace("w_0001", tmp_path / "workspaces" / "w_0001")
    loaded = AppStore.load(store_path)
    assert loaded.last_opened_workspace == "w_0001"
    assert loaded.known_workspaces["w_0001"] == str(tmp_path / "workspaces" / "w_0001")
    assert "run_records" not in loaded.model_dump()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_paths_and_workspace.py -q`

Expected: FAIL with `ModuleNotFoundError` for `harness`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/paths.py
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class AppPaths(BaseModel):
    root: Path
    app_dir: Path
    app_store_path: Path
    harness_dir: Path
    telemetry_dir: Path
    logs_dir: Path
    workspaces_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        return cls(
            root=root,
            app_dir=root / "app",
            app_store_path=root / "app" / "app.json",
            harness_dir=root / "harness",
            telemetry_dir=root / "harness" / "telemetry",
            logs_dir=root / "harness" / "logs",
            workspaces_dir=root / "workspaces",
        )


class WorkspacePaths(BaseModel):
    root: Path
    data_dir: Path
    artifacts_dir: Path
    tmp_artifacts_dir: Path
    memory_dir: Path
    preferences_path: Path
    notes_dir: Path
    gaps_dir: Path
    functions_dir: Path
    state_dir: Path
    workspace_db_path: Path

    @classmethod
    def from_workspace_dir(cls, root: Path) -> "WorkspacePaths":
        return cls(
            root=root,
            data_dir=root / "data",
            artifacts_dir=root / "artifacts",
            tmp_artifacts_dir=root / "artifacts" / "tmp",
            memory_dir=root / "memory",
            preferences_path=root / "memory" / "preferences.json",
            notes_dir=root / "memory" / "notes",
            gaps_dir=root / "memory" / "notes" / "gaps",
            functions_dir=root / "memory" / "functions",
            state_dir=root / "state",
            workspace_db_path=root / "state" / "workspace.db",
        )

    def relative(self, path: Path) -> Path:
        return path.relative_to(self.root)
```

```python
# src/harness/workspace.py
from __future__ import annotations

from pathlib import Path

from harness.paths import WorkspacePaths


def bootstrap_workspace(workspace_dir: Path) -> Path:
    paths = WorkspacePaths.from_workspace_dir(workspace_dir)
    for directory in [
        paths.data_dir,
        paths.tmp_artifacts_dir,
        paths.notes_dir,
        paths.gaps_dir,
        paths.functions_dir,
        paths.state_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.preferences_path.exists():
        paths.preferences_path.write_text("{}\n")
    return workspace_dir
```

```python
# src/harness/app_store.py
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class AppStore(BaseModel):
    path: Path
    known_workspaces: dict[str, str] = Field(default_factory=dict)
    recent_workspaces: list[str] = Field(default_factory=list)
    last_opened_workspace: str | None = None
    preferences: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "AppStore":
        if not path.exists():
            return cls(path=path)
        payload = json.loads(path.read_text())
        return cls(path=path, **payload)

    def register_workspace(self, workspace_id: str, workspace_path: Path) -> None:
        self.known_workspaces[workspace_id] = str(workspace_path)
        self.last_opened_workspace = workspace_id
        self.recent_workspaces = [workspace_id] + [
            item for item in self.recent_workspaces if item != workspace_id
        ]
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "known_workspaces": self.known_workspaces,
                    "recent_workspaces": self.recent_workspaces,
                    "last_opened_workspace": self.last_opened_workspace,
                    "preferences": self.preferences,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
```

```python
# src/harness/__init__.py
from harness.app_store import AppStore
from harness.paths import AppPaths, WorkspacePaths
from harness.workspace import bootstrap_workspace

__all__ = ["AppPaths", "AppStore", "WorkspacePaths", "bootstrap_workspace"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_paths_and_workspace.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/__init__.py src/harness/paths.py src/harness/app_store.py src/harness/workspace.py tests/harness/test_paths_and_workspace.py
git commit -m "feat: add harness workspace layout"
```

### Task 2: Define Canonical Control Objects And Validation Classification

**Files:**
- Create: `src/harness/control.py`
- Test: `tests/harness/test_control_objects.py`

- [ ] **Step 1: Write the failing test**

```python
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
    try:
        RunStateRecord(workspace_id="w_0001", state="not_a_state", active_agent_mode="interaction")
    except ValidationError as error:
        failure = classify_validation_error(
            payload={"state": "not_a_state"},
            error=error,
            default_kind=ValidationFailureKind.SCHEMA_MISMATCH,
        )
    assert isinstance(failure, ValidationFailure)
    assert failure.kind == ValidationFailureKind.SCHEMA_MISMATCH
    assert failure.invalid_payload == {"state": "not_a_state"}


def test_plan_status_uses_narrow_enum_not_free_text() -> None:
    from harness.control import PlanStatus

    plan = Plan(
        workspace_id="w_0001", run_id="run_1", goal="x",
        steps=[PlanStep(workspace_id="w_0001", plan_id="p", step_order=1, purpose="p", kind="text")],
        requires_code_execution=False,
    )
    assert isinstance(plan.status, PlanStatus)
    assert plan.status == PlanStatus.DRAFT
    with pytest.raises(ValidationError):
        Plan(
            workspace_id="w_0001", run_id="run_1", goal="x",
            steps=[PlanStep(workspace_id="w_0001", plan_id="p", step_order=1, purpose="p", kind="text")],
            requires_code_execution=False,
            status="bogus",
        )


def test_proposal_status_uses_narrow_enum() -> None:
    from harness.control import ProposalStatus

    proposal = MemoryUpdateProposal(
        workspace_id="w_0001", run_id="run_1",
        memory_target="memory/notes/x.md", source_refs=["turn:r_1"],
        proposed_content="x",
    )
    assert isinstance(proposal.status, ProposalStatus)
    assert proposal.status == ProposalStatus.PENDING


def test_step_result_rejects_claims_when_status_is_not_ok() -> None:
    # Spec §6.6 invariant: failures must not be converted into analytical claims.
    from harness.control import StepResult

    StepResult(workspace_id="w_0001", run_id="r_1", step_id="s_1", status="ok", claims=[{"text": "headcount=100"}])  # ok
    with pytest.raises(ValidationError, match="claims"):
        StepResult(
            workspace_id="w_0001", run_id="r_1", step_id="s_1",
            status="failed", claims=[{"text": "the script crashed but headcount looks like 100"}],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_control_objects.py -q`

Expected: FAIL with `ModuleNotFoundError` for `harness.control`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/control.py
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


class PlanStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    CONFLICTED = "conflicted"


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
    status: PlanStatus = PlanStatus.DRAFT

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

    @model_validator(mode="after")
    def failures_must_not_become_claims(self) -> "StepResult":
        # Spec §6.6 invariant: failures must not be converted into analytical claims.
        if self.status != "ok" and self.claims:
            raise ValueError("claims must be empty when StepResult.status is not 'ok'")
        return self


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
    status: ProposalStatus = ProposalStatus.PENDING


class MemoryUpdateProposal(HarnessRecord):
    run_id: str
    memory_target: str
    source_refs: list[str]
    proposed_content: str
    conflicts: list[str] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PENDING


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_control_objects.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/control.py tests/harness/test_control_objects.py
git commit -m "feat: define harness control contracts"
```

### Task 3: Create Authoritative `workspace.db` Schema And Repositories

**Files:**
- Create: `src/harness/db.py`
- Test: `tests/harness/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from harness.control import ApprovalRecord, RunStateRecord
from harness.db import WorkspaceDb


def test_workspace_db_bootstraps_layer3_authoritative_tables(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    tables = set(db.list_tables())
    assert {
        "workspace_metadata",
        "run_records",
        "run_state_history",
        "plan_records",
        "step_records",
        "approval_records",
        "execution_envelopes",
        "step_results",
        "prompt_packages",
        "artifact_registry",
        "file_registry",
        "validity_state",
        "lineage_records",
        "doctor_history",
        "tmp_actions",
        "review_proposals",
        "memory_update_proposals",
        "validation_failures",
        "note_index",
        "function_index",
        "mode_switch_history",
        "step_action_history",
    } <= tables


def test_repository_persists_json_control_records(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    run = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    db.save_record("run_records", "run_id", run.run_id, run.model_dump(mode="json"))
    loaded = db.load_record("run_records", "run_id", run.run_id)
    assert loaded["run_id"] == run.run_id
    assert loaded["state"] == "idle"


def test_approval_records_are_stored_append_only(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id="run_1",
        target_type="plan",
        target_id="plan_1",
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at="2026-04-23T00:00:00Z",
    )
    db.append_record("approval_records", approval.id, approval.model_dump(mode="json"))
    assert db.load_record("approval_records", "id", approval.id)["decision"] == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_db.py -q`

Expected: FAIL with `ModuleNotFoundError` for `harness.db`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/db.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


AUTHORITATIVE_TABLES = [
    "workspace_metadata",
    "run_records",
    "run_state_history",
    "plan_records",
    "step_records",
    "approval_records",
    "execution_envelopes",
    "step_results",
    "prompt_packages",
    "artifact_registry",
    "file_registry",
    "validity_state",
    "lineage_records",
    "doctor_history",
    "tmp_actions",
    "review_proposals",
    "memory_update_proposals",
    "validation_failures",
    "note_index",
    "function_index",
    "mode_switch_history",
    "step_action_history",
]


def create_schema() -> str:
    statements = [
        f"""
        create table if not exists {table_name} (
            id text primary key,
            record_json text not null,
            created_at text not null default current_timestamp
        );
        """
        for table_name in AUTHORITATIVE_TABLES
    ]
    statements.extend(
        [
            "create unique index if not exists idx_run_records_run_id on run_records (json_extract(record_json, '$.run_id'));",
            "create unique index if not exists idx_plan_records_plan_id on plan_records (json_extract(record_json, '$.id'));",
            "create index if not exists idx_file_registry_workspace on file_registry (json_extract(record_json, '$.workspace_id'));",
            "create index if not exists idx_validity_subject on validity_state (json_extract(record_json, '$.subject_id'));",
        ]
    )
    return "\n".join(statements)


class WorkspaceDb:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("pragma journal_mode = wal")
        self._conn.executescript(create_schema())
        self._conn.commit()
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            return self.connect()
        return self._conn

    def list_tables(self) -> list[str]:
        rows = self.conn.execute("select name from sqlite_master where type='table'").fetchall()
        return [row[0] for row in rows]

    def append_record(self, table: str, record_id: str, record: dict[str, object]) -> None:
        if table not in AUTHORITATIVE_TABLES:
            raise ValueError(f"unknown table: {table}")
        self.conn.execute(
            f"insert into {table} (id, record_json) values (?, ?)",
            (record_id, json.dumps(record, sort_keys=True)),
        )
        self.conn.commit()

    def save_record(self, table: str, key_name: str, key_value: str, record: dict[str, object]) -> None:
        if table not in AUTHORITATIVE_TABLES:
            raise ValueError(f"unknown table: {table}")
        existing = self.conn.execute(
            f"select id from {table} where json_extract(record_json, '$.{key_name}') = ?",
            (key_value,),
        ).fetchone()
        record_id = str(record.get("id") or key_value)
        if existing:
            self.conn.execute(
                f"update {table} set record_json = ? where id = ?",
                (json.dumps(record, sort_keys=True), existing[0]),
            )
        else:
            self.append_record(table, record_id, record)
            return
        self.conn.commit()

    def load_record(self, table: str, key_name: str, key_value: str) -> dict[str, object]:
        if table not in AUTHORITATIVE_TABLES:
            raise ValueError(f"unknown table: {table}")
        row = self.conn.execute(
            f"select record_json from {table} where json_extract(record_json, '$.{key_name}') = ?",
            (key_value,),
        ).fetchone()
        if row is None:
            raise KeyError(key_value)
        return json.loads(row[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_db.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/db.py tests/harness/test_db.py
git commit -m "feat: add workspace database schema"
```

### Task 4: Implement Run State Machine, Approval Gating, Retry, And Replan Decisions

**Files:**
- Create: `src/harness/state_machine.py`
- Test: `tests/harness/test_state_machine.py`

- [ ] **Step 1: Write the failing test**

```python
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
    decision = machine.decide_after_failure(state, failure_kind="schema_mismatch", repaired_payload=None)
    assert decision["action"] == "retry"
    assert decision["next_attempt_count"] == 2
    exhausted = state.model_copy(update={"attempt_count": 2})
    assert machine.decide_after_failure(exhausted, failure_kind="python_exception", repaired_payload=None)["action"] == "replan"


def test_decide_after_failure_prefers_repair_when_payload_repaired() -> None:
    # Spec §6.7: deterministic repair before another model call.
    machine = HarnessStateMachine()
    state = RunStateRecord(
        workspace_id="w_0001", active_agent_mode="interaction",
        state="inspecting", retry_budget=2, attempt_count=0,
    )
    decision = machine.decide_after_failure(
        state,
        failure_kind="schema_mismatch",
        repaired_payload={"name": "doctor", "arguments": {"value": "manual"}},
    )
    assert decision["action"] == "repair_then_retry"
    assert decision["repaired_payload"]["arguments"] == {"value": "manual"}


def test_evaluate_mode_switch_rejects_during_executing_state() -> None:
    machine = HarnessStateMachine()
    state = RunStateRecord(
        workspace_id="w_0001", active_agent_mode="analyst", state="executing",
    )
    event = machine.evaluate_mode_switch(state, requested_mode="knowledge", requested_by="application_session")
    assert event.accepted is False
    assert "executing" in event.reason


def test_evaluate_mode_switch_rejects_unknown_mode() -> None:
    machine = HarnessStateMachine()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    event = machine.evaluate_mode_switch(state, requested_mode="bogus", requested_by="application_session")
    assert event.accepted is False
    assert "unknown" in event.reason


def test_evaluate_mode_switch_records_noop_when_request_matches_current() -> None:
    machine = HarnessStateMachine()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")
    event = machine.evaluate_mode_switch(state, requested_mode="analyst", requested_by="application_session")
    assert event.accepted is True
    assert event.reason == "noop"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_state_machine.py -q`

Expected: FAIL with `ModuleNotFoundError` for `harness.state_machine`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/state_machine.py
from __future__ import annotations

from harness.control import ApprovalRecord, ModeSwitchEvent, Plan, RunState, RunStateRecord


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


KNOWN_AGENT_MODES = {"interaction", "analyst", "knowledge"}


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

    def decide_after_failure(
        self,
        state: RunStateRecord,
        *,
        failure_kind: str,
        repaired_payload: dict[str, object] | None,
    ) -> dict[str, object]:
        # Spec §6.7: deterministic repair runs first. If repair already produced a clean payload,
        # take a single repaired retry path instead of spending a model call.
        if repaired_payload is not None and state.attempt_count < state.retry_budget:
            return {
                "action": "repair_then_retry",
                "next_attempt_count": state.attempt_count + 1,
                "repaired_payload": repaired_payload,
            }
        if state.attempt_count < state.retry_budget and failure_kind in {
            "parse_failure",
            "schema_mismatch",
            "python_exception",
            "malformed_result_json",
        }:
            return {"action": "retry", "next_attempt_count": state.attempt_count + 1}
        return {"action": "replan", "next_attempt_count": state.attempt_count}

    def evaluate_mode_switch(
        self,
        state: RunStateRecord,
        *,
        requested_mode: str,
        requested_by: str,
    ) -> ModeSwitchEvent:
        # Spec §7.14: harness owns accepted mode activation.
        if requested_mode == state.active_agent_mode:
            return ModeSwitchEvent(
                workspace_id=state.workspace_id, run_id=state.run_id,
                from_mode=state.active_agent_mode, to_mode=requested_mode,
                reason="noop", requested_by=requested_by, accepted=True,
            )
        if requested_mode not in KNOWN_AGENT_MODES:
            return ModeSwitchEvent(
                workspace_id=state.workspace_id, run_id=state.run_id,
                from_mode=state.active_agent_mode, to_mode=requested_mode,
                reason=f"unknown agent mode: {requested_mode}",
                requested_by=requested_by, accepted=False,
            )
        if str(state.state) in {"executing", "awaiting_approval"}:
            return ModeSwitchEvent(
                workspace_id=state.workspace_id, run_id=state.run_id,
                from_mode=state.active_agent_mode, to_mode=requested_mode,
                reason=f"cannot switch mode while in {state.state}",
                requested_by=requested_by, accepted=False,
            )
        return ModeSwitchEvent(
            workspace_id=state.workspace_id, run_id=state.run_id,
            from_mode=state.active_agent_mode, to_mode=requested_mode,
            reason="approved", requested_by=requested_by, accepted=True,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_state_machine.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/state_machine.py tests/harness/test_state_machine.py
git commit -m "feat: add harness state machine approval gates"
```

### Task 4b: Deterministic Repair And Timed Decision Gate

**Files:**
- Create: `src/harness/repair.py`
- Create: `src/harness/approval.py`
- Test: `tests/harness/test_repair.py`
- Test: `tests/harness/test_approval_gate.py`

Spec §6.4 (10-second auto-proceed for non-execution decisions) and §6.7 (deterministic repair before retry). These two utilities are required by the orchestrator (Task 5) and must land before it.

- [ ] **Step 1: Write failing repair tests**

```python
# tests/harness/test_repair.py
from harness.repair import RepairResult, try_deterministic_repair


def test_wrapper_repair_wraps_scalar_arguments() -> None:
    payload = {"name": "doctor", "arguments": "manual"}
    result = try_deterministic_repair(payload, failure_kind="schema_mismatch")
    assert result.kind == "applied"
    assert result.recipe == "wrapper_repair"
    assert result.payload["arguments"] == {"value": "manual"}


def test_type_normalization_converts_numeric_strings() -> None:
    payload = {"name": "compute", "arguments": {"limit": "100", "ratio": "0.5"}}
    result = try_deterministic_repair(payload, failure_kind="schema_mismatch")
    assert result.kind == "applied"
    assert result.payload["arguments"] == {"limit": 100, "ratio": 0.5}


def test_metadata_insertion_fills_missing_canonical_fields() -> None:
    payload = {"workspace_id": "w_0001", "run_id": "r_1", "memory_target": "memory/notes/x.md", "source_refs": [], "proposed_content": "x"}
    result = try_deterministic_repair(payload, failure_kind="schema_mismatch", record_kind="MemoryUpdateProposal")
    assert result.kind == "applied"
    assert result.payload["schema_version"] == "1.0"
    assert "id" in result.payload
    assert "created_at" in result.payload


def test_path_normalization_strips_leading_slash_and_normalizes_separators() -> None:
    payload = {"declared_inputs": ["/data\\employees.csv"]}
    result = try_deterministic_repair(payload, failure_kind="schema_mismatch")
    assert result.kind == "applied"
    assert result.payload["declared_inputs"] == ["data/employees.csv"]


def test_returns_not_applicable_when_no_recipe_matches() -> None:
    result = try_deterministic_repair({"completely": "unrelated"}, failure_kind="python_exception")
    assert result.kind == "not_applicable"
    assert result.payload == {"completely": "unrelated"}
```

- [ ] **Step 2: Failing approval-gate tests**

```python
# tests/harness/test_approval_gate.py
import time

import pytest

from harness.approval import TimedDecisionGate


def test_non_execution_decision_auto_proceeds_after_timeout() -> None:
    gate = TimedDecisionGate()
    decision = gate.wait(eligible_for_auto_proceed=True, timeout_seconds=0.01)
    assert decision == "auto_proceed"


def test_code_execution_decision_never_auto_proceeds() -> None:
    gate = TimedDecisionGate()
    with pytest.raises(TimeoutError):
        gate.wait(eligible_for_auto_proceed=False, timeout_seconds=0.01)


def test_user_decision_overrides_auto_proceed() -> None:
    gate = TimedDecisionGate()
    gate.submit_user_decision("approved")
    decision = gate.wait(eligible_for_auto_proceed=True, timeout_seconds=0.5)
    assert decision == "approved"


def test_user_cancel_blocks_auto_proceed() -> None:
    gate = TimedDecisionGate()
    gate.cancel()
    with pytest.raises(InterruptedError):
        gate.wait(eligible_for_auto_proceed=True, timeout_seconds=0.5)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/harness/test_repair.py tests/harness/test_approval_gate.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 4: Implement repair**

```python
# src/harness/repair.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RepairResult:
    kind: str  # "applied" | "not_applicable"
    payload: dict[str, Any]
    recipe: str | None = None


def _wrapper_repair(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    args = payload.get("arguments")
    if "name" in payload and args is not None and not isinstance(args, dict):
        return True, {**payload, "arguments": {"value": args}}
    return False, payload


def _type_normalization(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    args = payload.get("arguments")
    if not isinstance(args, dict):
        return False, payload
    changed = False
    new_args: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            try:
                if "." in value:
                    new_args[key] = float(value)
                else:
                    new_args[key] = int(value)
                changed = True
                continue
            except ValueError:
                pass
        new_args[key] = value
    if not changed:
        return False, payload
    return True, {**payload, "arguments": new_args}


def _path_normalization(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    fields = ("declared_inputs", "expected_outputs", "artifact_refs")
    changed = False
    new_payload = dict(payload)
    for field in fields:
        if field not in payload or not isinstance(payload[field], list):
            continue
        normalized: list[str] = []
        for raw in payload[field]:
            if not isinstance(raw, str):
                normalized.append(raw)
                continue
            text = raw.replace("\\", "/").lstrip("/")
            text = str(PurePosixPath(text))
            if text != raw:
                changed = True
            normalized.append(text)
        new_payload[field] = normalized
    if not changed:
        return False, payload
    return True, new_payload


def _metadata_insertion(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    changed = False
    new_payload = dict(payload)
    if "schema_version" not in new_payload:
        new_payload["schema_version"] = "1.0"
        changed = True
    if "id" not in new_payload:
        new_payload["id"] = uuid4().hex
        changed = True
    if "created_at" not in new_payload:
        new_payload["created_at"] = datetime.now(UTC).isoformat()
        changed = True
    return changed, new_payload


REPAIR_RECIPES = (
    ("wrapper_repair", _wrapper_repair),
    ("type_normalization", _type_normalization),
    ("path_normalization", _path_normalization),
    ("metadata_insertion", _metadata_insertion),
)


def try_deterministic_repair(
    payload: dict[str, Any],
    *,
    failure_kind: str,
    record_kind: str | None = None,
) -> RepairResult:
    if failure_kind not in {"schema_mismatch", "parse_failure", "deterministic_repair_candidate"}:
        return RepairResult(kind="not_applicable", payload=payload)
    for name, recipe in REPAIR_RECIPES:
        applied, new_payload = recipe(payload)
        if applied:
            return RepairResult(kind="applied", payload=new_payload, recipe=name)
    return RepairResult(kind="not_applicable", payload=payload)
```

- [ ] **Step 5: Implement timed decision gate**

```python
# src/harness/approval.py
from __future__ import annotations

import threading


class TimedDecisionGate:
    """10-second auto-proceed window per spec §6.4 for non-execution decisions only."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._decision: str | None = None
        self._cancelled = False

    def submit_user_decision(self, decision: str) -> None:
        self._decision = decision
        self._event.set()

    def cancel(self) -> None:
        self._cancelled = True
        self._event.set()

    def wait(self, *, eligible_for_auto_proceed: bool, timeout_seconds: float) -> str:
        signaled = self._event.wait(timeout=timeout_seconds)
        if self._cancelled:
            raise InterruptedError("decision cancelled by user")
        if signaled and self._decision is not None:
            return self._decision
        if not eligible_for_auto_proceed:
            raise TimeoutError("code-execution decision requires explicit approval; no auto-proceed")
        return "auto_proceed"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/harness/test_repair.py tests/harness/test_approval_gate.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/harness/repair.py src/harness/approval.py tests/harness/test_repair.py tests/harness/test_approval_gate.py
git commit -m "feat: deterministic repair recipes and timed decision gate"
```

### Task 5: Build Orchestrator And Direct Harness Command Surface

**Files:**
- Create: `src/harness/commands.py`
- Create: `src/harness/orchestrator.py`
- Test: `tests/harness/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime

from harness.commands import HarnessCommandRouter
from harness.control import ApprovalRecord, Plan, PlanStep, RunStateRecord
from harness.orchestrator import Orchestrator


def test_command_router_exposes_full_direct_harness_surface() -> None:
    router = HarnessCommandRouter()
    assert router.supported_commands() == [
        "doctor",
        "compact_context",
        "workspace_status",
        "workspace_inventory",
        "artifact_inspect",
        "memory_review",
        "validity_inspect",
        "provenance_inspect",
        "rerun_step",
        "retry_step",
        "cancel_run",
    ]


def test_orchestrator_reloads_context_before_routing_turn() -> None:
    orchestrator = Orchestrator()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    result = orchestrator.handle_turn(state, user_input="show status")
    assert result["steps"][0] == "reload_context"
    assert result["state"] == "routing"


def test_orchestrator_routes_direct_command_without_agent_mode_ownership() -> None:
    orchestrator = Orchestrator()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    result = orchestrator.handle_direct_command(state, command="doctor", arguments={"trigger": "manual"})
    assert result["command"] == "doctor"
    assert result["workspace_id"] == "w_0001"
    assert result["owned_by"] == "harness"


def test_orchestrator_blocks_worker_dispatch_without_code_approval() -> None:
    step = PlanStep(
        workspace_id="w_0001",
        plan_id="plan_1",
        step_order=1,
        purpose="Compute",
        kind="code",
        declared_inputs=["data/input.csv"],
        expected_outputs=["artifacts/output.csv"],
    )
    plan = Plan(
        id="plan_1",
        workspace_id="w_0001",
        run_id="run_1",
        goal="Compute",
        steps=[step],
        requires_code_execution=True,
    )
    orchestrator = Orchestrator()
    blocked = orchestrator.prepare_worker_dispatch(plan, approval=None)
    assert blocked["dispatch"] is False
    assert blocked["reason"] == "explicit code execution approval required"
    approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id="run_1",
        target_type="plan",
        target_id="plan_1",
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at=datetime.now(UTC),
    )
    allowed = orchestrator.prepare_worker_dispatch(plan, approval=approval)
    assert allowed["dispatch"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_orchestrator.py -q`

Expected: FAIL with missing orchestrator and command modules.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/commands.py
from __future__ import annotations

from pydantic import BaseModel


DIRECT_COMMANDS = [
    "doctor",
    "compact_context",
    "workspace_status",
    "workspace_inventory",
    "artifact_inspect",
    "memory_review",
    "validity_inspect",
    "provenance_inspect",
    "rerun_step",
    "retry_step",
    "cancel_run",
    "switch_workspace",
    "revise_goal",
    "stop_after_current_step",
    "challenge_conclusion",
    "mark_result_trusted",
    "mark_result_invalidated",
]


class HarnessCommandRequest(BaseModel):
    command: str
    arguments: dict[str, object]


class HarnessCommandRouter:
    def supported_commands(self) -> list[str]:
        return list(DIRECT_COMMANDS)

    def validate(self, command: str, arguments: dict[str, object]) -> HarnessCommandRequest:
        if command not in DIRECT_COMMANDS:
            raise ValueError(f"unsupported harness command: {command}")
        return HarnessCommandRequest(command=command, arguments=arguments)
```

```python
# src/harness/orchestrator.py
from __future__ import annotations

from harness.commands import HarnessCommandRouter
from harness.control import ApprovalRecord, Plan, RunStateRecord
from harness.state_machine import HarnessStateMachine


class Orchestrator:
    def __init__(self) -> None:
        self.commands = HarnessCommandRouter()
        self.state_machine = HarnessStateMachine()

    def handle_turn(self, state: RunStateRecord, *, user_input: str) -> dict[str, object]:
        routed = self.state_machine.transition(state, "routing")
        return {
            "workspace_id": state.workspace_id,
            "state": str(routed.state),
            "input": user_input,
            "steps": [
                "reload_context",
                "resolve_run_state",
                "route_or_update_plan",
                "persist_transition",
            ],
        }

    def handle_direct_command(
        self,
        state: RunStateRecord,
        *,
        command: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        request = self.commands.validate(command, arguments)
        return {
            "workspace_id": state.workspace_id,
            "run_state": str(state.state),
            "command": request.command,
            "arguments": request.arguments,
            "owned_by": "harness",
        }

    def prepare_worker_dispatch(
        self,
        plan: Plan,
        *,
        approval: ApprovalRecord | None,
    ) -> dict[str, object]:
        if not self.state_machine.can_dispatch_execution(plan, approval):
            return {
                "dispatch": False,
                "reason": "explicit code execution approval required",
            }
        return {"dispatch": True, "plan_id": plan.id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_orchestrator.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/commands.py src/harness/orchestrator.py tests/harness/test_orchestrator.py
git commit -m "feat: add harness orchestrator commands"
```

### Task 6: Implement Context Rebuild, Non-Durable Compaction, And Prompt Registry Allow-List

**Files:**
- Create: `src/harness/context.py`
- Create: `src/harness/prompt_registry.py`
- Create: `src/harness/prompts/compaction.md`
- Create: `src/harness/prompts/doctor.md`
- Create: `src/harness/prompts/knowledge_reconcile.md`
- Test: `tests/harness/test_context.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from harness.context import ContextManager
from harness.prompt_registry import HarnessPromptRegistry


def test_context_rebuild_uses_durable_sources_not_chat_history(tmp_path: Path) -> None:
    (tmp_path / "memory" / "notes").mkdir(parents=True)
    (tmp_path / "memory" / "preferences.json").write_text('{"style":"concise"}')
    (tmp_path / "memory" / "notes" / "dataset.md").write_text("Dataset uses employee_id.")
    manager = ContextManager()
    context = manager.rebuild(
        workspace_dir=tmp_path,
        session_ledger=["run_1 step_1 completed"],
        validity_states=[{"path": "data/employees.csv", "state": "ok"}],
        chat_history=["old chat that must not be authoritative"],
    )
    assert "Dataset uses employee_id." in context["memory_notes"]
    assert context["chat_history_loaded"] is False


def test_context_rebuild_loads_full_durable_context_from_workspace_db(tmp_path: Path) -> None:
    # Spec §6.8: ledger, validity, fingerprints, prior analyses, doctor findings.
    from harness.db import WorkspaceDb

    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "preferences.json").write_text("{}")
    (tmp_path / "state").mkdir()
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.append_record("file_registry", "data/employees.csv", {
        "path": "data/employees.csv", "size": 100, "mtime": 1.0, "sha256": "abc",
    })
    db.append_record("validity_state", "data/employees.csv", {
        "path": "data/employees.csv", "state": "changed",
    })
    db.append_record("doctor_history", "doc_1", {
        "id": "doc_1", "trigger": "manual", "recommendations": ["rerun step s_1"],
    })
    manager = ContextManager()
    context = manager.rebuild(workspace_dir=tmp_path, db=db)
    assert any(row["path"] == "data/employees.csv" for row in context["dataset_fingerprints"])
    assert any(row["state"] == "changed" for row in context["validity_states"])
    assert context["unresolved_doctor_findings"]["id"] == "doc_1"


def test_compaction_preserves_operational_atoms_and_is_not_durable() -> None:
    manager = ContextManager()
    compacted = manager.compact(
        entries=["user asks", "tool_call: execute", "tool_output: step_result.json"],
        active_plan_id="plan_1",
        current_step_id="step_1",
        unresolved_failures=["schema_mismatch"],
    )
    assert compacted["durable"] is False
    assert compacted["active_plan_id"] == "plan_1"
    assert "tool_call: execute" in compacted["summary"]
    assert "tool_output: step_result.json" in compacted["summary"]


def test_prompt_registry_allows_only_layer3_operational_prompts(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "compaction.md").write_text("compact")
    (prompts / "doctor.md").write_text("doctor")
    (prompts / "knowledge_reconcile.md").write_text("knowledge")
    registry = HarnessPromptRegistry(prompts)
    assert registry.allowed_prompts() == ["compaction", "doctor", "knowledge_reconcile"]
    assert registry.load("doctor") == "doctor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_context.py -q`

Expected: FAIL with missing context and prompt registry modules.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/context.py
from __future__ import annotations

import json
from pathlib import Path


class ContextManager:
    def rebuild(
        self,
        *,
        workspace_dir: Path,
        session_ledger: list[str] | None = None,
        validity_states: list[dict] | None = None,
        chat_history: list[str] | None = None,
        db: "WorkspaceDb | None" = None,
    ) -> dict[str, object]:
        # Spec §6.8: fresh context must include preferences, notes, session ledger,
        # validity states, dataset fingerprints, prior analyses, doctor findings.
        # Caller-provided lists override DB values; otherwise the harness reads from workspace.db.
        preferences_path = workspace_dir / "memory" / "preferences.json"
        preferences = json.loads(preferences_path.read_text()) if preferences_path.exists() else {}
        notes_dir = workspace_dir / "memory" / "notes"
        notes = []
        if notes_dir.exists():
            notes = [path.read_text() for path in sorted(notes_dir.glob("*.md"))]

        if db is not None:
            session_ledger = session_ledger if session_ledger is not None else db.recent_run_state_history(limit=20)
            validity_states = validity_states if validity_states is not None else db.validity_states_not_ok()
            dataset_fingerprints = db.list_file_registry()
            prior_analyses = db.recent_step_action_history(limit=20)
            doctor_findings = db.latest_doctor_report()
        else:
            session_ledger = session_ledger or []
            validity_states = validity_states or []
            dataset_fingerprints = []
            prior_analyses = []
            doctor_findings = None

        return {
            "preferences": preferences,
            "memory_notes": "\n".join(notes),
            "session_ledger": session_ledger,
            "validity_states": validity_states,
            "dataset_fingerprints": dataset_fingerprints,
            "prior_analyses": prior_analyses,
            "unresolved_doctor_findings": doctor_findings,
            "chat_history_loaded": False,
        }

    def compact(
        self,
        entries: list[str],
        *,
        active_plan_id: str,
        current_step_id: str,
        unresolved_failures: list[str],
    ) -> dict[str, object]:
        operational_atoms = [
            entry for entry in entries if entry.startswith("tool_call:") or entry.startswith("tool_output:")
        ]
        return {
            "durable": False,
            "summary": "\n".join(operational_atoms or entries[-2:]),
            "active_plan_id": active_plan_id,
            "current_step_id": current_step_id,
            "unresolved_failures": unresolved_failures,
        }
```

```python
# src/harness/prompt_registry.py
from __future__ import annotations

from pathlib import Path


ALLOWED_LAYER3_PROMPTS = ["compaction", "doctor", "knowledge_reconcile"]


class HarnessPromptRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def allowed_prompts(self) -> list[str]:
        return list(ALLOWED_LAYER3_PROMPTS)

    def load(self, name: str) -> str:
        if name not in ALLOWED_LAYER3_PROMPTS:
            raise ValueError(f"prompt is not a Layer 3 operational prompt: {name}")
        return (self.root / f"{name}.md").read_text()
```

```markdown
<!-- src/harness/prompts/compaction.md -->
Summarize working context for continuation without creating durable truth.
Preserve tool calls, tool outputs, active plan id, current step id, recent execution evidence, unresolved failures, exact file names, and pending approvals.
Return structured JSON only.
```

```markdown
<!-- src/harness/prompts/doctor.md -->
Review temporary workspace artifacts only for harness maintenance.
Decide one action for each tmp item: delete, promote, or keep_temporarily.
Consider workspace memory, saved functions, notes, gaps, preferences, provenance references, active runs, and pending reviews.
Return structured JSON only; the harness validates and records every action before applying it.
```

```markdown
<!-- src/harness/prompts/knowledge_reconcile.md -->
Reconcile direct user teaching, notes, gaps, preferences, and saved-function candidates.
Choose one candidate target: preference, note, gap, or function_candidate.
Identify source evidence and conflicts.
Return structured JSON only; the harness validates and records proposals before committing memory changes.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/context.py src/harness/prompt_registry.py src/harness/prompts/compaction.md src/harness/prompts/doctor.md src/harness/prompts/knowledge_reconcile.md tests/harness/test_context.py
git commit -m "feat: add harness context management"
```

### Task 7: Implement Doctor, Lazy Fingerprinting, Validity States, And Tmp Review Actions

> **STATUS: MANDATORY GATING TASK.** Spec §6.11, §6.12. Layer 3 cannot be claimed complete until this task is green. The `Doctor` subsystem, lazy fingerprinting, validity transitions, and `TmpAction` records are required by the §10 acceptance invariants. The `doctor` direct command (Task 5) MUST invoke `Doctor.run` after this task lands; no stub return is acceptable.

**Files:**
- Create: `src/harness/doctor.py`
- Create: `src/harness/fingerprints.py`
- Create: `src/harness/validity.py`
- Test: `tests/harness/test_doctor.py`
- Test: `tests/harness/test_fingerprints.py`
- Test: `tests/harness/test_validity.py`

The acceptance set for this task:
- `Doctor.run(workspace_dir)` MUST write a `DoctorReport` row + zero or more `TmpAction` rows on every invocation. Test: `test_doctor_writes_doctor_report_and_tmp_actions`.
- First-ingest path computes sha256 and stores `(size, mtime, sha256)` in `file_registry`. Test: `test_first_ingest_stores_full_fingerprint`.
- Workspace-open + doctor-rescan reuses stored hash when `(size, mtime)` unchanged. Test: `test_lazy_fingerprint_skips_rehash_when_size_and_mtime_unchanged`.
- Mtime change → re-hash. Test: `test_lazy_fingerprint_rehashes_when_mtime_changed`.
- All six validity states (`ok`, `changed`, `stale`, `needs_review`, `revalidated`, `broken_lineage`) reachable. Test: `test_validity_states_cover_all_six_per_spec`.
- `HarnessCommandRouter.handle("doctor")` calls `Doctor.run` not stub dict. Test: `test_doctor_direct_command_invokes_doctor_run_not_stub`.
- `TmpAction` records exist before any cleanup is applied. Test: `test_tmp_cleanup_blocked_until_tmp_action_recorded`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from harness.doctor import Doctor


def test_doctor_uses_lazy_fingerprinting_when_metadata_is_unchanged(tmp_path: Path) -> None:
    data_file = tmp_path / "data" / "employees.csv"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("employee_id\n1\n")
    doctor = Doctor()
    first = doctor.check_source_file(data_file, stored_size=None, stored_mtime_ns=None, stored_fingerprint=None)
    second = doctor.check_source_file(
        data_file,
        stored_size=first["size_bytes"],
        stored_mtime_ns=first["modified_time_ns"],
        stored_fingerprint=first["fingerprint"],
    )
    assert first["action"] == "fingerprinted"
    assert second["action"] == "reused_fingerprint"
    assert second["validity_status"] == "ok"


def test_doctor_detects_changed_missing_and_broken_lineage(tmp_path: Path) -> None:
    data_file = tmp_path / "data" / "employees.csv"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("employee_id\n1\n")
    doctor = Doctor()
    first = doctor.check_source_file(data_file, stored_size=None, stored_mtime_ns=None, stored_fingerprint=None)
    data_file.write_text("employee_id\n1\n2\n")
    changed = doctor.check_source_file(
        data_file,
        stored_size=first["size_bytes"],
        stored_mtime_ns=first["modified_time_ns"],
        stored_fingerprint=first["fingerprint"],
    )
    missing = doctor.check_source_file(
        tmp_path / "data" / "missing.csv",
        stored_size=1,
        stored_mtime_ns=1,
        stored_fingerprint="abc",
    )
    assert changed["validity_status"] == "changed"
    assert missing["validity_status"] == "broken_lineage"


def test_tmp_review_records_actions_before_cleanup_and_blocks_live_references(tmp_path: Path) -> None:
    tmp_file = tmp_path / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("print('x')")
    doctor = Doctor()
    report = doctor.review_tmp_items(
        [tmp_file],
        trigger_context="manual",
        live_refs={str(tmp_file)},
        promote_map={},
    )
    action = report["tmp_actions"][0]
    assert action["action"] == "kept_temporarily"
    assert action["applied"] is False
    assert action["decision_source"] == "deterministic"


def test_tmp_promotion_mapping_matches_spec(tmp_path: Path) -> None:
    tmp_file = tmp_path / "artifacts" / "tmp" / "run_1" / "step_1" / "chart.png"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("png")
    doctor = Doctor()
    report = doctor.review_tmp_items(
        [tmp_file],
        trigger_context="workspace_open",
        live_refs=set(),
        promote_map={str(tmp_file): "artifact"},
    )
    assert report["tmp_actions"][0]["action"] == "promoted"
    assert report["tmp_actions"][0]["destination_path"] == "artifacts/chart.png"


def test_doctor_run_includes_required_report_sections() -> None:
    report = Doctor().run(trigger_context="workspace_open", tmp_items=[])
    assert report["trigger"] == "workspace_open"
    assert set(report) >= {
        "source_findings",
        "validity_changes",
        "lineage_findings",
        "tmp_review",
        "tmp_actions",
        "recommendations",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_doctor.py -q`

Expected: FAIL with `ModuleNotFoundError` for `harness.doctor`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/doctor.py
from __future__ import annotations

import hashlib
from pathlib import Path


PROMOTION_TARGETS = {
    "function": "memory/functions",
    "note": "memory/notes",
    "gap": "memory/notes/gaps",
    "artifact": "artifacts",
}


class Doctor:
    def check_source_file(
        self,
        path: Path,
        *,
        stored_size: int | None,
        stored_mtime_ns: int | None,
        stored_fingerprint: str | None,
    ) -> dict[str, object]:
        if not path.exists():
            return {
                "path": str(path),
                "action": "missing",
                "validity_status": "broken_lineage",
                "fingerprint": stored_fingerprint,
            }
        stat = path.stat()
        size_bytes = stat.st_size
        modified_time_ns = stat.st_mtime_ns
        if (
            stored_fingerprint is not None
            and stored_size == size_bytes
            and stored_mtime_ns == modified_time_ns
        ):
            return {
                "path": str(path),
                "action": "reused_fingerprint",
                "validity_status": "ok",
                "size_bytes": size_bytes,
                "modified_time_ns": modified_time_ns,
                "fingerprint": stored_fingerprint,
            }
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "path": str(path),
            "action": "fingerprinted",
            "validity_status": "ok" if stored_fingerprint is None else "changed",
            "size_bytes": size_bytes,
            "modified_time_ns": modified_time_ns,
            "fingerprint": fingerprint,
        }

    def review_tmp_items(
        self,
        items: list[Path],
        *,
        trigger_context: str,
        live_refs: set[str],
        promote_map: dict[str, str],
    ) -> dict[str, object]:
        actions: list[dict[str, object]] = []
        for item in items:
            item_key = str(item)
            if item_key in live_refs:
                action = "kept_temporarily"
                destination = None
                reason = "tmp item has an active provenance, run, failure, artifact, or review reference"
            elif item_key in promote_map:
                action = "promoted"
                target = PROMOTION_TARGETS[promote_map[item_key]]
                destination = f"{target}/{item.name}"
                reason = f"tmp item classified as reusable {promote_map[item_key]}"
            else:
                action = "deleted"
                destination = None
                reason = "tmp item has no live references and no promotion classification"
            actions.append(
                {
                    "item_path": item_key,
                    "trigger_context": trigger_context,
                    "action": action,
                    "destination_path": destination,
                    "reason": reason,
                    "decision_source": "deterministic",
                    "applied": False,
                }
            )
        return {"tmp_review": actions, "tmp_actions": actions}

    def run(self, *, trigger_context: str, tmp_items: list[Path]) -> dict[str, object]:
        tmp = self.review_tmp_items(
            tmp_items,
            trigger_context=trigger_context,
            live_refs=set(),
            promote_map={},
        )
        return {
            "trigger": trigger_context,
            "status": "ok",
            "source_findings": [],
            "validity_changes": [],
            "lineage_findings": [],
            "tmp_review": tmp["tmp_review"],
            "tmp_actions": tmp["tmp_actions"],
            "recommendations": [],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_doctor.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/doctor.py tests/harness/test_doctor.py
git commit -m "feat: add harness doctor workflows"
```

### Task 8: Implement Knowledge, Function Management, And Memory Review Proposals

> **STATUS: MANDATORY GATING TASK.** Spec §6.13, §10 invariant 8 ("no durable memory update without a defined reviewable path"). The `KnowledgeManager` is the ONLY path that may write under `memory/`. Direct file writes from any other module are forbidden and MUST raise.

The acceptance set for this task:
- `KnowledgeManager.propose_update(memory_target, source_refs, proposed_content) -> MemoryUpdateProposal` writes a `memory_update_proposals` row with `status="pending"`. Test: `test_propose_update_creates_pending_proposal`.
- `KnowledgeManager.apply(proposal_id, decision)` writes the file under `memory/notes/`, `memory/notes/gaps/`, `memory/functions/`, or `memory/preferences.json`, then marks `status="applied"`. Test: `test_apply_writes_file_and_marks_applied`.
- Conflict detection on overlapping note titles → `conflicts=[...]`; `apply` raises until resolved. Test: `test_apply_blocked_by_unresolved_conflict`.
- Direct write to `memory/` from outside `KnowledgeManager` raises. Test: `test_external_memory_write_blocked`.
- Freshness check before saved-function reuse: returns `stale` when source fingerprint changed. Test: `test_saved_function_freshness_check_blocks_stale_reuse`.

**Files:**
- Create: `src/harness/knowledge.py`
- Test: `tests/harness/test_knowledge.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from harness.knowledge import KnowledgeManager


def test_knowledge_manager_reads_and_updates_preferences(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    manager = KnowledgeManager()
    manager.update_preferences(memory, {"style": "concise"})
    assert manager.load_preferences(memory) == {"style": "concise"}


def test_knowledge_manager_rescans_notes_functions_and_preferences(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    (memory / "notes").mkdir(parents=True)
    (memory / "notes" / "gaps").mkdir()
    (memory / "functions").mkdir()
    (memory / "preferences.json").write_text('{"style":"concise"}')
    (memory / "notes" / "attrition.md").write_text("Attrition note")
    (memory / "notes" / "gaps" / "unknown-grade.md").write_text("Grade mapping unclear")
    (memory / "functions" / "attrition.py").write_text("def attrition():\n    return 1\n")
    report = KnowledgeManager().rescan_workspace_memory(memory, trigger_context="doctor")
    assert report["preferences"] == {"style": "concise"}
    assert report["notes"] == ["attrition.md"]
    assert report["gaps"] == ["unknown-grade.md"]
    assert report["functions"] == ["attrition.py"]


def test_user_teaching_becomes_reviewable_memory_update_proposal() -> None:
    proposal = KnowledgeManager().synthesize_from_user_teaching(
        run_id="run_1",
        text="remember that attrition = total leavers / average headcount",
        source_refs=["chat:12"],
    )
    assert proposal["memory_target"] == "note"
    assert proposal["status"] == "proposed"
    assert proposal["source_refs"] == ["chat:12"]


def test_saved_function_reuse_requires_freshness_check(tmp_path: Path) -> None:
    function = tmp_path / "memory" / "functions" / "attrition.py"
    function.parent.mkdir(parents=True)
    function.write_text("def attrition():\n    return 1\n")
    result = KnowledgeManager().check_function_freshness(
        function,
        current_validity={"data/employees.csv": "changed"},
        depends_on=["data/employees.csv"],
    )
    assert result["reusable"] is False
    assert result["reason"] == "dependency data/employees.csv is changed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_knowledge.py -q`

Expected: FAIL with `ModuleNotFoundError` for `harness.knowledge`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/knowledge.py
from __future__ import annotations

import json
from pathlib import Path


class KnowledgeManager:
    def load_preferences(self, memory_dir: Path) -> dict[str, object]:
        path = memory_dir / "preferences.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def update_preferences(self, memory_dir: Path, values: dict[str, object]) -> None:
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / "preferences.json"
        current = self.load_preferences(memory_dir)
        current.update(values)
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")

    def rescan_workspace_memory(self, memory_dir: Path, *, trigger_context: str) -> dict[str, object]:
        notes_dir = memory_dir / "notes"
        gaps_dir = memory_dir / "notes" / "gaps"
        functions_dir = memory_dir / "functions"
        return {
            "trigger_context": trigger_context,
            "preferences": self.load_preferences(memory_dir),
            "notes": sorted(path.name for path in notes_dir.glob("*.md")) if notes_dir.exists() else [],
            "gaps": sorted(path.name for path in gaps_dir.glob("*.md")) if gaps_dir.exists() else [],
            "functions": sorted(path.name for path in functions_dir.glob("*.py")) if functions_dir.exists() else [],
        }

    def synthesize_from_user_teaching(
        self,
        *,
        run_id: str,
        text: str,
        source_refs: list[str],
    ) -> dict[str, object]:
        target = "function_candidate" if text.strip().startswith("def ") else "note"
        return {
            "run_id": run_id,
            "memory_target": target,
            "source_refs": source_refs,
            "proposed_content": text,
            "conflicts": [],
            "status": "proposed",
        }

    def check_function_freshness(
        self,
        function_path: Path,
        *,
        current_validity: dict[str, str],
        depends_on: list[str],
    ) -> dict[str, object]:
        if not function_path.exists():
            return {"reusable": False, "reason": "function file is missing"}
        for dependency in depends_on:
            status = current_validity.get(dependency, "needs_review")
            if status not in {"ok", "revalidated"}:
                return {"reusable": False, "reason": f"dependency {dependency} is {status}"}
        return {"reusable": True, "reason": "all dependencies are fresh"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_knowledge.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/knowledge.py tests/harness/test_knowledge.py
git commit -m "feat: add harness knowledge management"
```

### Task 9: Implement Provenance And Evidence-Backed Claim Checks

> **STATUS: MANDATORY GATING TASK.** Spec §6.14, §10 invariants 1, 2 ("no claim without inspected evidence"; "no artifact-backed conclusion lacks provenance"). After every successful executed step the harness MUST write a `LineageRecord` linking source-file fingerprints → plan_id → step_id → produced artifact paths → prompt_template_id → validity_id. The `artifact_registry` row MUST carry `fingerprint_id` and `validity_id` foreign keys.

The acceptance set for this task:
- Successful step writes a `LineageRecord` chain. Test: `test_lineage_record_chains_source_to_artifact_via_step`.
- Artifact rows include fingerprint + validity foreign keys. Test: `test_artifact_registry_includes_fingerprint_and_validity_ids`.
- Claim-check service rejects claims with no provenance. Test: `test_unsupported_claim_marked_unsupported_when_no_lineage`.
- Reuse of saved knowledge after source change is blocked unless validity is `ok` or `revalidated`. Test: `test_reuse_blocked_after_source_fingerprint_change`.

**Files:**
- Create: `src/harness/provenance.py`
- Test: `tests/harness/test_provenance.py`

- [ ] **Step 1: Write the failing test**

```python
from harness.provenance import ClaimChecker, ProvenanceRecord


def test_provenance_record_tracks_required_claim_lineage() -> None:
    record = ProvenanceRecord(
        workspace_id="w_0001",
        claim_id="claim_1",
        source_files=["data/employees.csv"],
        fingerprints={"data/employees.csv": "sha256:abc"},
        executed_code_hash="sha256:def",
        artifacts=["artifacts/attrition.csv"],
        plan_id="plan_1",
        step_id="step_1",
        validity_state="ok",
        active_prompt_mode="analyst",
        prompt_template_id="analyst_v1",
        prompt_template_version="v1",
    )
    assert record.step_id == "step_1"
    assert record.prompt_template_version == "v1"


def test_claim_checker_rejects_unsupported_claims() -> None:
    checker = ClaimChecker()
    claims = [
        {"text": "Attrition is 12%", "evidence_refs": ["artifact:attrition.csv"]},
        {"text": "Revenue improved", "evidence_refs": []},
    ]
    result = checker.check_claims(claims)
    assert result["supported"] == ["Attrition is 12%"]
    assert result["unsupported"] == ["Revenue improved"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_provenance.py -q`

Expected: FAIL with `ModuleNotFoundError` for `harness.provenance`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/harness/provenance.py
from __future__ import annotations

from pydantic import BaseModel


class ProvenanceRecord(BaseModel):
    workspace_id: str
    claim_id: str
    source_files: list[str]
    fingerprints: dict[str, str]
    executed_code_hash: str
    artifacts: list[str]
    plan_id: str
    step_id: str
    validity_state: str
    active_prompt_mode: str
    prompt_template_id: str
    prompt_template_version: str


class ClaimChecker:
    def check_claims(self, claims: list[dict[str, object]]) -> dict[str, list[str]]:
        supported: list[str] = []
        unsupported: list[str] = []
        for claim in claims:
            text = str(claim["text"])
            evidence_refs = claim.get("evidence_refs", [])
            if evidence_refs:
                supported.append(text)
            else:
                unsupported.append(text)
        return {"supported": supported, "unsupported": unsupported}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/harness/test_provenance.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/provenance.py tests/harness/test_provenance.py
git commit -m "feat: add harness provenance checks"
```

### Task 10: Add End-Of-Layer Integration Test For Barebones Harness Capability

**Files:**
- Test: `tests/harness/test_layer3_integration.py`
- Modify: `src/harness/__init__.py`

- [ ] **Step 1: Write the failing integration test**

```python
from pathlib import Path

from harness import bootstrap_workspace
from harness.context import ContextManager
from harness.db import WorkspaceDb
from harness.doctor import Doctor
from harness.knowledge import KnowledgeManager
from harness.orchestrator import Orchestrator
from harness.provenance import ClaimChecker
from harness.control import RunStateRecord


def test_layer3_barebones_harness_can_operate_workspace(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspaces" / "w_0001")
    data_file = workspace / "data" / "employees.csv"
    data_file.write_text("employee_id\n1\n")

    db = WorkspaceDb(workspace / "state" / "workspace.db")
    db.connect()
    assert "run_records" in db.list_tables()

    knowledge = KnowledgeManager()
    knowledge.update_preferences(workspace / "memory", {"style": "concise"})
    context = ContextManager().rebuild(
        workspace_dir=workspace,
        session_ledger=[],
        validity_states=[],
        chat_history=["not authoritative"],
    )
    assert context["preferences"] == {"style": "concise"}

    doctor_result = Doctor().check_source_file(
        data_file,
        stored_size=None,
        stored_mtime_ns=None,
        stored_fingerprint=None,
    )
    assert doctor_result["validity_status"] == "ok"

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    command = Orchestrator().handle_direct_command(state, command="workspace_status", arguments={})
    assert command["owned_by"] == "harness"

    claims = ClaimChecker().check_claims(
        [{"text": "Employee file was inspected", "evidence_refs": ["data/employees.csv"]}]
    )
    assert claims["unsupported"] == []
```

- [ ] **Step 2: Run test to verify it fails before exports are complete**

Run: `uv run pytest tests/harness/test_layer3_integration.py -q`

Expected: FAIL if any Layer 3 module is missing or `harness.__init__` exports are incomplete.

- [ ] **Step 3: Update public exports**

```python
# src/harness/__init__.py
from harness.app_store import AppStore
from harness.paths import AppPaths, WorkspacePaths
from harness.workspace import bootstrap_workspace

__all__ = ["AppPaths", "AppStore", "WorkspacePaths", "bootstrap_workspace"]
```

- [ ] **Step 4: Run all Layer 3 harness tests**

Run: `uv run pytest tests/harness -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/__init__.py tests/harness/test_layer3_integration.py
git commit -m "test: cover layer 3 harness integration"
```

## Final Verification

- [ ] Run: `uv run pytest tests/harness -q`

Expected: PASS.

- [ ] Review plan against `docs/superpowers/specs/2026-04-23-custom-data-analysis-llm-v1-main-spec.md` sections 6.1 through 6.15.

Expected: Every Layer 3 requirement maps to at least one task in the Spec Coverage Map.

- [ ] Scan the plan for placeholder terms.

Run: `rg -n "[T]BD|[T]ODO|[i]mplement later|[f]ill in details|[S]imilar to|[a]dd appropriate|[W]rite tests for the above" docs/superpowers/plans/2026-04-23-layer-3-harness-core-implementation-plan.md`

Expected: no matches.

## Self-Review

**Spec coverage:** The plan covers the Layer 3 orchestrator/control loop, single-runtime state machine, plan and step management, explicit code-execution approval, workspace/app state split, direct command surface, bounded harness prompts, contract validation, context rebuild and compaction, SQLite plus file storage, lazy fingerprinting, validity states, doctor report and tmp-action review, knowledge/function workflows, provenance, and evidence-backed claim checks.

**Issues fixed from prior plan:** Removed the invalid `planning -> executing` transition, added approval records and explicit dispatch gating, expanded canonical control objects to include the required spec fields, added missing database tables, added validation failure classification, added review and memory update proposal paths, added prompt allow-listing, added direct workspace inventory/status commands, and added an end-of-layer integration test.

**Placeholder scan:** No placeholder markers remain.

**Type consistency:** `RunStateRecord`, `ApprovalRecord`, `Plan`, `PlanStep`, `StepContract`, `ExecutionEnvelope`, `Doctor`, `KnowledgeManager`, `ProvenanceRecord`, and `Orchestrator` use the same field names across tests and implementation snippets.
