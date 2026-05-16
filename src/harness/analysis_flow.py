from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AnalysisPhase(StrEnum):
    INSPECTING = "inspecting"
    PLAN_PENDING = "plan_pending"
    APPROVAL_PENDING = "approval_pending"
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"


_TERMINAL_PHASES = {AnalysisPhase.DONE, AnalysisPhase.FAILED}


class AnalysisFlow(BaseModel):
    """Layer-3-owned state for an in-flight analysis question on one chat.

    Persisted/replayed by the orchestrator (mirror of _pending_plans) so the
    flow survives turns and the per-message L4 mode router cannot lose it.
    """

    chat_id: str
    run_id: str
    workspace_id: str
    phase: AnalysisPhase
    goal: str | None = None
    plan_id: str | None = None
    original_request: str | None = None
    inspection_summary: str | None = None
    force_attempts: int = 0
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    def is_terminal(self) -> bool:
        return self.phase in _TERMINAL_PHASES
