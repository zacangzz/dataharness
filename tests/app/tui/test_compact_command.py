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
