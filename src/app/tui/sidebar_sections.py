from __future__ import annotations

from collections import deque
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class ResumeChatRequested(Message):
    def __init__(self, chat_id: str) -> None:
        self.chat_id = chat_id
        super().__init__()


class InsertMentionRequested(Message):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__()


class WorkspaceSection(Vertical):
    DEFAULT_CLASSES = "sidebar-section"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._workspace_id = "unknown"
        self._run_state = "starting"
        self._active_mode = "interaction"
        self._runtime_status = "checking"

    def compose(self) -> ComposeResult:
        yield Static("WORKSPACE", classes="sidebar-section-header")
        yield Static("", id="workspace_section_body")

    def update_status(
        self,
        *,
        workspace_id: str,
        run_state: str,
        active_mode: str,
        runtime_status: str,
    ) -> None:
        self._workspace_id = workspace_id
        self._run_state = run_state
        self._active_mode = active_mode
        self._runtime_status = runtime_status
        try:
            self.query_one("#workspace_section_body", Static).update(self._body())
        except Exception:
            pass

    def _body(self) -> str:
        return (
            f"{self._workspace_id}\nstate: {self._run_state}\n"
            f"mode: {self._active_mode}\nruntime: {self._runtime_status}"
        )

    def text_buffer(self) -> str:
        return f"WORKSPACE\n{self._body()}"


class ChatsSection(Vertical):
    DEFAULT_CLASSES = "sidebar-section"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._chat_lines: list[str] = []
        self._chat_ids: list[str] = []
        self._active_chat_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("CHAT", classes="sidebar-section-header")
        yield OptionList(id="chats_options")

    def update_chats(self, summaries: list[Any]) -> None:
        self._chat_lines = []
        self._chat_ids = []
        for summary in summaries:
            if isinstance(summary, str):
                self._chat_lines.append(summary)
                self._chat_ids.append(summary)
                continue
            chat_id = getattr(summary, "chat_id", str(summary))
            title = getattr(summary, "title", None) or chat_id
            count = getattr(summary, "message_count", 0)
            self._chat_lines.append(f"{title} · {count} msgs")
            self._chat_ids.append(chat_id)
        try:
            options = self.query_one("#chats_options", OptionList)
        except Exception:
            return
        options.set_options(
            Option(label, id=f"chat:{i}")
            for i, label in enumerate(self._chat_lines)
        )

    def set_active_chat(self, chat_id: str | None) -> None:
        self._active_chat_id = chat_id

    @on(OptionList.OptionSelected, "#chats_options")
    def _on_chat_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None or not event.option.id.startswith("chat:"):
            return
        idx = int(event.option.id.split(":", 1)[1])
        if 0 <= idx < len(self._chat_ids):
            self.post_message(ResumeChatRequested(self._chat_ids[idx]))
        event.stop()

    def text_buffer(self) -> str:
        body = "\n".join(self._chat_lines) or (self._active_chat_id or "no active chat")
        return f"CHAT\n{body}"


class FilesSection(Vertical):
    DEFAULT_CLASSES = "sidebar-section"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("FILES", classes="sidebar-section-header")
        yield OptionList(id="files_options")

    def update_files(self, files: list[str]) -> None:
        self._files = list(files)[:20]
        try:
            options = self.query_one("#files_options", OptionList)
        except Exception:
            return
        options.set_options(
            Option(path, id=f"file:{i}") for i, path in enumerate(self._files)
        )

    @on(OptionList.OptionSelected, "#files_options")
    def _on_file_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None or not event.option.id.startswith("file:"):
            return
        idx = int(event.option.id.split(":", 1)[1])
        if 0 <= idx < len(self._files):
            self.post_message(InsertMentionRequested(self._files[idx]))
        event.stop()

    def text_buffer(self) -> str:
        body = "\n".join(self._files) or "no files"
        return f"FILES\n{body}"


class _DequeSection(Vertical):
    DEFAULT_CLASSES = "sidebar-section"
    title = "SECTION"
    empty = "(empty)"

    def __init__(self, *, maxlen: int = 20, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines: deque[str] = deque(maxlen=maxlen)

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="sidebar-section-header")
        yield Static("", id=f"{self.title.lower()}_body")

    def _body_id(self) -> str:
        return f"{self.title.lower()}_body"

    def append(self, line: str) -> None:
        self._lines.append(line)
        self._refresh()

    def replace(self, lines: list[str]) -> None:
        self._lines.clear()
        self._lines.extend(lines)
        self._refresh()

    def _refresh(self) -> None:
        try:
            self.query_one(f"#{self._body_id()}", Static).update(
                "\n".join(self._lines) or self.empty
            )
        except Exception:
            pass

    def text_buffer(self) -> str:
        body = "\n".join(self._lines) or self.empty
        return f"{self.title}\n{body}"


class TraceSection(_DequeSection):
    title = "TRACE"
    empty = "no trace yet"

    def __init__(self, **kwargs) -> None:
        super().__init__(maxlen=20, **kwargs)


class CommandsSection(_DequeSection):
    title = "COMMANDS"
    empty = "no commands yet"

    def __init__(self, **kwargs) -> None:
        super().__init__(maxlen=12, **kwargs)


class DoctorSection(_DequeSection):
    title = "DOCTOR"
    empty = "no doctor findings"

    def __init__(self, **kwargs) -> None:
        super().__init__(maxlen=8, **kwargs)


class FailuresSection(Vertical):
    DEFAULT_CLASSES = "sidebar-section"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._failure = "no failures"

    def compose(self) -> ComposeResult:
        yield Static("FAILURES", classes="sidebar-section-header")
        yield Static(self._failure, id="failures_body")

    def set_failure(self, summary: str, error_code: str) -> None:
        self._failure = f"{error_code}: {summary}"
        try:
            self.query_one("#failures_body", Static).update(self._failure)
        except Exception:
            pass

    def text_buffer(self) -> str:
        return f"FAILURES\n{self._failure}"
