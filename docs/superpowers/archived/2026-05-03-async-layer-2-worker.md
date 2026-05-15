# Layer 2 Worker Async Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-01-async-layered-architecture-design.md` §7.

**Goal:** Replace sync `PythonStepExecutor.execute(...)` with an async task-management API: `submit`, `wait`, `cancel`, `list_tasks`, `get_task`. Use `asyncio.create_subprocess_exec` so the event loop is never blocked. Cancelled work returns an envelope with `status.status == "cancelled"`. Maintain a task registry keyed by `task_id`. Layer 3 will only ever hold one outstanding task in V1, but the registry supports multiple entries for diagnostics.

**Architecture:** A single `PythonStepExecutor` instance holds a `dict[str, _TaskRecord]` registry. `submit(...)` validates the request, allocates a `task_id`, kicks off an `asyncio.Task` that runs the subprocess, and returns a `StepTaskHandle`. The internal task records `StepTaskStatus` transitions. `wait(...)` awaits completion and returns the spec-shaped `StepExecutionEnvelope` wrapping the existing rich `ExecutionEnvelope` under `diagnostics`. `cancel(...)` flips a cancellation flag and terminates the subprocess; the resulting envelope carries `status.status == "cancelled"`.

**Tech Stack:** Python 3.12, `asyncio`, `pydantic` 2.x, `pytest-asyncio`.

---

## File Structure

- `src/worker/models.py` — add `StepTaskHandle`, `StepTaskStatus`, `StepExecutionEnvelope`, extend `StepExecutionRequest` per §7 (`permitted_paths`, `timeout_seconds`, `env_overrides` mapped to existing fields). Keep existing `ExecutionEnvelope` for telemetry/persistence.
- `src/worker/executor.py` — async refactor: split `execute(...)` into a private sync core + async wrapper that uses `asyncio.create_subprocess_exec`. Add task registry. Add public `submit/wait/cancel/list_tasks/get_task`. Drop public sync `execute(...)`.
- `src/worker/tasks.py` — **new**: internal `_TaskRecord` dataclass + status transitions (kept private to executor module).
- `tests/worker/test_async_executor.py` — **new**: submit/wait/cancel/list/get + async subprocess + cancellation envelope.
- `tests/worker/test_executor.py` — convert sync tests to async submit/wait pattern.

---

## Prep

- [ ] **Step 0.1: Verify Layer 1 plan completed**

Run: `uv run pytest tests/runtime -q`
Expected: PASS. (`pytest-asyncio` already configured.)

---

## Task 1: New schemas in `worker/models.py`

**Files:**
- Modify: `src/worker/models.py`
- Test: `tests/worker/test_async_models.py` (new)

- [ ] **Step 1.1: Failing tests**

Create `tests/worker/test_async_models.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

from worker.models import (
    StepTaskHandle, StepTaskStatus, StepExecutionEnvelope,
    StepExecutionRequest, PermissionEnvelope, ResourceLimits,
)


def test_step_task_handle_initial_status():
    h = StepTaskHandle(task_id="t1", status="queued", submitted_at=datetime.now(UTC))
    assert h.status == "queued"


def test_step_task_status_progression_values():
    statuses = ("queued", "running", "completed", "failed", "cancelled", "timeout")
    for s in statuses:
        StepTaskStatus(
            task_id="t", workspace_id="w", run_id="r", plan_id="p", step_id="s",
            status=s, started_at=None, finished_at=None, return_code=None,
        )


def test_step_execution_envelope_holds_spec_fields():
    st = StepTaskStatus(
        task_id="t1", workspace_id="w", run_id="r", plan_id="p", step_id="s",
        status="completed", started_at=None, finished_at=None, return_code=0,
    )
    env = StepExecutionEnvelope(
        task_id="t1", status=st, stdout="out", stderr="err",
        artifacts=[Path("a.txt")], diagnostics={"foo": 1},
    )
    assert env.diagnostics["foo"] == 1
    assert env.artifacts == [Path("a.txt")]


def test_step_execution_request_has_permitted_paths(tmp_path):
    req = StepExecutionRequest(
        id="req1", workspace_id="w", run_id="r", plan_id="p", step_id="s",
        workspace_dir=tmp_path, code="print(1)",
        declared_inputs={}, workspace_paths={}, permission_envelope=PermissionEnvelope(),
        permitted_paths=[Path("data/x.csv")],
        timeout_seconds=30, env_overrides={"K": "V"},
    )
    assert req.permitted_paths == [Path("data/x.csv")]
    assert req.timeout_seconds == 30
    assert req.env_overrides == {"K": "V"}
```

- [ ] **Step 1.2: Run; expect failure**

Run: `uv run pytest tests/worker/test_async_models.py -v`
Expected: FAIL — names missing.

- [ ] **Step 1.3: Extend `src/worker/models.py`**

Append to file:

```python
from typing import Literal


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
```

Modify `StepExecutionRequest` to add three optional spec fields **without** breaking existing usage:

```python
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
```

- [ ] **Step 1.4: Run; expect pass**

Run: `uv run pytest tests/worker/test_async_models.py tests/worker/test_models_and_paths.py -v`
Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add src/worker/models.py tests/worker/test_async_models.py
git commit -m "feat(worker): add StepTaskHandle/Status/Envelope and request fields per §7"
```

---

## Task 2: Async subprocess core

**Files:**
- Modify: `src/worker/executor.py`
- Test: `tests/worker/test_async_executor.py` (new)

The strategy: keep all existing validation/sandbox setup/contract classification logic, factor it into private helpers, and wrap the subprocess call with `asyncio.create_subprocess_exec`. The original sync `execute()` becomes private `_execute_blocking` for compatibility internally; the public surface becomes `submit/wait/cancel/list_tasks/get_task`.

- [ ] **Step 2.1: Failing async tests**

Create `tests/worker/test_async_executor.py`:

```python
import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from worker.executor import PythonStepExecutor
from worker.models import (
    PermissionEnvelope, ResourceLimits, StepExecutionRequest,
)


def make_request(workspace_dir: Path, *, code: str, timeout: int = 5, run_id="r1", step_id="s1"):
    return StepExecutionRequest(
        id="req",
        workspace_id="w1",
        run_id=run_id, plan_id="p", step_id=step_id,
        workspace_dir=workspace_dir,
        code=code,
        declared_inputs={},
        workspace_paths={"workspace": "."},
        permission_envelope=PermissionEnvelope(allowed_packages=["pathlib"]),
        expected_output_contract=[],
        timeout_seconds=timeout,
        permitted_paths=[],
    )


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "data").mkdir()
    return tmp_path


async def test_submit_returns_handle_without_blocking(workspace):
    ex = PythonStepExecutor()
    req = make_request(workspace, code="from pathlib import Path; Path('output.txt').write_text('x')")
    handle = await ex.submit(req)
    assert handle.task_id
    assert handle.status in ("queued", "running")
    assert handle.submitted_at <= datetime.utcnow().replace(tzinfo=handle.submitted_at.tzinfo)
    env = await ex.wait(handle.task_id)
    assert env.task_id == handle.task_id
    assert env.status.status == "completed"


async def test_list_and_get_show_states(workspace):
    ex = PythonStepExecutor()
    req = make_request(workspace, code="print('hi')")
    h = await ex.submit(req)
    listed = await ex.list_tasks()
    assert any(s.task_id == h.task_id for s in listed)
    got = await ex.get_task(h.task_id)
    assert got is not None and got.status in ("queued", "running", "completed")
    await ex.wait(h.task_id)
    final = await ex.get_task(h.task_id)
    assert final.status == "completed"


async def test_cancel_terminates_running_subprocess(workspace):
    ex = PythonStepExecutor()
    req = make_request(workspace, code="import time\nfor _ in range(50): time.sleep(0.1)\n", timeout=30)
    h = await ex.submit(req)
    await asyncio.sleep(0.2)
    env = await ex.cancel(h.task_id, reason="user_requested")
    assert env.status.status == "cancelled"
    assert env.task_id == h.task_id


async def test_timeout_envelope(workspace):
    ex = PythonStepExecutor()
    req = make_request(workspace, code="import time\ntime.sleep(5)\n", timeout=1)
    h = await ex.submit(req)
    env = await ex.wait(h.task_id)
    assert env.status.status == "timeout"


async def test_event_loop_not_blocked_during_subprocess(workspace):
    ex = PythonStepExecutor()
    req = make_request(workspace, code="import time; time.sleep(1)\n", timeout=5)
    other_progressed = []

    async def heartbeat():
        for _ in range(10):
            await asyncio.sleep(0.05)
            other_progressed.append(1)

    h = await ex.submit(req)
    hb = asyncio.create_task(heartbeat())
    env = await ex.wait(h.task_id)
    await hb
    assert env.status.status == "completed"
    assert len(other_progressed) >= 5  # loop ticked while subprocess ran


async def test_permission_violation_returns_failed_status(workspace):
    ex = PythonStepExecutor()
    code = "open('/etc/passwd').read()\n"
    req = make_request(workspace, code=code, timeout=5)
    h = await ex.submit(req)
    env = await ex.wait(h.task_id)
    assert env.status.status in ("failed",)
    # Underlying sandbox-error envelope preserved in diagnostics:
    assert "underlying_status" in env.diagnostics


async def test_failed_task_still_records_diagnostic(workspace):
    ex = PythonStepExecutor()
    req = make_request(workspace, code="raise SystemError('boom')", timeout=5)
    h = await ex.submit(req)
    env = await ex.wait(h.task_id)
    assert env.status.status == "failed"
    assert env.stderr  # captured
```

- [ ] **Step 2.2: Run; expect failure**

Run: `uv run pytest tests/worker/test_async_executor.py -v`
Expected: FAIL — async API does not exist.

- [ ] **Step 2.3: Refactor `src/worker/executor.py`**

Replace the public surface. Keep `_classify_success_contract`, `_preserve_malformed_user_result`, `_is_sandbox_violation`, `_package_versions`, `_write_envelope`, `_subprocess_env`, validation logic, telemetry emissions. Replace `execute(...)` and add async API:

Add at top:

```python
import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
```

Add private record + status mapping inside the module:

```python
@dataclass
class _TaskRecord:
    task_id: str
    request: StepExecutionRequest
    status: StepTaskStatus
    process: asyncio.subprocess.Process | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    envelope: StepExecutionEnvelope | None = None
    runner_task: asyncio.Task | None = None


def _to_step_task_status(*, request, status, started_at, finished_at, return_code, task_id):
    return StepTaskStatus(
        task_id=task_id,
        workspace_id=request.workspace_id,
        run_id=request.run_id,
        plan_id=request.plan_id,
        step_id=request.step_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        return_code=return_code,
    )
```

Replace class:

```python
class PythonStepExecutor:
    def __init__(self, telemetry: Telemetry | None = None) -> None:
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())
        self._registry: dict[str, _TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def submit(self, request: StepExecutionRequest) -> StepTaskHandle:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        submitted_at = datetime.now(UTC)
        rec = _TaskRecord(
            task_id=task_id,
            request=request,
            status=_to_step_task_status(
                request=request, status="queued",
                started_at=None, finished_at=None, return_code=None,
                task_id=task_id,
            ),
        )
        async with self._lock:
            self._registry[task_id] = rec
        rec.runner_task = asyncio.create_task(self._run(rec))
        return StepTaskHandle(task_id=task_id, status="queued", submitted_at=submitted_at)

    async def wait(self, task_id: str) -> StepExecutionEnvelope:
        rec = self._registry.get(task_id)
        if rec is None:
            raise KeyError(f"unknown task {task_id}")
        await rec.done_event.wait()
        assert rec.envelope is not None
        return rec.envelope

    async def cancel(self, task_id: str, reason: str) -> StepExecutionEnvelope:
        rec = self._registry.get(task_id)
        if rec is None:
            raise KeyError(f"unknown task {task_id}")
        rec.cancel_event.set()
        if rec.process is not None and rec.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                rec.process.terminate()
        await rec.done_event.wait()
        env = rec.envelope
        if env is None or env.status.status != "cancelled":
            cancelled_status = _to_step_task_status(
                request=rec.request, status="cancelled",
                started_at=rec.status.started_at,
                finished_at=datetime.now(UTC),
                return_code=rec.status.return_code,
                task_id=rec.task_id,
            )
            env = StepExecutionEnvelope(
                task_id=rec.task_id, status=cancelled_status,
                stdout=env.stdout if env else "",
                stderr=(env.stderr if env else "") + f"\ncancelled: {reason}",
                artifacts=env.artifacts if env else [],
                diagnostics={**(env.diagnostics if env else {}), "cancel_reason": reason},
            )
            rec.envelope = env
        return env

    async def list_tasks(self) -> list[StepTaskStatus]:
        async with self._lock:
            return [rec.status for rec in self._registry.values()]

    async def get_task(self, task_id: str) -> StepTaskStatus | None:
        rec = self._registry.get(task_id)
        return rec.status if rec else None

    async def _run(self, rec: _TaskRecord) -> None:
        try:
            envelope = await self._execute_async(rec)
        except Exception as exc:  # noqa: BLE001
            failed_status = _to_step_task_status(
                request=rec.request, status="failed",
                started_at=rec.status.started_at,
                finished_at=datetime.now(UTC),
                return_code=None, task_id=rec.task_id,
            )
            envelope = StepExecutionEnvelope(
                task_id=rec.task_id, status=failed_status,
                stdout="", stderr=f"{type(exc).__name__}: {exc}",
                artifacts=[], diagnostics={"exception": True},
            )
        rec.envelope = envelope
        rec.status = envelope.status
        rec.done_event.set()

    async def _execute_async(self, rec: _TaskRecord) -> StepExecutionEnvelope:
        request = rec.request
        timeout_seconds = request.effective_timeout()
        tmp_dir = build_step_tmp_dir(request.workspace_dir, run_id=request.run_id, step_id=request.step_id)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = tmp_dir / "stdout.txt"
        stderr_path = tmp_dir / "stderr.txt"
        script_path = tmp_dir / "step.py"
        config_path = tmp_dir / "sandbox_config.json"
        script_path.write_text(request.code)

        envelope_perm = request.permission_envelope
        limits = request.resource_limits

        # Validate (sync; small CPU-bound work).
        try:
            validator = WorkerPolicyValidator(request.workspace_dir, envelope_perm)
            validator.validate_resource_limits(limits)
            validator.validate_code_imports(request.code)
            allowed_reads = [
                str(validator.validate_read(p))
                for p in envelope_perm.allowed_read_paths + envelope_perm.registered_artifact_paths
            ]
            allowed_write_roots = [
                str(validator._resolve_relative(root)) for root in envelope_perm.allowed_write_roots
            ]
        except WorkerPolicyError as exc:
            stdout_path.write_text("")
            stderr_path.write_text(str(exc))
            self.telemetry.emit(
                Layer.WORKER, EventKind.WORKER_SANDBOX_VIOLATION,
                payload={"phase": "policy_validation", "message": str(exc)},
            )
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.SANDBOX_ERROR, FailureKind.SANDBOX_VIOLATION, str(exc),
            )
            return self._wrap_envelope(rec, inner, status="failed", return_code=None)

        config_path.write_text(json.dumps({
            "tmp_dir": str(tmp_dir),
            "workspace_dir": str(request.workspace_dir),
            "allowed_reads": allowed_reads,
            "allowed_write_roots": allowed_write_roots,
            "allowed_code_roots": allowed_code_roots(),
            "allowed_packages": envelope_perm.allowed_packages,
            "allow_network": envelope_perm.allow_network,
            "allow_shell": envelope_perm.allow_shell,
            "script_path": str(script_path),
            "memory_bytes": limits.memory_mb * 1024 * 1024,
        }))
        env = _subprocess_env()
        env.update(request.env_overrides)
        command = [sys.executable, "-m", "worker.sandbox_bootstrap", str(config_path)]

        rec.status = _to_step_task_status(
            request=request, status="running",
            started_at=datetime.now(UTC), finished_at=None,
            return_code=None, task_id=rec.task_id,
        )
        self.telemetry.emit(Layer.WORKER, EventKind.WORKER_SUBPROCESS_START, payload={"command": command})
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(tmp_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        rec.process = proc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            stdout_path.write_text((stdout_bytes or b"").decode("utf-8", "replace")[: limits.stdout_bytes])
            stderr_path.write_text(((stderr_bytes or b"").decode("utf-8", "replace") + "\nexecution timed out")[: limits.stderr_bytes])
            self.telemetry.emit(Layer.WORKER, EventKind.WORKER_TIMEOUT, payload={"timeout_seconds": timeout_seconds})
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.TIMEOUT, FailureKind.TIMEOUT_OR_RESOURCE_EXHAUSTION,
                "execution timed out",
            )
            return self._wrap_envelope(rec, inner, status="timeout", return_code=proc.returncode)

        if rec.cancel_event.is_set():
            stdout_path.write_text((stdout_bytes or b"").decode("utf-8", "replace")[: limits.stdout_bytes])
            stderr_path.write_text((stderr_bytes or b"").decode("utf-8", "replace")[: limits.stderr_bytes])
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.EXECUTION_ERROR, FailureKind.PYTHON_EXCEPTION,
                "cancelled",
            )
            return self._wrap_envelope(rec, inner, status="cancelled", return_code=proc.returncode)

        stdout_text = (stdout_bytes or b"").decode("utf-8", "replace")
        stderr_text = (stderr_bytes or b"").decode("utf-8", "replace")
        stdout_path.write_text(stdout_text[: limits.stdout_bytes])
        stderr_path.write_text(stderr_text[: limits.stderr_bytes])
        self.telemetry.emit(
            Layer.WORKER, EventKind.WORKER_SUBPROCESS_END,
            payload={
                "rc": proc.returncode,
                "stdout_bytes": len(stdout_text.encode("utf-8")),
                "stderr_bytes": len(stderr_text.encode("utf-8")),
            },
        )

        if proc.returncode == 0:
            status, failure_kind, failure_summary = self._classify_success_contract(request, tmp_dir)
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                status, failure_kind, failure_summary,
            )
            spec_status = "completed" if status == ExecutionStatus.OK else "failed"
            return self._wrap_envelope(rec, inner, status=spec_status, return_code=proc.returncode)

        if self._is_sandbox_violation(stderr_text):
            self.telemetry.emit(
                Layer.WORKER, EventKind.WORKER_SANDBOX_VIOLATION,
                payload={"phase": "subprocess", "message": stderr_text[:500]},
            )
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.SANDBOX_ERROR, FailureKind.SANDBOX_VIOLATION,
                stderr_text,
            )
        else:
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.EXECUTION_ERROR, FailureKind.PYTHON_EXCEPTION,
                stderr_text,
            )
        return self._wrap_envelope(rec, inner, status="failed", return_code=proc.returncode)

    def _wrap_envelope(
        self, rec: _TaskRecord, inner: ExecutionEnvelope, *, status: str, return_code: int | None,
    ) -> StepExecutionEnvelope:
        finished_at = datetime.now(UTC)
        new_status = _to_step_task_status(
            request=rec.request, status=status,
            started_at=rec.status.started_at, finished_at=finished_at,
            return_code=return_code, task_id=rec.task_id,
        )
        rec.status = new_status
        artifact_paths = [Path(p) for p in inner.artifact_refs]
        diagnostics = {
            "underlying_status": str(inner.status),
            "failure_kind": str(inner.failure_kind),
            "execution_metadata": inner.execution_metadata,
            "step_result_path": inner.step_result_path,
            "step_report_path": inner.step_report_path,
        }
        return StepExecutionEnvelope(
            task_id=rec.task_id,
            status=new_status,
            stdout=Path(rec.request.workspace_dir / inner.stdout_path).read_text() if Path(rec.request.workspace_dir / inner.stdout_path).exists() else "",
            stderr=Path(rec.request.workspace_dir / inner.stderr_path).read_text() if Path(rec.request.workspace_dir / inner.stderr_path).exists() else "",
            artifacts=artifact_paths,
            diagnostics=diagnostics,
        )
```

Remove the public `execute(...)` method. (Keep nothing pointing at the old sync entry from outside the worker package.)

- [ ] **Step 2.4: Run; expect pass**

Run: `uv run pytest tests/worker/test_async_executor.py -v`
Expected: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/worker/executor.py
git commit -m "feat(worker): async submit/wait/cancel/list/get with subprocess via asyncio"
```

---

## Task 3: Convert legacy worker tests

**Files:**
- Modify: `tests/worker/test_executor.py`

- [ ] **Step 3.1: Inspect failures**

Run: `uv run pytest tests/worker/test_executor.py -v`
Expected: many failures pointing at `executor.execute(...)`.

- [ ] **Step 3.2: Convert each test**

Replace direct `ex.execute(req)` calls with:

```python
async def run_once(ex, req):
    h = await ex.submit(req)
    return await ex.wait(h.task_id)
```

Then mark tests `async def`. Replace assertions on `ExecutionEnvelope` with assertions on `StepExecutionEnvelope`:
- `env.status` → `env.status.status` (now a literal string)
- `env.failure_kind` → `env.diagnostics["failure_kind"]`
- `env.artifact_refs` → `[str(p) for p in env.artifacts]`
- `env.stdout_path` → no longer present; use `env.stdout` for content

For sandbox-violation tests, the spec maps these to `status.status == "failed"`; assert that and `"sandbox" in env.stderr.lower()` or `env.diagnostics["failure_kind"] == "FailureKind.SANDBOX_VIOLATION"`.

- [ ] **Step 3.3: Run worker suite**

Run: `uv run pytest tests/worker -v`
Expected: PASS.

- [ ] **Step 3.4: Commit**

```bash
git add tests/worker
git commit -m "test(worker): migrate executor tests to async submit/wait pattern"
```

---

## Task 4: Note downstream callers

`src/harness/orchestrator.py` calls `self.worker.execute(request)` — that path is migrated in plan 3a. Do not touch it here.

- [ ] **Step 4.1: Add note**

Run:
```bash
grep -rn "worker.execute\|self.worker.execute" src/harness | wc -l
```
Confirm one or more remaining. These will be migrated in plan 3a.

- [ ] **Step 4.2: Final commit (optional)**

If you added inline comments in this plan file, commit. Otherwise skip.

---

## Self-Review Checklist

- `submit/wait/cancel/list_tasks/get_task` all async ✓
- Public `execute(...)` removed ✓
- `asyncio.create_subprocess_exec` used; loop not blocked ✓
- Cancelled task envelope has `status.status == "cancelled"` ✓
- Timeout envelope has `status.status == "timeout"` ✓
- Permission/sandbox failures still return diagnostic envelope ✓
- Task registry holds multiple entries; supports `list_tasks` ✓
- Existing telemetry events preserved ✓
- `pytest tests/worker -q` green ✓
