import pytest
from textual.app import App, ComposeResult

from app.tui.prompt_editor import PromptEditor


class PromptEditorHarness(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.submitted: str | None = None

    def compose(self) -> ComposeResult:
        yield PromptEditor(id="editor")

    def on_prompt_editor_submitted(self, event: PromptEditor.Submitted) -> None:
        self.submitted = event.text


@pytest.mark.asyncio
async def test_prompt_editor_set_insert_and_text_buffer():
    app = PromptEditorHarness()
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", PromptEditor)
        editor.set_text("hello")
        editor.insert_text("\nworld")

        assert editor.text == "hello\nworld"


@pytest.mark.asyncio
async def test_prompt_editor_ctrl_j_inserts_newline_without_submit():
    app = PromptEditorHarness()
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", PromptEditor)
        editor.set_text("hello")
        editor.focus()
        await pilot.press("ctrl+j")

        assert editor.text == "hello\n"
        assert app.submitted is None


@pytest.mark.asyncio
async def test_prompt_editor_shift_enter_inserts_newline():
    app = PromptEditorHarness()
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", PromptEditor)
        editor.set_text("hello")
        editor.focus()
        await pilot.press("shift+enter")

        assert editor.text == "hello\n"
        assert app.submitted is None


@pytest.mark.asyncio
async def test_prompt_editor_enter_submits_text():
    app = PromptEditorHarness()
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", PromptEditor)
        editor.set_text("run analysis")
        editor.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert app.submitted == "run analysis"
