from pathlib import Path

from harness.control import ApprovalRecord, RunStateRecord
from harness.core.db import WorkspaceDb


def test_workspace_db_bootstraps_layer3_authoritative_tables(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    tables = set(db.list_tables())
    assert {
        "workspace_metadata",
        "run_records",
        "run_state_history",
        "plan_records",
        "step_records",
        "approval_records",
        "execution_envelopes",
        "step_results",
        "prompt_packages",
        "artifact_registry",
        "file_registry",
        "validity_state",
        "lineage_records",
        "doctor_history",
        "tmp_actions",
        "review_proposals",
        "memory_update_proposals",
        "validation_failures",
        "note_index",
        "function_index",
        "mode_switch_history",
        "step_action_history",
    } <= tables


def test_repository_persists_json_control_records(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    run = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    db.save_record("run_records", "run_id", run.run_id, run.model_dump(mode="json"))
    loaded = db.load_record("run_records", "run_id", run.run_id)
    assert loaded["run_id"] == run.run_id
    assert loaded["state"] == "idle"


def test_approval_records_are_stored_append_only(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id="run_1",
        target_type="plan",
        target_id="plan_1",
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at="2026-04-23T00:00:00Z",
    )
    db.append_record("approval_records", approval.id, approval.model_dump(mode="json"))
    assert db.load_record("approval_records", "id", approval.id)["decision"] == "approved"


def test_list_records_where_filters_by_json_field(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    db.append_record("tmp_actions", "a1", {"id": "a1", "doctor_report_id": "r1"})
    db.append_record("tmp_actions", "a2", {"id": "a2", "doctor_report_id": "r2"})
    db.append_record("tmp_actions", "a3", {"id": "a3", "doctor_report_id": "r1"})

    rows = db.list_records_where("tmp_actions", "doctor_report_id", "r1")
    assert sorted(r["id"] for r in rows) == ["a1", "a3"]
    assert db.list_records_where("tmp_actions", "doctor_report_id", "rX") == []
