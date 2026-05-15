from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tui.app import DataHarnessApp


@pytest.mark.asyncio
async def test_compact_command_resolves_existing_chat_when_active_chat_missing(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        summary = await app._session.create_chat("w_0001")
        app._active_chat_id = None
        captured: dict = {}

        async def fake_handle_direct_command(state, *, command, arguments):
            captured["command"] = command
            captured["arguments"] = dict(arguments)
            if False:
                yield None

        app._session.handle_direct_command = fake_handle_direct_command

        await app._stream_command("compact", {})

        assert captured["command"] == "compact"
        assert captured["arguments"]["chat_id"] == summary.chat_id
        assert app.active_chat_id == summary.chat_id


def test_compaction_completion_refreshes_sidebar_resources():
    app = DataHarnessApp(workspace_dir=Path("/tmp/dataharness-test/workspaces/w_0001"))
    app._active_chat_id = "chat_1"
    scheduled = []

    def fake_run_worker(coro):
        scheduled.append(coro)

    app.run_worker = fake_run_worker
    event = SimpleNamespace(
        status="completed",
        chat_id="chat_1",
        replaced_turn_count=5,
    )

    app._handle_chat_history_compacted(event)

    try:
        assert [coro.cr_code.co_name for coro in scheduled] == [
            "_rehydrate_active_chat",
            "_refresh_sidebar_resources",
        ]
    finally:
        for coro in scheduled:
            coro.close()
