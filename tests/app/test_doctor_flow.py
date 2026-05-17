from pathlib import Path

import pytest

from app.session import AppSession
from harness.control import RunStateRecord
from harness.core.db import WorkspaceDb
from harness.orchestrator import Orchestrator
from harness.core.persistence import HarnessPersistence


def _make_orchestrator(tmp_path: Path) -> Orchestrator:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    persistence = HarnessPersistence(db)
    return Orchestrator(app_root=tmp_path, persistence=persistence)


async def test_doctor_session_flow_emits_narration_and_approval(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    session = AppSession(orchestrator=orchestrator, app_root=tmp_path)
    await orchestrator.create_workspace("w_0001")
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    tmp_file = workspace_dir / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("noop\n")

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in session.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    names = [e.event_name for e in events]
    assert "AppDoctorReportReady" in names
    assert "AppDoctorNarrationReady" in names
    assert "AppDoctorApprovalRequested" in names

    report = next(e for e in events if e.event_name == "AppDoctorReportReady")

    apply_events = [e async for e in session.handle_doctor_approval(
        state=state, workspace_dir=workspace_dir, report_id=report.report_id, decision="yes",
    )]
    assert any(e.event_name == "AppDoctorActionsApplied" for e in apply_events)
    applied = next(e for e in apply_events if e.event_name == "AppDoctorActionsApplied")
    assert applied.applied_count == 1
    assert not tmp_file.exists()


async def test_doctor_session_flow_no_decision_keeps_files(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    session = AppSession(orchestrator=orchestrator, app_root=tmp_path)
    await orchestrator.create_workspace("w_0001")
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    tmp_file = workspace_dir / "artifacts" / "tmp" / "run_2" / "step_1" / "draft.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("x\n")

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in session.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    report = next(e for e in events if e.event_name == "AppDoctorReportReady")
    apply_events = [e async for e in session.handle_doctor_approval(
        state=state, workspace_dir=workspace_dir, report_id=report.report_id, decision="no",
    )]
    applied = next(e for e in apply_events if e.event_name == "AppDoctorActionsApplied")
    assert applied.applied_count == 0
    assert tmp_file.exists()


async def test_doctor_session_flow_selected_actions_only_apply_selected(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    session = AppSession(orchestrator=orchestrator, app_root=tmp_path)
    await orchestrator.create_workspace("w_0001")
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    first = workspace_dir / "artifacts" / "tmp" / "run_3" / "step_1" / "first.py"
    second = workspace_dir / "artifacts" / "tmp" / "run_3" / "step_2" / "second.py"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("x = 1\n")
    second.write_text("y = 2\n")

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in session.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    report = next(e for e in events if e.event_name == "AppDoctorReportReady")
    distinct_records = list({r["item_path"]: r for r in report.action_records}.values())
    assert len(distinct_records) >= 2
    selected = next(r for r in distinct_records if str(r["item_path"]).endswith("second.py"))
    action_id = selected["id"]
    selected_path = workspace_dir / selected["item_path"]
    unselected = next(r for r in distinct_records if str(r["item_path"]).endswith("first.py"))
    unselected_path = workspace_dir / unselected["item_path"]

    apply_events = [e async for e in session.handle_doctor_approval(
        state=state,
        workspace_dir=workspace_dir,
        report_id=report.report_id,
        decision="yes",
        action_ids=[action_id],
    )]
    applied = next(e for e in apply_events if e.event_name == "AppDoctorActionsApplied")
    assert applied.applied_count == 1
    assert any(d.get("note") == "not_selected" for d in applied.details)
    assert not selected_path.exists()
    assert unselected_path.exists()
