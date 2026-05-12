import pytest
from textual.widgets import Input

from app.tui.prompt_editor import PromptEditor

from app.tui.app import DataHarnessApp
from app.tui.commands import DataHarnessCommandProvider, build_command_prefill


@pytest.mark.asyncio
async def test_command_provider_discovers_layer3_commands(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        provider = DataHarnessCommandProvider(screen=app.screen, match_style=None)
        hits = [hit async for hit in provider.discover()]
        prompts = [str(hit.prompt) for hit in hits]

        assert any("doctor" in prompt for prompt in prompts)
        assert any("switch_workspace" in prompt for prompt in prompts)


@pytest.mark.asyncio
async def test_command_provider_search_filters_commands(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        provider = DataHarnessCommandProvider(screen=app.screen, match_style=None)
        hits = [hit async for hit in provider.search("doctor")]
        prompts = [str(hit.prompt).lower() for hit in hits]

        assert prompts
        assert all("doctor" in prompt for prompt in prompts)


@pytest.mark.asyncio
async def test_build_command_prefill_uses_argument_placeholders(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        descriptors = await app._session.list_commands()
        switch = next(d for d in descriptors if d.name == "switch_workspace")

        assert build_command_prefill(switch) == "/switch_workspace <workspace_id>"


@pytest.mark.asyncio
async def test_optional_argument_command_selection_does_not_prefill_input(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        descriptors = await app._session.list_commands()
        help_command = next(d for d in descriptors if d.name == "help")
        user_input = app.query_one("#user_input", PromptEditor)
        user_input.set_text("keep this text")

        app.handle_command_palette_selection(help_command)
        await pilot.pause()

        assert user_input.text == "keep this text"
