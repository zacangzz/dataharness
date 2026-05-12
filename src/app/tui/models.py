from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RunState(StrEnum):
    idle = "idle"
    running = "running"
    stopping = "stopping"
    error = "error"


class ActiveMode(StrEnum):
    interaction = "interaction"
    analyst = "analyst"
    knowledge = "knowledge"


class WorkspaceStatus(StrEnum):
    ready = "ready"
    busy = "busy"
    degraded = "degraded"


class ResultState(StrEnum):
    trusted = "trusted"
    invalidated = "invalidated"
    challenged = "challenged"
    pending = "pending"


class WorkspaceView(BaseModel):
    workspace_id: str
    run_state: RunState
    active_mode: ActiveMode


class AppView(BaseModel):
    workspace: WorkspaceView
    workspace_status: WorkspaceStatus = WorkspaceStatus.ready
    available_workspaces: list[str] = Field(default_factory=list)
    available_commands: list[str] = Field(default_factory=list)
    doctor_warning_count: int = 0
