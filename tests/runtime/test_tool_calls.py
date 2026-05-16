import pytest

from runtime.tool_calls import (
    ToolCallParseError,
    extract_fenced_code,
    parse_tool_call_block,
    repair_tool_call_block,
)


def test_parse_tool_call_block_returns_name_and_arguments() -> None:
    payload = '<tool_call>{"name":"arbitrary_unregistered_tool","arguments":{"mode":"manual"}}</tool_call>'
    parsed = parse_tool_call_block(payload)
    assert parsed.name == "arbitrary_unregistered_tool"
    assert parsed.arguments == {"mode": "manual"}


def test_parse_tool_call_block_defaults_missing_arguments() -> None:
    parsed = parse_tool_call_block('<tool_call>{"name":"doctor"}</tool_call>')
    assert parsed.name == "doctor"
    assert parsed.arguments == {}


def test_parse_tool_call_block_rejects_missing_name() -> None:
    with pytest.raises(ToolCallParseError):
        parse_tool_call_block('<tool_call>{"arguments":{}}</tool_call>')


def test_parse_tool_call_block_rejects_invalid_json() -> None:
    with pytest.raises(ToolCallParseError):
        parse_tool_call_block('<tool_call>{"name":"doctor",</tool_call>')


def test_repair_tool_call_block_wraps_single_object_arguments() -> None:
    repaired = repair_tool_call_block('<tool_call>{"name":"doctor","arguments":"manual"}</tool_call>')
    assert repaired == '<tool_call>{"name":"doctor","arguments":{"value":"manual"}}</tool_call>'


def test_extract_fenced_code_python_block() -> None:
    text = (
        "Here is the code:\n"
        "```python\n"
        "import pandas as pd\n"
        'df = pd.read_csv("data/x.csv")\n'
        "```\n"
    )
    assert extract_fenced_code(text) == [
        "import pandas as pd",
        'df = pd.read_csv("data/x.csv")',
    ]


def test_extract_fenced_code_missing_close_fence() -> None:
    # gen-2 uses stop=["```"], so the closing fence is consumed by the runtime.
    text = "```python\nx = 1\nprint(x)\n"
    assert extract_fenced_code(text) == ["x = 1", "print(x)"]


def test_extract_fenced_code_bare_fence_no_language() -> None:
    text = "```\ntotal = df['amount'].sum()\n```"
    assert extract_fenced_code(text) == ["total = df['amount'].sum()"]


def test_extract_fenced_code_no_fence_returns_empty() -> None:
    assert extract_fenced_code("just prose, no code at all") == []


def test_extract_fenced_code_strips_trailing_blank_lines() -> None:
    text = "```python\na = 1\n\n\n```"
    assert extract_fenced_code(text) == ["a = 1"]
