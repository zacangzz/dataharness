from harness.events import DoctorApprovalRequested, DoctorNarrationReady, DoctorReportReady
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord
from harness.core.db import WorkspaceDb
from harness.core.persistence import HarnessPersistence


async def test_doctor_command_emits_narration_and_approval_from_l3(tmp_path):
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    orch = Orchestrator(app_root=tmp_path, persistence=HarnessPersistence(db))
    await orch.create_workspace("w1")
    # Seed a tmp artifact so the sweep produces a proposed cleanup action
    # (without proposed actions the no-actions branch emits ActionsApplied,
    # not ApprovalRequested -- matching AppSession's prior behavior).
    tmp_file = tmp_path / "workspaces" / "w1" / "artifacts" / "tmp" / "run_1" / "step_1" / "draft.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("noop\n")
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="interaction")

    events = [
        ev async for ev in orch.handle_direct_command(
            state, command="doctor", arguments={"chat_id": "c1"},
        )
    ]
    kinds = [type(ev).__name__ for ev in events]
    assert "DoctorReportReady" in kinds
    # Narration + approval now originate in L3, after the report:
    assert "DoctorNarrationReady" in kinds
    assert "DoctorApprovalRequested" in kinds
    assert kinds.index("DoctorReportReady") < kinds.index("DoctorNarrationReady")
