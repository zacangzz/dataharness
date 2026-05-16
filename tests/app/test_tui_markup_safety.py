"""Markup-safety smoke tests.

Stored chat messages and harness error summaries may contain literal `[`/`]`
sequences (e.g. `[TOOL_RESULT]`, pydantic `[type=..., input_value=...]`) and
`<tool_call>` blocks. Textual's `Static` parses content as Rich markup by
default, so unbalanced brackets crash with `MarkupError`. These tests
construct the affected widgets directly with hostile strings and assert no
exception escapes.
"""

from __future__ import annotations

from app.tui.conversation import (
    AssistantMessageBlock,
    SystemMessageBlock,
    UserMessageBlock,
    _clean,
)
from app.tui.widgets import (
    ArtifactsPane,
    ContextMemoryPane,
    DoctorPane,
    FailurePane,
    PlanPane,
    ProvenancePane,
    StatusPane,
    StepStatusPane,
    WorkspaceBar,
)

HOSTILE = (
    "validation error: [type=value_error, input_value={'id': 'plan_1', "
    "'steps': [{'purpose': 'x'}]}, input_type=dict]\n"
    "<tool_call>{\"name\":\"analysis_plan\",\"arguments\":{}}</tool_call>"
)


def test_user_message_block_accepts_hostile_brackets():
    block = UserMessageBlock(HOSTILE)
    # _clean strips <tool_call> blocks; pydantic-style brackets remain literal
    assert "<tool_call>" not in block.text_buffer()
    assert "validation error" in block.text_buffer()
    assert "[type=value_error" in block.text_buffer()


def test_system_message_block_accepts_hostile_brackets():
    block = SystemMessageBlock(HOSTILE)
    assert block.text_buffer() == HOSTILE


def test_assistant_message_block_strips_tool_calls_via_clean():
    cleaned = _clean(HOSTILE)
    assert "<tool_call>" not in cleaned
    assert "validation error" in cleaned


def test_assistant_clean_renders_csv_code_fence_as_markdown_table():
    cleaned = _clean(
        "The content is:\n```csv\n"
        "customer_id,name,region\n"
        "c001,Acme Corp,EU\n"
        "c002,Globex,US\n"
        "```"
    )
    assert "```csv" not in cleaned
    assert "| customer_id | name | region |" in cleaned
    assert "| c001 | Acme Corp | EU |" in cleaned


def test_assistant_message_block_constructs_with_hostile_text():
    block = AssistantMessageBlock(HOSTILE)
    assert block.text_buffer() == HOSTILE


def test_static_subclasses_default_to_markup_false():
    for cls in (
        WorkspaceBar,
        PlanPane,
        StepStatusPane,
        ArtifactsPane,
        ContextMemoryPane,
        DoctorPane,
        FailurePane,
        ProvenancePane,
        StatusPane,
    ):
        w = cls()
        # _render_markup is the internal attribute set by Widget from the
        # `markup` kwarg passed to Static.__init__.
        assert getattr(w, "_render_markup", True) is False, (
            f"{cls.__name__} did not disable markup parsing"
        )
