from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RepairResult:
    kind: str  # "applied" | "not_applicable"
    payload: dict[str, Any]
    recipe: str | None = None


def _wrapper_repair(payload: dict[str, Any], record_kind: str | None) -> tuple[bool, dict[str, Any]]:
    args = payload.get("arguments")
    if "name" in payload and args is not None and not isinstance(args, dict):
        return True, {**payload, "arguments": {"value": args}}
    return False, payload


def _type_normalization(payload: dict[str, Any], record_kind: str | None) -> tuple[bool, dict[str, Any]]:
    args = payload.get("arguments")
    if not isinstance(args, dict):
        return False, payload
    changed = False
    new_args: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            try:
                new_args[key] = float(value) if "." in value else int(value)
                changed = True
                continue
            except ValueError:
                pass
        new_args[key] = value
    if not changed:
        return False, payload
    return True, {**payload, "arguments": new_args}


def _path_normalization(payload: dict[str, Any], record_kind: str | None) -> tuple[bool, dict[str, Any]]:
    fields = ("declared_inputs", "expected_outputs", "artifact_refs")
    changed = False
    new_payload = dict(payload)
    for field in fields:
        if field not in payload or not isinstance(payload[field], list):
            continue
        normalized: list[Any] = []
        for raw in payload[field]:
            if not isinstance(raw, str):
                normalized.append(raw)
                continue
            text = raw.replace("\\", "/").lstrip("/")
            text = str(PurePosixPath(text))
            if text != raw:
                changed = True
            normalized.append(text)
        new_payload[field] = normalized
    if not changed:
        return False, payload
    return True, new_payload


def _metadata_insertion(payload: dict[str, Any], record_kind: str | None) -> tuple[bool, dict[str, Any]]:
    if record_kind is None:
        return False, payload
    changed = False
    new_payload = dict(payload)
    if "schema_version" not in new_payload:
        new_payload["schema_version"] = "1.0"
        changed = True
    if "id" not in new_payload:
        new_payload["id"] = uuid4().hex
        changed = True
    if "created_at" not in new_payload:
        new_payload["created_at"] = datetime.now(UTC).isoformat()
        changed = True
    return changed, new_payload


REPAIR_RECIPES = (
    ("wrapper_repair", _wrapper_repair),
    ("type_normalization", _type_normalization),
    ("path_normalization", _path_normalization),
    ("metadata_insertion", _metadata_insertion),
)


def try_deterministic_repair(
    payload: dict[str, Any],
    *,
    failure_kind: str,
    record_kind: str | None = None,
) -> RepairResult:
    if failure_kind not in {"schema_mismatch", "parse_failure", "deterministic_repair_candidate"}:
        return RepairResult(kind="not_applicable", payload=payload)
    for name, recipe in REPAIR_RECIPES:
        applied, new_payload = recipe(payload, record_kind)
        if applied:
            return RepairResult(kind="applied", payload=new_payload, recipe=name)
    return RepairResult(kind="not_applicable", payload=payload)
