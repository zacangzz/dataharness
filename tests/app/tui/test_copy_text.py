from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from app.tui.conversation import AssistantMessageBlock, UserMessageBlock
from app.tui.prompt_bar import PromptBar
from app.tui.widgets import ConversationPane


def test_assistant_block_is_focusable():
    assert AssistantMessageBlock.can_focus is True


def test_user_block_is_focusable():
    assert UserMessageBlock.can_focus is True


def test_assistant_block_text_buffer_returns_text():
    block = AssistantMessageBlock("hello world")
    assert block.text_buffer() == "hello world"


class _Harness(App[None]):
    def compose(self) -> ComposeResult:
        yield ConversationPane(id="conversation")


class _FakeClipboard:
    def __init__(self, paste_text: str | None = None, copy_result: bool = True) -> None:
        self.paste_text = paste_text
        self.copy_result = copy_result
        self.copied: list[str] = []

    def copy(self, text: str) -> bool:
        self.copied.append(text)
        return self.copy_result

    def paste(self) -> str | None:
        return self.paste_text


@pytest.mark.asyncio
async def test_copy_text_falls_back_to_last_assistant_message(tmp_path: Path):
    from app.tui.app import DataHarnessApp
    from app.session import AppSession
    from harness.control import RunStateRecord

    workspace = tmp_path / "workspaces" / "w_0001"
    workspace.mkdir(parents=True)
    session = AppSession(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    app = DataHarnessApp(session=session, workspace_dir=workspace, state=state)
    async with app.run_test() as pilot:
        pane = app.query_one("#conversation", ConversationPane)
        pane.append_assistant("first reply")
        pane.append_assistant("second reply")
        await pilot.pause()
        text, source = app._copyable_text_with_source()
        assert text == "second reply"
        assert source == "last assistant reply"


@pytest.mark.asyncio
async def test_copy_action_copies_last_assistant_message(tmp_path: Path):
    from app.tui.app import DataHarnessApp
    from app.session import AppSession
    from harness.control import RunStateRecord

    workspace = tmp_path / "workspaces" / "w_0001"
    workspace.mkdir(parents=True)
    session = AppSession(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    native_clipboard = _FakeClipboard()
    app = DataHarnessApp(
        session=session,
        workspace_dir=workspace,
        state=state,
        clipboard=native_clipboard,
    )
    async with app.run_test() as pilot:
        pane = app.query_one("#conversation", ConversationPane)
        pane.append_assistant("first reply")
        pane.append_assistant("second reply")
        await pilot.pause()

        await pilot.press("ctrl+c")

        assert app._clipboard == "second reply"
        assert native_clipboard.copied == ["second reply"]


@pytest.mark.asyncio
async def test_paste_action_inserts_native_clipboard_text_into_prompt(tmp_path: Path):
    from app.tui.app import DataHarnessApp
    from app.session import AppSession
    from harness.control import RunStateRecord

    workspace = tmp_path / "workspaces" / "w_0001"
    workspace.mkdir(parents=True)
    session = AppSession(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    app = DataHarnessApp(
        session=session,
        workspace_dir=workspace,
        state=state,
        clipboard=_FakeClipboard(paste_text="external paste"),
    )
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        prompt.editor.focus()
        await pilot.press("ctrl+v")

        assert prompt.editor.text == "external paste"


@pytest.mark.asyncio
async def test_paste_action_falls_back_to_textual_clipboard(tmp_path: Path):
    from app.tui.app import DataHarnessApp
    from app.session import AppSession
    from harness.control import RunStateRecord

    workspace = tmp_path / "workspaces" / "w_0001"
    workspace.mkdir(parents=True)
    session = AppSession(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    app = DataHarnessApp(
        session=session,
        workspace_dir=workspace,
        state=state,
        clipboard=_FakeClipboard(paste_text=None),
    )
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        app.copy_to_clipboard("local paste")
        prompt.editor.focus()
        await pilot.press("ctrl+v")

        assert prompt.editor.text == "local paste"


@pytest.mark.asyncio
async def test_copy_text_uses_focused_block_buffer(tmp_path: Path):
    from app.tui.app import DataHarnessApp
    from app.session import AppSession
    from harness.control import RunStateRecord

    workspace = tmp_path / "workspaces" / "w_0001"
    workspace.mkdir(parents=True)
    session = AppSession(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    app = DataHarnessApp(session=session, workspace_dir=workspace, state=state)
    async with app.run_test() as pilot:
        pane = app.query_one("#conversation", ConversationPane)
        pane.append_assistant("first reply")
        pane.append_assistant("second reply")
        await pilot.pause()
        first_block = next(iter(pane.query(AssistantMessageBlock)))
        first_block.focus()
        await pilot.pause()
        text, source = app._copyable_text_with_source()
        assert text == "first reply"
        assert source == "focused message"


@pytest.mark.asyncio
async def test_copy_text_empty_returns_blank(tmp_path: Path):
    from app.tui.app import DataHarnessApp
    from app.session import AppSession
    from harness.control import RunStateRecord

    workspace = tmp_path / "workspaces" / "w_0001"
    workspace.mkdir(parents=True)
    session = AppSession(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    app = DataHarnessApp(session=session, workspace_dir=workspace, state=state)
    async with app.run_test() as pilot:
        await pilot.pause()
        text, source = app._copyable_text_with_source()
        assert text == ""
        assert source == ""
