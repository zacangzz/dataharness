from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform
import sys
import sysconfig
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from observability import Telemetry, current_boot_id, current_session_id, current_step_id, current_turn_id, resolve_telemetry_dir
from observability.events import EventKind, Layer
from worker.models import (
    ExecutionEnvelope, ExecutionStatus, FailureKind,
    StepExecutionEnvelope, StepExecutionRequest, StepTaskHandle, StepTaskStatus,
)
from worker.paths import as_posix_workspace_relative, build_step_tmp_dir
from worker.policy import WorkerPolicyError, WorkerPolicyValidator

INTERNAL_FILES = frozenset({
    "step.py",
    "sandbox_config.json",
    "step_result.json",
    "step_report.md",
    "stdout.txt",
    "stderr.txt",
})

SANDBOX_VIOLATION_MARKERS = (
    "write outside sandbox",
    "read outside sandbox",
    "code import outside allowed runtime roots",
    "operation blocked by sandbox",
    "package not allowed at runtime",
    "network import not allowed at runtime",
    "shell import not allowed at runtime",
)


def allowed_code_roots() -> list[str]:
    roots: list[str] = [str(Path(entry).resolve()) for entry in sys.path if entry]
    # PyInstaller frozen binary: include the extracted bundle dir (`_MEIPASS`),
    # the binary's parent dir, and stdlib/site-packages from sysconfig so the
    # worker subprocess can read its own runtime files past the sandbox audit.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(str(Path(meipass).resolve()))
    if getattr(sys, "frozen", False):
        try:
            roots.append(str(Path(sys.executable).resolve().parent))
        except (OSError, ValueError):
            pass
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        try:
            p = sysconfig.get_path(key)
        except (KeyError, OSError):
            p = None
        if p:
            roots.append(str(Path(p).resolve()))
    return list(dict.fromkeys(roots))


def _stage_declared_inputs(
    *, workspace_dir: Path, tmp_dir: Path, declared_inputs: list[str],
) -> set[Path]:
    """Symlink each declared input under tmp_dir preserving subpath structure.

    The worker subprocess runs with cwd=tmp_dir but prompts instruct the model
    to read inputs at workspace-relative paths (e.g. "data/foo.csv"). Staging
    via symlinks makes that convention actually resolve without changing cwd
    (which would break artifact discovery in _write_envelope).

    Returns the set of top-level dirs created under tmp_dir, so _write_envelope
    can exclude them from produced-artifact discovery.
    """
    workspace_root = workspace_dir.resolve()
    tmp_root = tmp_dir.resolve()
    staged_roots: set[Path] = set()
    for rel in declared_inputs:
        rel_path = Path(rel)
        if rel_path.is_absolute():
            continue
        source = (workspace_root / rel_path).resolve()
        if not source.exists():
            continue
        try:
            source.relative_to(workspace_root)
        except ValueError:
            continue
        target = tmp_root / rel_path
        if target.exists() or target.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(source, target)
        except OSError:
            continue
        # Track the top-level dir under tmp_dir (e.g. "data") to skip later.
        top = rel_path.parts[0] if rel_path.parts else None
        if top:
            staged_roots.add(tmp_root / top)
    return staged_roots


def _subprocess_env() -> dict[str, str]:
    """Build env for sandbox subprocess, ensuring the worker package is importable."""
    env = os.environ.copy()
    # src/ is the parent of the worker package dir (src/worker/).
    src_dir = Path(__file__).resolve().parent.parent
    extra_paths = [str(src_dir)]
    # Also include any paths from sys.path that are real directories (e.g. pytest injects src/).
    for entry in sys.path:
        if entry and Path(entry).is_dir() and entry not in extra_paths:
            extra_paths.append(entry)
    existing = env.get("PYTHONPATH", "")
    if existing:
        extra_paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(extra_paths)
    if current_boot_id() is not None:
        env["DATAHARNESS_BOOT_ID"] = str(current_boot_id())
    if current_session_id() is not None:
        env["DATAHARNESS_SESSION_ID"] = str(current_session_id())
    if current_turn_id() is not None:
        env["DATAHARNESS_TURN_ID"] = str(current_turn_id())
    if current_step_id() is not None:
        env["DATAHARNESS_STEP_ID"] = str(current_step_id())
    return env


def _decode(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _to_step_task_status(
    *, request: StepExecutionRequest, status: str, started_at: datetime | None,
    finished_at: datetime | None, return_code: int | None, task_id: str,
) -> StepTaskStatus:
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
            return self._wrap_envelope(rec, inner, stdout_path, stderr_path, status="failed", return_code=None)

        staged_input_roots = _stage_declared_inputs(
            workspace_dir=request.workspace_dir,
            tmp_dir=tmp_dir,
            declared_inputs=list(envelope_perm.allowed_read_paths) + list(envelope_perm.registered_artifact_paths),
        )

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
            self.telemetry.emit(
                Layer.WORKER, EventKind.WORKER_SUBPROCESS_END,
                payload={
                    "rc": proc.returncode,
                    "stdout_bytes": len((stdout_bytes or b"")),
                    "stderr_bytes": len((stderr_bytes or b"")),
                    "outcome": "timeout",
                },
            )
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.TIMEOUT, FailureKind.TIMEOUT_OR_RESOURCE_EXHAUSTION,
                "execution timed out",
                staged_input_roots=staged_input_roots,
            )
            return self._wrap_envelope(rec, inner, stdout_path, stderr_path, status="timeout", return_code=proc.returncode)

        # Issue 1 fix: only treat as cancelled when the process was actually terminated
        # (negative returncode on POSIX = killed by signal, or non-zero from terminate).
        # If proc.returncode == 0, the process completed cleanly before terminate landed.
        if rec.cancel_event.is_set() and proc.returncode != 0:
            stdout_path.write_text((stdout_bytes or b"").decode("utf-8", "replace")[: limits.stdout_bytes])
            stderr_path.write_text((stderr_bytes or b"").decode("utf-8", "replace")[: limits.stderr_bytes])
            self.telemetry.emit(
                Layer.WORKER, EventKind.WORKER_SUBPROCESS_END,
                payload={
                    "rc": proc.returncode,
                    "stdout_bytes": len((stdout_bytes or b"")),
                    "stderr_bytes": len((stderr_bytes or b"")),
                    "outcome": "cancelled",
                },
            )
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.EXECUTION_ERROR, FailureKind.PYTHON_EXCEPTION,
                "cancelled",
                staged_input_roots=staged_input_roots,
            )
            return self._wrap_envelope(rec, inner, stdout_path, stderr_path, status="cancelled", return_code=proc.returncode)

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
                staged_input_roots=staged_input_roots,
            )
            spec_status = "completed" if status == ExecutionStatus.OK else "failed"
            return self._wrap_envelope(rec, inner, stdout_path, stderr_path, status=spec_status, return_code=proc.returncode)

        if self._is_sandbox_violation(stderr_text):
            self.telemetry.emit(
                Layer.WORKER, EventKind.WORKER_SANDBOX_VIOLATION,
                payload={"phase": "subprocess", "message": stderr_text[:500]},
            )
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.SANDBOX_ERROR, FailureKind.SANDBOX_VIOLATION,
                stderr_text,
                staged_input_roots=staged_input_roots,
            )
        else:
            inner = self._write_envelope(
                request, tmp_dir, stdout_path, stderr_path,
                ExecutionStatus.EXECUTION_ERROR, FailureKind.PYTHON_EXCEPTION,
                stderr_text,
                staged_input_roots=staged_input_roots,
            )
        return self._wrap_envelope(rec, inner, stdout_path, stderr_path, status="failed", return_code=proc.returncode)

    def _wrap_envelope(
        self,
        rec: _TaskRecord,
        inner: ExecutionEnvelope,
        stdout_path: Path,
        stderr_path: Path,
        *,
        status: str,
        return_code: int | None,
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
            "failure_summary": inner.failure_summary,
            "execution_metadata": inner.execution_metadata,
            "step_result_path": inner.step_result_path,
            "step_report_path": inner.step_report_path,
        }
        # Read stdout/stderr from the local path objects we already populated
        stdout_text = stdout_path.read_text() if stdout_path.exists() else ""
        stderr_text = stderr_path.read_text() if stderr_path.exists() else ""
        return StepExecutionEnvelope(
            task_id=rec.task_id,
            status=new_status,
            stdout=stdout_text,
            stderr=stderr_text,
            artifacts=artifact_paths,
            diagnostics=diagnostics,
        )

    def _classify_success_contract(self, request: StepExecutionRequest, tmp_dir: Path) -> tuple[ExecutionStatus, FailureKind, str | None]:
        malformed_result = self._preserve_malformed_user_result(tmp_dir)
        if malformed_result:
            return ExecutionStatus.CONTRACT_ERROR, FailureKind.MALFORMED_RESULT_JSON, malformed_result
        expected = set(request.expected_output_contract)
        produced = {path.name for path in tmp_dir.iterdir() if path.is_file()}
        missing = sorted(expected - produced)
        if missing and expected & produced:
            return ExecutionStatus.CONTRACT_ERROR, FailureKind.PARTIAL_ARTIFACT_GENERATION, f"missing expected outputs: {missing}"
        if missing:
            return ExecutionStatus.CONTRACT_ERROR, FailureKind.MISSING_OUTPUT_FILES, f"missing expected outputs: {missing}"
        total_bytes = sum(
            path.stat().st_size
            for path in tmp_dir.iterdir()
            if path.is_file() and path.name not in INTERNAL_FILES
        )
        if total_bytes > request.resource_limits.artifact_bytes:
            return ExecutionStatus.RESOURCE_EXHAUSTED, FailureKind.TIMEOUT_OR_RESOURCE_EXHAUSTION, f"artifact byte limit exceeded: {total_bytes}"
        return ExecutionStatus.OK, FailureKind.OK, None

    def _preserve_malformed_user_result(self, tmp_dir: Path) -> str | None:
        result_path = tmp_dir / "step_result.json"
        if not result_path.exists():
            return None
        try:
            json.loads(result_path.read_text())
        except json.JSONDecodeError as exc:
            result_path.rename(tmp_dir / "malformed_step_result.json")
            return f"malformed result JSON: {exc.msg}"
        return None

    def _is_sandbox_violation(self, stderr: str) -> bool:
        return any(marker in stderr for marker in SANDBOX_VIOLATION_MARKERS)

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
        dispatch_started: float | None = None,
        staged_input_roots: set[Path] | None = None,
    ) -> ExecutionEnvelope:
        result_path = tmp_dir / "step_result.json"
        report_path = tmp_dir / "step_report.md"
        staged_input_roots = staged_input_roots or set()
        staged_resolved = {p.resolve() for p in staged_input_roots}
        artifact_refs = [
            as_posix_workspace_relative(request.workspace_dir, path)
            for path in tmp_dir.iterdir()
            if path.name not in INTERNAL_FILES
            and not path.is_symlink()
            and path.resolve() not in staged_resolved
        ]
        started_at = datetime.now(UTC)
        finished_at = datetime.now(UTC)
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
            "duration_ms": 0,
        }
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
        for artifact_ref in artifact_refs:
            self.telemetry.emit(
                Layer.WORKER,
                EventKind.WORKER_ARTIFACT_EMITTED,
                payload={"path": artifact_ref, "run_id": request.run_id, "step_id": request.step_id},
            )
        self.telemetry.emit(
            Layer.WORKER,
            EventKind.WORKER_DISPATCH_END,
            duration_ms=None,
            payload={
                "status": str(status),
                "failure_kind": str(failure_kind),
                "artifact_count": len(artifact_refs),
                "stdout_bytes": stdout_path.stat().st_size if stdout_path.exists() else 0,
                "stderr_bytes": stderr_path.stat().st_size if stderr_path.exists() else 0,
            },
        )
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
            failure_summary=failure_summary,
        )
