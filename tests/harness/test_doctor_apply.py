from pathlib import Path

import pytest

from harness.control import RunStateRecord
from harness.db import WorkspaceDb
from harness.orchestrator import Orchestrator
from harness.persistence import HarnessPersistence


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
