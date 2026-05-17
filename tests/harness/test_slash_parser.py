import pytest

from harness.core.command_registry import parse_slash


def test_simple_command():
    cmd, args = parse_slash("/doctor")
    assert cmd == "doctor" and args == []


def test_positional_args():
    cmd, args = parse_slash("/rerun_step step_1")
    assert cmd == "rerun_step" and args == ["step_1"]


def test_quoted_arg_with_spaces():
    cmd, args = parse_slash('/inspect_artifact "Project Reports/q1.csv"')
    assert cmd == "inspect_artifact" and args == ["Project Reports/q1.csv"]


def test_multiple_quoted_args():
    cmd, args = parse_slash('/cancel_run "stuck mid step"')
    assert cmd == "cancel_run" and args == ["stuck mid step"]


def test_unknown_grammar_named_flag_raises():
    with pytest.raises(ValueError):
        parse_slash("/doctor --verbose")


def test_non_slash_raises():
    with pytest.raises(ValueError):
        parse_slash("doctor")
