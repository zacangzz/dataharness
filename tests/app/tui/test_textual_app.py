import pytest

from app.tui.app import DataHarnessApp
from app.tui.widgets import ConversationPane, SidebarPane


@pytest.mark.asyncio
async def test_submit_user_text_streams_into_conversation_pane(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.press("h", "i", "enter")
        await pilot.pause()
        pane = app.query_one("#conversation")
        assert "hi" in pane.text_buffer().lower()


@pytest.mark.asyncio
async def test_conversation_rehydrates_on_resume_chat(tmp_path):
    from app.tui.app import DataHarnessApp
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        sess = app._session
        await sess.create_workspace("w_0001")
        chat = await sess.create_chat("w_0001")
        # Seed messages by appending directly via store (orchestrator integration test covers run_turn case)
        from datetime import UTC, datetime
        from harness.chat import ChatMessage
        await sess.orchestrator.chat_store.append_message(chat.chat_id, ChatMessage(
            message_id="m1", role="user", text="prior question",
            ts=datetime.now(UTC), turn_id="t", active_mode="m", token_estimate=1,
        ))
        await sess.orchestrator.chat_store.append_message(chat.chat_id, ChatMessage(
            message_id="m2", role="assistant", text="prior answer",
            ts=datetime.now(UTC), turn_id="t", active_mode="m", token_estimate=1,
        ))
        await app.action_resume_chat(chat.chat_id)
        await pilot.pause()
        pane = app.query_one("#conversation")
        text = pane.text_buffer()
        assert "prior question" in text and "prior answer" in text


@pytest.mark.asyncio
async def test_tui_uses_single_scrollable_conversation_surface(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        pane = app.query_one("#conversation", ConversationPane)
        assert pane.can_focus is True
        assert pane.styles.overflow_y == "auto"
        for removed_id in ("plan", "step_status", "artifacts", "memory", "failure", "provenance"):
            assert not app.query(f"#{removed_id}")


@pytest.mark.asyncio
async def test_conversation_and_sidebar_have_real_scroll_ranges(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        conversation = app.query_one("#conversation", ConversationPane)
        sidebar = app.query_one("#sidebar", SidebarPane)

        for index in range(80):
            conversation.append_user(f"question {index}")
        sidebar.update_trace([f"trace line {index}" for index in range(80)])
        await pilot.pause()

        assert conversation.max_scroll_y > 0
        assert sidebar.max_scroll_y > 0


@pytest.mark.asyncio
async def test_status_bar_shows_runtime_status(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one("#workspace_bar")
        assert "runtime:" in str(bar.render())
        assert "not_loaded" in str(bar.render())


@pytest.mark.asyncio
async def test_slash_switch_workspace_updates_workspace_bar(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await app._session.create_workspace("w_0002")
        await app.submit_user_text("/switch_workspace w_0002")
        await pilot.pause()
        bar = app.query_one("#workspace_bar")
        assert "workspace: w_0002" in str(bar.render())


@pytest.mark.asyncio
async def test_slash_workspaces_opens_workspace_gui(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await app._session.create_workspace("w_0002")
        await app.submit_user_text("/workspaces")
        await pilot.pause()
        assert type(app.screen).__name__ == "WorkspaceManagerScreen"
        assert "w_0001" in app.screen.text_buffer()
        assert "w_0002" in app.screen.text_buffer()


@pytest.mark.asyncio
async def test_workspace_gui_switch_updates_workspace_bar(tmp_path):
    from app.tui.screens.workspace_manager import WorkspaceManagerScreen

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
        await screen.switch_to("w_0002")
        await pilot.pause()
        bar = app.query_one("#workspace_bar")
        assert app.state.workspace_id == "w_0002"
        assert "workspace: w_0002" in str(bar.render())
