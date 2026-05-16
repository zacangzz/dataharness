import pytest

from app.tui.app import DataHarnessApp
from app.tui.widgets import ConversationPane


@pytest.mark.asyncio
async def test_create_chat_command_activates_empty_titled_chat(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        old_chat = await app._session.create_chat("w_0001", title="old")
        app._active_chat_id = old_chat.chat_id
        app.query_one("#conversation", ConversationPane).append_user("stale transcript")

        await app._stream_command("create_chat", {"title": "Fresh"})
        await pilot.pause()

        chats = await app._session.list_chats("w_0001")
        created = next(chat for chat in chats if chat.title == "Fresh")

        assert app.active_chat_id == created.chat_id
        assert app.query_one("#conversation", ConversationPane).text_buffer() == ""
        assert "Fresh" in app.query_one("#sidebar").text_buffer()
