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


def make_pandas_request(tmp_path: Path, *, code: str) -> StepExecutionRequest:
    workspace = tmp_path / "w_0001"
    (workspace / "data").mkdir(parents=True, exist_ok=True)
    (workspace / "data" / "sales.csv").write_text("amount,units\n10,2\n20,3\n")
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
            allowed_read_paths=["data/sales.csv"],
            registered_artifact_paths=[],
            allowed_write_roots=["artifacts/tmp"],
            allowed_packages=["pandas", "numpy", "pathlib", "json", "csv", "math", "statistics", "time"],
        ),
        expected_output_contract=[],
        run_metadata={"attempt": 1},
        resource_limits=ResourceLimits(timeout_seconds=10, memory_mb=1024, artifact_bytes=100_000),
    )


async def run_once(ex: PythonStepExecutor, req: StepExecutionRequest):
    h = await ex.submit(req)
    return await ex.wait(h.task_id)


async def test_executor_blocks_network_import_at_policy_layer(tmp_path: Path) -> None:
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code="import socket"))
    assert env.status.status == "failed"
    assert env.diagnostics["failure_kind"] == "sandbox_violation"


async def test_executor_blocks_runtime_write_outside_tmp(tmp_path: Path) -> None:
    code = "from pathlib import Path\nPath('../../../../memory/x.md').write_text('bad')"
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code=code))
    assert env.status.status == "failed"
    assert env.diagnostics["failure_kind"] == "sandbox_violation"
    assert "write outside sandbox" in env.stderr


async def test_executor_blocks_dynamic_import_of_disallowed_package(tmp_path: Path) -> None:
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code="__import__('pandas')"))
    assert env.status.status == "failed"
    assert env.diagnostics["failure_kind"] == "sandbox_violation"
    assert "package not allowed at runtime" in env.stderr


async def test_executor_allows_declared_pandas_numpy_imports(tmp_path: Path) -> None:
    code = (
        "import pandas as pd\n"
        "df = pd.read_csv('data/sales.csv')\n"
        "total_sales = df['amount'].sum()\n"
        "total_units = df['units'].sum()\n"
        "print(f'total_sales={total_sales}; total_units={total_units}; average={total_sales / total_units}')\n"
    )
    env = await run_once(PythonStepExecutor(), make_pandas_request(tmp_path, code=code))
    assert env.status.status == "completed", env.stderr
    assert "total_sales=30" in env.stdout
    assert "total_units=5" in env.stdout


async def test_executor_stages_declared_inputs_as_symlinks(tmp_path: Path) -> None:
    """Declared inputs are symlinked under tmp_dir so workspace-relative paths resolve at cwd=tmp_dir."""
    req = make_pandas_request(tmp_path, code="from pathlib import Path\nprint(Path('data/sales.csv').read_text())\n")
    env = await run_once(PythonStepExecutor(), req)
    assert env.status.status == "completed", env.stderr
    assert "amount,units" in env.stdout
    tmp_dir = req.workspace_dir / "artifacts" / "tmp" / "r_1" / "s_1"
    staged = tmp_dir / "data" / "sales.csv"
    assert staged.is_symlink()
    assert staged.resolve() == (req.workspace_dir / "data" / "sales.csv").resolve()


async def test_executor_excludes_staged_inputs_from_produced_artifacts(tmp_path: Path) -> None:
    """Staged input dirs/symlinks must not appear as produced_artifact_paths."""
    code = (
        "import pandas as pd\n"
        "from pathlib import Path\n"
        "df = pd.read_csv('data/sales.csv')\n"
        "Path('result.txt').write_text(str(df['amount'].sum()))\n"
    )
    env = await run_once(PythonStepExecutor(), make_pandas_request(tmp_path, code=code))
    assert env.status.status == "completed", env.stderr
    produced = env.diagnostics["execution_metadata"]["produced_artifact_paths"]
    joined = " ".join(produced)
    assert "data/sales.csv" not in joined
    assert "data" not in [Path(p).name for p in produced]
    assert any(p.endswith("result.txt") for p in produced)


async def test_executor_blocks_user_shell_import_after_pandas_loads(tmp_path: Path) -> None:
    code = "import pandas as pd\n__import__('subprocess')\n"
    env = await run_once(PythonStepExecutor(), make_pandas_request(tmp_path, code=code))
    assert env.status.status == "failed"
    assert env.diagnostics["failure_kind"] == "sandbox_violation"
    assert "shell import not allowed at runtime: subprocess" in env.stderr


async def test_executor_times_out_long_running_code(tmp_path: Path) -> None:
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code="import time\ntime.sleep(10)"))
    assert env.status.status == "timeout"
    assert env.diagnostics["failure_kind"] == "timeout_or_resource_exhaustion"


async def test_executor_writes_stdout_and_stderr_evidence_files(tmp_path: Path) -> None:
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code="print('hello')"))
    assert env.stdout == "hello\n"
    assert env.stderr == ""
    workspace = tmp_path / "w_0001"
    result = json.loads((workspace / env.diagnostics["step_result_path"]).read_text())
    assert result["status"] == "ok"


async def test_executor_passes_memory_ceiling_to_sandbox_config(tmp_path: Path) -> None:
    await run_once(PythonStepExecutor(), make_request(tmp_path, code="print('ok')"))
    workspace = tmp_path / "w_0001"
    config = json.loads((workspace / "artifacts/tmp/r_1/s_1/sandbox_config.json").read_text())
    assert config["memory_bytes"] == 128 * 1024 * 1024


async def test_executor_flags_missing_expected_outputs(tmp_path: Path) -> None:
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code="print('ok')", expected_outputs=["table.csv"]))
    assert env.status.status == "failed"
    assert env.diagnostics["failure_kind"] == "missing_output_files"
    assert env.diagnostics.get("failure_summary") == "missing expected outputs: ['table.csv']"


async def test_executor_flags_partial_artifact_generation(tmp_path: Path) -> None:
    code = "from pathlib import Path\nPath('table.csv').write_text('x')"
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code=code, expected_outputs=["table.csv", "chart.png"]))
    assert env.status.status == "failed"
    assert env.diagnostics["failure_kind"] == "partial_artifact_generation"


async def test_executor_preserves_malformed_step_result_before_writing_canonical_failure(tmp_path: Path) -> None:
    code = "from pathlib import Path\nPath('step_result.json').write_text('{bad json')\nPath('table.csv').write_text('x')"
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code=code, expected_outputs=["table.csv"]))
    workspace = tmp_path / "w_0001"
    assert env.status.status == "failed"
    assert env.diagnostics["failure_kind"] == "malformed_result_json"
    assert (workspace / "artifacts/tmp/r_1/s_1/malformed_step_result.json").read_text() == "{bad json"
    payload = json.loads((workspace / env.diagnostics["step_result_path"]).read_text())
    assert "malformed result JSON" in (payload["failure_summary"] or "")
    assert "failure_kind" not in payload


async def test_executor_flags_artifact_size_resource_exhaustion(tmp_path: Path) -> None:
    request = make_request(tmp_path, code="from pathlib import Path\nPath('large.bin').write_bytes(b'x' * 2048)", expected_outputs=["large.bin"])
    request.resource_limits.artifact_bytes = 128
    env = await run_once(PythonStepExecutor(), request)
    assert env.status.status == "failed"
    assert env.diagnostics["failure_kind"] == "timeout_or_resource_exhaustion"


async def test_envelope_records_audit_metadata_without_semantic_fields(tmp_path: Path) -> None:
    from datetime import datetime

    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code="print('ok')"))
    metadata = env.diagnostics["execution_metadata"]
    assert metadata["code_hash"]
    assert metadata["environment"]["python"]
    assert "json" in metadata["package_versions"]
    assert metadata["input_refs"] == {}
    assert metadata["produced_artifact_paths"] == []
    assert metadata["run_id"] == "r_1"
    assert metadata["step_id"] == "s_1"
    started = datetime.fromisoformat(metadata["started_at"])
    finished = datetime.fromisoformat(metadata["finished_at"])
    assert started.tzinfo is not None
    assert finished.tzinfo is not None
    assert metadata["duration_ms"] >= 0
    assert "semantic_conclusion" not in metadata
    assert "memory_update" not in metadata
    assert "doctor_decision" not in metadata
    assert "final_answer" not in metadata


async def test_step_result_json_matches_canonical_schema_and_keeps_claims_empty_on_failure(tmp_path: Path) -> None:
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code="raise RuntimeError('boom')"))
    workspace = tmp_path / "w_0001"
    payload = json.loads((workspace / env.diagnostics["step_result_path"]).read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["workspace_id"] == "w_0001"
    assert payload["run_id"] == "r_1"
    assert payload["step_id"] == "s_1"
    assert payload["observations"] == []
    assert payload["claims"] == []
    assert payload["metrics"] == {}
    assert "failure_summary" in payload
    assert "failure_kind" not in payload


async def test_envelope_exists_even_when_policy_validation_fails(tmp_path: Path) -> None:
    env = await run_once(PythonStepExecutor(), make_request(tmp_path, code="import requests"))
    workspace = tmp_path / "w_0001"
    assert env.status.status == "failed"
    assert (workspace / env.diagnostics["step_result_path"]).exists()
    assert (workspace / env.diagnostics["step_report_path"]).exists()


async def test_executor_allows_pandas_to_markdown(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "data").mkdir()
    (ws / "data" / "test.csv").write_text("a,b\n1,2\n3,4\n")
    (ws / "artifacts" / "tmp").mkdir(parents=True)

    executor = PythonStepExecutor()
    request = StepExecutionRequest(
        id="step_md_1",
        workspace_id="w_test",
        workspace_dir=ws,
        run_id="run_test_md",
        plan_id="plan_test",
        step_id="step_1",
        code='import pandas as pd\ndf = pd.read_csv("data/test.csv")\nprint(df.to_markdown())\n',
        declared_inputs={},
        workspace_paths={"tmp_root": "artifacts/tmp"},
        permission_envelope=PermissionEnvelope(
            allowed_read_paths=["data/test.csv"],
            registered_artifact_paths=[],
            allowed_write_roots=["artifacts/tmp"],
            allowed_packages=["pandas", "numpy", "tabulate", "pathlib", "csv"],
        ),
        expected_output_contract=[],
        run_metadata={"attempt": 1},
        resource_limits=ResourceLimits(timeout_seconds=30, memory_mb=1024, artifact_bytes=100_000),
    )
    handle = await executor.submit(request)
    envelope = await executor.wait(handle.task_id)
    assert envelope.status.status == "completed"
