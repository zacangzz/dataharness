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
    path.parent.mkdir(parents=True, exist_ok=True)
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


def test_default_worker_timeout_is_two_minutes() -> None:
    assert ResourceLimits().timeout_seconds == 120


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
