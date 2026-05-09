import pytest

from runtime.tool_calls import ToolCallParseError, parse_tool_call_block, repair_tool_call_block


def test_parse_tool_call_block_returns_name_and_arguments() -> None:
    payload = '<tool_call>{"name":"doctor","arguments":{"mode":"manual"}}</tool_call>'
    parsed = parse_tool_call_block(payload)
    assert parsed.name == "doctor"
    assert parsed.arguments == {"mode": "manual"}


def test_parse_tool_call_block_rejects_missing_arguments() -> None:
    with pytest.raises(ToolCallParseError):
        parse_tool_call_block('<tool_call>{"name":"doctor"}</tool_call>')


def test_parse_tool_call_block_rejects_invalid_json() -> None:
    with pytest.raises(ToolCallParseError):
        parse_tool_call_block('<tool_call>{"name":"doctor",</tool_call>')


def test_repair_tool_call_block_wraps_single_object_arguments() -> None:
    repaired = repair_tool_call_block('<tool_call>{"name":"doctor","arguments":"manual"}</tool_call>')
    assert repaired == '<tool_call>{"name":"doctor","arguments":{"value":"manual"}}</tool_call>'
