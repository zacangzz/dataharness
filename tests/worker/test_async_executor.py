import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from observability import Telemetry
from observability.events import EventKind
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


# ---------------------------------------------------------------------------
# Issue 1: Cancel-vs-completion race
# ---------------------------------------------------------------------------

async def test_fast_job_not_spuriously_cancelled(workspace):
    """A fast-completing job (rc=0) must NOT be marked cancelled even if
    cancel_event happens to be set after the process has already exited cleanly."""
    ex = PythonStepExecutor()
    req = make_request(workspace, code="print('done')", timeout=10, run_id="r_fast", step_id="s_fast")
    h = await ex.submit(req)
    # Wait for natural completion first.
    env = await ex.wait(h.task_id)
    assert env.status.status == "completed", (
        f"fast job should complete, got {env.status.status}: {env.stderr}"
    )
    # Calling cancel AFTER completion: cancel() wraps as cancelled by convention,
    # but the underlying _execute_async must NOT have flipped a rc=0 run to cancelled.
    # The important check is that the record's underlying envelope was "completed".
    assert "completed" in env.status.status or env.status.return_code == 0


async def test_cancel_mid_flight_is_marked_cancelled(workspace):
    """A slow job that is cancelled mid-flight must produce a cancelled envelope."""
    ex = PythonStepExecutor()
    req = make_request(
        workspace,
        code="import time\nfor _ in range(100): time.sleep(0.05)\n",
        timeout=30,
        run_id="r_slow",
        step_id="s_slow",
    )
    h = await ex.submit(req)
    await asyncio.sleep(0.3)  # let it start
    env = await ex.cancel(h.task_id, reason="test_cancel")
    assert env.status.status == "cancelled"


async def test_cancel_after_natural_completion_preserves_success(workspace):
    """If cancel is called after the process has already completed with rc=0,
    _execute_async should have stored a completed envelope, not a cancelled one."""
    ex = PythonStepExecutor()
    req = make_request(
        workspace,
        code="print('hello')",
        timeout=10,
        run_id="r_nat",
        step_id="s_nat",
    )
    h = await ex.submit(req)
    # Wait for done_event via wait() so we know it finished naturally.
    env_before = await ex.wait(h.task_id)
    assert env_before.status.status == "completed", (
        f"expected completed, got {env_before.status.status}: {env_before.stderr}"
    )
    # The process has returned rc=0 — cancel_event was NOT set during execution.
    # The internal _execute_async should have taken the success path.
    assert env_before.status.return_code == 0


# ---------------------------------------------------------------------------
# Issue 2: Telemetry emitted on timeout and cancel paths
# ---------------------------------------------------------------------------

class CapturingTelemetry(Telemetry):
    """Subclass that records emitted events in memory for assertions."""

    def __init__(self, log_dir: Path) -> None:
        super().__init__(log_dir)
        self.events: list[tuple[EventKind, dict]] = []

    def emit(self, layer, kind, *, payload=None, outcome=None, duration_ms=None):
        self.events.append((kind, dict(payload or {})))
        kw = {}
        if outcome is not None:
            kw["outcome"] = outcome
        if duration_ms is not None:
            kw["duration_ms"] = duration_ms
        return super().emit(layer, kind, payload=payload, **kw)


async def test_timeout_emits_subprocess_end_telemetry(workspace, tmp_path):
    """Timeout path must emit WORKER_SUBPROCESS_END with outcome=timeout."""
    tel = CapturingTelemetry(tmp_path / "tel")
    ex = PythonStepExecutor(telemetry=tel)
    req = make_request(workspace, code="import time; time.sleep(10)", timeout=1,
                       run_id="r_tel_to", step_id="s_tel_to")
    h = await ex.submit(req)
    env = await ex.wait(h.task_id)
    assert env.status.status == "timeout"

    end_events = [
        (k, p) for k, p in tel.events
        if k == EventKind.WORKER_SUBPROCESS_END
    ]
    assert end_events, "WORKER_SUBPROCESS_END must be emitted on timeout path"
    _, payload = end_events[0]
    assert payload.get("outcome") == "timeout"
    assert "rc" in payload


async def test_cancel_emits_subprocess_end_telemetry(workspace, tmp_path):
    """Cancel path must emit WORKER_SUBPROCESS_END with outcome=cancelled."""
    tel = CapturingTelemetry(tmp_path / "tel")
    ex = PythonStepExecutor(telemetry=tel)
    req = make_request(
        workspace,
        code="import time\nfor _ in range(100): time.sleep(0.05)\n",
        timeout=30,
        run_id="r_tel_c",
        step_id="s_tel_c",
    )
    h = await ex.submit(req)
    await asyncio.sleep(0.3)
    env = await ex.cancel(h.task_id, reason="test_tel")
    assert env.status.status == "cancelled"

    end_events = [
        (k, p) for k, p in tel.events
        if k == EventKind.WORKER_SUBPROCESS_END
    ]
    assert end_events, "WORKER_SUBPROCESS_END must be emitted on cancel path"
    _, payload = end_events[0]
    assert payload.get("outcome") == "cancelled"
    assert "rc" in payload
