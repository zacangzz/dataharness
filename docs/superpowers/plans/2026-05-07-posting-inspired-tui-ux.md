# Posting-Inspired TUI UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Posting-style Textual interaction quality to DataHarness through command discovery, prompt hints, status visibility, keyboard navigation, focused help, and TCSS styling.

**Architecture:** Keep DataHarness Layer 4 as the only UI layer and keep `AppSession` as the boundary to Layer 3. Add small TUI modules for command search, prompt hints, jump navigation, help, and run trace state; wire them into `DataHarnessApp` without importing `harness.orchestrator` directly.

**Tech Stack:** Python 3.12, Textual >=8.2.4, pytest, pytest-asyncio, Pydantic command descriptors, existing `AppSession` async facade.

**Repository Rule:** Do not commit during execution unless the user grants permission. Each task ends with verification and a checkpoint summary instead of a commit step.

---

## File Structure

- Create `src/app/tui/commands.py`: Textual command provider and command-selection helpers backed by `AppSession.list_commands()`.
- Create `src/app/tui/prompt_bar.py`: composed prompt input widget, command hint rendering, argument hint/candidate logic.
- Create `src/app/tui/jump.py`: stable-ID jump target scanner and modal jump overlay.
- Create `src/app/tui/help.py`: `HelpData`, focused-widget protocol, and help modal.
- Create `src/app/tui/run_trace.py`: bounded phase state model for top bar and sidebar rendering.
- Create `src/app/tui/dataharness.tcss`: extracted app styles, focus states, compact mode, modal styling, and severity classes.
- Modify `src/app/tui/app.py`: register command provider, bind keys, mount `PromptBar`, wire jump/help/status/trace updates, and load TCSS.
- Modify `src/app/tui/widgets.py`: add help metadata, status phase rendering, sidebar trace rendering, and remove permanent instruction-heavy text.
- Modify `src/app/tui/screens/workspace_manager.py`: add `j/k/l/enter/escape` navigation bindings.
- Modify `src/app/tui/screens/chat_manager.py`: add consistent list navigation bindings where the screen is active.
- Modify `scripts/build_app.sh`: include `src/app/tui/dataharness.tcss` as PyInstaller data.
- Modify `tests/packaging/test_build_app_script.py`: assert TCSS is bundled.
- Add tests under `tests/app/tui/` for command provider, prompt bar, jump overlay, help screen, status trace, keyboard navigation, TCSS, and layer boundaries.

---

### Task 1: Command Provider And Searchable Palette

**Files:**
- Create: `src/app/tui/commands.py`
- Modify: `src/app/tui/app.py`
- Test: `tests/app/tui/test_command_provider.py`
- Keep: `src/app/tui/screens/command_palette.py` until tests are migrated, then leave as compatibility if still referenced.

- [ ] **Step 1: Write failing command provider tests**

Add `tests/app/tui/test_command_provider.py`:

```python
import pytest

from app.tui.app import DataHarnessApp
from app.tui.commands import DataHarnessCommandProvider, build_command_prefill


@pytest.mark.asyncio
async def test_command_provider_discovers_layer3_commands(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        provider = DataHarnessCommandProvider(screen=app.screen, match_style=None)
        hits = [hit async for hit in provider.discover()]
        prompts = [str(hit.prompt) for hit in hits]

        assert any("doctor" in prompt for prompt in prompts)
        assert any("switch_workspace" in prompt for prompt in prompts)


@pytest.mark.asyncio
async def test_command_provider_search_filters_commands(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        provider = DataHarnessCommandProvider(screen=app.screen, match_style=None)
        hits = [hit async for hit in provider.search("doctor")]
        prompts = [str(hit.prompt).lower() for hit in hits]

        assert prompts
        assert all("doctor" in prompt for prompt in prompts)


@pytest.mark.asyncio
async def test_build_command_prefill_uses_argument_placeholders(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        descriptors = await app._session.list_commands()
        switch = next(d for d in descriptors if d.name == "switch_workspace")

        assert build_command_prefill(switch) == "/switch_workspace <workspace_id>"
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run pytest tests/app/tui/test_command_provider.py -q
```

Expected result: fail because `app.tui.commands` does not exist.

- [ ] **Step 3: Implement command provider**

Create `src/app/tui/commands.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.types import IgnoreReturnCallbackType

from harness.command_registry import CommandContext, HarnessCommandDescriptor

if TYPE_CHECKING:
    from app.tui.app import DataHarnessApp


def build_command_context(app: DataHarnessApp) -> CommandContext:
    state = app.state
    return CommandContext(
        workspace_id=state.workspace_id,
        chat_id=app.active_chat_id,
        run_id=state.run_id,
        has_pending_approval=False,
        has_pending_clarification=False,
    )


def command_title(descriptor: HarnessCommandDescriptor) -> str:
    prefix = descriptor.slash_alias.lstrip("/")
    if descriptor.available:
        return prefix
    reason = descriptor.disabled_reason or "unavailable"
    return f"{prefix} ({reason})"


def build_command_prefill(descriptor: HarnessCommandDescriptor) -> str:
    parts = [descriptor.slash_alias]
    parts.extend(f"<{arg.name}>" for arg in descriptor.arguments if arg.required)
    return " ".join(parts)


class DataHarnessCommandProvider(Provider):
    async def _descriptors(self) -> list[HarnessCommandDescriptor]:
        app = cast("DataHarnessApp", self.screen.app)
        return await app.session.list_commands(build_command_context(app))

    def _callback_for(
        self,
        descriptor: HarnessCommandDescriptor,
    ) -> IgnoreReturnCallbackType:
        app = cast("DataHarnessApp", self.screen.app)
        return cast(
            IgnoreReturnCallbackType,
            partial(app.handle_command_palette_selection, descriptor),
        )

    async def discover(self) -> Hits:
        for descriptor in await self._descriptors():
            yield DiscoveryHit(
                command_title(descriptor),
                self._callback_for(descriptor),
                help=descriptor.short_description,
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for descriptor in await self._descriptors():
            title = command_title(descriptor)
            score = matcher.match(title)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(title),
                    self._callback_for(descriptor),
                    help=descriptor.short_description,
                )
```

- [ ] **Step 4: Wire provider into the app**

Modify `src/app/tui/app.py`:

```python
from textual.binding import Binding

from app.tui.commands import DataHarnessCommandProvider, build_command_prefill
from harness.command_registry import HarnessCommandDescriptor
```

Update the class attributes:

```python
class DataHarnessApp(App[None]):
    TITLE = "DataHarness"
    COMMANDS = {DataHarnessCommandProvider}
    BINDINGS = [
        Binding("ctrl+p", "command_palette", "Commands", id="commands"),
        Binding("f2", "open_workspaces", "Workspaces", id="workspaces"),
    ]
```

Add the method:

```python
    @property
    def active_chat_id(self) -> str | None:
        return self._active_chat_id

    def handle_command_palette_selection(self, descriptor: HarnessCommandDescriptor) -> None:
        if not descriptor.available:
            self.notify(descriptor.disabled_reason or "command unavailable", severity="warning")
            return
        if descriptor.arguments:
            prompt = self.query_one("#prompt_bar", PromptBar)
            prompt.prefill(build_command_prefill(descriptor))
            self.set_focus(prompt.input)
            return
        self.run_worker(self._stream_command(descriptor.name, {}))
```

Import `PromptBar` in `app.py` after Task 2 creates it. Until Task 2, use `Input` fallback by setting `#user_input.value`.

- [ ] **Step 5: Verify command provider**

Run:

```bash
uv run pytest tests/app/tui/test_command_provider.py tests/app/tui/test_command_palette.py tests/app/tui/test_layer_boundaries.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 6: Checkpoint**

Summarize changed files and test output. Do not commit without user permission.

---

### Task 2: Prompt Bar With Command And Argument Hints

**Files:**
- Create: `src/app/tui/prompt_bar.py`
- Modify: `src/app/tui/app.py`
- Test: `tests/app/tui/test_prompt_bar.py`

- [ ] **Step 1: Write failing prompt bar tests**

Add `tests/app/tui/test_prompt_bar.py`:

```python
import pytest

from app.tui.app import DataHarnessApp
from app.tui.prompt_bar import PromptBar


@pytest.mark.asyncio
async def test_prompt_bar_replaces_plain_user_input(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()

        prompt = app.query_one("#prompt_bar", PromptBar)
        assert prompt.input.id == "user_input"


@pytest.mark.asyncio
async def test_prompt_bar_shows_command_hints_after_slash(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        prompt = app.query_one("#prompt_bar", PromptBar)

        await prompt.refresh_hints("/")

        text = prompt.text_buffer()
        assert "/doctor" in text
        assert "/switch_workspace" in text


@pytest.mark.asyncio
async def test_prompt_bar_shows_workspace_candidates_for_switch_workspace(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await app._session.create_workspace("w_0002")
        prompt = app.query_one("#prompt_bar", PromptBar)

        await prompt.refresh_hints("/switch_workspace ")

        text = prompt.text_buffer()
        assert "workspace_id" in text
        assert "w_0002" in text
```

- [ ] **Step 2: Run failing prompt bar tests**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_bar.py -q
```

Expected result: fail because `PromptBar` does not exist.

- [ ] **Step 3: Implement prompt bar**

Create `src/app/tui/prompt_bar.py`:

```python
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

from app.tui.help import HelpData
from harness.command_registry import HarnessCommandDescriptor, parse_slash


class PromptBar(Vertical):
    help = HelpData(
        title="Prompt Bar",
        description=(
            "Type a message for the active DataHarness agent. "
            "Start with `/` to search commands and view argument hints."
        ),
    )

    def __init__(self, *, session, state, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.state = state
        self._hint_text = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="prompt_status")
        yield Input(placeholder="Ask the data analyst or enter /help...", id="user_input")
        yield Static("", id="prompt_hints")

    @property
    def input(self) -> Input:
        return self.query_one("#user_input", Input)

    def on_mount(self) -> None:
        self.update_status(active_mode=self.state.active_agent_mode, run_state=str(self.state.state))

    def update_status(self, *, active_mode: str, run_state: str) -> None:
        self.query_one("#prompt_status", Static).update(
            f"mode: {active_mode} | run: {run_state}"
        )

    def prefill(self, text: str) -> None:
        self.input.value = text
        self.input.cursor_position = len(text)

    async def refresh_hints(self, text: str) -> None:
        if not text.startswith("/"):
            self._hint_text = ""
            self.query_one("#prompt_hints", Static).update("")
            return

        descriptors = await self.session.list_commands()
        self._hint_text = await self._build_hint_text(text, descriptors)
        self.query_one("#prompt_hints", Static).update(self._hint_text)

    async def _build_hint_text(
        self,
        text: str,
        descriptors: list[HarnessCommandDescriptor],
    ) -> str:
        stripped = text.strip()
        if stripped == "/":
            return "\n".join(
                f"{d.slash_alias}  {d.short_description}"
                for d in descriptors[:8]
            )

        try:
            command, args = parse_slash(text)
        except ValueError:
            command = text[1:].split(" ", 1)[0]
            args = []

        descriptor = next((d for d in descriptors if d.name == command), None)
        if descriptor is None:
            matches = [d for d in descriptors if d.name.startswith(command)]
            return "\n".join(f"{d.slash_alias}  {d.short_description}" for d in matches[:8])

        arg_index = len(args)
        if text.endswith(" "):
            arg_index = len(args)
        if arg_index >= len(descriptor.arguments):
            return descriptor.example_usage

        spec = descriptor.arguments[arg_index]
        candidates = await self._argument_candidates(spec.type)
        candidate_text = ", ".join(candidates[:6])
        suffix = f"\n{candidate_text}" if candidate_text else ""
        example = f" example: {spec.example}" if spec.example else ""
        return f"{spec.name}: {spec.type} - {spec.description}{example}{suffix}"

    async def _argument_candidates(self, arg_type: str) -> list[str]:
        if arg_type == "workspace_id":
            workspaces = await self.session.list_workspaces()
            return [w.workspace_id for w in workspaces]
        if arg_type == "chat_id":
            workspace_id = self.state.workspace_id
            chats = await self.session.list_chats(workspace_id)
            return [c.chat_id for c in chats]
        return []

    @on(Input.Changed, "#user_input")
    async def on_input_changed(self, event: Input.Changed) -> None:
        await self.refresh_hints(event.value)

    def text_buffer(self) -> str:
        return self._hint_text
```

- [ ] **Step 4: Replace plain input in app compose**

Modify imports in `src/app/tui/app.py`:

```python
from app.tui.prompt_bar import PromptBar
```

Replace this compose fragment:

```python
Input(placeholder="Ask the data analyst or enter /help...", id="user_input"),
```

with:

```python
PromptBar(session=self._session, state=self._state, id="prompt_bar"),
```

Update CSS IDs from `#user_input` height rules to `#prompt_bar` and keep the nested input height stable.

Update focus calls:

```python
self.set_focus(self.query_one("#prompt_bar", PromptBar).input)
```

Keep `on_input_submitted()` unchanged because the nested input still has `id="user_input"`.

- [ ] **Step 5: Verify prompt bar behavior**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_bar.py tests/app/tui/test_textual_app.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 6: Checkpoint**

Summarize prompt bar behavior, changed files, and test output. Do not commit without user permission.

---

### Task 3: Status Bar And Run Trace

**Files:**
- Create: `src/app/tui/run_trace.py`
- Modify: `src/app/tui/widgets.py`
- Modify: `src/app/tui/app.py`
- Test: `tests/app/tui/test_run_trace.py`

- [ ] **Step 1: Write failing run trace tests**

Add `tests/app/tui/test_run_trace.py`:

```python
from datetime import UTC, datetime

from app.events import AppCommandCompleted, AppCommandProgress, AppCommandStarted
from app.tui.run_trace import RunTrace
from app.tui.widgets import SidebarPane, WorkspaceBar


def test_run_trace_records_bounded_phase_lines():
    trace = RunTrace(max_lines=2)

    trace.command_started("doctor")
    trace.command_progress("doctor", "scan", 1, 2)
    trace.command_completed("doctor", {"ok": True})

    assert trace.current_phase == "doctor complete"
    assert trace.lines == ["doctor: scan 1/2", "doctor: complete"]


def test_workspace_bar_includes_chat_and_phase():
    bar = WorkspaceBar()

    bar.update_from(
        workspace_id="w_0001",
        chat_id="chat_1",
        run_state="idle",
        active_mode="analyst",
        runtime_status="not_loaded",
        phase="doctor complete",
    )

    rendered = str(bar.render())
    assert "chat: chat_1" in rendered
    assert "phase: doctor complete" in rendered


def test_sidebar_renders_trace_lines():
    sidebar = SidebarPane()

    sidebar.update_trace(["doctor: scan 1/2", "doctor: complete"])

    rendered = sidebar.text_buffer()
    assert "TRACE" in rendered
    assert "doctor: complete" in rendered
```

- [ ] **Step 2: Run failing run trace tests**

Run:

```bash
uv run pytest tests/app/tui/test_run_trace.py -q
```

Expected result: fail because `RunTrace`, `WorkspaceBar.chat_id`, and `SidebarPane.update_trace()` do not exist.

- [ ] **Step 3: Implement trace model**

Create `src/app/tui/run_trace.py`:

```python
from __future__ import annotations

from collections import deque


class RunTrace:
    def __init__(self, *, max_lines: int = 20) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        self.current_phase = "idle"

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    def command_started(self, command: str) -> None:
        self.current_phase = f"{command} started"
        self._lines.append(f"{command}: started")

    def command_progress(self, command: str, phase: str, phase_index: int, phase_total: int) -> None:
        self.current_phase = phase
        self._lines.append(f"{command}: {phase} {phase_index}/{phase_total}")

    def command_completed(self, command: str, result: dict) -> None:
        self.current_phase = f"{command} complete"
        if "error" in result:
            self._lines.append(f"{command}: {result['error']}")
        else:
            self._lines.append(f"{command}: complete")

    def turn_started(self, active_mode: str) -> None:
        self.current_phase = f"{active_mode} turn started"
        self._lines.append(self.current_phase)

    def runtime_delta(self, delta_type: str) -> None:
        self.current_phase = f"runtime {delta_type}"

    def failed(self, summary: str, error_code: str) -> None:
        self.current_phase = "failed"
        self._lines.append(f"{error_code}: {summary}")
```

- [ ] **Step 4: Update widgets**

Modify `WorkspaceBar.update_from()` in `src/app/tui/widgets.py`:

```python
    def update_from(
        self,
        *,
        workspace_id: str,
        run_state: str,
        active_mode: str,
        runtime_status: str = "checking",
        chat_id: str | None = None,
        phase: str = "idle",
    ) -> None:
        chat = chat_id or "none"
        self.update(
            f"workspace: {workspace_id} | chat: {chat} | state: {run_state} | "
            f"mode: {active_mode} | runtime: {runtime_status} | phase: {phase}"
        )
```

Modify `SidebarPane.__init__()`:

```python
self._trace_lines: deque[str] = deque(maxlen=20)
```

Add `SidebarPane.update_trace()`:

```python
    def update_trace(self, lines: list[str]) -> None:
        self._trace_lines.clear()
        self._trace_lines.extend(lines)
        self._refresh_text()
```

Modify `_refresh_text()` to include trace:

```python
trace = "\n".join(self._trace_lines) or "no trace yet"
self.update(
    f"STATUS\n{self._status}\n\n"
    f"TRACE\n{trace}\n\n"
    f"COMMANDS\n{commands}\n\n"
    f"DOCTOR\n{doctor}\n\n"
    f"FAILURES\n{failure}\n\n"
    f"{self._help}"
)
```

- [ ] **Step 5: Wire trace into event handling**

Modify `DataHarnessApp.__init__()`:

```python
from app.tui.run_trace import RunTrace

self._trace = RunTrace()
```

Update `_build_consumer()` handlers so command and turn events update `_trace` before widgets:

```python
"AppTurnStarted": self._handle_turn_started,
"AppRuntimeDelta": self._handle_runtime_delta,
"AppTurnFailed": self._handle_turn_failed,
"AppCommandStarted": self._handle_command_started,
"AppCommandProgress": self._handle_command_progress,
"AppCommandCompleted": self._handle_command_completed,
```

Add helper methods:

```python
    def _refresh_trace_widgets(self) -> None:
        self.query_one("#sidebar", SidebarPane).update_trace(self._trace.lines)
        self.query_one("#workspace_bar", WorkspaceBar).update_from(
            workspace_id=self._state.workspace_id,
            chat_id=self._active_chat_id,
            run_state=str(self._state.state),
            active_mode=self._state.active_agent_mode,
            runtime_status="checking",
            phase=self._trace.current_phase,
        )

    def _handle_turn_started(self, event) -> None:
        self._trace.turn_started(event.active_mode)
        self._refresh_trace_widgets()

    def _handle_runtime_delta(self, event) -> None:
        self._trace.runtime_delta(event.delta_type)
        self.query_one("#conversation", ConversationPane).append_assistant_delta(event)
        self._refresh_trace_widgets()

    def _handle_turn_failed(self, event) -> None:
        self._trace.failed(event.failure_summary, event.error_code)
        self.query_one("#sidebar", SidebarPane).failure(event.failure_summary, event.error_code)
        self._refresh_trace_widgets()

    def _handle_command_started(self, event) -> None:
        self._trace.command_started(event.command)
        self.query_one("#sidebar", SidebarPane).command_started(event.command)
        self._refresh_trace_widgets()

    def _handle_command_progress(self, event) -> None:
        self._trace.command_progress(event.command, event.phase, event.phase_index, event.phase_total)
        self.query_one("#sidebar", SidebarPane).command_progress(
            event.command, event.phase, event.phase_index, event.phase_total
        )
        self._refresh_trace_widgets()
```

Keep the existing `_handle_command_completed()` and add trace update at the beginning:

```python
self._trace.command_completed(event.command, event.result)
```

- [ ] **Step 6: Verify trace behavior**

Run:

```bash
uv run pytest tests/app/tui/test_run_trace.py tests/app/tui/test_event_streaming.py tests/app/tui/test_textual_app.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 7: Checkpoint**

Summarize trace behavior, changed files, and test output. Do not commit without user permission.

---

### Task 4: Keyboard Navigation And Jump Overlay

**Files:**
- Create: `src/app/tui/jump.py`
- Modify: `src/app/tui/app.py`
- Modify: `src/app/tui/screens/workspace_manager.py`
- Modify: `src/app/tui/screens/chat_manager.py`
- Test: `tests/app/tui/test_jump_navigation.py`
- Test: `tests/app/tui/test_keyboard_navigation.py`

- [ ] **Step 1: Write failing jump and navigation tests**

Add `tests/app/tui/test_jump_navigation.py`:

```python
import pytest

from app.tui.app import DataHarnessApp
from app.tui.jump import Jumper, JumpOverlay
from app.tui.widgets import ConversationPane


@pytest.mark.asyncio
async def test_jumper_finds_visible_widget_targets(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        jumper = Jumper({"conversation": "2", "sidebar": "3"}, screen=app.screen)

        overlays = jumper.get_overlays()
        keys = {info.key for info in overlays.values()}

        assert "2" in keys
        assert "3" in keys


@pytest.mark.asyncio
async def test_jump_overlay_focuses_selected_target(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()

        await app.action_toggle_jump_mode()
        await pilot.press("2")
        await pilot.pause()

        assert isinstance(app.focused, ConversationPane)
```

Add `tests/app/tui/test_keyboard_navigation.py`:

```python
import pytest

from app.tui.app import DataHarnessApp
from app.tui.screens.workspace_manager import WorkspaceManagerScreen


@pytest.mark.asyncio
async def test_workspace_manager_supports_j_k_l_navigation(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await app._session.create_workspace("w_0002")
        screen = WorkspaceManagerScreen(
            session=app._session,
            active_workspace_id="w_0001",
        )
        await app.push_screen(screen)
        await pilot.pause()

        await pilot.press("j", "l")
        await pilot.pause()

        assert app.state.workspace_id in {"w_0001", "w_0002"}
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/app/tui/test_jump_navigation.py tests/app/tui/test_keyboard_navigation.py -q
```

Expected result: fail because `app.tui.jump` and `action_toggle_jump_mode()` do not exist.

- [ ] **Step 3: Implement jump module**

Create `src/app/tui/jump.py`:

```python
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
```

- [ ] **Step 4: Wire jump action into app**

Modify `src/app/tui/app.py` imports:

```python
from app.tui.jump import Jumper, JumpOverlay
```

Add binding:

```python
Binding("ctrl+o", "toggle_jump_mode", "Jump", id="jump")
```

Add action:

```python
    async def action_toggle_jump_mode(self) -> None:
        focused_before = self.focused
        jumper = Jumper(
            {
                "prompt_bar": "1",
                "conversation": "2",
                "sidebar": "3",
                "workspace_bar": "w",
            },
            screen=self.screen,
        )

        def handle_target(target) -> None:
            if target is None:
                if focused_before is not None:
                    self.set_focus(focused_before, scroll_visible=False)
                return
            if isinstance(target, str):
                widget = self.query_one(f"#{target}")
                self.set_focus(widget)
                return
            self.set_focus(target)

        await self.push_screen(JumpOverlay(jumper), callback=handle_target)
```

- [ ] **Step 5: Add list navigation bindings**

Modify `WorkspaceManagerScreen.BINDINGS`:

```python
BINDINGS = [
    ("escape", "app.pop_screen", "back"),
    ("j", "cursor_down", "down"),
    ("k", "cursor_up", "up"),
    ("l", "select_cursor", "select"),
    ("enter", "select_cursor", "select"),
]
```

Add actions if `ListView` does not already receive them:

```python
    def action_cursor_down(self) -> None:
        self.query_one(ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(ListView).action_cursor_up()

    async def action_select_cursor(self) -> None:
        list_view = self.query_one(ListView)
        if list_view.highlighted_child is not None:
            await self.on_list_view_selected(
                ListView.Selected(list_view, list_view.highlighted_child)
            )
```

Apply the same pattern to `ChatManagerScreen` if it uses `ListView`; if it uses buttons, add explicit `j/k` focus movement and `l/enter` press behavior.

- [ ] **Step 6: Verify navigation**

Run:

```bash
uv run pytest tests/app/tui/test_jump_navigation.py tests/app/tui/test_keyboard_navigation.py tests/app/tui/test_textual_app.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 7: Checkpoint**

Summarize navigation changes, changed files, and test output. Do not commit without user permission.

---

### Task 5: Focused-Widget Help

**Files:**
- Create: `src/app/tui/help.py`
- Modify: `src/app/tui/app.py`
- Modify: `src/app/tui/widgets.py`
- Modify: `src/app/tui/prompt_bar.py`
- Test: `tests/app/tui/test_focused_help.py`

- [ ] **Step 1: Write failing help tests**

Add `tests/app/tui/test_focused_help.py`:

```python
import pytest

from app.tui.app import DataHarnessApp
from app.tui.help import HelpData, HelpScreen
from app.tui.prompt_bar import PromptBar


def test_help_data_is_plain_widget_metadata():
    data = HelpData(title="Prompt", description="Type text")

    assert data.title == "Prompt"
    assert data.description == "Type text"


@pytest.mark.asyncio
async def test_help_screen_renders_focused_widget_help(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt_bar", PromptBar)
        app.set_focus(prompt.input)

        await app.action_help()
        await pilot.pause()

        assert isinstance(app.screen, HelpScreen)
        assert "Prompt Bar" in app.screen.text_buffer()
```

- [ ] **Step 2: Run failing help tests**

Run:

```bash
uv run pytest tests/app/tui/test_focused_help.py -q
```

Expected result: fail because `app.tui.help` does not exist.

- [ ] **Step 3: Implement help module**

Create `src/app/tui/help.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
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
    BINDINGS = [Binding("escape", "dismiss", "Close Help")]

    def __init__(self, widget: Widget | None) -> None:
        super().__init__()
        self.widget = widget
        self._text = ""

    def compose(self) -> ComposeResult:
        widget = self.widget
        if widget is not None and isinstance(widget, Helpable):
            title = widget.help.title
            description = widget.help.description
        elif widget is not None:
            title = widget.__class__.__name__
            description = "No focused help is available for this widget."
        else:
            title = "DataHarness"
            description = "No widget is currently focused."

        binding_lines: list[str] = []
        if widget is not None:
            for key, bindings in widget._bindings.key_to_bindings.items():
                descriptions = ", ".join(b.description for b in bindings if b.description)
                if descriptions:
                    binding_lines.append(f"{key}: {descriptions}")

        bindings_text = "\n".join(binding_lines) or "No local keybindings."
        self._text = f"{title}\n\n{description}\n\nKEYS\n{bindings_text}"
        with VerticalScroll(id="help_body"):
            yield Static(self._text, id="help_text")

    def text_buffer(self) -> str:
        return self._text
```

- [ ] **Step 4: Wire help action**

Modify `src/app/tui/app.py`:

```python
from app.tui.help import HelpScreen
```

Add binding:

```python
Binding("f1,ctrl+question_mark", "help", "Help", id="help")
```

Add action:

```python
    async def action_help(self) -> None:
        focused = self.focused

        def restore_focus(_) -> None:
            if focused is not None:
                self.set_focus(focused, scroll_visible=False)

        await self.push_screen(HelpScreen(focused), callback=restore_focus)
```

- [ ] **Step 5: Add help metadata to widgets**

Modify `src/app/tui/widgets.py`:

```python
from app.tui.help import HelpData
```

Add class attributes:

```python
class WorkspaceBar(Static):
    help = HelpData(
        title="Workspace Status",
        description="Shows the active workspace, chat, mode, runtime status, and current phase.",
    )
```

```python
class ConversationPane(Static):
    help = HelpData(
        title="Conversation",
        description="Shows user messages, streamed assistant output, and resumed chat history.",
    )
```

```python
class SidebarPane(Static):
    help = HelpData(
        title="Status Sidebar",
        description="Shows command progress, run trace, doctor findings, and failures.",
    )
```

- [ ] **Step 6: Verify help behavior**

Run:

```bash
uv run pytest tests/app/tui/test_focused_help.py tests/app/tui/test_textual_app.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 7: Checkpoint**

Summarize help behavior, changed files, and test output. Do not commit without user permission.

---

### Task 6: TCSS Extraction And Packaging

**Files:**
- Create: `src/app/tui/dataharness.tcss`
- Modify: `src/app/tui/app.py`
- Modify: `scripts/build_app.sh`
- Modify: `tests/packaging/test_build_app_script.py`
- Test: `tests/app/tui/test_tcss_packaging.py`

- [ ] **Step 1: Write failing TCSS tests**

Add `tests/app/tui/test_tcss_packaging.py`:

```python
from pathlib import Path

from app.tui.app import DataHarnessApp


def test_app_uses_dataharness_tcss_file():
    css_path = DataHarnessApp.CSS_PATH

    assert str(css_path).endswith("dataharness.tcss")
    assert Path(css_path).name == "dataharness.tcss"


def test_dataharness_tcss_defines_interaction_classes():
    tcss = Path("src/app/tui/dataharness.tcss").read_text()

    assert ".textual-jump-label" in tcss
    assert ".status-error" in tcss
    assert "HelpScreen" in tcss
    assert "CommandPalette" in tcss
```

Modify `tests/packaging/test_build_app_script.py`:

```python
def test_build_app_bundles_tui_tcss() -> None:
    script = Path("scripts/build_app.sh").read_text()

    assert "src/app/tui/dataharness.tcss:app/tui/dataharness.tcss" in script
```

- [ ] **Step 2: Run failing TCSS tests**

Run:

```bash
uv run pytest tests/app/tui/test_tcss_packaging.py tests/packaging/test_build_app_script.py -q
```

Expected result: fail because `dataharness.tcss` and the build-script data entry do not exist.

- [ ] **Step 3: Create TCSS file**

Create `src/app/tui/dataharness.tcss`:

```css
Screen {
    layout: vertical;
}

.surface {
    border: solid $primary;
    padding: 0 1;
}

.status-running {
    color: $warning;
}

.status-success {
    color: $success;
}

.status-warning {
    color: $warning;
}

.status-error {
    color: $error;
}

.status-disabled {
    color: $text-muted 60%;
}

#workspace_bar {
    height: 1;
    border: none;
    padding: 0;
}

#main {
    height: 1fr;
}

#chat_column {
    width: 1fr;
}

#conversation {
    height: 1fr;
    min-height: 4;
    overflow-y: auto;
    border: none;
    padding: 0 1;
}

#conversation:focus {
    border-left: wide $accent;
    padding-left: 0;
}

#sidebar {
    width: 34;
    min-width: 28;
    overflow-y: auto;
    border-left: solid $primary;
    padding: 0 1;
}

#sidebar:focus {
    border-left: wide $accent;
}

#prompt_bar {
    height: auto;
}

#prompt_status {
    height: 1;
    color: $text-muted;
}

#user_input {
    height: 3;
}

#prompt_hints {
    height: auto;
    max-height: 8;
    color: $text-muted;
    background: $surface;
}

CommandPalette {
    background: black 33%;
}

CommandPalette > Vertical {
    width: 65vw;
    max-height: 65vh;
}

HelpScreen {
    align: center middle;
    background: black 30%;
}

HelpScreen #help_body {
    width: 70%;
    height: 75%;
    background: $background;
    border: wide $primary;
    padding: 1 2;
}

JumpOverlay {
    background: black 25%;
}

.textual-jump-label {
    dock: top;
    color: $text-accent;
    background: $accent-muted;
    text-style: bold;
    padding: 0 1;
    height: 1;
    width: auto;
}

#textual-jump-info {
    dock: bottom;
    height: 1;
    content-align: center middle;
    color: $text-accent;
    background: $accent-muted;
}

#textual-jump-dismiss {
    dock: bottom;
    height: 1;
    content-align: center middle;
    color: $text-muted;
}

Footer {
    dock: bottom;
    height: 1;
}
```

- [ ] **Step 4: Load TCSS from app**

Modify `src/app/tui/app.py`:

```python
class DataHarnessApp(App[None]):
    TITLE = "DataHarness"
    CSS_PATH = Path(__file__).with_name("dataharness.tcss")
```

Remove the inline `CSS = """..."""` block after the TCSS file covers the same selectors.

- [ ] **Step 5: Bundle TCSS in packaging script**

Modify `scripts/build_app.sh` by adding:

```bash
  --add-data "${PROJECT_ROOT}/src/app/tui/dataharness.tcss:app/tui/dataharness.tcss" \
```

Place it next to the existing prompt `--add-data` entries.

- [ ] **Step 6: Verify TCSS and packaging coverage**

Run:

```bash
uv run pytest tests/app/tui/test_tcss_packaging.py tests/packaging/test_build_app_script.py tests/app/tui/test_textual_app.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 7: Checkpoint**

Summarize styling and packaging changes, changed files, and test output. Do not commit without user permission.

---

### Task 7: Integration Verification And Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-05-07-posting-inspired-tui-ux-design.md` only if implementation reveals a spec mismatch.
- Modify: `Lessons.md` only if execution discovers a new project lesson.
- Test: existing TUI, app, packaging, and layer-boundary tests.

- [ ] **Step 1: Run focused TUI suite**

Run:

```bash
uv run pytest tests/app/tui -q
```

Expected result: all TUI tests pass.

- [ ] **Step 2: Run app and packaging tests touched by this work**

Run:

```bash
uv run pytest tests/app tests/packaging/test_build_app_script.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 3: Run layer-boundary check**

Run:

```bash
uv run pytest tests/app/tui/test_layer_boundaries.py -q
```

Expected result: pass, confirming TUI still does not import `harness.orchestrator` directly.

- [ ] **Step 4: Run full suite if focused suites pass**

Run:

```bash
uv run pytest -q
```

Expected result: full suite passes. If it fails outside touched TUI/app/packaging areas, record the failing tests and inspect whether the failure is caused by this work before changing unrelated code.

- [ ] **Step 5: Update Lessons only for new findings**

If execution discovers a reusable project lesson, append a short entry to `Lessons.md` using this format:

```markdown
## <short lesson title>
- <one concrete lesson tied to a command, file, packaging behavior, Textual behavior, or layer rule>
```

Do not delete existing lessons.

- [ ] **Step 6: Final checkpoint**

Report:

- files changed
- behavior added
- verification commands and outcomes
- any unresolved risks
- whether user permission is needed for commit or broader packaging verification

Do not commit without user permission.

---

## Self-Review Notes

Spec coverage:

- Command provider: Task 1.
- Prompt hints and argument candidates: Task 2.
- Status and trace visibility: Task 3.
- Keyboard navigation and jump overlay: Task 4.
- Focused-widget help: Task 5.
- TCSS extraction and packaging: Task 6.
- Layer-boundary and verification coverage: Task 7.

Scope:

- The plan does not rewrite Layer 3 command behavior.
- The plan keeps slash grammar unchanged.
- The plan does not add a full settings system.
- The plan adapts Posting patterns without copying its domain model.
- The plan keeps `AppSession` as the TUI boundary.

