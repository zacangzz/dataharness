from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class AppEvent(BaseModel):
    app_event_id: str = Field(default_factory=lambda: f"app_{uuid4().hex[:12]}")
    event_name: str
    ts: datetime
    workspace_id: str | None = None
    chat_id: str | None = None
    run_id: str | None = None


class AppTurnStarted(AppEvent):
    event_name: Literal["AppTurnStarted"] = "AppTurnStarted"
    turn_id: str
    user_message_id: str
    active_mode: str


class AppRuntimeDelta(AppEvent):
    event_name: Literal["AppRuntimeDelta"] = "AppRuntimeDelta"
    delta_type: Literal["text", "reasoning", "tool_call"]
    text: str | None
    tool_call: dict[str, Any] | None


class AppFinalMessage(AppEvent):
    event_name: Literal["AppFinalMessage"] = "AppFinalMessage"
    assistant_message_id: str
    text: str
    usage: dict[str, int] = Field(default_factory=dict)


class AppTurnFailed(AppEvent):
    event_name: Literal["AppTurnFailed"] = "AppTurnFailed"
    failure_summary: str
    error_code: str
    details: dict[str, Any] = Field(default_factory=dict)


class AppTurnCancelled(AppEvent):
    event_name: Literal["AppTurnCancelled"] = "AppTurnCancelled"
    reason: str
    cancelled_at: datetime


class AppStatusChanged(AppEvent):
    event_name: Literal["AppStatusChanged"] = "AppStatusChanged"
    snapshot: dict[str, Any]


class AppChatHistoryLoaded(AppEvent):
    event_name: Literal["AppChatHistoryLoaded"] = "AppChatHistoryLoaded"
    message_count: int
    token_estimate: int
    source: str


class AppApprovalRequired(AppEvent):
    event_name: Literal["AppApprovalRequired"] = "AppApprovalRequired"
    plan_id: str
    step_id: str
    step: dict[str, Any]
    prompt: str


class AppCommandStarted(AppEvent):
    event_name: Literal["AppCommandStarted"] = "AppCommandStarted"
    command: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AppCommandProgress(AppEvent):
    event_name: Literal["AppCommandProgress"] = "AppCommandProgress"
    command: str
    phase: str
    phase_index: int
    phase_total: int
    message: str | None


class AppCommandCompleted(AppEvent):
    event_name: Literal["AppCommandCompleted"] = "AppCommandCompleted"
    command: str
    result: dict[str, Any] = Field(default_factory=dict)


class AppDoctorFinding(AppEvent):
    event_name: Literal["AppDoctorFinding"] = "AppDoctorFinding"
    report_id: str
    category: str
    severity: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class AppDoctorReportReady(AppEvent):
    event_name: Literal["AppDoctorReportReady"] = "AppDoctorReportReady"
    report_id: str
    summary_counts: dict[str, int] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


class AppRaw(AppEvent):
    """Catch-all for events we don't yet map specifically."""
    event_name: Literal["AppRaw"] = "AppRaw"
    harness_event_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
