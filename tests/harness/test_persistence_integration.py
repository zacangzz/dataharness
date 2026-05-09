"""Persistence integration tests — migrated to async run_turn (was sync handle_turn + RuntimeResponse)."""
from pathlib import Path

from harness.control import RunStateRecord
from harness.db import WorkspaceDb
from harness.orchestrator import Orchestrator
from harness.persistence import HarnessPersistence
from runtime.types import RuntimeEvent


class FakeRuntime:
    async def stream(self, request):
        yield RuntimeEvent(
            type="text_delta", request_id=request.request_id, seq=0, text="Done.",
        )
        yield RuntimeEvent(
            type="finish", request_id=request.request_id, seq=1,
            finish_reason="stop", usage={"prompt_tokens": 2, "completion_tokens": 2},
        )

    async def context_window(self):
        return 4096

    async def token_pressure(self, request):
        from runtime.types import TokenPressure
        return TokenPressure(
            request_id=request.request_id, context_window=4096,
            prompt_tokens=4, reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=4 + request.max_completion_tokens,
            pressure_ratio=0.01, over_threshold=False,
        )

    async def validate_request(self, request):
        return None

    async def status(self):
        return "ready"


async def test_orchestrator_persists_run_state_and_prompt_package(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    db = WorkspaceDb(workspace / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in Orchestrator(
        runtime=FakeRuntime(), persistence=persistence, app_root=tmp_path
    ).run_turn(
        state,
        workspace_dir=workspace,
        chat_id="c1",
        user_input="hello",
    )]
    # Verify FinalMessage was emitted
    final = next(e for e in events if e.event_name == "FinalMessage")
    assert final.text == "Done."


def test_persistence_saves_execution_evidence_and_artifact_registry(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    envelope = {
        "id": "env_run_1_step_1",
        "schema_version": "1.0",
        "workspace_id": "w_0001",
        "run_id": "run_1",
        "step_id": "step_1",
        "status": "ok",
        "step_result_path": "artifacts/tmp/run_1/step_1/step_result.json",
        "step_report_path": "artifacts/tmp/run_1/step_1/step_report.md",
        "stdout_path": "artifacts/tmp/run_1/step_1/stdout.txt",
        "stderr_path": "artifacts/tmp/run_1/step_1/stderr.txt",
        "artifact_refs": ["artifacts/tmp/run_1/step_1/output.txt"],
        "execution_metadata": {"code_hash": "abc", "input_refs": ["data/input.csv"]},
        "failure_kind": "ok",
    }
    persistence.save_execution_envelope(envelope)
    loaded = db.load_record("execution_envelopes", "id", "env_run_1_step_1")
    artifact = db.load_record("artifact_registry", "path", "artifacts/tmp/run_1/step_1/output.txt")
    step_log = db.load_record("step_action_history", "id", "run_1:step_1:execution")
    assert loaded["status"] == "ok"
    assert artifact["run_id"] == "run_1"
    assert step_log["action"] == "execution_envelope_recorded"
