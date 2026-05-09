import pytest

from app.tui.app import DataHarnessApp
from app.tui.screens.workspace_manager import WorkspaceManagerScreen


@pytest.mark.asyncio
async def test_workspace_manager_supports_j_k_l_navigation(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await app._session.create_workspace("w_0002")
        screen = WorkspaceManagerScreen(
            session=app._session,
            active_workspace_id="w_0001",
        )
        await app.push_screen(screen)
        await pilot.pause()

        await pilot.press("j", "l")
        await pilot.pause()

        assert app.state.workspace_id in {"w_0001", "w_0002"}
