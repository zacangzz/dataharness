from __future__ import annotations

from typing import Any

from textual import events, on
from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from app.tui.help import HelpData
from harness.command_registry import HarnessCommandDescriptor, parse_slash


type HintTarget = tuple[str, str]


class PromptBar(Vertical):
    help = HelpData(
        title="Prompt Bar",
        description=(
            "Type a message for the active DataHarness agent. Start with `/` to search commands "
            "and view argument hints."
        ),
    )

    def __init__(self, *, session: Any, state: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.state = state
        self._hint_text = ""
        self._hint_targets: dict[str, HintTarget] = {}
        self._last_descriptors: list[HarnessCommandDescriptor] = []

    def compose(self):
        yield Static("", id="prompt_status")
        yield Input(placeholder="Ask the data analyst or enter /help...", id="user_input")
        yield Static("", id="prompt_hints")
        yield OptionList(id="prompt_hint_options")

    @property
    def input(self) -> Input:
        return self.query_one("#user_input", Input)

    def on_mount(self) -> None:
        self.update_status(active_mode=self.state.active_agent_mode, run_state=str(self.state.state))
        self.query_one("#prompt_hint_options", OptionList).display = False

    def update_status(self, active_mode: str, run_state: str) -> None:
        self.query_one("#prompt_status", Static).update(f"{active_mode} | {run_state}")

    def update_state(self, state: Any) -> None:
        self.state = state

    def prefill(self, text: str) -> None:
        self.input.value = text
        self.input.cursor_position = len(text)

    async def refresh_hints(self, text: str) -> None:
        if not text.startswith("/"):
            self._hint_text = ""
            self.query_one("#prompt_hints", Static).update("")
            self._set_hint_options([])
            return

        descriptors = await self.session.list_commands()
        self._last_descriptors = descriptors
        self._hint_text = await self._build_hint_text(text, descriptors)
        options = await self._build_hint_options(text, descriptors)
        self.query_one("#prompt_hints", Static).update("" if options else self._hint_text)
        self._set_hint_options(options)

    async def _build_hint_text(
        self,
        text: str,
        descriptors: list[HarnessCommandDescriptor],
    ) -> str:
        stripped = text.strip()
        if stripped == "/":
            overview = descriptors[:8]
            switch_workspace = next(
                (descriptor for descriptor in descriptors if descriptor.name == "switch_workspace"),
                None,
            )
            if switch_workspace is not None and switch_workspace not in overview:
                overview = [*overview, switch_workspace]
            return self._format_descriptors(overview)

        try:
            command, args = parse_slash(text)
        except ValueError:
            prefix = stripped.lstrip("/")
            return self._format_descriptors(
                [descriptor for descriptor in descriptors if descriptor.name.startswith(prefix)]
            )

        descriptor = next((item for item in descriptors if item.name == command), None)
        if descriptor is None:
            return self._format_descriptors(
                [item for item in descriptors if item.name.startswith(command)]
            )

        current_arg_index = len(args) if text.endswith(" ") else max(len(args) - 1, 0)
        if current_arg_index >= len(descriptor.arguments):
            return descriptor.example_usage

        argument = descriptor.arguments[current_arg_index]
        parts = [f"{argument.name}: {argument.type} - {argument.description}"]
        if argument.example:
            parts.append(f"example: {argument.example}")

        candidates = await self._argument_candidates(argument.type)
        if candidates:
            parts.append(f"candidates: {', '.join(candidates)}")
        return " ".join(parts)

    def _format_descriptors(self, descriptors: list[HarnessCommandDescriptor]) -> str:
        return "\n".join(
            f"{descriptor.slash_alias}  {descriptor.short_description}"
            for descriptor in descriptors
        )

    async def _build_hint_options(
        self,
        text: str,
        descriptors: list[HarnessCommandDescriptor],
    ) -> list[tuple[str, str, HintTarget]]:
        stripped = text.strip()
        if stripped == "/":
            return [
                (
                    f"cmd:{descriptor.name}",
                    f"{descriptor.slash_alias}  {descriptor.short_description}",
                    ("command", descriptor.name),
                )
                for descriptor in descriptors
            ]

        try:
            command, args = parse_slash(text)
        except ValueError:
            prefix = stripped.lstrip("/")
            return [
                (
                    f"cmd:{descriptor.name}",
                    f"{descriptor.slash_alias}  {descriptor.short_description}",
                    ("command", descriptor.name),
                )
                for descriptor in descriptors
                if descriptor.name.startswith(prefix)
            ]

        descriptor = next((item for item in descriptors if item.name == command), None)
        if descriptor is None:
            return [
                (
                    f"cmd:{item.name}",
                    f"{item.slash_alias}  {item.short_description}",
                    ("command", item.name),
                )
                for item in descriptors
                if item.name.startswith(command)
            ]

        current_arg_index = len(args) if text.endswith(" ") else max(len(args) - 1, 0)
        if current_arg_index >= len(descriptor.arguments):
            return []
        argument = descriptor.arguments[current_arg_index]
        candidates = await self._argument_candidates(argument.type)
        return [
            (
                f"arg:{index}",
                candidate,
                ("argument", candidate),
            )
            for index, candidate in enumerate(candidates)
        ]

    def _set_hint_options(self, options: list[tuple[str, str, HintTarget]]) -> None:
        option_list = self.query_one("#prompt_hint_options", OptionList)
        self._hint_targets = {option_id: target for option_id, _, target in options}
        option_list.set_options(
            Option(prompt, id=option_id)
            for option_id, prompt, _ in options
        )
        option_list.display = bool(options)
        if options:
            option_list.highlighted = 0

    def _has_hint_options(self) -> bool:
        return self.query_one("#prompt_hint_options", OptionList).option_count > 0

    def _accept_highlighted_hint(self) -> None:
        option_list = self.query_one("#prompt_hint_options", OptionList)
        option = option_list.highlighted_option
        if option is None or option.id is None:
            return
        target = self._hint_targets.get(option.id)
        if target is None:
            return
        kind, value = target
        if kind == "command":
            self._prefill_command(value)
        elif kind == "argument":
            self._prefill_argument(value)
        self._set_hint_options([])
        self.query_one("#prompt_hints", Static).update("")
        self._hint_text = ""

    def _prefill_command(self, command_name: str) -> None:
        descriptor = next((item for item in self._last_descriptors if item.name == command_name), None)
        if descriptor is None:
            self.prefill(f"/{command_name}")
            return
        suffix = " " if descriptor.arguments else ""
        self.prefill(f"{descriptor.slash_alias}{suffix}")

    def _prefill_argument(self, value: str) -> None:
        text = self.input.value
        trailing = " " if text.endswith(" ") else ""
        parts = text.strip().split()
        if len(parts) <= 1:
            self.prefill(f"{parts[0] if parts else ''} {value} ")
            return
        if trailing:
            parts.append(value)
        else:
            parts[-1] = value
        self.prefill(" ".join(parts) + " ")

    async def _argument_candidates(self, arg_type: str) -> list[str]:
        if arg_type == "workspace_id":
            workspaces = await self.session.list_workspaces()
            return [workspace.workspace_id for workspace in workspaces]
        if arg_type == "chat_id":
            chats = await self.session.list_chats(self.state.workspace_id)
            return [chat.chat_id for chat in chats]
        return []

    @on(Input.Changed, "#user_input")
    async def on_input_changed(self, event: Input.Changed) -> None:
        await self.refresh_hints(event.value)

    @on(Input.Submitted, "#user_input")
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._has_hint_options():
            return
        self._accept_highlighted_hint()
        event.stop()

    @on(OptionList.OptionSelected, "#prompt_hint_options")
    def on_hint_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._accept_highlighted_hint()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if not self._has_hint_options():
            return
        option_list = self.query_one("#prompt_hint_options", OptionList)
        actions = {
            "down": option_list.action_cursor_down,
            "ctrl+n": option_list.action_cursor_down,
            "up": option_list.action_cursor_up,
            "ctrl+p": option_list.action_cursor_up,
            "pagedown": option_list.action_page_down,
            "pageup": option_list.action_page_up,
            "home": option_list.action_first,
            "end": option_list.action_last,
        }
        action = actions.get(event.key)
        if action is None:
            return
        action()
        option_list.scroll_to_highlight()
        event.prevent_default()
        event.stop()

    def text_buffer(self) -> str:
        return self._hint_text
