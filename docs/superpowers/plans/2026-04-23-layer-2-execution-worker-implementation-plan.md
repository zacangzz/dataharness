# Layer 2 Execution Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the controlled Python execution worker required by Layer 2: sandboxed step execution, workspace-local tmp evidence, canonical execution envelopes, raw runtime metadata, and deterministic failure reporting.

**Architecture:** Implement the worker as a focused `src/worker/` package. The harness owns planning, approval, execution policy, provenance interpretation, memory, doctor, and final-answer authority; the worker only consumes an already-approved executable step contract, executes it inside a constrained Python subprocess, writes raw evidence under `artifacts/tmp/<run_id>/<step_id>/`, and returns a typed envelope. All persisted path fields are workspace-relative so envelopes remain portable across machines.

**Tech Stack:** Python 3.12, `pydantic`, `pytest`, `subprocess`, `json`, `ast`, `hashlib`, `pathlib`, `resource` on POSIX

---

## File Structure

**Create:**
- `src/worker/__init__.py` - public worker exports.
- `src/worker/models.py` - Pydantic request, envelope, enum, and metadata models.
- `src/worker/paths.py` - workspace-relative path helpers and tmp layout functions.
- `src/worker/policy.py` - path, package, runtime, and resource policy validation.
- `src/worker/sandbox_bootstrap.py` - constrained subprocess entrypoint used by the executor.
- `src/worker/executor.py` - Python step executor that writes canonical evidence and envelopes.
- `tests/worker/test_models_and_paths.py`
- `tests/worker/test_policy.py`
- `tests/worker/test_executor.py`

## Layer Boundary Notes

- The worker receives a `StepExecutionRequest` only after the harness has explicitly approved the executable plan or executable step.
- The worker must not create, infer, expire, or auto-approve approval records.
- The worker enforces the permission envelope it receives, but it does not decide harness execution policy.
- The worker records execution facts; it does not create semantic conclusions, memory updates, doctor decisions, provenance validity decisions, or final answers.

### Task 1: Define Typed Contracts And Workspace-Relative Paths

**Files:**
- Create: `src/worker/__init__.py`
- Create: `src/worker/models.py`
- Create: `src/worker/paths.py`
- Test: `tests/worker/test_models_and_paths.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from worker.models import (
    ExecutionEnvelope,
    ExecutionStatus,
    FailureKind,
    PermissionEnvelope,
    ResourceLimits,
    StepExecutionRequest,
)
from worker.paths import build_step_tmp_dir, to_workspace_relative


def test_step_tmp_dir_uses_workspace_artifacts_tmp_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    path = build_step_tmp_dir(workspace, run_id="r_0001", step_id="s_0003")
    assert path == workspace / "artifacts" / "tmp" / "r_0001" / "s_0003"


def test_workspace_relative_paths_are_portable(tmp_path: Path) -> None:
    workspace = tmp_path / "w_0001"
    path = workspace / "artifacts" / "tmp" / "r_1" / "s_1" / "stdout.txt"
    assert to_workspace_relative(workspace, path) == Path("artifacts/tmp/r_1/s_1/stdout.txt")


def test_request_tracks_declared_inputs_permissions_outputs_and_run_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "w_0001"
    request = StepExecutionRequest(
        id="step_contract_r_1_s_1",
        workspace_id="w_0001",
        run_id="r_1",
        plan_id="p_1",
        step_id="s_1",
        workspace_dir=workspace,
        code="print('ok')",
        declared_inputs={"employees": "data/employees.csv"},
        workspace_paths={"tmp_root": "artifacts/tmp"},
        permission_envelope=PermissionEnvelope(
            allowed_read_paths=["data/employees.csv"],
            registered_artifact_paths=["artifacts/previous/table.csv"],
            allowed_write_roots=["artifacts/tmp"],
            allowed_packages=["json", "pandas"],
        ),
        expected_output_contract=["table.csv"],
        run_metadata={"attempt": 1},
        resource_limits=ResourceLimits(timeout_seconds=30, memory_mb=512, artifact_bytes=10_000_000),
    )
    assert request.schema_version == "1.0"
    assert request.declared_inputs["employees"] == "data/employees.csv"
    assert request.permission_envelope.allowed_write_roots == ["artifacts/tmp"]
    assert request.expected_output_contract == ["table.csv"]


def test_envelope_uses_spec_field_names_and_workspace_relative_paths() -> None:
    envelope = ExecutionEnvelope(
        id="env_r_1_s_1",
        workspace_id="w_0001",
        run_id="r_1",
        step_id="s_1",
        status=ExecutionStatus.OK,
        step_result_path="artifacts/tmp/r_1/s_1/step_result.json",
        step_report_path="artifacts/tmp/r_1/s_1/step_report.md",
        stdout_path="artifacts/tmp/r_1/s_1/stdout.txt",
        stderr_path="artifacts/tmp/r_1/s_1/stderr.txt",
        artifact_refs=["artifacts/tmp/r_1/s_1/table.csv"],
        execution_metadata={"code_hash": "abc"},
        failure_kind=FailureKind.OK,
    )
    assert envelope.schema_version == "1.0"
    assert envelope.status == ExecutionStatus.OK
    assert envelope.step_result_path == "artifacts/tmp/r_1/s_1/step_result.json"
    assert envelope.stdout_path.endswith("stdout.txt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/worker/test_models_and_paths.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'worker'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/worker/models.py
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

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
    timeout_seconds: int = 60
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
    artifact_refs: list[str]
    execution_metadata: dict[str, Any]
    failure_kind: FailureKind
```

```python
# src/worker/paths.py
from __future__ import annotations

from pathlib import Path


def build_step_tmp_dir(workspace_dir: Path, *, run_id: str, step_id: str) -> Path:
    return workspace_dir / "artifacts" / "tmp" / run_id / step_id


def to_workspace_relative(workspace_dir: Path, path: Path) -> Path:
    return path.resolve().relative_to(workspace_dir.resolve())


def as_posix_workspace_relative(workspace_dir: Path, path: Path) -> str:
    return to_workspace_relative(workspace_dir, path).as_posix()
```

```python
# src/worker/__init__.py
from worker.models import (
    ExecutionEnvelope,
    ExecutionStatus,
    FailureKind,
    PermissionEnvelope,
    ResourceLimits,
    StepExecutionRequest,
)

__all__ = [
    "ExecutionEnvelope",
    "ExecutionStatus",
    "FailureKind",
    "PermissionEnvelope",
    "ResourceLimits",
    "StepExecutionRequest",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/worker/test_models_and_paths.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/worker/__init__.py src/worker/models.py src/worker/paths.py tests/worker/test_models_and_paths.py
git commit -m "feat: add worker execution contracts"
```

### Task 2: Enforce Permission Envelope Before Dispatch

**Files:**
- Create: `src/worker/policy.py`
- Test: `tests/worker/test_policy.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from worker.models import PermissionEnvelope, ResourceLimits
from worker.policy import WorkerPolicyError, WorkerPolicyValidator


def test_policy_allows_declared_reads_registered_artifacts_and_tmp_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "w_0001"
    validator = WorkerPolicyValidator(
        workspace,
        PermissionEnvelope(
            allowed_read_paths=["data/employees.csv"],
            registered_artifact_paths=["artifacts/previous/table.csv"],
            allowed_write_roots=["artifacts/tmp"],
            allowed_packages=["json", "pandas"],
        ),
    )
    assert validator.validate_read("data/employees.csv") == workspace / "data" / "employees.csv"
    assert validator.validate_read("artifacts/previous/table.csv") == workspace / "artifacts" / "previous" / "table.csv"
    assert validator.validate_write("artifacts/tmp/r_1/s_1/table.csv") == workspace / "artifacts" / "tmp" / "r_1" / "s_1" / "table.csv"


def test_policy_blocks_data_memory_state_and_durable_artifact_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "w_0001"
    validator = WorkerPolicyValidator(workspace, PermissionEnvelope())
    for path in ["data/raw.csv", "memory/notes/x.md", "state/workspace.db", "artifacts/final/table.csv"]:
        with pytest.raises(WorkerPolicyError, match="write outside allowed tmp roots"):
            validator.validate_write(path)


def test_policy_rejects_absolute_paths_and_escape_segments(tmp_path: Path) -> None:
    workspace = tmp_path / "w_0001"
    validator = WorkerPolicyValidator(workspace, PermissionEnvelope(allowed_read_paths=["data/employees.csv"]))
    with pytest.raises(WorkerPolicyError, match="workspace-relative"):
        validator.validate_read("/etc/passwd")
    with pytest.raises(WorkerPolicyError, match="workspace escape"):
        validator.validate_read("../outside.csv")


def test_policy_rejects_disallowed_imports_network_and_shell(tmp_path: Path) -> None:
    workspace = tmp_path / "w_0001"
    validator = WorkerPolicyValidator(
        workspace,
        PermissionEnvelope(allowed_packages=["json"], allow_network=False, allow_shell=False),
    )
    validator.validate_code_imports("import json\nprint(json.dumps({'ok': True}))")
    with pytest.raises(WorkerPolicyError, match="package not allowed"):
        validator.validate_code_imports("import pandas as pd")
    with pytest.raises(WorkerPolicyError, match="network import not allowed"):
        validator.validate_code_imports("import socket")
    with pytest.raises(WorkerPolicyError, match="shell import not allowed"):
        validator.validate_code_imports("import subprocess")


def test_policy_accepts_resource_limits_with_positive_ceilings(tmp_path: Path) -> None:
    validator = WorkerPolicyValidator(tmp_path / "w_0001", PermissionEnvelope())
    validator.validate_resource_limits(ResourceLimits(timeout_seconds=1, memory_mb=128, artifact_bytes=1024))
    with pytest.raises(WorkerPolicyError, match="positive"):
        validator.validate_resource_limits(ResourceLimits(timeout_seconds=0, memory_mb=128, artifact_bytes=1024))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/worker/test_policy.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'worker.policy'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/worker/policy.py
from __future__ import annotations

import ast
from pathlib import Path

from worker.models import PermissionEnvelope, ResourceLimits


class WorkerPolicyError(ValueError):
    pass


class WorkerPolicyValidator:
    def __init__(self, workspace_dir: Path, permission_envelope: PermissionEnvelope) -> None:
        self.workspace_dir = workspace_dir.resolve()
        self.permission_envelope = permission_envelope

    def _resolve_relative(self, path_text: str) -> Path:
        path = Path(path_text)
        if path.is_absolute():
            raise WorkerPolicyError(f"path must be workspace-relative: {path_text}")
        candidate = (self.workspace_dir / path).resolve()
        if not candidate.is_relative_to(self.workspace_dir):
            raise WorkerPolicyError(f"workspace escape blocked: {path_text}")
        return candidate

    def validate_read(self, path_text: str) -> Path:
        allowed = set(self.permission_envelope.allowed_read_paths + self.permission_envelope.registered_artifact_paths)
        if path_text not in allowed:
            raise WorkerPolicyError(f"read outside allowed inputs: {path_text}")
        return self._resolve_relative(path_text)

    def validate_write(self, path_text: str) -> Path:
        candidate = self._resolve_relative(path_text)
        allowed_roots = [self._resolve_relative(root) for root in self.permission_envelope.allowed_write_roots]
        if any(candidate.is_relative_to(root) for root in allowed_roots):
            return candidate
        raise WorkerPolicyError(f"write outside allowed tmp roots: {path_text}")

    def validate_code_imports(self, code: str) -> None:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            else:
                continue
            for name in names:
                if name in {"socket", "urllib", "http", "requests"} and not self.permission_envelope.allow_network:
                    raise WorkerPolicyError(f"network import not allowed: {name}")
                if name in {"subprocess", "pty", "shlex"} and not self.permission_envelope.allow_shell:
                    raise WorkerPolicyError(f"shell import not allowed: {name}")
                if name not in self.permission_envelope.allowed_packages and name not in {"pathlib", "json", "csv", "math", "statistics"}:
                    raise WorkerPolicyError(f"package not allowed: {name}")

    def validate_resource_limits(self, limits: ResourceLimits) -> None:
        values = [limits.timeout_seconds, limits.memory_mb, limits.artifact_bytes, limits.stdout_bytes, limits.stderr_bytes]
        if any(value <= 0 for value in values):
            raise WorkerPolicyError("resource ceilings must be positive")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/worker/test_policy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/worker/policy.py tests/worker/test_policy.py
git commit -m "feat: validate worker permission envelope"
```

### Task 3: Add Subprocess Sandbox Bootstrap

**Files:**
- Modify: `src/worker/__init__.py`
- Create: `src/worker/executor.py`
- Create: `src/worker/sandbox_bootstrap.py`
- Test: `tests/worker/test_executor.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from worker.executor import PythonStepExecutor
from worker.models import PermissionEnvelope, ResourceLimits, StepExecutionRequest


def make_request(tmp_path: Path, *, code: str, expected_outputs: list[str] | None = None) -> StepExecutionRequest:
    workspace = tmp_path / "w_0001"
    return StepExecutionRequest(
        id="step_contract_r_1_s_1",
        workspace_id="w_0001",
        run_id="r_1",
        plan_id="p_1",
        step_id="s_1",
        workspace_dir=workspace,
        code=code,
        declared_inputs={},
        workspace_paths={"tmp_root": "artifacts/tmp"},
        permission_envelope=PermissionEnvelope(
            allowed_read_paths=[],
            registered_artifact_paths=[],
            allowed_write_roots=["artifacts/tmp"],
            allowed_packages=["json", "pathlib", "time"],
        ),
        expected_output_contract=expected_outputs or [],
        run_metadata={"attempt": 1},
        resource_limits=ResourceLimits(timeout_seconds=2, memory_mb=128, artifact_bytes=100_000),
    )


def test_executor_blocks_network_import_at_policy_layer(tmp_path: Path) -> None:
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="import socket"))
    assert envelope.status == "sandbox_error"
    assert envelope.failure_kind == "sandbox_violation"


def test_executor_blocks_runtime_write_outside_tmp(tmp_path: Path) -> None:
    code = "from pathlib import Path\nPath('../../../../memory/x.md').write_text('bad')"
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code=code))
    assert envelope.status == "sandbox_error"
    assert envelope.failure_kind == "sandbox_violation"
    stderr = (tmp_path / "w_0001" / envelope.stderr_path).read_text()
    assert "write outside sandbox" in stderr


def test_executor_blocks_dynamic_import_of_disallowed_package(tmp_path: Path) -> None:
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="__import__('pandas')"))
    assert envelope.status == "sandbox_error"
    assert envelope.failure_kind == "sandbox_violation"
    stderr = (tmp_path / "w_0001" / envelope.stderr_path).read_text()
    assert "package not allowed at runtime" in stderr


def test_executor_times_out_long_running_code(tmp_path: Path) -> None:
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="import time\ntime.sleep(10)"))
    assert envelope.status == "timeout"
    assert envelope.failure_kind == "timeout_or_resource_exhaustion"


def test_executor_writes_stdout_and_stderr_evidence_files(tmp_path: Path) -> None:
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="print('hello')"))
    workspace = tmp_path / "w_0001"
    assert (workspace / envelope.stdout_path).read_text() == "hello\n"
    assert (workspace / envelope.stderr_path).read_text() == ""
    result = json.loads((workspace / envelope.step_result_path).read_text())
    assert result["status"] == "ok"


def test_executor_passes_memory_ceiling_to_sandbox_config(tmp_path: Path) -> None:
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="print('ok')"))
    workspace = tmp_path / "w_0001"
    config = json.loads((workspace / "artifacts/tmp/r_1/s_1/sandbox_config.json").read_text())
    assert config["memory_bytes"] == 128 * 1024 * 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/worker/test_executor.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'worker.executor'`.

- [ ] **Step 3: Write minimal sandbox bootstrap implementation**

```python
# src/worker/sandbox_bootstrap.py
from __future__ import annotations

import builtins
import json
import os
import runpy
import sys
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    config = json.loads(Path(sys.argv[1]).read_text())
    tmp_dir = Path(config["tmp_dir"]).resolve()
    workspace_dir = Path(config["workspace_dir"]).resolve()
    allowed_reads = {Path(path).resolve() for path in config["allowed_reads"]}
    allowed_write_roots = [Path(path).resolve() for path in config["allowed_write_roots"]]
    allowed_code_roots = [Path(path).resolve() for path in config["allowed_code_roots"]]
    allowed_packages = set(config["allowed_packages"])
    allow_network = bool(config["allow_network"])
    allow_shell = bool(config["allow_shell"])
    script_path = Path(config["script_path"]).resolve()
    memory_bytes = int(config["memory_bytes"])

    if resource is not None:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

    original_import = builtins.__import__

    def guarded_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0) -> object:
        root_name = name.split(".", 1)[0]
        if root_name in {"socket", "urllib", "http", "requests"} and not allow_network:
            raise PermissionError(f"network import not allowed at runtime: {root_name}")
        if root_name in {"subprocess", "pty", "shlex"} and not allow_shell:
            raise PermissionError(f"shell import not allowed at runtime: {root_name}")
        if root_name not in allowed_packages and root_name not in {"pathlib", "json", "csv", "math", "statistics", "time"}:
            raise PermissionError(f"package not allowed at runtime: {root_name}")
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = guarded_import

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event == "open" and args:
            target = args[0]
            mode = str(args[1]) if len(args) > 1 and args[1] is not None else "r"
            if not isinstance(target, (str, bytes, os.PathLike)):
                return
            path = Path(target).resolve()
            if any(flag in mode for flag in ("w", "a", "+", "x")):
                if not any(_is_relative_to(path, root) for root in allowed_write_roots):
                    raise PermissionError(f"write outside sandbox: {path}")
            elif _is_relative_to(path, workspace_dir) and not (_is_relative_to(path, tmp_dir) or path in allowed_reads or path == script_path):
                raise PermissionError(f"read outside sandbox: {path}")
            elif not _is_relative_to(path, workspace_dir) and path.suffix in {".py", ".pyc", ".so", ".pyd", ".dll", ".dylib"}:
                if not any(_is_relative_to(path, root) for root in allowed_code_roots):
                    raise PermissionError(f"code import outside allowed runtime roots: {path}")
        if event in {"socket.__new__", "subprocess.Popen", "os.system"}:
            raise PermissionError(f"operation blocked by sandbox: {event}")

    sys.addaudithook(audit)
    runpy.run_path(str(script_path), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write minimal executor implementation**

```python
# src/worker/executor.py
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from worker.models import ExecutionEnvelope, ExecutionStatus, FailureKind, StepExecutionRequest
from worker.paths import as_posix_workspace_relative, build_step_tmp_dir
from worker.policy import WorkerPolicyError, WorkerPolicyValidator


def allowed_code_roots() -> list[str]:
    return [str(Path(entry).resolve()) for entry in sys.path if entry]


class PythonStepExecutor:
    def execute(self, request: StepExecutionRequest) -> ExecutionEnvelope:
        tmp_dir = build_step_tmp_dir(request.workspace_dir, run_id=request.run_id, step_id=request.step_id)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = tmp_dir / "stdout.txt"
        stderr_path = tmp_dir / "stderr.txt"
        script_path = tmp_dir / "step.py"
        config_path = tmp_dir / "sandbox_config.json"
        script_path.write_text(request.code)

        try:
            validator = WorkerPolicyValidator(request.workspace_dir, request.permission_envelope)
            validator.validate_resource_limits(request.resource_limits)
            validator.validate_code_imports(request.code)
            allowed_reads = [
                str(validator.validate_read(path))
                for path in request.permission_envelope.allowed_read_paths + request.permission_envelope.registered_artifact_paths
            ]
            allowed_write_roots = [str(validator.validate_write(f"{root}/{request.run_id}/{request.step_id}")) for root in request.permission_envelope.allowed_write_roots]
        except WorkerPolicyError as exc:
            stdout_path.write_text("")
            stderr_path.write_text(str(exc))
            return self._write_envelope(request, tmp_dir, stdout_path, stderr_path, ExecutionStatus.SANDBOX_ERROR, FailureKind.SANDBOX_VIOLATION, str(exc))

        config_path.write_text(json.dumps({
            "tmp_dir": str(tmp_dir),
            "workspace_dir": str(request.workspace_dir),
            "allowed_reads": allowed_reads,
            "allowed_write_roots": allowed_write_roots,
            "allowed_code_roots": allowed_code_roots(),
            "allowed_packages": request.permission_envelope.allowed_packages,
            "allow_network": request.permission_envelope.allow_network,
            "allow_shell": request.permission_envelope.allow_shell,
            "script_path": str(script_path),
            "memory_bytes": request.resource_limits.memory_mb * 1024 * 1024,
        }))
        command = [sys.executable, "-m", "worker.sandbox_bootstrap", str(config_path)]
        started_at = datetime.now(UTC)
        try:
            completed = subprocess.run(command, cwd=tmp_dir, text=True, capture_output=True, timeout=request.resource_limits.timeout_seconds, check=False)
            self._last_started_at = started_at
            self._last_finished_at = datetime.now(UTC)
            stdout_path.write_text(completed.stdout[: request.resource_limits.stdout_bytes])
            stderr_path.write_text(completed.stderr[: request.resource_limits.stderr_bytes])
            if completed.returncode == 0:
                return self._write_envelope(request, tmp_dir, stdout_path, stderr_path, ExecutionStatus.OK, FailureKind.OK, None)
            if self._is_sandbox_violation(completed.stderr):
                return self._write_envelope(request, tmp_dir, stdout_path, stderr_path, ExecutionStatus.SANDBOX_ERROR, FailureKind.SANDBOX_VIOLATION, completed.stderr)
            return self._write_envelope(request, tmp_dir, stdout_path, stderr_path, ExecutionStatus.EXECUTION_ERROR, FailureKind.PYTHON_EXCEPTION, completed.stderr)
        except subprocess.TimeoutExpired as exc:
            self._last_finished_at = datetime.now(UTC)
            stdout_path.write_text((exc.stdout or "")[: request.resource_limits.stdout_bytes])
            stderr_path.write_text((exc.stderr or "execution timed out")[: request.resource_limits.stderr_bytes])
            return self._write_envelope(request, tmp_dir, stdout_path, stderr_path, ExecutionStatus.TIMEOUT, FailureKind.TIMEOUT_OR_RESOURCE_EXHAUSTION, "execution timed out")

    def _is_sandbox_violation(self, stderr: str) -> bool:
        markers = (
            "PermissionError:",
            "write outside sandbox",
            "read outside sandbox",
            "operation blocked by sandbox",
            "package not allowed at runtime",
            "network import not allowed at runtime",
            "shell import not allowed at runtime",
        )
        return any(marker in stderr for marker in markers)

    def _package_versions(self, packages: list[str]) -> dict[str, str]:
        versions: dict[str, str] = {}
        for package in packages:
            try:
                versions[package] = version(package)
            except PackageNotFoundError:
                versions[package] = "not-installed-or-stdlib"
        return versions

    def _write_envelope(
        self,
        request: StepExecutionRequest,
        tmp_dir: Path,
        stdout_path: Path,
        stderr_path: Path,
        status: ExecutionStatus,
        failure_kind: FailureKind,
        failure_summary: str | None,
    ) -> ExecutionEnvelope:
        result_path = tmp_dir / "step_result.json"
        report_path = tmp_dir / "step_report.md"
        artifact_refs = [
            as_posix_workspace_relative(request.workspace_dir, path)
            for path in tmp_dir.iterdir()
            if path.name not in {"step.py", "sandbox_config.json", "step_result.json", "step_report.md", "stdout.txt", "stderr.txt"}
        ]
        started_at = getattr(self, "_last_started_at", datetime.now(UTC))
        finished_at = getattr(self, "_last_finished_at", datetime.now(UTC))
        metadata: dict[str, Any] = {
            "code_hash": hashlib.sha256(request.code.encode("utf-8")).hexdigest(),
            "environment": {"python": sys.version, "platform": platform.platform()},
            "package_versions": self._package_versions(request.permission_envelope.allowed_packages),
            "input_refs": request.declared_inputs,
            "produced_artifact_paths": artifact_refs,
            "run_id": request.run_id,
            "step_id": request.step_id,
            "run_metadata": request.run_metadata,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
        }
        # Canonical StepResult shape per spec §6.6. Failures NEVER appear in `claims`.
        # Worker writes empty observations/claims; the harness populates them after inspection.
        now_iso = datetime.now(UTC).isoformat()
        canonical_step_result = {
            "schema_version": "1.0",
            "id": f"step_result_{request.run_id}_{request.step_id}",
            "workspace_id": request.workspace_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "run_id": request.run_id,
            "step_id": request.step_id,
            "status": str(status),
            "observations": [],
            "claims": [],
            "artifact_refs": artifact_refs,
            "metrics": {},
            "failure_summary": failure_summary,
        }
        result_path.write_text(json.dumps(canonical_step_result, indent=2))
        report_path.write_text(f"# Step Report\n\nstatus: {status}\nfailure_kind: {failure_kind}\n")
        return ExecutionEnvelope(
            id=f"exec_{request.run_id}_{request.step_id}",
            workspace_id=request.workspace_id,
            run_id=request.run_id,
            step_id=request.step_id,
            status=status,
            step_result_path=as_posix_workspace_relative(request.workspace_dir, result_path),
            step_report_path=as_posix_workspace_relative(request.workspace_dir, report_path),
            stdout_path=as_posix_workspace_relative(request.workspace_dir, stdout_path),
            stderr_path=as_posix_workspace_relative(request.workspace_dir, stderr_path),
            artifact_refs=artifact_refs,
            execution_metadata=metadata,
            failure_kind=failure_kind,
        )
```

- [ ] **Step 5: Update public package exports**

```python
# src/worker/__init__.py
from worker.executor import PythonStepExecutor
from worker.models import (
    ExecutionEnvelope,
    ExecutionStatus,
    FailureKind,
    PermissionEnvelope,
    ResourceLimits,
    StepExecutionRequest,
)

__all__ = [
    "ExecutionEnvelope",
    "ExecutionStatus",
    "FailureKind",
    "PermissionEnvelope",
    "PythonStepExecutor",
    "ResourceLimits",
    "StepExecutionRequest",
]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/worker/test_executor.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/worker/__init__.py src/worker/sandbox_bootstrap.py src/worker/executor.py tests/worker/test_executor.py
git commit -m "feat: execute python steps in constrained worker"
```

### Task 4: Validate Output Contract, Malformed Result JSON, And Artifact Size

**Files:**
- Modify: `src/worker/executor.py`
- Test: `tests/worker/test_executor.py`

- [ ] **Step 1: Add failing tests**

```python
def test_executor_flags_missing_expected_outputs(tmp_path: Path) -> None:
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="print('ok')", expected_outputs=["table.csv"]))
    assert envelope.status == "contract_error"
    assert envelope.failure_kind == "missing_output_files"


def test_executor_flags_partial_artifact_generation(tmp_path: Path) -> None:
    code = "from pathlib import Path\nPath('table.csv').write_text('x')"
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code=code, expected_outputs=["table.csv", "chart.png"]))
    assert envelope.status == "contract_error"
    assert envelope.failure_kind == "partial_artifact_generation"


def test_executor_preserves_malformed_step_result_before_writing_canonical_failure(tmp_path: Path) -> None:
    code = "from pathlib import Path\nPath('step_result.json').write_text('{bad json')\nPath('table.csv').write_text('x')"
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code=code, expected_outputs=["table.csv"]))
    workspace = tmp_path / "w_0001"
    assert envelope.status == "contract_error"
    assert envelope.failure_kind == "malformed_result_json"
    assert (workspace / "artifacts/tmp/r_1/s_1/malformed_step_result.json").read_text() == "{bad json"
    assert json.loads((workspace / envelope.step_result_path).read_text())["failure_kind"] == "malformed_result_json"


def test_executor_flags_artifact_size_resource_exhaustion(tmp_path: Path) -> None:
    request = make_request(tmp_path, code="from pathlib import Path\nPath('large.bin').write_bytes(b'x' * 2048)", expected_outputs=["large.bin"])
    request.resource_limits.artifact_bytes = 128
    envelope = PythonStepExecutor().execute(request)
    assert envelope.status == "resource_exhausted"
    assert envelope.failure_kind == "timeout_or_resource_exhaustion"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/worker/test_executor.py -q`

Expected: FAIL because output contract, malformed JSON preservation, and artifact-size checks are not implemented.

- [ ] **Step 3: Extend executor with contract validation**

```python
# Add these methods inside PythonStepExecutor in src/worker/executor.py.
    def _classify_success_contract(self, request: StepExecutionRequest, tmp_dir: Path) -> tuple[ExecutionStatus, FailureKind, str | None]:
        malformed_result = self._preserve_malformed_user_result(tmp_dir)
        if malformed_result:
            return ExecutionStatus.CONTRACT_ERROR, FailureKind.MALFORMED_RESULT_JSON, malformed_result
        expected = set(request.expected_output_contract)
        produced = {path.name for path in tmp_dir.iterdir() if path.is_file()}
        produced_contract_outputs = expected.intersection(produced)
        missing = sorted(expected - produced)
        if missing and produced_contract_outputs:
            return ExecutionStatus.CONTRACT_ERROR, FailureKind.PARTIAL_ARTIFACT_GENERATION, f"missing expected outputs: {missing}"
        if missing:
            return ExecutionStatus.CONTRACT_ERROR, FailureKind.MISSING_OUTPUT_FILES, f"missing expected outputs: {missing}"
        total_bytes = sum(path.stat().st_size for path in tmp_dir.iterdir() if path.is_file())
        if total_bytes > request.resource_limits.artifact_bytes:
            return ExecutionStatus.RESOURCE_EXHAUSTED, FailureKind.TIMEOUT_OR_RESOURCE_EXHAUSTION, f"artifact byte limit exceeded: {total_bytes}"
        return ExecutionStatus.OK, FailureKind.OK, None

    def _preserve_malformed_user_result(self, tmp_dir: Path) -> str | None:
        result_path = tmp_dir / "step_result.json"
        if not result_path.exists():
            return None
        raw = result_path.read_text()
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            malformed_path = tmp_dir / "malformed_step_result.json"
            malformed_path.write_text(raw)
            result_path.unlink()
            return f"malformed result JSON: {exc.msg}"
        return None
```

```python
# Replace the return branch for completed.returncode == 0 in execute().
            if completed.returncode == 0:
                status, failure_kind, failure_summary = self._classify_success_contract(request, tmp_dir)
                return self._write_envelope(request, tmp_dir, stdout_path, stderr_path, status, failure_kind, failure_summary)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/worker/test_executor.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/worker/executor.py tests/worker/test_executor.py
git commit -m "feat: classify worker output contract failures"
```

### Task 5: Record Raw Evidence And Preserve Non-Semantic Boundaries

**Files:**
- Modify: `src/worker/executor.py`
- Test: `tests/worker/test_executor.py`

- [ ] **Step 1: Add failing tests**

```python
def test_envelope_records_audit_metadata_without_semantic_fields(tmp_path: Path) -> None:
    from datetime import datetime

    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="print('ok')"))
    metadata = envelope.execution_metadata
    assert metadata["code_hash"]
    assert metadata["environment"]["python"]
    assert "json" in metadata["package_versions"]
    assert metadata["input_refs"] == {}
    assert metadata["produced_artifact_paths"] == []
    assert metadata["run_id"] == "r_1"
    assert metadata["step_id"] == "s_1"
    # Spec §5.5 timestamps must be present in ISO 8601 with timezone.
    started = datetime.fromisoformat(metadata["started_at"])
    finished = datetime.fromisoformat(metadata["finished_at"])
    assert started.tzinfo is not None
    assert finished.tzinfo is not None
    assert metadata["duration_ms"] >= 0
    assert "semantic_conclusion" not in metadata
    assert "memory_update" not in metadata
    assert "doctor_decision" not in metadata
    assert "final_answer" not in metadata


def test_step_result_json_matches_canonical_schema_and_keeps_claims_empty_on_failure(tmp_path: Path) -> None:
    # The worker MUST write the canonical StepResult shape per spec §6.6, never the
    # ExecutionEnvelope-shape. Failures NEVER appear as analytical claims.
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="raise RuntimeError('boom')"))
    workspace = tmp_path / "w_0001"
    payload = json.loads((workspace / envelope.step_result_path).read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["run_id"] == "r_1"
    assert payload["step_id"] == "s_1"
    assert payload["observations"] == []
    assert payload["claims"] == []
    assert payload["metrics"] == {}
    assert "failure_summary" in payload
    # Envelope-only fields must not leak into step_result.json.
    assert "failure_kind" not in payload


def test_harness_can_deserialize_worker_step_result_into_canonical_object(tmp_path: Path) -> None:
    from harness.control import StepResult

    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="print('ok')"))
    workspace = tmp_path / "w_0001"
    raw = (workspace / envelope.step_result_path).read_text()
    parsed = StepResult.model_validate_json(raw)
    assert parsed.run_id == "r_1"
    assert parsed.step_id == "s_1"
    assert parsed.claims == []


def test_envelope_exists_even_when_policy_validation_fails(tmp_path: Path) -> None:
    envelope = PythonStepExecutor().execute(make_request(tmp_path, code="import requests"))
    workspace = tmp_path / "w_0001"
    assert envelope.status == "sandbox_error"
    assert (workspace / envelope.step_result_path).exists()
    assert (workspace / envelope.step_report_path).exists()
    assert (workspace / envelope.stdout_path).exists()
    assert (workspace / envelope.stderr_path).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/worker/test_executor.py -q`

Expected: FAIL if metadata is incomplete or failure envelopes omit evidence files.

- [ ] **Step 3: Ensure envelope metadata and evidence are canonical**

```python
# In PythonStepExecutor._write_envelope(), keep metadata limited to execution facts.
        started_at = getattr(self, "_last_started_at", datetime.now(UTC))
        finished_at = getattr(self, "_last_finished_at", datetime.now(UTC))
        metadata: dict[str, Any] = {
            "code_hash": hashlib.sha256(request.code.encode("utf-8")).hexdigest(),
            "environment": {"python": sys.version, "platform": platform.platform()},
            "package_versions": self._package_versions(request.permission_envelope.allowed_packages),
            "input_refs": request.declared_inputs,
            "produced_artifact_paths": artifact_refs,
            "run_id": request.run_id,
            "step_id": request.step_id,
            "run_metadata": request.run_metadata,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
        }
```

```python
# Also ensure policy-failure evidence files are written before _write_envelope() is called.
            stdout_path.write_text("")
            stderr_path.write_text(str(exc))
            return self._write_envelope(
                request,
                tmp_dir,
                stdout_path,
                stderr_path,
                ExecutionStatus.SANDBOX_ERROR,
                FailureKind.SANDBOX_VIOLATION,
                str(exc),
            )
```

- [ ] **Step 4: Run full worker tests**

Run: `uv run pytest tests/worker -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/worker/executor.py tests/worker/test_executor.py
git commit -m "feat: record worker audit evidence"
```

## Self-Review

**Spec coverage:**
- Layer 2.2 core capabilities are covered by Tasks 1-5: sandboxed Python execution, allowed package/runtime policy, filesystem boundaries, execution envelopes, artifact registration refs, runtime metadata capture, and failure reporting.
- Layer 2.3 execution contract is covered by `StepExecutionRequest`, `PermissionEnvelope`, `ResourceLimits`, `expected_output_contract`, `ExecutionEnvelope`, and files written under `artifacts/tmp/<run_id>/<step_id>/`.
- Layer 2.4 sandbox rules are covered by pre-dispatch policy validation, subprocess audit hooks, no-network/no-shell defaults, timeout, POSIX `RLIMIT_AS` memory ceiling, artifact-size ceiling, stdout/stderr limits, tmp-only writes, and blocked `data/`, `memory/`, `state/` mutation.
- Layer 2.5 provenance responsibilities are covered as raw execution metadata: code hash, environment summary, relevant package versions, input refs, produced artifact paths, run id, step id, and timestamps on the envelope.
- Layer 2.6 failure semantics are covered: Python exception, timeout/resource exhaustion, missing output files, malformed result JSON, and partial artifact generation.
- Layer 2.7 boundaries are explicit: the worker owns execution, sandbox behavior, artifact production, and raw runtime metadata only; it does not own planning, approval, semantic conclusions, memory updates, doctor decisions, provenance interpretation, or final answer authority.
- Contract table alignment is covered: object models are JSON-compatible Pydantic models with `schema_version`, `id`, `workspace_id`, timestamps where applicable, narrow status enums, workspace-relative path fields, and deterministic failure records.

**Placeholder scan:**
- No placeholder markers remain.

**Type consistency:**
- `StepExecutionRequest`, `PermissionEnvelope`, `ResourceLimits`, `ExecutionEnvelope`, `ExecutionStatus`, `FailureKind`, `WorkerPolicyValidator`, and `PythonStepExecutor` are used consistently across tasks.
