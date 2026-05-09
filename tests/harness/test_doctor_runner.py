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
