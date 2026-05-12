import pytest

from app.session import AppSession
from app.tui.app import DataHarnessApp
from app.tui.screens.chat_manager import ChatManagerScreen


@pytest.mark.asyncio
async def test_chat_manager_lists_workspace_chats(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        # Create two chats via session.
        await app._session.create_workspace("w_0001")
        c1 = await app._session.create_chat("w_0001")
        c2 = await app._session.create_chat("w_0001")
        screen = ChatManagerScreen(workspace_id="w_0001", session=app._session)
        await app.push_screen(screen)
        await pilot.pause()
        rendered = screen.text_buffer()
        assert c1.chat_id in rendered
        assert c2.chat_id in rendered
