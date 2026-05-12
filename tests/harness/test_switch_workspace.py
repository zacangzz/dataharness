from pathlib import Path

from harness.control import RunStateRecord
from harness.db import WorkspaceDb
from harness.orchestrator import Orchestrator
from harness.persistence import HarnessPersistence


def test_switch_workspace_updates_workspace_id_and_resets_run_id(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    orchestrator = Orchestrator(persistence=HarnessPersistence(db))
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    new_state = orchestrator.switch_workspace(state, new_workspace_id="w_0002")

    assert new_state.workspace_id == "w_0002"
    assert new_state.run_id != state.run_id
    assert str(new_state.state) == "idle"
    assert new_state.active_agent_mode == "interaction"


def test_switch_workspace_persists_history_and_run_record(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    orchestrator = Orchestrator(persistence=HarnessPersistence(db))
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    new_state = orchestrator.switch_workspace(state, new_workspace_id="w_0002")

    run_record = db.load_record("run_records", "run_id", new_state.run_id)
    history_id = f"{state.run_id}:switch:{new_state.run_id}"
    history = db.load_record("mode_switch_history", "id", history_id)

    assert run_record["workspace_id"] == "w_0002"
    assert history["to_workspace_id"] == "w_0002"
    assert history["reason"] == "switch_workspace_command"
