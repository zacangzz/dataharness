from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.chat import ChatMessage, ChatStore, ChatSummary
from harness.exceptions import ChatNotFound


@pytest.fixture
def store(tmp_path: Path):
    return ChatStore(app_root=tmp_path)


async def test_create_chat_does_not_write_to_disk(store, tmp_path):
    summary = await store.create_chat(workspace_id="w1", title="t")
    assert summary.workspace_id == "w1"
    assert summary.message_count == 0
    chat_dir = tmp_path / "workspaces" / "w1" / "chats" / summary.chat_id
    assert not chat_dir.exists()


async def test_first_message_creates_files(store, tmp_path):
    summary = await store.create_chat(workspace_id="w1", title=None)
    msg = ChatMessage(
        message_id="m1", role="user", text="hi",
        ts=datetime.now(UTC), turn_id="t1", active_mode="analyst", token_estimate=1,
    )
    await store.append_message(summary.chat_id, msg)
    chat_dir = tmp_path / "workspaces" / "w1" / "chats" / summary.chat_id
    assert (chat_dir / "metadata.json").exists()
    assert (chat_dir / "messages.jsonl").exists()


async def test_view_chat_returns_full_record(store):
    summary = await store.create_chat(workspace_id="w1", title="t")
    msg = ChatMessage(message_id="m1", role="user", text="hi", ts=datetime.now(UTC),
                      turn_id="t1", active_mode="m", token_estimate=1)
    await store.append_message(summary.chat_id, msg)
    rec = await store.view_chat(summary.chat_id)
    assert rec.chat_id == summary.chat_id
    assert len(rec.messages) == 1
    assert rec.messages[0].text == "hi"


async def test_view_chat_unknown_raises_chat_not_found(store):
    with pytest.raises(ChatNotFound):
        await store.view_chat("missing")


async def test_list_chats_filters_by_workspace(store):
    a = await store.create_chat(workspace_id="w1", title=None)
    await store.append_message(a.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    b = await store.create_chat(workspace_id="w2", title=None)
    await store.append_message(b.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    listed_w1 = await store.list_chats("w1")
    assert {s.chat_id for s in listed_w1} == {a.chat_id}


async def test_delete_chat_removes_files(store, tmp_path):
    s = await store.create_chat(workspace_id="w1", title=None)
    await store.append_message(s.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    chat_dir = tmp_path / "workspaces" / "w1" / "chats" / s.chat_id
    assert chat_dir.exists()
    result = await store.delete_chat(s.chat_id)
    assert result.deleted is True
    assert result.files_removed >= 2
    assert not chat_dir.exists()


async def test_cascade_delete_for_workspace(store, tmp_path):
    a = await store.create_chat(workspace_id="w1", title=None)
    await store.append_message(a.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    b = await store.create_chat(workspace_id="w1", title=None)
    await store.append_message(b.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    removed = await store.cascade_delete_for_workspace("w1")
    assert {r.chat_id for r in removed} == {a.chat_id, b.chat_id}
    assert not (tmp_path / "workspaces" / "w1" / "chats").exists()
