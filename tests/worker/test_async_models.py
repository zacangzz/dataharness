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
