"""Artifact validity classification."""
from __future__ import annotations

from enum import StrEnum


class ValidityState(StrEnum):
    OK = "ok"
    CHANGED = "changed"
    STALE = "stale"
    NEEDS_REVIEW = "needs_review"
    REVALIDATED = "revalidated"
    BROKEN_LINEAGE = "broken_lineage"


def classify(
    *,
    fingerprint_action: str,
    stored_fingerprint: str | None,
    new_fingerprint: str | None,
    has_dependents_with_stale_inputs: bool = False,
    needs_user_review: bool = False,
    user_revalidated: bool = False,
) -> ValidityState:
    if user_revalidated:
        return ValidityState.REVALIDATED
    if needs_user_review:
        return ValidityState.NEEDS_REVIEW
    if has_dependents_with_stale_inputs:
        return ValidityState.STALE
    if fingerprint_action == "missing":
        return ValidityState.BROKEN_LINEAGE
    if (
        stored_fingerprint is not None
        and new_fingerprint is not None
        and stored_fingerprint != new_fingerprint
    ):
        return ValidityState.CHANGED
    if fingerprint_action in ("reused_fingerprint", "fingerprinted"):
        return ValidityState.OK
    if fingerprint_action == "changed":
        return ValidityState.CHANGED
    return ValidityState.NEEDS_REVIEW
