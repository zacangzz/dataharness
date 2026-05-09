from datetime import UTC, datetime
from pathlib import Path

from harness.chat import ChatMessage, ChatStore


async def test_cascade_removes_directory(tmp_path: Path):
    store = ChatStore(app_root=tmp_path)
    s = await store.create_chat(workspace_id="w42", title=None)
    await store.append_message(s.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    res = await store.cascade_delete_for_workspace("w42")
    assert len(res) == 1
    assert not (tmp_path / "chats" / "w42").exists()
