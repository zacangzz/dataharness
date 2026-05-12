from __future__ import annotations

from typing import Any


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)
