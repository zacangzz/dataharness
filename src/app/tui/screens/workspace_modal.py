from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from harness.exceptions import WorkspaceSwitchBlocked


class WorkspaceModal(Screen):
    def __init__(self, *, session, target_workspace_id: str) -> None:
        super().__init__()
        self.session = session
        self.target = target_workspace_id

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"Switch to {self.target}?"),
            Button("Switch", id="confirm_switch"),
            Button("Cancel", id="cancel_switch"),
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_switch":
            try:
                await self.session.activate_workspace(self.target, force=False)
            except WorkspaceSwitchBlocked:
                self.mount(Static("Active run will be cancelled."))
                self.mount(Button("Force", id="force_switch"))
                return
            self.app.pop_screen()
        elif event.button.id == "force_switch":
            await self.session.activate_workspace(self.target, force=True)
            self.app.pop_screen()
        elif event.button.id == "cancel_switch":
            self.app.pop_screen()
