"""
FileDrop widget — adapted from https://github.com/agmmnn/textual-filedrop
for Textual 8.x (removed icon support, updated to modern event handler API).

Drag a file onto the terminal while this widget is focused to trigger a
`FileDrop.Dropped` message.  Terminals translate drag-and-drop into a Paste
event containing the file paths, which this widget intercepts.
"""

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from textual import events
from textual.message import Message
from textual.widget import Widget


def _extract_filepaths(text: str) -> list[str]:
    """Parse a pasted string into a list of existing file paths."""
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()

    paths: list[str] = []
    for part in parts:
        item = part.replace("\x00", "").strip('"')
        if os.path.isfile(item):
            paths.append(item)
        elif os.path.isdir(item):
            for root, _, files in os.walk(item):
                for f in files:
                    paths.append(os.path.join(root, f))
    return paths


@dataclass
class FileInfo:
    """Lightweight file descriptor carried in the Dropped message."""

    path: str
    name: str
    ext: str

    @classmethod
    def from_path(cls, filepath: str) -> "FileInfo":
        name = os.path.basename(filepath)
        _, ext = os.path.splitext(name)
        return cls(path=filepath, name=name, ext=ext.lstrip("."))


class FileDrop(Widget, can_focus=True, can_focus_children=False):
    """Drop zone widget. Focus it, then drag files onto the terminal window."""

    DEFAULT_CSS = """
    FileDrop {
        border: round gray;
        height: 3;
        background: $panel;
        content-align: center middle;
        padding: 0 2;
    }
    """

    class Dropped(Message):
        """Posted when one or more files are dropped onto the widget."""

        def __init__(self, filepaths: list[FileInfo]) -> None:
            super().__init__()
            self.filepaths = filepaths

    def render(self) -> str:
        return "Drop files here"

    def on_focus(self, _event: events.Focus) -> None:
        self.styles.border = ("round", "dodgerblue")

    def on_blur(self, _event: events.Blur) -> None:
        self.styles.border = ("round", "gray")

    def on_paste(self, event: events.Paste) -> None:
        raw_paths = _extract_filepaths(event.text)
        if raw_paths:
            files = [FileInfo.from_path(p) for p in raw_paths]
            self.post_message(self.Dropped(files))
        event.stop()
