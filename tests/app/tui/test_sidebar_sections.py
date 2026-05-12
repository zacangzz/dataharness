import pytest
from textual.app import App, ComposeResult

from app.tui.app import DataHarnessApp
from app.tui.sidebar import SidebarState
from app.tui.widgets import SidebarPane


def test_sidebar_state_renders_stable_sections():
    state = SidebarState()
    state.update_status(
        workspace_id="w_0001",
        run_state="idle",
        active_mode="interaction",
        runtime_status="ready",
        chat_id="chat_1",
    )
    state.set_files(["data/sales.csv"])
    state.set_chats(["chat_1"])
    state.update_trace(["turn started"])

    text = state.text_buffer()

    assert "WORKSPACE" in text
    assert "CHAT" in text
    assert "FILES" in text
    assert "TRACE" in text
    assert "COMMANDS" in text
    assert "DOCTOR" in text
    assert "FAILURES" in text
    assert "data/sales.csv" in text


class SidebarHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield SidebarPane(id="sidebar")


@pytest.mark.asyncio
async def test_sidebar_pane_preserves_existing_update_methods():
    app = SidebarHarness()
    async with app.run_test() as pilot:
        sidebar = app.query_one("#sidebar", SidebarPane)
        sidebar.update_status(
            workspace_id="w_0001",
            run_state="idle",
            active_mode="interaction",
            runtime_status="ready",
        )
        sidebar.update_files(["data/sales.csv"])
        sidebar.update_chats(["chat_1"])

        text = sidebar.text_buffer()
        assert "WORKSPACE" in text
        assert "data/sales.csv" in text
        assert "chat_1" in text


class _SectionHarness(App[None]):
    def __init__(self, section) -> None:
        super().__init__()
        self._section = section
        self.received: list = []

    def compose(self) -> ComposeResult:
        yield self._section

    def on_resume_chat_requested(self, event) -> None:
        self.received.append(("resume", event.chat_id))

    def on_insert_mention_requested(self, event) -> None:
        self.received.append(("mention", event.path))


@pytest.mark.asyncio
async def test_files_section_emits_insert_mention_requested():
    from app.tui.sidebar_sections import FilesSection
    from textual.widgets import OptionList
    section = FilesSection(id="files")
    app = _SectionHarness(section)
    async with app.run_test() as pilot:
        section.update_files(["data/sales.csv"])
        await pilot.pause()
        options = section.query_one("#files_options", OptionList)
        options.highlighted = 0
        await pilot.pause()
        options.action_select()
        await pilot.pause()
        assert ("mention", "data/sales.csv") in app.received


@pytest.mark.asyncio
async def test_chats_section_emits_resume_chat_requested():
    from app.tui.sidebar_sections import ChatsSection
    from textual.widgets import OptionList
    section = ChatsSection(id="chats")
    app = _SectionHarness(section)

    class _Summary:
        chat_id = "chat_42"
        title = "experiment"
        message_count = 3
        updated_at = None

    async with app.run_test() as pilot:
        section.update_chats([_Summary()])
        await pilot.pause()
        options = section.query_one("#chats_options", OptionList)
        options.highlighted = 0
        await pilot.pause()
        options.action_select()
        await pilot.pause()
        assert ("resume", "chat_42") in app.received


@pytest.mark.asyncio
async def test_sidebar_pane_workspace_header_always_present():
    app = SidebarHarness()
    async with app.run_test() as pilot:
        sidebar = app.query_one("#sidebar", SidebarPane)
        # Without any update, text_buffer should still include WORKSPACE.
        assert "WORKSPACE" in sidebar.text_buffer()
        assert "FILES" in sidebar.text_buffer()


@pytest.mark.asyncio
async def test_app_refreshes_sidebar_files_after_workspace_snapshot(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        app.apply_workspace_snapshot(
            {
                "workspace_id": "w_0001",
                "run_state": "idle",
                "active_mode": "interaction",
                "runtime_status": "ready",
            }
        )
        await pilot.pause()
        await pilot.pause()

        sidebar = app.query_one("#sidebar", SidebarPane)
        assert "data/sales.csv" in sidebar.text_buffer()
