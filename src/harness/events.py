from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from harness.status import HarnessStatusSnapshot
from runtime.types import RuntimeStatus
from worker.models import StepExecutionEnvelope, StepTaskStatus


def _new_event_id() -> str:
    return f"ev_{uuid4().hex[:12]}"


class HarnessEvent(BaseModel):
    event_id: str = Field(default_factory=_new_event_id)
    event_name: str
    ts: datetime
    workspace_id: str | None = None
    chat_id: str | None = None
    run_id: str | None = None


class HarnessEventRef(BaseModel):
    event_id: str
    event_name: str
    ts: datetime
    run_id: str | None = None


# --- turn lifecycle ---

class TurnStarted(HarnessEvent):
    event_name: Literal["TurnStarted"] = "TurnStarted"
    turn_id: str
    user_message_id: str
    active_mode: str


class FinalMessage(HarnessEvent):
    event_name: Literal["FinalMessage"] = "FinalMessage"
    assistant_message_id: str
    text: str
    usage: dict[str, int] = Field(default_factory=dict)


class TurnFailed(HarnessEvent):
    event_name: Literal["TurnFailed"] = "TurnFailed"
    failure_summary: str
    error_code: str
    details: dict[str, Any] = Field(default_factory=dict)


class TurnCancelled(HarnessEvent):
    event_name: Literal["TurnCancelled"] = "TurnCancelled"
    reason: str
    cancelled_at: datetime


class TurnPaused(HarnessEvent):
    event_name: Literal["TurnPaused"] = "TurnPaused"
    reason: Literal["awaiting_tool_dispatch"]
    pending_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    partial_text: str = ""


class ModeHandoffAccepted(HarnessEvent):
    event_name: Literal["ModeHandoffAccepted"] = "ModeHandoffAccepted"
    from_mode: str
    to_mode: str
    reason: str


class ToolCallExecuted(HarnessEvent):
    event_name: Literal["ToolCallExecuted"] = "ToolCallExecuted"
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    iteration: int = 0


# --- status / health ---

class StatusChanged(HarnessEvent):
    event_name: Literal["StatusChanged"] = "StatusChanged"
    snapshot: HarnessStatusSnapshot


class WorkspaceHealthChanged(HarnessEvent):
    event_name: Literal["WorkspaceHealthChanged"] = "WorkspaceHealthChanged"
    health: Literal["ready", "busy", "degraded", "error"]
    reason: str | None = None


class RuntimeStatusChanged(HarnessEvent):
    event_name: Literal["RuntimeStatusChanged"] = "RuntimeStatusChanged"
    runtime_status: RuntimeStatus
    reason: str | None = None


class ModeActivated(HarnessEvent):
    event_name: Literal["ModeActivated"] = "ModeActivated"
    mode: str
    prior_mode: str | None
    decided_at: datetime


class ContextReloaded(HarnessEvent):
    event_name: Literal["ContextReloaded"] = "ContextReloaded"
    workspace_id: str
    source_count: int
    memory_token_estimate: int


class PromptBuilt(HarnessEvent):
    event_name: Literal["PromptBuilt"] = "PromptBuilt"
    request_id: str
    prompt_token_estimate: int
    breakdown: dict[str, int] = Field(default_factory=dict)


# --- chat ---

class ChatCreated(HarnessEvent):
    event_name: Literal["ChatCreated"] = "ChatCreated"
    chat: dict[str, Any]  # ChatSummary serialized


class ChatSelected(HarnessEvent):
    event_name: Literal["ChatSelected"] = "ChatSelected"
    chat_id: str


class ChatDeleted(HarnessEvent):
    event_name: Literal["ChatDeleted"] = "ChatDeleted"
    chat_id: str


class ChatHistoryLoaded(HarnessEvent):
    event_name: Literal["ChatHistoryLoaded"] = "ChatHistoryLoaded"
    chat_id: str
    message_count: int
    token_estimate: int
    source: Literal["new", "resumed"]


class ChatHistoryCompacted(HarnessEvent):
    event_name: Literal["ChatHistoryCompacted"] = "ChatHistoryCompacted"
    chat_id: str
    status: Literal["queued", "running", "completed", "failed"]
    summary_token_estimate: int | None = None
    replaced_turn_count: int | None = None
    compaction_count: int = 0


# --- commands ---

class CommandStarted(HarnessEvent):
    event_name: Literal["CommandStarted"] = "CommandStarted"
    command: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class CommandProgress(HarnessEvent):
    event_name: Literal["CommandProgress"] = "CommandProgress"
    command: str
    phase: str
    phase_index: int
    phase_total: int
    message: str | None = None


class CommandCompleted(HarnessEvent):
    event_name: Literal["CommandCompleted"] = "CommandCompleted"
    command: str
    result: dict[str, Any] = Field(default_factory=dict)


# --- runtime stream ---

class RuntimeDelta(HarnessEvent):
    event_name: Literal["RuntimeDelta"] = "RuntimeDelta"
    request_id: str
    seq: int
    delta_type: Literal["text", "reasoning", "tool_call"]
    text: str | None = None
    tool_call: dict[str, Any] | None = None


# --- plans / approval ---

class PlanReady(HarnessEvent):
    event_name: Literal["PlanReady"] = "PlanReady"
    plan_id: str
    plan: dict[str, Any]


class ApprovalRequired(HarnessEvent):
    event_name: Literal["ApprovalRequired"] = "ApprovalRequired"
    plan_id: str
    step_id: str
    step: dict[str, Any]
    prompt: str


class ApprovalResolved(HarnessEvent):
    event_name: Literal["ApprovalResolved"] = "ApprovalResolved"
    plan_id: str
    step_id: str
    decision: Literal["approved", "rejected", "clarified"]


# --- worker tasks ---

class StepTaskSubmitted(HarnessEvent):
    event_name: Literal["StepTaskSubmitted"] = "StepTaskSubmitted"
    task_id: str
    step_id: str
    plan_id: str


class StepTaskStatusChanged(HarnessEvent):
    event_name: Literal["StepTaskStatusChanged"] = "StepTaskStatusChanged"
    task_id: str
    status: StepTaskStatus


class StepCompleted(HarnessEvent):
    event_name: Literal["StepCompleted"] = "StepCompleted"
    task_id: str
    envelope: StepExecutionEnvelope


class ArtifactsReady(HarnessEvent):
    event_name: Literal["ArtifactsReady"] = "ArtifactsReady"
    step_id: str
    artifacts: list[Path]


# --- doctor ---

class DoctorStarted(HarnessEvent):
    event_name: Literal["DoctorStarted"] = "DoctorStarted"
    trigger: str
    report_id: str


class DoctorFinding(HarnessEvent):
    event_name: Literal["DoctorFinding"] = "DoctorFinding"
    report_id: str
    category: Literal["source", "validity", "lineage", "tmp", "memory"]
    severity: Literal["info", "warn", "error"]
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class DoctorActionProposed(HarnessEvent):
    event_name: Literal["DoctorActionProposed"] = "DoctorActionProposed"
    report_id: str
    action: Literal["cleanup", "promote", "keep", "review"]
    target: str
    rationale: str
    destination_path: str | None = None


class DoctorReportReady(HarnessEvent):
    event_name: Literal["DoctorReportReady"] = "DoctorReportReady"
    report_id: str
    summary_counts: dict[str, int] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    action_records: list[dict[str, Any]] = Field(default_factory=list)
