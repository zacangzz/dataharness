import pytest

from app.session import AppSession
from app.tui.app import DataHarnessApp
from app.tui.commands import DataHarnessCommandProvider
from app.tui.prompt_bar import PromptBar
from app.tui.screens.command_palette import CommandPaletteScreen
from harness.core.command_registry import CommandContext
from harness.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_all_harness_commands_are_reachable_from_l4_command_list(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    session = AppSession(orchestrator=orch)
    ctx = CommandContext(
        workspace_id=None,
        chat_id=None,
        run_id=None,
        has_pending_approval=False,
        has_pending_clarification=False,
    )

    harness_command_names = {d.name for d in orch.registry.help().commands}
    l4_command_names = {d.name for d in await session.list_commands(ctx)}

    assert harness_command_names
    assert harness_command_names <= l4_command_names


@pytest.mark.asyncio
async def test_registered_commands_are_reachable_from_tui_provider_palette_and_slash_hints(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "workspaces" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        descriptors = await app._session.list_commands()
        expected = {descriptor.name for descriptor in descriptors}

        provider = DataHarnessCommandProvider(screen=app.screen, match_style=None)
        provider_hits = [hit async for hit in provider.discover()]
        provider_names = {str(hit.prompt).split()[0].split("(")[0] for hit in provider_hits}

        palette = CommandPaletteScreen(session=app._session)
        await app.push_screen(palette)
        await pilot.pause()
        palette_text = palette.text_buffer()
        await app.pop_screen()
        await pilot.pause()

        prompt = app.query_one("#prompt_bar", PromptBar)
        await prompt.refresh_hints("/")
        slash_options = await prompt._build_hint_options("/", descriptors)
        slash_names = {target[1] for _, _, target in slash_options if target[0] == "command"}

        assert expected <= provider_names
        assert all(f"/{name}" in palette_text for name in expected)
        assert expected <= slash_names


@pytest.mark.asyncio
async def test_contextual_tui_commands_have_reachability_paths(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "workspaces" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        chat = await app._session.create_chat("w_0001")
        app._active_chat_id = chat.chat_id

        descriptors = {descriptor.name: descriptor for descriptor in await app._session.list_commands()}

        contextual_names = {
            "compact",
            "resume_chat",
            "delete_chat",
            "switch_workspace",
            "doctor",
            "memory_review",
            "request_execution",
            "cancel_run",
        }
        assert contextual_names <= set(descriptors)

        prompt = app.query_one("#prompt_bar", PromptBar)
        for name in sorted(contextual_names):
            prefix_len = max(1, min(len(name) - 1, 8))
            prefix = f"/{name[:prefix_len]}"
            hint_options = await prompt._build_hint_options(prefix, list(descriptors.values()))
            option_names = {target[1] for _, _, target in hint_options if target[0] == "command"}
            assert name in option_names
