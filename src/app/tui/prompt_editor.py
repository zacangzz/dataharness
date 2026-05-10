from __future__ import annotations

from typing import Any

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class PromptEditor(TextArea):
    can_focus = True

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(text="", language="markdown", show_line_numbers=False, **kwargs)

    @property
    def text(self) -> str:
        return self.document.text

    def set_text(self, text: str) -> None:
        self.load_text(text)
        lines = self.document.lines
        last_row = max(len(lines) - 1, 0)
        last_col = len(lines[-1]) if lines else 0
        try:
            self.move_cursor((last_row, last_col))
        except Exception:
            pass

    def insert_text(self, text: str) -> None:
        self.insert(text)

    def clear_text(self) -> None:
        self.load_text("")

    def submit(self) -> None:
        value = self.text.strip()
        if not value:
            return
        # Note: text is NOT cleared here so parents can inspect editor state
        # in their Submitted handler. Receivers should call clear_text() once
        # they have consumed the submission.
        self.post_message(self.Submitted(value))

    def on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+j", "shift+enter"):
            self.insert_text("\n")
            event.stop()
            event.prevent_default()
            return
        if event.key == "enter":
            self.submit()
            event.stop()
            event.prevent_default()
