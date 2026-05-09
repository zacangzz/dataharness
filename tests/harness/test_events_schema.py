from datetime import UTC, datetime
from pathlib import Path

from harness.events import (
    HarnessEvent, HarnessEventRef,
    TurnStarted, StatusChanged, WorkspaceHealthChanged,
    ChatCreated, ChatSelected, ChatDeleted, ChatHistoryLoaded,
    CommandStarted, CommandProgress, CommandCompleted,
    RuntimeStatusChanged, ModeActivated, ContextReloaded, PromptBuilt,
    ChatHistoryCompacted, RuntimeDelta,
    PlanReady, ApprovalRequired, ApprovalResolved,
    StepTaskSubmitted, StepTaskStatusChanged, StepCompleted, ArtifactsReady,
    DoctorStarted, DoctorFinding, DoctorActionProposed, DoctorReportReady,
    FinalMessage, TurnFailed, TurnCancelled,
)
from harness.status import HarnessStatusSnapshot
from worker.models import StepExecutionEnvelope, StepTaskStatus


def base_kwargs():
    return {
        "event_id": "ev_1", "ts": datetime.now(UTC),
        "workspace_id": "w1", "chat_id": "c1", "run_id": "run_1",
    }


def test_turn_started_fields():
    e = TurnStarted(**base_kwargs(), turn_id="t1", user_message_id="m1", active_mode="analyst")
    assert e.event_name == "TurnStarted"


def test_runtime_delta_text():
    e = RuntimeDelta(
        **base_kwargs(), request_id="req1", seq=3, delta_type="text", text="hi", tool_call=None,
    )
    assert e.delta_type == "text"


def test_chat_history_compacted_status_terminals():
    for s in ("queued", "running", "completed", "failed"):
        ChatHistoryCompacted(
            **base_kwargs(), status=s,
            summary_token_estimate=None, replaced_turn_count=None, compaction_count=1,
        )


def test_doctor_finding_categories():
    for cat in ("source", "validity", "lineage", "tmp", "memory"):
        DoctorFinding(
            **base_kwargs(), report_id="r1", category=cat, severity="info",
            summary="x", details={},
        )


def test_event_ref_round_trip():
    ref = HarnessEventRef(event_id="e", event_name="TurnStarted", ts=datetime.now(UTC), run_id="r")
    assert ref.run_id == "r"


def test_event_discriminator_present():
    e = TurnStarted(**base_kwargs(), turn_id="t1", user_message_id="m1", active_mode="analyst")
    assert e.model_dump()["event_name"] == "TurnStarted"
