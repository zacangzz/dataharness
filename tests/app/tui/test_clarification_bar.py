"""ClarificationBar: inline replacement for the full-screen ClarificationScreen."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from app.tui.widgets import ClarificationBar


class _Host(App):
    submitted: list[ClarificationBar.ClarificationSubmitted]
    dismissed: list[ClarificationBar.ClarificationDismissed]

    def __init__(self) -> None:
        super().__init__()
        self.submitted = []
        self.dismissed = []

    def compose(self) -> ComposeResult:
        yield ClarificationBar(id="clarification_bar")

    def on_clarification_bar_clarification_submitted(
        self, message: ClarificationBar.ClarificationSubmitted
    ) -> None:
        self.submitted.append(message)

    def on_clarification_bar_clarification_dismissed(
        self, message: ClarificationBar.ClarificationDismissed
    ) -> None:
        self.dismissed.append(message)


@pytest.mark.asyncio
async def test_show_hide_toggles_display():
    async with _Host().run_test() as pilot:
        bar = pilot.app.query_one("#clarification_bar", ClarificationBar)
        assert bar.display is False
        bar.show(question="Which file?")
        assert bar.display is True
        bar.hide()
        assert bar.display is False


@pytest.mark.asyncio
async def test_submit_via_enter_emits_message():
    async with _Host().run_test() as pilot:
        bar = pilot.app.query_one("#clarification_bar", ClarificationBar)
        bar.show(question="What?")
        input_widget = bar.query_one("#clarification_input", Input)
        input_widget.value = "yes"
        input_widget.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert any(m.text == "yes" for m in pilot.app.submitted)


@pytest.mark.asyncio
async def test_empty_input_does_not_emit_on_enter():
    async with _Host().run_test() as pilot:
        bar = pilot.app.query_one("#clarification_bar", ClarificationBar)
        bar.show(question="What?")
        input_widget = bar.query_one("#clarification_input", Input)
        input_widget.value = ""
        input_widget.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert pilot.app.submitted == []


@pytest.mark.asyncio
async def test_escape_emits_dismissed_message():
    async with _Host().run_test() as pilot:
        bar = pilot.app.query_one("#clarification_bar", ClarificationBar)
        bar.show(question="?")
        bar.focus()
        await pilot.press("escape")
        await pilot.pause()
        assert len(pilot.app.dismissed) == 1


@pytest.mark.asyncio
async def test_show_with_hostile_brackets_does_not_raise():
    hostile_question = (
        "validation error: [type=value_error, input_value={'a': [1,2]}, "
        "input_type=dict]"
    )
    async with _Host().run_test() as pilot:
        bar = pilot.app.query_one("#clarification_bar", ClarificationBar)
        bar.show(question=hostile_question)
        await pilot.pause()
        assert bar.display is True
