import pytest

from app.tui.app import DataHarnessApp
from app.tui.screens.workspace_modal import WorkspaceModal
from harness.exceptions import WorkspaceSwitchBlocked


@pytest.mark.asyncio
async def test_workspace_switch_blocked_then_force(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        sess = app._session
        await sess.create_workspace("w_0001")
        await sess.create_workspace("w_0002")
        # Simulate active run.
        sess.orchestrator._active_run_id = "fake_run"
        with pytest.raises(WorkspaceSwitchBlocked):
            await sess.activate_workspace("w_0002", force=False)
        snap = await sess.activate_workspace("w_0002", force=True)
        assert snap.workspace_id == "w_0002"


@pytest.mark.asyncio
async def test_command_palette_lists_v1_required_commands(tmp_path):
    from app.tui.app import DataHarnessApp
    from app.tui.screens.command_palette import CommandPaletteScreen

    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        screen = CommandPaletteScreen(session=app._session)
        await app.push_screen(screen)
        await pilot.pause()
        text = screen.text_buffer()
        for required in [
            "/doctor", "/compact", "/cancel_run", "/retry_step", "/revise_goal",
            "/stop_after_current_step", "/rerun_step", "/challenge_conclusion",
            "/mark_result_trusted", "/mark_result_invalidated", "/inspect_artifact",
            "/memory_review", "/provenance_inspect", "/switch_workspace",
            "/workspace_status", "/workspace_inventory", "/validity_inspect",
            "/help", "/create_chat", "/list_chats", "/view_chat",
            "/resume_chat", "/delete_chat",
        ]:
            assert required in text, required
