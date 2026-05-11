import asyncio
from pathlib import Path

import pytest

from harness.doctor_runner import DoctorRunner
from harness.events import (
    CommandCompleted, CommandProgress, CommandStarted,
    DoctorActionProposed, DoctorFinding, DoctorReportReady, DoctorStarted,
)


@pytest.fixture
def runner():
    return DoctorRunner()


async def test_emits_full_event_sequence(runner, tmp_path):
    workspace_dir = tmp_path / "w"
    (workspace_dir / "memory").mkdir(parents=True)
    (workspace_dir / "artifacts" / "tmp").mkdir(parents=True)
    events = [
        e async for e in runner.run(
            workspace_id="w1", workspace_dir=workspace_dir, trigger="manual",
        )
    ]
    names = [e.event_name for e in events]
    assert names[0] == "CommandStarted"
    assert "DoctorStarted" in names
    assert "DoctorReportReady" in names
    assert names[-1] == "CommandCompleted"


async def test_progress_events_have_phase_indices(runner, tmp_path):
    ws = tmp_path / "w"
    (ws / "memory").mkdir(parents=True)
    (ws / "artifacts" / "tmp").mkdir(parents=True)
    events = [e async for e in runner.run(workspace_id="w1", workspace_dir=ws, trigger="manual")]
    progresses = [e for e in events if isinstance(e, CommandProgress)]
    assert progresses[0].phase_index == 1
    assert progresses[-1].phase_index == progresses[-1].phase_total


async def test_tmp_review_proposes_successful_step_script_promotion(runner, tmp_path):
    ws = tmp_path / "w"
    step_dir = ws / "artifacts" / "tmp" / "run_1" / "step_1"
    step_dir.mkdir(parents=True)
    (step_dir / "step.py").write_text("from pathlib import Path\nPath('result.txt').write_text('ok')\n")
    (step_dir / "step_result.json").write_text('{"status":"ok","failure_summary":null}')
    events = [e async for e in runner.run(workspace_id="w1", workspace_dir=ws, trigger="manual")]
    actions = [e for e in events if isinstance(e, DoctorActionProposed)]
    assert actions
    assert actions[0].action == "promote"
    assert actions[0].target == str(step_dir / "step.py")
    report = next(e for e in events if isinstance(e, DoctorReportReady))
    assert report.action_records[0]["destination_path"] == "memory/functions/step.py"
