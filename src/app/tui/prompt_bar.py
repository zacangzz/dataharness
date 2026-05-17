from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events, on
from textual.containers import Vertical
from textual.widgets import OptionList, Static, TextArea
from textual.widgets.option_list import Option

from app.tui.file_picker import FilePicker, format_file_mention
from app.tui.help import HelpData
from app.tui.prompt_editor import PromptEditor
from harness.core.command_registry import HarnessCommandDescriptor, parse_slash


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
        self._last_workspace_id: str | None = getattr(state, "workspace_id", None)
        self._picker_was_visible: bool = False

    def compose(self):
        yield Static("", id="prompt_status")
        yield PromptEditor(id="user_input")
        yield Static("", id="prompt_hints")
        yield OptionList(id="prompt_hint_options")
        yield FilePicker(self._workspace_dir(), id="prompt_file_picker")

    @property
    def editor(self) -> PromptEditor:
        return self.query_one("#user_input", PromptEditor)

    @property
    def input(self) -> PromptEditor:
        return self.editor

    def on_mount(self) -> None:
        self.update_status(active_mode=self.state.active_agent_mode, run_state=str(self.state.state))
        self.query_one("#prompt_hint_options", OptionList).display = False
        self.query_one("#prompt_file_picker", FilePicker).display = False

    def update_status(self, active_mode: str, run_state: str) -> None:
        self.query_one("#prompt_status", Static).update(f"{active_mode} | {run_state}")

    def update_state(self, state: Any) -> None:
        prior = self._last_workspace_id
        self.state = state
        new_id = getattr(state, "workspace_id", None)
        if new_id != prior:
            self._last_workspace_id = new_id
            try:
                picker = self.query_one("#prompt_file_picker", FilePicker)
            except Exception:
                return
            picker.index.workspace_dir = self._workspace_dir()
            picker.index.invalidate()

    def prefill(self, text: str) -> None:
        self.editor.set_text(text)

    def _workspace_dir(self) -> Path:
        return self.session.app_root / "workspaces" / self.state.workspace_id

    def _file_query(self, text: str) -> str | None:
        cursor_text = text
        at_index = cursor_text.rfind("@")
        if at_index < 0:
            return None
        token = cursor_text[at_index + 1 :]
        if " " in token and not token.startswith('"'):
            return None
        return token.strip('"')

    def _show_file_picker(self, query: str) -> None:
        picker = self.query_one("#prompt_file_picker", FilePicker)
        new_dir = self._workspace_dir()
        if picker.index.workspace_dir != new_dir:
            picker.index.workspace_dir = new_dir
            picker.index.invalidate()
        picker.refresh_query(query)
        was_visible = self._picker_was_visible
        picker.display = True
        if not was_visible:
            try:
                picker.focus_picker()
            except Exception:
                pass
        self._picker_was_visible = True

    async def refresh_hints(self, text: str) -> None:
        file_query = self._file_query(text)
        if file_query is not None:
            self._hint_text = ""
            self.query_one("#prompt_hints", Static).update("")
            self._set_hint_options([])
            self._show_file_picker(file_query)
            return
        self.query_one("#prompt_file_picker", FilePicker).display = False
        self._picker_was_visible = False

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

    def _restore_editor_focus(self) -> None:
        try:
            self.app.set_focus(self.editor)
        except Exception:
            try:
                self.editor.focus()
            except Exception:
                pass

    def _accept_highlighted_hint(self, source_text: str | None = None) -> None:
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
            self._prefill_argument(value, source_text=source_text)
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

    def _prefill_argument(self, value: str, source_text: str | None = None) -> None:
        text = source_text if source_text is not None else self.editor.text
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

    @on(TextArea.Changed, "#user_input")
    async def on_editor_changed(self, event: TextArea.Changed) -> None:
        await self.refresh_hints(self.editor.text)

    @on(PromptEditor.Submitted)
    def on_prompt_editor_submitted(self, event: PromptEditor.Submitted) -> None:
        # If hints visible, accept hint instead of letting submit propagate to app.
        if self._has_hint_options():
            self._accept_highlighted_hint(source_text=event.text)
            event.stop()
            return
        # Clear editor before dispatching to app so re-entrant typing is clean.
        self.editor.clear_text()

    @on(OptionList.OptionSelected, "#prompt_hint_options")
    def on_hint_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._accept_highlighted_hint()
        event.stop()

    @on(FilePicker.Selected)
    def on_file_picker_selected(self, event: FilePicker.Selected) -> None:
        text = self.editor.text
        at_index = text.rfind("@")
        if at_index < 0:
            return
        prefix = text[:at_index]
        suffix = " "
        self.editor.set_text(prefix + format_file_mention(event.path) + suffix)
        picker = self.query_one("#prompt_file_picker", FilePicker)
        picker.display = False
        self._picker_was_visible = False
        self._restore_editor_focus()
        event.stop()

    @on(FilePicker.Dismissed)
    def on_file_picker_dismissed(self, event: FilePicker.Dismissed) -> None:
        self._picker_was_visible = False
        self._restore_editor_focus()
        event.stop()

    def _picker_visible(self) -> bool:
        try:
            return bool(self.query_one("#prompt_file_picker", FilePicker).display)
        except Exception:
            return False

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            if self._picker_visible():
                picker = self.query_one("#prompt_file_picker", FilePicker)
                picker.dismiss_picker()
                event.prevent_default()
                event.stop()
                return
            if self._has_hint_options():
                self._set_hint_options([])
                self.query_one("#prompt_hints", Static).update("")
                self._hint_text = ""
                event.prevent_default()
                event.stop()
                return
            return

        if self._picker_visible():
            picker = self.query_one("#prompt_file_picker", FilePicker)
            if event.key in ("up", "down", "tab"):
                if event.key == "tab":
                    picker.toggle_mode()
                else:
                    option_list = picker.query_one("#file_picker_options", OptionList)
                    if event.key == "down":
                        option_list.action_cursor_down()
                    else:
                        option_list.action_cursor_up()
                event.prevent_default()
                event.stop()
                return
            if event.key == "enter":
                picker._select_current()
                event.prevent_default()
                event.stop()
                return

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
