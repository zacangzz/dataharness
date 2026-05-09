from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel


TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)


class ToolCallParseError(ValueError):
    pass


class ParsedToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


def _match_and_parse(text: str) -> dict[str, Any]:
    match = TOOL_CALL_RE.search(text)
    if match is None:
        raise ToolCallParseError("missing tool_call block")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ToolCallParseError(f"invalid tool_call json: {exc}") from exc


def parse_tool_call_block(text: str) -> ParsedToolCall:
    payload = _match_and_parse(text)
    if set(payload) != {"name", "arguments"}:
        raise ToolCallParseError("tool_call payload must contain name and arguments")
    if not isinstance(payload["arguments"], dict):
        raise ToolCallParseError("tool_call arguments must be an object")
    return ParsedToolCall(name=payload["name"], arguments=payload["arguments"])


def repair_tool_call_block(text: str) -> str:
    payload = _match_and_parse(text)
    if isinstance(payload.get("arguments"), dict):
        return text
    payload["arguments"] = {"value": payload.get("arguments")}
    return f"<tool_call>{json.dumps(payload, separators=(',', ':'))}</tool_call>"
