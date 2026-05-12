from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static


@dataclass(frozen=True)
class HelpData:
    title: str
    description: str


@runtime_checkable
class Helpable(Protocol):
    help: HelpData


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, widget: Widget | None) -> None:
        super().__init__()
        self.widget = widget
        self._text = self._build_text(widget)

    def compose(self) -> ComposeResult:
        yield Vertical(Static(self._text, id="focused_help_body"), id="focused_help")

    def action_close(self) -> None:
        self.dismiss(None)

    def text_buffer(self) -> str:
        return self._text

    def _build_text(self, widget: Widget | None) -> str:
        if widget is None:
            return "Help\n\nNo focused widget."

        source = self._find_help_source(widget)
        if source is None:
            title = type(widget).__name__
            body = f"{title}\n\nNo help is available for this widget."
        else:
            data = source.help
            body = f"{data.title}\n\n{data.description}"

        bindings = self._format_bindings(widget)
        if bindings:
            body = f"{body}\n\nBindings\n{bindings}"
        return body

    def _find_help_source(self, widget: Widget) -> Helpable | None:
        current: Widget | None = widget
        while current is not None:
            if isinstance(current, Helpable) and isinstance(current.help, HelpData):
                return current
            parent = getattr(current, "parent", None)
            current = parent if isinstance(parent, Widget) else None
        return None

    def _format_bindings(self, widget: Widget) -> str:
        bindings = getattr(widget, "_bindings", None)
        key_to_bindings = getattr(bindings, "key_to_bindings", None)
        if not key_to_bindings:
            return ""

        lines: list[str] = []
        for key, local_bindings in key_to_bindings.items():
            for binding in local_bindings:
                description = getattr(binding, "description", "") or getattr(
                    binding, "action", ""
                )
                if description:
                    lines.append(f"{key}: {description}")
        return "\n".join(lines)
