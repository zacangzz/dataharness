from __future__ import annotations

import csv
import re
from io import StringIO

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static

_TOOL_CALL_RE = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL)
_TOOL_RESULT_RE = re.compile(r"\[TOOL_RESULT[^\]]*\].*?\[/TOOL_RESULT\]", re.DOTALL)
_ASSISTANT_DRAFT_TAG_RE = re.compile(r"\[/?ASSISTANT_DRAFT\]\s*")
_FOLLOWUP_HINT_RE = re.compile(r"^Use the tool result\(s\) above.*$", re.MULTILINE)
_CSV_FENCE_RE = re.compile(r"```(csv|tsv)\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _markdown_table_from_delimited(content: str, *, delimiter: str, max_rows: int = 50) -> str:
    rows = list(csv.reader(StringIO(content.strip()), delimiter=delimiter))
    if not rows:
        return ""
    preview = rows[: max_rows + 1]

    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").strip()

    header = [cell(v) for v in preview[0]]
    if not header:
        return ""
    width = len(header)
    body = [([cell(v) for v in row] + [""] * width)[:width] for row in preview[1:]]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _format_tabular_fences(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        delimiter = "\t" if kind == "tsv" else ","
        table = _markdown_table_from_delimited(match.group(2), delimiter=delimiter)
        return table or match.group(0)

    return _CSV_FENCE_RE.sub(replace, text)


def _clean(text: str) -> str:
    text = _TOOL_CALL_RE.sub("", text)
    text = _TOOL_RESULT_RE.sub("", text)
    text = _ASSISTANT_DRAFT_TAG_RE.sub("", text)
    text = _FOLLOWUP_HINT_RE.sub("", text)
    text = _format_tabular_fences(text)
    return text.strip()


class UserMessageBlock(Static):
    def __init__(self, text: str, **kwargs) -> None:
        cleaned = _clean(text) or text
        super().__init__(cleaned, markup=False, **kwargs)
        self._text = cleaned
        self.add_class("message-user")

    def text_buffer(self) -> str:
        return self._text


class AssistantMessageBlock(Vertical):
    def __init__(self, text: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self.add_class("message-assistant")

    def compose(self) -> ComposeResult:
        yield Markdown(_clean(self._text), id="assistant_markdown")

    def update_text(self, text: str) -> None:
        self._text = text
        try:
            markdown = self.query_one("#assistant_markdown", Markdown)
        except Exception:
            return
        markdown.update(_clean(text))

    def append_delta(self, text: str) -> None:
        if text:
            self.update_text(self._text + text)

    def text_buffer(self) -> str:
        return self._text


class SystemMessageBlock(Static):
    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, markup=False, **kwargs)
        self._text = text
        self.add_class("message-system")

    def text_buffer(self) -> str:
        return self._text
