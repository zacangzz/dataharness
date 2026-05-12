from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static


class CommandPaletteScreen(Screen):
    def __init__(self, *, session) -> None:
        super().__init__()
        self.session = session
        self._body = Static(id="palette_body")
        self._body_text: str = ""

    def compose(self) -> ComposeResult:
        yield Vertical(Static("Commands"), self._body)

    async def on_mount(self) -> None:
        descs = await self.session.list_commands()
        lines = []
        for d in descs:
            mark = "" if d.available else f"  (unavailable: {d.disabled_reason or 'n/a'})"
            lines.append(f"{d.slash_alias}\t{d.short_description}{mark}")
        self._body_text = "\n".join(lines)
        self._body.update(self._body_text)

    def text_buffer(self) -> str:
        return self._body_text
