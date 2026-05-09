from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static


class WorkspaceManagerScreen(Screen):
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("n", "create_workspace", "New"),
        Binding("d", "delete_workspace", "Delete"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("l", "switch_selected", "Switch", show=False),
        Binding("enter", "switch_selected", "Switch"),
    ]

    def __init__(self, *, session, active_workspace_id: str) -> None:
        super().__init__()
        self.session = session
        self.active_workspace_id = active_workspace_id
        self._selected_workspace_id = active_workspace_id
        self._list_text = ""

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Vertical(
                Label("Workspaces", id="workspace_manager_title"),
                ListView(id="workspace_manager_list"),
                Input(placeholder="workspace id, e.g. w_0002", id="workspace_manager_input"),
                Horizontal(
                    Button("New", id="workspace_new"),
                    Button("Switch", id="workspace_switch", variant="primary"),
                    Button("Delete", id="workspace_delete", variant="error"),
                    Button("Close", id="workspace_close"),
                    id="workspace_manager_actions",
                ),
                Static("", id="workspace_manager_error"),
                id="workspace_manager_left",
            ),
            Vertical(
                Label("Files", id="workspace_files_title"),
                Static("", id="workspace_file_list"),
                id="workspace_manager_right",
            ),
            id="workspace_manager",
        )

    async def on_mount(self) -> None:
        await self.refresh_list()
        self.set_focus(self.query_one("#workspace_manager_list", ListView))

    async def refresh_list(self) -> None:
        workspaces = await self.session.list_workspaces()
        list_view = self.query_one("#workspace_manager_list", ListView)
        await list_view.remove_children()
        lines: list[str] = []
        for workspace in workspaces:
            marker = "*" if workspace.workspace_id == self.active_workspace_id else " "
            line = (
                f"{marker} {workspace.workspace_id}  "
                f"{workspace.source_count} files  {workspace.chat_count} chats"
            )
            lines.append(line)
            await list_view.append(
                ListItem(Label(line), id=f"workspace_item_{workspace.workspace_id}")
            )
        self._list_text = "\n".join(lines)
        self._highlight_selected_workspace(list_view)
        await self._refresh_files()

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "workspace_manager_list" or event.item is None:
            return
        self._update_selected_from_item(event.item)
        await self._refresh_files()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "workspace_manager_list":
            return
        if self._update_selected_from_item(event.item):
            await self._refresh_files()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "workspace_new": self.action_create_workspace,
            "workspace_switch": self.action_switch_selected,
            "workspace_delete": self.action_delete_workspace,
            "workspace_close": self.action_close,
        }
        handler = handlers.get(event.button.id or "")
        if handler is not None:
            await handler()

    async def action_create_workspace(self) -> None:
        workspace_id = self._input_value()
        if not workspace_id:
            self._show_error("Enter a workspace id first.")
            return
        try:
            await self.session.create_workspace(workspace_id)
            self._selected_workspace_id = workspace_id
            self._clear_error()
            self.query_one("#workspace_manager_input", Input).value = ""
            await self.refresh_list()
        except Exception as exc:  # noqa: BLE001
            self._show_error(f"{type(exc).__name__}: {exc}")

    async def action_switch_selected(self) -> None:
        await self.switch_to(self._selected_workspace_id)

    def action_cursor_down(self) -> None:
        self.query_one("#workspace_manager_list", ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#workspace_manager_list", ListView).action_cursor_up()

    async def action_delete_workspace(self) -> None:
        workspace_id = self._selected_workspace_id
        if workspace_id == self.active_workspace_id:
            self._show_error("Switch away before deleting the active workspace.")
            return
        try:
            await self.session.delete_workspace(workspace_id)
            self._clear_error()
            await self.refresh_list()
        except Exception as exc:  # noqa: BLE001
            self._show_error(f"{type(exc).__name__}: {exc}")

    async def switch_to(self, workspace_id: str) -> None:
        try:
            snapshot = await self.session.activate_workspace(workspace_id, force=False)
        except Exception as exc:  # noqa: BLE001
            self._show_error(f"{type(exc).__name__}: {exc}")
            return
        self.active_workspace_id = workspace_id
        self._selected_workspace_id = workspace_id
        handler = getattr(self.app, "apply_workspace_snapshot", None)
        if handler is not None:
            handler(snapshot)
        self.app.pop_screen()

    async def action_close(self) -> None:
        self.app.pop_screen()

    async def _refresh_files(self) -> None:
        workspace_id = self._selected_workspace_id
        workspace_dir = self.session.app_root / "workspaces" / workspace_id
        data_dir = workspace_dir / "data"
        files = self._list_files(data_dir)
        body = "\n".join(files) if files else "no files"
        self.query_one("#workspace_file_list", Static).update(body)

    def _list_files(self, data_dir: Path) -> list[str]:
        if not data_dir.exists():
            return []
        return [
            path.name
            for path in sorted(data_dir.iterdir())
            if path.is_file() and not path.name.startswith(".")
        ]

    def _input_value(self) -> str:
        return self.query_one("#workspace_manager_input", Input).value.strip()

    def _show_error(self, text: str) -> None:
        self.query_one("#workspace_manager_error", Static).update(text)

    def _clear_error(self) -> None:
        self.query_one("#workspace_manager_error", Static).update("")

    def _highlight_selected_workspace(self, list_view: ListView) -> None:
        for index, item in enumerate(list_view.children):
            if item.id == f"workspace_item_{self._selected_workspace_id}":
                list_view.index = index
                return
        list_view.index = 0 if list_view.children else None

    def _update_selected_from_item(self, item: ListItem) -> bool:
        item_id = item.id or ""
        if not item_id.startswith("workspace_item_"):
            return False
        self._selected_workspace_id = item_id.removeprefix("workspace_item_")
        return True

    def text_buffer(self) -> str:
        return self._list_text
