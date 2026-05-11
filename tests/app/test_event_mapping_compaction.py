from datetime import UTC, datetime

from app.event_mapping import to_app_event
from harness.events import (
    ChatHistoryCompacted, DoctorActionsApplied, DoctorApprovalRequested,
    DoctorNarrationReady,
)


def test_chat_history_compacted_maps_to_dedicated_app_event():
    ev = ChatHistoryCompacted(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id=None,
        status="completed", summary_token_estimate=42, replaced_turn_count=5,
        compaction_count=1,
    )
    app_ev = to_app_event(ev)
    assert app_ev.event_name == "AppChatHistoryCompacted"
    assert app_ev.status == "completed"
    assert app_ev.replaced_turn_count == 5
    assert app_ev.summary_token_estimate == 42
    assert app_ev.compaction_count == 1


def test_doctor_narration_maps():
    ev = DoctorNarrationReady(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id=None,
        report_id="r1", narration_text="hi", action_summaries=["a"],
    )
    out = to_app_event(ev)
    assert out.event_name == "AppDoctorNarrationReady"
    assert out.narration_text == "hi"
    assert out.action_summaries == ["a"]


def test_doctor_approval_requested_maps():
    ev = DoctorApprovalRequested(
        ts=datetime.now(UTC), workspace_id="w", chat_id=None, run_id=None,
        report_id="r1", question="Apply? (yes / no)", action_count=2,
    )
    out = to_app_event(ev)
    assert out.event_name == "AppDoctorApprovalRequested"
    assert out.question == "Apply? (yes / no)"
    assert out.action_count == 2


def test_doctor_actions_applied_maps():
    ev = DoctorActionsApplied(
        ts=datetime.now(UTC), workspace_id="w", chat_id=None, run_id=None,
        report_id="r1", applied_count=3, skipped_count=1, details=[{"id": "x"}],
    )
    out = to_app_event(ev)
    assert out.event_name == "AppDoctorActionsApplied"
    assert out.applied_count == 3
    assert out.skipped_count == 1
