from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Static


class ChatManagerScreen(Screen):
    def __init__(self, *, workspace_id: str, session) -> None:
        super().__init__()
        self.workspace_id = workspace_id
        self.session = session
        self._list = Static(id="chat_list")
        self._list_text: str = ""

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"Chats for workspace {self.workspace_id}"),
            self._list,
            Button("Create new chat", id="create_chat"),
            Button("Close", id="close_chat_manager"),
        )

    async def on_mount(self) -> None:
        await self.refresh_list()

    async def refresh_list(self) -> None:
        chats = await self.session.list_chats(self.workspace_id)
        body = "\n".join(
            f"{c.chat_id}\t{c.title or '(untitled)'}\t{c.message_count} msgs"
            for c in chats
        )
        self._list_text = body
        self._list.update(body)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create_chat":
            summary = await self.session.create_chat(self.workspace_id)
            await self.app.activate_chat(summary.chat_id)
            self.app.pop_screen()
        elif event.button.id == "close_chat_manager":
            self.app.pop_screen()

    def text_buffer(self) -> str:
        return self._list_text
