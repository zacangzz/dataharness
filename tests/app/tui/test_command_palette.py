import pytest

from app.tui.app import DataHarnessApp
from app.tui.screens.command_palette import CommandPaletteScreen


@pytest.mark.asyncio
async def test_palette_shows_registered_commands(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        screen = CommandPaletteScreen(session=app._session)
        await app.push_screen(screen)
        await pilot.pause()
        text = screen.text_buffer()
        assert "doctor" in text
        assert "retry_step" in text
        assert "rerun_step" in text


@pytest.mark.asyncio
async def test_palette_annotates_unavailable_commands(tmp_path):
    from harness.command_registry import HarnessCommandDescriptor, ArgSpec

    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        orch = app._session.orchestrator
        orch.registry.register(
            HarnessCommandDescriptor(
                name="_test_unavailable", slash_alias="/_test_unavailable",
                short_description="test stub", arguments=[],
                available=False, disabled_reason="test fixture",
                affected_resource="run",
                expected_event_types=["CommandCompleted"],
                example_usage="/_test_unavailable",
            ),
            lambda ctx, args: None,
        )
        screen = CommandPaletteScreen(session=app._session)
        await app.push_screen(screen)
        await pilot.pause()
        text = screen.text_buffer()
        assert "(unavailable" in text
