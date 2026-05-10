from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from app.tui.file_picker import FilePicker


class FileIngestScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss_screen", "Cancel"),
        Binding("ctrl+r", "change_root", "Change root"),
    ]

    def __init__(
        self,
        *,
        session: Any,
        workspace_id: str,
        initial_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._workspace_id = workspace_id
        self._root = initial_root or Path.home()

    def compose(self) -> ComposeResult:
        with Vertical(id="ingest_root"):
            yield Static(
                f"Ingest into workspace: {self._workspace_id}", id="ingest_header"
            )
            yield FilePicker(
                root=self._root, allow_multiselect=True, id="ingest_picker"
            )
            yield Static("Selected: (none)", id="ingest_staged")
            yield Footer()

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    async def action_change_root(self) -> None:
        new_root = Path.cwd() if self._root == Path.home() else Path.home()
        self._root = new_root
        picker = self.query_one("#ingest_picker", FilePicker)
        picker.update_root(new_root)
        self.query_one("#ingest_header", Static).update(
            f"Root: {new_root} -> workspace {self._workspace_id}"
        )

    @on(FilePicker.Selected)
    def _on_single_selected(self, event: FilePicker.Selected) -> None:
        self.query_one("#ingest_staged", Static).update(f"Selected: {event.path}")

    @on(FilePicker.Confirmed)
    async def _on_confirmed(self, event: FilePicker.Confirmed) -> None:
        absolute = [self._root / Path(p) for p in event.paths]
        try:
            result = await self._session.ingest_files(self._workspace_id, absolute)
        except Exception as exc:  # noqa: BLE001
            self.query_one("#ingest_staged", Static).update(f"Error: {exc}")
            return
        self.dismiss(result)
