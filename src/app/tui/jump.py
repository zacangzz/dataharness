from __future__ import annotations

from typing import Any, Mapping, NamedTuple

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.errors import NoWidget
from textual.geometry import Offset
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Label


class JumpInfo(NamedTuple):
    key: str
    widget: str | Widget


class Jumper:
    def __init__(self, ids_to_keys: Mapping[str, str], screen: Screen[Any]) -> None:
        self.ids_to_keys = ids_to_keys
        self.screen = screen

    def get_overlays(self) -> dict[Offset, JumpInfo]:
        overlays: dict[Offset, JumpInfo] = {}
        for child in self.screen.walk_children(Widget):
            if not child.id or child.id not in self.ids_to_keys:
                continue
            if not child.display:
                continue
            try:
                x, y = self.screen.get_offset(child)
            except NoWidget:
                continue
            overlays[Offset(x, y)] = JumpInfo(self.ids_to_keys[child.id], child.id)
        return overlays


class JumpOverlay(ModalScreen[str | Widget | None]):
    BINDINGS = [Binding("escape", "dismiss_overlay", "Dismiss", show=False)]

    def __init__(self, jumper: Jumper) -> None:
        super().__init__()
        self.jumper = jumper
        self.keys_to_widgets: dict[str, str | Widget] = {}

    def compose(self) -> ComposeResult:
        overlays = self.jumper.get_overlays()
        self.keys_to_widgets = {info.key: info.widget for info in overlays.values()}
        for offset, info in overlays.items():
            label = Label(info.key, classes="textual-jump-label")
            label.styles.margin = offset.y, offset.x
            yield label
        yield Label("Press a key to jump", id="textual-jump-info")
        yield Label("ESC to dismiss", id="textual-jump-dismiss")

    def on_key(self, event: events.Key) -> None:
        target = self.keys_to_widgets.get(event.key)
        if target is not None:
            event.stop()
            event.prevent_default()
            self.dismiss(target)

    def action_dismiss_overlay(self) -> None:
        self.dismiss(None)
