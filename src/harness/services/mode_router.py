from __future__ import annotations

import re
from typing import Callable

from pydantic import BaseModel

from observability import Telemetry, resolve_telemetry_dir
from observability.events import EventKind, Layer

from harness.services.profile_modes import (
    INTERACTION, ANALYST, KNOWLEDGE, CLARIFICATION, VALID_PROFILE_MODES,
)


class ProfileDecision(BaseModel):
    mode: str
    reason: str


class ModeRouter:
    def __init__(
        self,
        telemetry: Telemetry | None = None,
        *,
        enable_llm_classifier: bool = False,
        llm_classifier: Callable[[str], str | None] | None = None,
    ) -> None:
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())
        self.enable_llm_classifier = enable_llm_classifier
        self.llm_classifier = llm_classifier
        self._classifier_cache: dict[str, str] = {}

    analysis_terms = frozenset({
        "analyze", "analysis", "compare", "calculate", "compute",
        "chart", "plot", "correlation", "regression", "forecast", "summary",
        # aggregations / counts
        "count", "total", "sum", "average", "mean", "median",
        "max", "maximum", "min", "minimum",
        # grouping / filtering / shape
        "group", "filter", "top", "bottom", "distinct", "unique", "aggregate",
        "rank", "percent", "percentage", "ratio", "trend", "distribution",
        "histogram",
    })
    rule_language_terms = frozenset({
        "derive", "derived", "transform", "transformed", "normalize", "normalized",
        "encode", "bucket", "map", "join", "merge", "flag", "classify", "lookup",
        "enrich", "moving", "rolling", "lag", "lead", "cumulative",
    })
    column_language_terms = frozenset({"column", "columns", "field", "fields"})
    # Gate set = rule ∪ column signals plus standalone tokens; derived so the
    # subsets stay the single source of truth and cannot drift.
    transformation_terms = rule_language_terms | column_language_terms | frozenset(
        {"add", "one", "hot"}
    )
    workspace_reference_patterns = (
        ".csv", ".tsv", ".parquet", ".xlsx", ".xls", "data/", "@data/",
    )
    analysis_phrases = (
        "how many", "how much", "number of", "breakdown of", "rate of",
        "share of", "what percent", "what percentage",
    )
    knowledge_terms = frozenset({
        "remember", "save", "note", "preference", "definition",
        "means", "teach", "metric",
    })

    def route(self, user_text: str) -> ProfileDecision:
        normalized = user_text.lower()
        words = {w for w in re.split(r"[^a-z0-9_]+", normalized) if w}

        if words & self.knowledge_terms:
            decision = ProfileDecision(mode=KNOWLEDGE, reason="knowledge_capture_intent")
            self._emit_decision(decision, user_text)
            return decision

        if (
            words & self.analysis_terms
            or self._phrase_match(normalized)
            or self._transformation_match(normalized, words)
        ):
            decision = ProfileDecision(mode=ANALYST, reason="analysis_intent")
            self._emit_decision(decision, user_text)
            return decision

        classified = self._classify_with_llm(user_text)
        if classified is not None and classified != INTERACTION:
            decision = ProfileDecision(mode=classified, reason="llm_classifier")
            self._emit_decision(decision, user_text)
            return decision

        decision = ProfileDecision(mode=INTERACTION, reason="front_door_default")
        self._emit_decision(decision, user_text)
        return decision

    def _phrase_match(self, normalized: str) -> bool:
        return any(phrase in normalized for phrase in self.analysis_phrases)

    def _transformation_match(self, normalized: str, words: set[str]) -> bool:
        if not (words & self.transformation_terms):
            return False
        has_workspace_ref = any(p in normalized for p in self.workspace_reference_patterns)
        has_column_language = bool(words & self.column_language_terms)
        has_rule_language = bool(words & self.rule_language_terms)
        one_hot = {"one", "hot"} <= words
        min_max = {"min", "max"} <= words and bool(words & {"normalize", "normalized"})
        return has_workspace_ref or has_column_language or has_rule_language or one_hot or min_max

    def _classify_with_llm(self, user_text: str) -> str | None:
        if not self.enable_llm_classifier or self.llm_classifier is None:
            return None
        cached = self._classifier_cache.get(user_text)
        if cached is not None:
            return cached
        try:
            result = self.llm_classifier(user_text)
        except Exception:  # noqa: BLE001
            return None
        if result in VALID_PROFILE_MODES:
            self._classifier_cache[user_text] = result
            return result
        return None

    def _emit_decision(self, decision: ProfileDecision, user_text: str) -> None:
        self.telemetry.emit(
            Layer.HARNESS,
            EventKind.AGENT_MODE_PROPOSED,
            payload={"mode": decision.mode, "reason": decision.reason, "input_chars": len(user_text)},
        )
