from runtime.tool_calls import parse_tool_call_block


def test_parse_tolerates_literal_newline_in_string():
    raw = '<tool_call>{"name":"x","arguments":{"text":"line1\nline2"}}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.name == "x"
    assert parsed.arguments == {"text": "line1\nline2"}


def test_parse_tolerates_tab_and_cr_in_string():
    raw = '<tool_call>{"name":"x","arguments":{"text":"a\tb\rc"}}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.arguments == {"text": "a\tb\rc"}


def test_parse_handles_other_control_chars_via_sanitizer():
    raw = '<tool_call>{"name":"x","arguments":{"text":"x\x01y"}}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.arguments["text"] == "x\x01y"


def test_parse_preserves_escaped_quote_inside_string():
    raw = '<tool_call>{"name":"x","arguments":{"text":"say \\"hi\\"\nnext"}}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.arguments["text"] == 'say "hi"\nnext'


def test_strict_json_still_works():
    raw = '<tool_call>{"name":"y","arguments":{"a":1}}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.name == "y"
    assert parsed.arguments == {"a": 1}


def test_parse_accepts_parameters_alias_for_arguments():
    raw = '<tool_call>{"name":"x","parameters":{"a":1}}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.arguments == {"a": 1}


def test_parse_accepts_tool_name_alias_for_name():
    raw = '<tool_call>{"tool_name":"x","arguments":{"a":1}}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.name == "x"


def test_parse_ignores_extra_keys():
    raw = '<tool_call>{"name":"x","arguments":{"a":1},"description":"foo"}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.name == "x"
    assert parsed.arguments == {"a": 1}


def test_parse_coerces_non_dict_arguments():
    raw = '<tool_call>{"name":"x","arguments":"hello"}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.arguments == {"value": "hello"}


def test_parse_defaults_missing_arguments_to_empty_dict():
    raw = '<tool_call>{"name":"x"}</tool_call>'
    parsed = parse_tool_call_block(raw)
    assert parsed.arguments == {}
