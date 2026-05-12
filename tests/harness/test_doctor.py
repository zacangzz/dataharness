from pathlib import Path

import pytest

from harness.control import RunStateRecord
from harness.db import WorkspaceDb
from harness.doctor import Doctor, TmpCleanupBlocked
from harness.orchestrator import Orchestrator
from harness.persistence import HarnessPersistence


def test_doctor_uses_lazy_fingerprinting_when_metadata_is_unchanged(tmp_path: Path) -> None:
    data_file = tmp_path / "data" / "employees.csv"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("employee_id\n1\n")
    doctor = Doctor()
    first = doctor.check_source_file(data_file, stored_size=None, stored_mtime_ns=None, stored_fingerprint=None)
    second = doctor.check_source_file(
        data_file,
        stored_size=first["size_bytes"],
        stored_mtime_ns=first["modified_time_ns"],
        stored_fingerprint=first["fingerprint"],
    )
    assert first["action"] == "fingerprinted"
    assert second["action"] == "reused_fingerprint"
    assert second["validity_status"] == "ok"


def test_doctor_detects_changed_missing_and_broken_lineage(tmp_path: Path) -> None:
    data_file = tmp_path / "data" / "employees.csv"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("employee_id\n1\n")
    doctor = Doctor()
    first = doctor.check_source_file(data_file, stored_size=None, stored_mtime_ns=None, stored_fingerprint=None)
    data_file.write_text("employee_id\n1\n2\n")
    changed = doctor.check_source_file(
        data_file,
        stored_size=first["size_bytes"],
        stored_mtime_ns=first["modified_time_ns"],
        stored_fingerprint=first["fingerprint"],
    )
    missing = doctor.check_source_file(
        tmp_path / "data" / "missing.csv",
        stored_size=1,
        stored_mtime_ns=1,
        stored_fingerprint="abc",
    )
    assert changed["validity_status"] == "changed"
    assert missing["validity_status"] == "broken_lineage"


def test_tmp_review_records_actions_before_cleanup_and_blocks_live_references(tmp_path: Path) -> None:
    tmp_file = tmp_path / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("print('x')")
    doctor = Doctor()
    report = doctor.review_tmp_items(
        [tmp_file],
        trigger_context="manual",
        live_refs={str(tmp_file)},
        promote_map={},
    )
    action = report["tmp_actions"][0]
    assert action["action"] == "kept_temporarily"
    assert action["applied"] is False
    assert action["decision_source"] == "deterministic"


def test_tmp_promotion_mapping_matches_spec(tmp_path: Path) -> None:
    tmp_file = tmp_path / "artifacts" / "tmp" / "run_1" / "step_1" / "chart.png"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("png")
    doctor = Doctor()
    report = doctor.review_tmp_items(
        [tmp_file],
        trigger_context="workspace_open",
        live_refs=set(),
        promote_map={str(tmp_file): "artifact"},
    )
    assert report["tmp_actions"][0]["action"] == "promoted"
    assert report["tmp_actions"][0]["destination_path"] == "artifacts/chart.png"


def test_doctor_run_includes_required_report_sections() -> None:
    report = Doctor().run(trigger_context="workspace_open", tmp_items=[])
    assert report["trigger"] == "workspace_open"
    assert set(report) >= {
        "source_findings",
        "validity_changes",
        "lineage_findings",
        "tmp_review",
        "tmp_actions",
        "recommendations",
    }


def _make_persistence(tmp_path: Path) -> HarnessPersistence:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    return HarnessPersistence(db)


def test_doctor_writes_doctor_report_and_tmp_actions(tmp_path: Path) -> None:
    tmp_file = tmp_path / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("print('x')")
    persistence = _make_persistence(tmp_path)
    report = Doctor().run(
        workspace_dir=tmp_path,
        trigger_context="manual",
        persistence=persistence,
        workspace_id="w_0001",
    )
    assert "doctor_report_id" in report
    stored = persistence.db.load_record("doctor_history", "id", report["doctor_report_id"])
    assert stored["trigger"] == "manual"
    assert len(report["tmp_action_records"]) == 1
    action_id = report["tmp_action_records"][0]["id"]
    assert persistence.db.load_record("tmp_actions", "id", action_id)["action"] == "deleted"


def test_doctor_run_writes_report_even_when_no_tmp_items(tmp_path: Path) -> None:
    persistence = _make_persistence(tmp_path)
    report = Doctor().run(
        workspace_dir=tmp_path,
        trigger_context="workspace_open",
        persistence=persistence,
        workspace_id="w_0001",
    )
    assert persistence.db.load_record("doctor_history", "id", report["doctor_report_id"])["trigger"] == "workspace_open"


def test_tmp_cleanup_blocked_until_tmp_action_recorded(tmp_path: Path) -> None:
    tmp_file = tmp_path / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("x")
    doctor = Doctor()
    review = doctor.review_tmp_items(
        [tmp_file], trigger_context="manual", live_refs=set(), promote_map={}
    )
    action = review["tmp_actions"][0]
    assert action["applied"] is False
    applied = doctor.apply_tmp_action(action, workspace_dir=tmp_path)
    assert applied["applied"] is True
    assert not tmp_file.exists()
    with pytest.raises(TmpCleanupBlocked):
        doctor.apply_tmp_action(applied, workspace_dir=tmp_path)


async def test_doctor_direct_command_invokes_doctor_run_not_stub(tmp_path: Path) -> None:
    orchestrator = Orchestrator(app_root=tmp_path)
    # Create workspace so DoctorRunner has a valid directory
    await orchestrator.create_workspace("w_0001")
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in orchestrator.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    assert any(e.event_name == "DoctorReportReady" for e in events)
