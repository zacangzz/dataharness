"""Canonical Layer 3 prompt-profile mode identifiers.

Single source of truth for the closed set of prompt-profile names used by the
intent router, the prompt-profile registry, and the orchestrator. Values are
the exact historical strings so persistence/serialization is unchanged.
"""
from __future__ import annotations

INTERACTION = "interaction"
ANALYST = "analyst"
KNOWLEDGE = "knowledge"
CLARIFICATION = "clarification"

VALID_PROFILE_MODES = frozenset({INTERACTION, ANALYST, KNOWLEDGE, CLARIFICATION})
