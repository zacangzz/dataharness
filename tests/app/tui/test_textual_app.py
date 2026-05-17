import pytest
from types import SimpleNamespace

from app.tui.app import DataHarnessApp
from app.tui.widgets import ApprovalBanner, ClarificationBar, ConversationPane, SidebarPane


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
        from harness.services.chat import ChatMessage
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
async def test_copy_action_copies_focused_text_when_no_selection(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        conversation = app.query_one("#conversation", ConversationPane)
        conversation.append_user("question to copy")
        conversation.append_assistant("answer to copy")
        app.set_focus(conversation)

        await pilot.press("ctrl+c")

        assert "question to copy" in app._clipboard
        assert "answer to copy" in app._clipboard


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


@pytest.mark.asyncio
async def test_doctor_apply_selected_schedules_doctor_approval(tmp_path):
    class FakeSession:
        def __init__(self, app_root):
            self.app_root = app_root
            self.calls = []

        async def watch_status(self):
            if False:
                yield None

        async def list_chats(self, workspace_id):
            return []

        async def handle_doctor_approval(self, *, state, workspace_dir, report_id, decision, action_ids=None):
            self.calls.append((report_id, decision, action_ids))
            from app.events import AppDoctorActionsApplied
            from datetime import UTC, datetime
            yield AppDoctorActionsApplied(
                ts=datetime.now(UTC),
                workspace_id=state.workspace_id,
                chat_id=None,
                run_id=None,
                report_id=report_id,
                applied_count=len(action_ids or []),
                skipped_count=0,
                details=[],
            )

    fake = FakeSession(tmp_path / "w")
    app = DataHarnessApp(session=fake, workspace_dir=fake.app_root / "workspaces" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        banner = app.query_one("#approval_banner", ApprovalBanner)
        actions = [
            {"id": "a1", "action": "cleanup", "target": "artifacts/tmp/a.py", "rationale": "stale"},
            {"id": "a2", "action": "cleanup", "target": "artifacts/tmp/b.py", "rationale": "orphaned"},
        ]
        banner.show_doctor_review("report_1", actions, [])
        await pilot.pause()
        banner.query_one("#doctor_action_1").value = False
        await pilot.click("#doctor_apply_selected")
        await pilot.pause()
        assert fake.calls == [("report_1", "yes", ["a1"])]


@pytest.mark.asyncio
async def test_doctor_approval_request_does_not_show_clarification_when_banner_active(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        banner = app.query_one("#approval_banner", ApprovalBanner)
        banner.show_doctor_review(
            "report_1",
            [{"id": "a1", "action": "cleanup", "target": "artifacts/tmp/a.py"}],
            [],
        )
        await pilot.pause()

        app._handle_doctor_approval_requested(
            SimpleNamespace(report_id="report_1", question="Apply all?")
        )
        await pilot.pause()

        clarification = app.query_one("#clarification_bar", ClarificationBar)
        assert clarification.display is False
        assert app._pending_doctor_report_id is None


@pytest.mark.asyncio
async def test_doctor_report_ready_with_actions_hides_stale_clarification(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        clarification = app.query_one("#clarification_bar", ClarificationBar)
        clarification.show(question="stale doctor prompt")
        app._pending_doctor_report_id = "stale_report"

        app._handle_doctor_report_ready(
            SimpleNamespace(
                report_id="report_1",
                summary_counts={},
                recommendations=[],
                action_records=[
                    {"id": "a1", "action": "cleanup", "target": "artifacts/tmp/a.py"}
                ],
            )
        )
        await pilot.pause()

        banner = app.query_one("#approval_banner", ApprovalBanner)
        assert banner.display is True
        assert clarification.display is False
        assert app._pending_doctor_report_id is None


@pytest.mark.asyncio
async def test_doctor_banner_decision_hides_clarification_bar(tmp_path):
    class FakeSession:
        def __init__(self, app_root):
            self.app_root = app_root

        async def watch_status(self):
            if False:
                yield None

        async def list_chats(self, workspace_id):
            return []

        async def handle_doctor_approval(self, *, state, workspace_dir, report_id, decision, action_ids=None):
            if False:
                yield None

    fake = FakeSession(tmp_path / "w")
    app = DataHarnessApp(session=fake, workspace_dir=fake.app_root / "workspaces" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        clarification = app.query_one("#clarification_bar", ClarificationBar)
        clarification.show(question="stale prompt")
        banner = app.query_one("#approval_banner", ApprovalBanner)
        banner.show_doctor_review(
            "report_1",
            [{"id": "a1", "action": "cleanup", "target": "artifacts/tmp/a.py"}],
            [],
        )
        await pilot.pause()

        await pilot.click("#doctor_accept_all")
        await pilot.pause()

        assert clarification.display is False
