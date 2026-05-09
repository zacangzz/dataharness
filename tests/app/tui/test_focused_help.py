import pytest

from app.tui.app import DataHarnessApp
from app.tui.help import HelpData, HelpScreen
from app.tui.prompt_bar import PromptBar


def test_help_data_is_plain_widget_metadata():
    data = HelpData(title="Prompt", description="Type text")

    assert data.title == "Prompt"
    assert data.description == "Type text"


@pytest.mark.asyncio
async def test_help_screen_renders_focused_widget_help(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt_bar", PromptBar)
        app.set_focus(prompt.input)

        await app.action_help()
        await pilot.pause()

        assert isinstance(app.screen, HelpScreen)
        assert "Prompt Bar" in app.screen.text_buffer()


@pytest.mark.asyncio
async def test_help_screen_restores_focus_to_original_widget_on_close(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt_bar", PromptBar)
        app.set_focus(prompt.input)

        await app.action_help()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert app.focused is prompt.input
