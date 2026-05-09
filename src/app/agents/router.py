from __future__ import annotations

from pydantic import BaseModel

from observability import Telemetry, resolve_telemetry_dir
from observability.events import EventKind, Layer


class AgentModeRequest(BaseModel):
    mode: str
    reason: str


AgentModeDecision = AgentModeRequest


class AgentModeRouter:
    def __init__(self, telemetry: Telemetry | None = None) -> None:
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())

    analysis_terms = {
        "analyze",
        "analysis",
        "compare",
        "calculate",
        "compute",
        "chart",
        "plot",
        "correlation",
        "regression",
        "forecast",
        "summary",
    }
    knowledge_terms = {
        "remember",
        "save",
        "note",
        "preference",
        "definition",
        "means",
        "teach",
        "metric",
    }

    def request_mode(self, user_text: str) -> AgentModeRequest:
        return self.route(user_text)

    def route(self, user_text: str) -> AgentModeRequest:
        normalized = user_text.lower()
        words = set(normalized.replace("?", " ").replace(",", " ").split())
        if words & self.knowledge_terms:
            decision = AgentModeRequest(mode="knowledge", reason="knowledge_capture_intent")
            self._emit_decision(decision, user_text)
            return decision
        if words & self.analysis_terms:
            decision = AgentModeRequest(mode="analyst", reason="analysis_intent")
            self._emit_decision(decision, user_text)
            return decision
        decision = AgentModeRequest(mode="interaction", reason="front_door_default")
        self._emit_decision(decision, user_text)
        return decision

    def _emit_decision(self, decision: AgentModeRequest, user_text: str) -> None:
        self.telemetry.emit(
            Layer.APP,
            EventKind.AGENT_MODE_PROPOSED,
            payload={"mode": decision.mode, "reason": decision.reason, "input_chars": len(user_text)},
        )
