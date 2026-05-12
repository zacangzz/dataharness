import pytest
from textual.widgets import Input

from app.tui.app import DataHarnessApp
from app.tui.jump import Jumper
from app.tui.prompt_editor import PromptEditor
from app.tui.widgets import ConversationPane, SidebarPane, WorkspaceBar


@pytest.mark.asyncio
async def test_jumper_finds_visible_widget_targets(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        jumper = Jumper({"conversation": "2", "sidebar": "3"}, screen=app.screen)

        overlays = jumper.get_overlays()
        keys = {info.key for info in overlays.values()}

        assert "2" in keys
        assert "3" in keys


@pytest.mark.asyncio
async def test_jump_overlay_focuses_selected_target(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()

        await app.action_toggle_jump_mode()
        await pilot.press("2")
        await pilot.pause()

        assert isinstance(app.focused, ConversationPane)


@pytest.mark.asyncio
async def test_jump_overlay_focuses_prompt_input_for_one(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_focus(app.query_one("#conversation", ConversationPane))

        await app.action_toggle_jump_mode()
        await pilot.press("1")
        await pilot.pause()

        assert isinstance(app.focused, PromptEditor)
        assert app.focused.id == "user_input"


@pytest.mark.asyncio
async def test_jump_overlay_focuses_sidebar_for_three(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_focus(app.query_one("#conversation", ConversationPane))

        await app.action_toggle_jump_mode()
        await pilot.press("3")
        await pilot.pause()

        assert isinstance(app.focused, SidebarPane)


@pytest.mark.asyncio
async def test_jump_overlay_focuses_workspace_bar_for_w(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_focus(app.query_one("#conversation", ConversationPane))

        await app.action_toggle_jump_mode()
        await pilot.press("w")
        await pilot.pause()

        assert isinstance(app.focused, WorkspaceBar)
