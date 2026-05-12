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


_CONTROL_CHAR_MAP = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape_control_chars_in_strings(raw: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    for ch in raw:
        if in_string:
            if escape:
                out.append(ch)
                escape = False
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                continue
            mapped = _CONTROL_CHAR_MAP.get(ch)
            if mapped is not None:
                out.append(mapped)
                continue
            if ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


_NAME_ALIASES = ("name", "tool_name", "tool", "function", "function_name")
_ARGS_ALIASES = ("arguments", "parameters", "args", "params", "input")


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    name: Any = None
    for key in _NAME_ALIASES:
        if key in payload and payload[key] is not None:
            name = payload[key]
            break
    args: Any = None
    for key in _ARGS_ALIASES:
        if key in payload and payload[key] is not None:
            args = payload[key]
            break
    if name is None:
        raise ToolCallParseError("tool_call payload missing name")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        args = {"value": args}
    return {"name": str(name), "arguments": args}


def _match_and_parse(text: str) -> dict[str, Any]:
    match = TOOL_CALL_RE.search(text)
    if match is None:
        raise ToolCallParseError("missing tool_call block")
    raw = match.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_escape_control_chars_in_strings(raw))
    except json.JSONDecodeError as exc:
        snippet = raw[:200] + ("…" if len(raw) > 200 else "")
        raise ToolCallParseError(f"invalid tool_call json: {exc} | raw={snippet!r}") from exc


def parse_tool_call_block(text: str) -> ParsedToolCall:
    payload = _match_and_parse(text)
    normalized = _normalize_payload(payload)
    return ParsedToolCall(name=normalized["name"], arguments=normalized["arguments"])


def repair_tool_call_block(text: str) -> str:
    payload = _match_and_parse(text)
    normalized = _normalize_payload(payload)
    return f"<tool_call>{json.dumps(normalized, separators=(',', ':'))}</tool_call>"
