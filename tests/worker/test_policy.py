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
        validator.validate_code_imports("import scipy")
    with pytest.raises(WorkerPolicyError, match="network import not allowed"):
        validator.validate_code_imports("import socket")
    with pytest.raises(WorkerPolicyError, match="shell import not allowed"):
        validator.validate_code_imports("import subprocess")
    with pytest.raises(WorkerPolicyError, match="network import not allowed"):
        validator.validate_code_imports("from socket import create_connection")
    with pytest.raises(WorkerPolicyError, match="shell import not allowed"):
        validator.validate_code_imports("from subprocess import run")


def test_policy_accepts_resource_limits_with_positive_ceilings(tmp_path: Path) -> None:
    validator = WorkerPolicyValidator(tmp_path / "w_0001", PermissionEnvelope())
    validator.validate_resource_limits(ResourceLimits(timeout_seconds=1, memory_mb=128, artifact_bytes=1024))
    with pytest.raises(WorkerPolicyError, match="positive"):
        validator.validate_resource_limits(ResourceLimits(timeout_seconds=0, memory_mb=128, artifact_bytes=1024))
    with pytest.raises(WorkerPolicyError, match="positive"):
        validator.validate_resource_limits(ResourceLimits(timeout_seconds=30, memory_mb=0, artifact_bytes=1024))
    with pytest.raises(WorkerPolicyError, match="positive"):
        validator.validate_resource_limits(ResourceLimits(timeout_seconds=30, memory_mb=128, artifact_bytes=0))
