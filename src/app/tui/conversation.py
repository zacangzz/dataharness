from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static


class UserMessageBlock(Static):
    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self._text = text
        self.add_class("message-user")

    def text_buffer(self) -> str:
        return self._text


class AssistantMessageBlock(Vertical):
    def __init__(self, text: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self.add_class("message-assistant")

    def compose(self) -> ComposeResult:
        yield Markdown(self._text, id="assistant_markdown")

    def update_text(self, text: str) -> None:
        self._text = text
        try:
            markdown = self.query_one("#assistant_markdown", Markdown)
        except Exception:
            return
        markdown.update(text)

    def append_delta(self, text: str) -> None:
        if text:
            self.update_text(self._text + text)

    def text_buffer(self) -> str:
        return self._text


class SystemMessageBlock(Static):
    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self._text = text
        self.add_class("message-system")

    def text_buffer(self) -> str:
        return self._text
