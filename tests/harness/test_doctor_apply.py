from pathlib import Path

import pytest

from harness.control import RunStateRecord
from harness.core.db import WorkspaceDb
from harness.orchestrator import Orchestrator
from harness.core.persistence import HarnessPersistence


def _make_persistence(tmp_path: Path) -> HarnessPersistence:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    return HarnessPersistence(db)


async def _setup_orchestrator_with_tmp(tmp_path: Path) -> tuple[Orchestrator, Path, str]:
    persistence = _make_persistence(tmp_path)
    orchestrator = Orchestrator(app_root=tmp_path, persistence=persistence)
    await orchestrator.create_workspace("w_0001")
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    tmp_file = workspace_dir / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("x = 1\n")
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in orchestrator.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    report_id = next(
        e.report_id for e in events if e.event_name == "DoctorReportReady"
    )
    return orchestrator, workspace_dir, report_id


async def test_apply_doctor_actions_yes_deletes_orphan_tmp(tmp_path: Path) -> None:
    orchestrator, workspace_dir, report_id = await _setup_orchestrator_with_tmp(tmp_path)
    tmp_file = workspace_dir / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    assert tmp_file.exists()
    events = [e async for e in orchestrator.apply_doctor_actions(
        report_id=report_id, decision="yes",
        workspace_id="w_0001", workspace_dir=workspace_dir,
    )]
    applied_events = [e for e in events if e.event_name == "DoctorActionsApplied"]
    assert applied_events, "expected DoctorActionsApplied"
    assert applied_events[0].applied_count == 1
    assert not tmp_file.exists()
    rows = orchestrator.persistence.db.list_records("tmp_actions")
    matching = [r for r in rows if r["doctor_report_id"] == report_id]
    assert matching and all(r["applied"] is True for r in matching)


async def test_apply_doctor_actions_no_keeps_files(tmp_path: Path) -> None:
    orchestrator, workspace_dir, report_id = await _setup_orchestrator_with_tmp(tmp_path)
    tmp_file = workspace_dir / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    events = [e async for e in orchestrator.apply_doctor_actions(
        report_id=report_id, decision="no",
        workspace_id="w_0001", workspace_dir=workspace_dir,
    )]
    applied_events = [e for e in events if e.event_name == "DoctorActionsApplied"]
    assert applied_events[0].applied_count == 0
    assert tmp_file.exists()
    rows = orchestrator.persistence.db.list_records("tmp_actions")
    matching = [r for r in rows if r["doctor_report_id"] == report_id]
    assert matching and all(r["applied"] is False for r in matching)


async def test_apply_doctor_actions_selected_ids_only_applies_chosen(tmp_path: Path) -> None:
    orchestrator, workspace_dir, report_id = await _setup_orchestrator_with_tmp(tmp_path)
    second_file = workspace_dir / "artifacts" / "tmp" / "run_1" / "step_2" / "other.py"
    second_file.parent.mkdir(parents=True)
    second_file.write_text("y = 2\n")

    # Re-run doctor so both tmp files are persisted as tmp_actions for one report.
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in orchestrator.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    report_id = next(e.report_id for e in events if e.event_name == "DoctorReportReady")
    rows = [
        r for r in orchestrator.persistence.db.list_records("tmp_actions")
        if r["doctor_report_id"] == report_id
    ]
    assert len(rows) >= 2
    distinct_rows = list({r["item_path"]: r for r in rows}.values())
    assert len(distinct_rows) >= 2
    selected = next(r for r in distinct_rows if str(r["item_path"]).endswith("other.py"))
    selected_id = selected["id"]
    selected_path = workspace_dir / selected["item_path"]
    unselected = next(r for r in distinct_rows if str(r["item_path"]).endswith("draft.py"))
    unselected_path = workspace_dir / unselected["item_path"]

    events = [e async for e in orchestrator.apply_doctor_actions(
        report_id=report_id,
        decision="yes",
        workspace_id="w_0001",
        workspace_dir=workspace_dir,
        action_ids=[selected_id],
    )]

    applied = next(e for e in events if e.event_name == "DoctorActionsApplied")
    assert applied.applied_count == 1
    assert applied.skipped_count >= 1
    assert any(d.get("note") == "not_selected" for d in applied.details)
    assert not selected_path.exists()
    assert unselected_path.exists()


async def test_apply_doctor_actions_empty_selected_ids_applies_none(tmp_path: Path) -> None:
    orchestrator, workspace_dir, report_id = await _setup_orchestrator_with_tmp(tmp_path)
    second_file = workspace_dir / "artifacts" / "tmp" / "run_1" / "step_2" / "other.py"
    second_file.parent.mkdir(parents=True)
    second_file.write_text("y = 2\n")

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in orchestrator.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    report_id = next(e.report_id for e in events if e.event_name == "DoctorReportReady")
    rows = [
        r for r in orchestrator.persistence.db.list_records("tmp_actions")
        if r["doctor_report_id"] == report_id
    ]
    assert len({r["item_path"] for r in rows}) >= 2

    events = [e async for e in orchestrator.apply_doctor_actions(
        report_id=report_id,
        decision="yes",
        workspace_id="w_0001",
        workspace_dir=workspace_dir,
        action_ids=[],
    )]

    applied = next(e for e in events if e.event_name == "DoctorActionsApplied")
    assert applied.applied_count == 0
    assert applied.skipped_count == len(rows)
    assert all(d.get("note") == "not_selected" for d in applied.details)
    assert (workspace_dir / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py").exists()
    assert second_file.exists()
