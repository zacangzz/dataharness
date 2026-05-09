from __future__ import annotations

from app.events import (
    AppApprovalRequired, AppChatHistoryLoaded, AppCommandCompleted,
    AppCommandProgress, AppCommandStarted, AppDoctorFinding,
    AppDoctorReportReady, AppEvent, AppFinalMessage, AppRaw,
    AppRuntimeDelta, AppStatusChanged, AppTurnCancelled,
    AppTurnFailed, AppTurnStarted,
)
from harness.events import (
    ApprovalRequired, ChatHistoryLoaded, CommandCompleted, CommandProgress,
    CommandStarted, DoctorFinding, DoctorReportReady, FinalMessage, HarnessEvent,
    RuntimeDelta, StatusChanged, TurnCancelled, TurnFailed, TurnStarted,
)


def to_app_event(ev: HarnessEvent) -> AppEvent:
    base = dict(ts=ev.ts, workspace_id=ev.workspace_id, chat_id=ev.chat_id, run_id=ev.run_id)
    if isinstance(ev, TurnStarted):
        return AppTurnStarted(**base, turn_id=ev.turn_id, user_message_id=ev.user_message_id, active_mode=ev.active_mode)
    if isinstance(ev, RuntimeDelta):
        return AppRuntimeDelta(**base, delta_type=ev.delta_type, text=ev.text, tool_call=ev.tool_call)
    if isinstance(ev, FinalMessage):
        return AppFinalMessage(**base, assistant_message_id=ev.assistant_message_id, text=ev.text, usage=ev.usage)
    if isinstance(ev, TurnFailed):
        return AppTurnFailed(**base, failure_summary=ev.failure_summary, error_code=ev.error_code, details=ev.details)
    if isinstance(ev, TurnCancelled):
        return AppTurnCancelled(**base, reason=ev.reason, cancelled_at=ev.cancelled_at)
    if isinstance(ev, StatusChanged):
        return AppStatusChanged(**base, snapshot=ev.snapshot.model_dump(mode="json"))
    if isinstance(ev, ChatHistoryLoaded):
        return AppChatHistoryLoaded(**base, message_count=ev.message_count, token_estimate=ev.token_estimate, source=ev.source)
    if isinstance(ev, ApprovalRequired):
        return AppApprovalRequired(**base, plan_id=ev.plan_id, step_id=ev.step_id, step=ev.step, prompt=ev.prompt)
    if isinstance(ev, CommandStarted):
        return AppCommandStarted(**base, command=ev.command, arguments=ev.arguments)
    if isinstance(ev, CommandProgress):
        return AppCommandProgress(
            **base, command=ev.command, phase=ev.phase,
            phase_index=ev.phase_index, phase_total=ev.phase_total, message=ev.message,
        )
    if isinstance(ev, CommandCompleted):
        return AppCommandCompleted(**base, command=ev.command, result=ev.result)
    if isinstance(ev, DoctorFinding):
        return AppDoctorFinding(
            **base, report_id=ev.report_id, category=ev.category, severity=ev.severity,
            summary=ev.summary, details=ev.details,
        )
    if isinstance(ev, DoctorReportReady):
        return AppDoctorReportReady(
            **base, report_id=ev.report_id, summary_counts=ev.summary_counts,
            recommendations=ev.recommendations,
        )
    return AppRaw(**base, harness_event_name=ev.event_name, payload=ev.model_dump(mode="json"))
