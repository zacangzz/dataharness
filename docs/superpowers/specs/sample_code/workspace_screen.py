import logging
import shutil
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView
from textual.containers import Horizontal, Vertical

from src.cli.file_browser import WorkspaceFileBrowser
from src.cli.filedrop import FileDrop
from src.core.workspace import WorkspaceManager

_log = logging.getLogger(__name__)


class WorkspaceScreen(ModalScreen):
    """Modal for managing workspaces and data files."""

    BINDINGS = [
        Binding("n", "new_workspace", "New"),
        Binding("r", "rename_workspace", "Rename"),
        Binding("d", "delete_workspace", "Delete"),
        Binding("b", "browse_files", "Browse"),
        Binding("escape", "dismiss_screen", "Close"),
    ]

    class WorkspaceSwitched(Message):
        """Posted to the app when the active workspace changes."""

        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    def __init__(self, manager: WorkspaceManager) -> None:
        super().__init__()
        self._manager = manager
        self._confirm_pending: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace-modal"):
            with Vertical(id="workspace-list-panel"):
                yield Label("Workspaces", id="workspace-panel-title")
                yield ListView(id="workspace-list")
                yield Label("", id="workspace-error", classes="error-label")
                yield Input(placeholder="Workspace name…", id="workspace-name-input")
                with Horizontal(id="workspace-actions"):
                    yield Button("New [N]", id="btn-new", variant="primary")
                    yield Button("Rename [R]", id="btn-rename", variant="default")
                    yield Button("Delete [D]", id="btn-delete", variant="error")
                with Horizontal(id="delete-confirm"):
                    yield Label("", id="delete-confirm-msg")
                    yield Button(
                        "Confirm Delete", id="btn-confirm-yes", variant="error"
                    )
                    yield Button("Cancel", id="btn-confirm-no", variant="default")
            with Vertical(id="file-panel"):
                yield Label("Files", id="file-panel-title")
                yield ListView(id="file-list")
                yield FileDrop(id="file-drop")
                yield Label(
                    "Drop files here  •  [B] Browse",
                    id="drop-label",
                )

    async def on_mount(self) -> None:
        self.query_one("#delete-confirm").display = False
        await self._refresh_workspace_list()
        await self._refresh_file_list()

    # ── workspace list ────────────────────────────────────────────────────────

    async def _refresh_workspace_list(self) -> None:
        lv = self.query_one("#workspace-list", ListView)
        await lv.remove_children()
        workspaces = self._manager.list_workspaces()
        active = self._manager.active_name()
        for entry in workspaces:
            marker = "►" if entry.name == active else " "
            lv.append(ListItem(Label(f"{marker} {entry.name}"), id=f"ws-{entry.name}"))
        self.query_one("#btn-delete", Button).disabled = len(workspaces) <= 1

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "workspace-list":
            return
        item_id = event.item.id or ""
        if not item_id.startswith("ws-"):
            return
        name = item_id[3:]
        self._manager.switch(name)
        self.app.post_message(self.WorkspaceSwitched(name))
        await self._refresh_workspace_list()
        await self._refresh_file_list()
        self._clear_error()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "btn-new": self._do_new,
            "btn-rename": self._do_rename,
            "btn-delete": self._do_delete_start,
            "btn-confirm-yes": self._do_delete_confirm,
            "btn-confirm-no": self._do_delete_cancel,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            await handler()

    async def action_new_workspace(self) -> None:
        await self._do_new()

    async def action_rename_workspace(self) -> None:
        await self._do_rename()

    async def action_delete_workspace(self) -> None:
        await self._do_delete_start()

    def action_browse_files(self) -> None:
        self.app.push_screen(
            WorkspaceFileBrowser(
                self._manager.active_dir(),
                self._manager.active_name(),
            )
        )

    async def action_dismiss_screen(self) -> None:
        if self._confirm_pending:
            await self._do_delete_cancel()
        else:
            self.dismiss()

    # ── CRUD helpers ──────────────────────────────────────────────────────────

    async def _do_new(self) -> None:
        name = self.query_one("#workspace-name-input", Input).value.strip()
        if not name:
            self._show_error("Enter a workspace name first.")
            return
        try:
            self._manager.create(name)
            self.query_one("#workspace-name-input", Input).clear()
            self._clear_error()
            await self._refresh_workspace_list()
        except ValueError as exc:
            self._show_error(str(exc))

    async def _do_rename(self) -> None:
        new_name = self.query_one("#workspace-name-input", Input).value.strip()
        if not new_name:
            self._show_error("Enter a new name first.")
            return
        old_name = self._manager.active_name()
        try:
            self._manager.rename(old_name, new_name)
            self.query_one("#workspace-name-input", Input).clear()
            self._clear_error()
            self.app.post_message(self.WorkspaceSwitched(new_name))
            await self._refresh_workspace_list()
            await self._refresh_file_list()
        except (ValueError, KeyError, OSError) as exc:
            self._show_error(str(exc))

    async def _do_delete_start(self) -> None:
        if len(self._manager.list_workspaces()) <= 1:
            return
        active = self._manager.active_name()
        self._confirm_pending = active
        self.query_one("#delete-confirm-msg", Label).update(
            f"Delete '{active}'? This cannot be undone."
        )
        self.query_one("#workspace-actions").display = False
        self.query_one("#delete-confirm").display = True

    async def _do_delete_confirm(self) -> None:
        name = self._confirm_pending
        if name is None:
            return
        try:
            self._manager.delete(name)
            self.app.post_message(self.WorkspaceSwitched(self._manager.active_name()))
        except (ValueError, KeyError, OSError) as exc:
            self._show_error(str(exc))
        finally:
            self._confirm_pending = None
            await self._reset_confirm_ui()

    async def _do_delete_cancel(self) -> None:
        self._confirm_pending = None
        await self._reset_confirm_ui()

    async def _reset_confirm_ui(self) -> None:
        self.query_one("#workspace-actions").display = True
        self.query_one("#delete-confirm").display = False
        await self._refresh_workspace_list()
        await self._refresh_file_list()

    def _show_error(self, msg: str) -> None:
        self.query_one("#workspace-error", Label).update(msg)

    def _clear_error(self) -> None:
        self.query_one("#workspace-error", Label).update("")

    # ── file list ─────────────────────────────────────────────────────────────

    async def _refresh_file_list(self) -> None:
        lv = self.query_one("#file-list", ListView)
        await lv.remove_children()
        data_dir = self._manager.active_dir() / "data"
        if not data_dir.exists():
            return
        for f in sorted(data_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                lv.append(ListItem(Label(f.name)))

    async def on_file_drop_dropped(self, event: FileDrop.Dropped) -> None:
        dest_dir = self._manager.active_dir() / "data"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for fp in event.filepaths:
            src = Path(fp.path)
            dst = dest_dir / fp.name
            try:
                shutil.copy2(src, dst)
                _log.info("WorkspaceScreen: copied %s → %s", src, dst)
            except OSError as exc:
                _log.error("WorkspaceScreen: failed to copy %s: %s", src, exc)
                self._show_error(f"Failed to copy {fp.name}: {exc}")
        await self._refresh_file_list()
