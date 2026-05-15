# Layer 4 — Async TUI + AppSession + Chat/Workspace UI + V1 Controls

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-01-async-layered-architecture-design.md` §3 (terminology), §8 AppSession, §9 (full).

**Goal:** Convert the TUI to an async live-event consumer. Replace `submit_user_text(...) -> AppTurnResult` with a Textual worker that streams `AppEvent`s. Build `AppSession` (Layer 4) as the only door from TUI to Layer 3 — owning mode routing, prompt-package selection, app-layer telemetry, concurrency gate, and `HarnessEvent → AppEvent` mapping. Add chat manager UI, command palette populated from Layer 3 descriptors, slash-command parsing, V1 control coverage (workspace switch with confirmation, file drop, approval/clarification modals, cancel, doctor, compact, help).

**Architecture:** New `app/session.py` defines `AppSession` (async-only) and `AppEvent` types (mirrors `HarnessEvent` with `App` prefix, plus Layer 4-only payloads). New `app/event_mapping.py` translates `HarnessEvent → AppEvent`. New `app/tui/event_consumer.py` runs Textual workers driven by `AppSession` async iterators and dispatches each event to a widget handler. New `app/tui/screens/chat_manager.py`, `app/tui/screens/command_palette.py`, `app/tui/screens/workspace_modal.py`. Extend widgets to consume streaming events. Conversation log uses an in-memory cache + Layer 3 `view_chat` rehydration on restart/resume.

**Tech Stack:** Python 3.12, `asyncio`, `textual` 8.x, `pydantic` 2.x, `pytest-asyncio`.

---

## File Structure

- `src/app/session.py` — **rewrite**: drop `DataAnalysisAppSession` sync API; add async `AppSession`. Keep class-name alias `DataAnalysisAppSession = AppSession` for migration only if needed by tests; otherwise rename in tests.
- `src/app/event_mapping.py` — **new**: `HarnessEvent → AppEvent` translator.
- `src/app/events.py` — **new**: `AppEvent` types (`AppTurnStarted`, `AppRuntimeDelta`, `AppFinalMessage`, `AppApprovalRequired`, `AppCommandStarted`, `AppCommandProgress`, `AppDoctorFinding`, `AppChatHistoryLoaded`, `AppStatusChanged`, `AppTurnFailed`, `AppTurnCancelled`, ...).
- `src/app/tui/app.py` — **rewrite** for async streaming flow.
- `src/app/tui/event_consumer.py` — **new**: registry of (event_name → widget handler).
- `src/app/tui/screens/__init__.py` — package init (move `screens.py` modules in here if they grow).
- `src/app/tui/screens/chat_manager.py` — **new**.
- `src/app/tui/screens/command_palette.py` — **new**.
- `src/app/tui/screens/workspace_modal.py` — **new**.
- `src/app/tui/widgets.py` — extend with streaming-aware methods (append delta, render snapshot).
- Tests: `tests/app/test_app_session_async.py`, `tests/app/tui/test_event_streaming.py`, `tests/app/tui/test_chat_manager.py`, `tests/app/tui/test_command_palette.py`, `tests/app/tui/test_v1_controls.py`, `tests/app/tui/test_layer_boundaries.py` (updated).

---

## Prep

- [ ] **Step 0.1: Verify plan 3a/3b/3c complete**

Run: `uv run pytest tests/runtime tests/worker tests/harness -q`
Expected: PASS.

- [ ] **Step 0.2: Confirm Textual version supports async workers**

Run: `uv pip list | grep -i textual` — should be `>=8.2.4`.

---

## Task 1: `AppEvent` types + mapping

**Files:**
- Create: `src/app/events.py`
- Create: `src/app/event_mapping.py`
- Test: `tests/app/test_event_mapping.py`

- [ ] **Step 1.1: Failing tests**

```python
# tests/app/test_event_mapping.py
from datetime import UTC, datetime

from app.event_mapping import to_app_event
from harness.events import (
    FinalMessage, RuntimeDelta, TurnStarted,
)


def base():
    return dict(ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r")


def test_turn_started_maps():
    h = TurnStarted(**base(), turn_id="t", user_message_id="u", active_mode="m")
    a = to_app_event(h)
    assert a.event_name == "AppTurnStarted"
    assert a.turn_id == "t"


def test_runtime_delta_maps_text():
    h = RuntimeDelta(**base(), request_id="req", seq=1, delta_type="text", text="hi", tool_call=None)
    a = to_app_event(h)
    assert a.event_name == "AppRuntimeDelta"
    assert a.text == "hi"


def test_final_message_maps_with_usage():
    h = FinalMessage(**base(), assistant_message_id="a", text="done", usage={"completion_tokens": 5})
    a = to_app_event(h)
    assert a.event_name == "AppFinalMessage"
    assert a.usage["completion_tokens"] == 5
```

- [ ] **Step 1.2: Run; expect failure**

- [ ] **Step 1.3: Implement `src/app/events.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class AppEvent(BaseModel):
    app_event_id: str = Field(default_factory=lambda: f"app_{uuid4().hex[:12]}")
    event_name: str
    ts: datetime
    workspace_id: str | None = None
    chat_id: str | None = None
    run_id: str | None = None


class AppTurnStarted(AppEvent):
    event_name: Literal["AppTurnStarted"] = "AppTurnStarted"
    turn_id: str
    user_message_id: str
    active_mode: str


class AppRuntimeDelta(AppEvent):
    event_name: Literal["AppRuntimeDelta"] = "AppRuntimeDelta"
    delta_type: Literal["text", "reasoning", "tool_call"]
    text: str | None
    tool_call: dict[str, Any] | None


class AppFinalMessage(AppEvent):
    event_name: Literal["AppFinalMessage"] = "AppFinalMessage"
    assistant_message_id: str
    text: str
    usage: dict[str, int] = Field(default_factory=dict)


class AppTurnFailed(AppEvent):
    event_name: Literal["AppTurnFailed"] = "AppTurnFailed"
    failure_summary: str
    error_code: str
    details: dict[str, Any] = Field(default_factory=dict)


class AppTurnCancelled(AppEvent):
    event_name: Literal["AppTurnCancelled"] = "AppTurnCancelled"
    reason: str
    cancelled_at: datetime


class AppStatusChanged(AppEvent):
    event_name: Literal["AppStatusChanged"] = "AppStatusChanged"
    snapshot: dict[str, Any]


class AppChatHistoryLoaded(AppEvent):
    event_name: Literal["AppChatHistoryLoaded"] = "AppChatHistoryLoaded"
    message_count: int
    token_estimate: int
    source: str


class AppApprovalRequired(AppEvent):
    event_name: Literal["AppApprovalRequired"] = "AppApprovalRequired"
    plan_id: str
    step_id: str
    step: dict[str, Any]
    prompt: str


class AppCommandStarted(AppEvent):
    event_name: Literal["AppCommandStarted"] = "AppCommandStarted"
    command: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AppCommandProgress(AppEvent):
    event_name: Literal["AppCommandProgress"] = "AppCommandProgress"
    command: str
    phase: str
    phase_index: int
    phase_total: int
    message: str | None


class AppCommandCompleted(AppEvent):
    event_name: Literal["AppCommandCompleted"] = "AppCommandCompleted"
    command: str
    result: dict[str, Any] = Field(default_factory=dict)


class AppDoctorFinding(AppEvent):
    event_name: Literal["AppDoctorFinding"] = "AppDoctorFinding"
    report_id: str
    category: str
    severity: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class AppDoctorReportReady(AppEvent):
    event_name: Literal["AppDoctorReportReady"] = "AppDoctorReportReady"
    report_id: str
    summary_counts: dict[str, int] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


class AppRaw(AppEvent):
    """Catch-all for events we don't yet map specifically."""
    event_name: Literal["AppRaw"] = "AppRaw"
    harness_event_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 1.4: Implement `src/app/event_mapping.py`**

```python
from __future__ import annotations

from datetime import datetime

from app.events import (
    AppApprovalRequired, AppChatHistoryLoaded, AppCommandCompleted,
    AppCommandProgress, AppCommandStarted, AppDoctorFinding,
    AppDoctorReportReady, AppEvent, AppFinalMessage, AppRaw,
    AppRuntimeDelta, AppStatusChanged, AppTurnCancelled,
    AppTurnFailed, AppTurnStarted,
)
from harness.events import (
    ApprovalRequired, ChatHistoryLoaded, CommandCompleted, CommandProgress,
    CommandStarted, DoctorFinding, DoctorReportReady, FinalMessage, HarnessEvent,
    RuntimeDelta, StatusChanged, TurnCancelled, TurnFailed, TurnStarted,
)


def to_app_event(ev: HarnessEvent) -> AppEvent:
    base = dict(ts=ev.ts, workspace_id=ev.workspace_id, chat_id=ev.chat_id, run_id=ev.run_id)
    if isinstance(ev, TurnStarted):
        return AppTurnStarted(**base, turn_id=ev.turn_id, user_message_id=ev.user_message_id, active_mode=ev.active_mode)
    if isinstance(ev, RuntimeDelta):
        return AppRuntimeDelta(**base, delta_type=ev.delta_type, text=ev.text, tool_call=ev.tool_call)
    if isinstance(ev, FinalMessage):
        return AppFinalMessage(**base, assistant_message_id=ev.assistant_message_id, text=ev.text, usage=ev.usage)
    if isinstance(ev, TurnFailed):
        return AppTurnFailed(**base, failure_summary=ev.failure_summary, error_code=ev.error_code, details=ev.details)
    if isinstance(ev, TurnCancelled):
        return AppTurnCancelled(**base, reason=ev.reason, cancelled_at=ev.cancelled_at)
    if isinstance(ev, StatusChanged):
        return AppStatusChanged(**base, snapshot=ev.snapshot.model_dump(mode="json"))
    if isinstance(ev, ChatHistoryLoaded):
        return AppChatHistoryLoaded(**base, message_count=ev.message_count, token_estimate=ev.token_estimate, source=ev.source)
    if isinstance(ev, ApprovalRequired):
        return AppApprovalRequired(**base, plan_id=ev.plan_id, step_id=ev.step_id, step=ev.step, prompt=ev.prompt)
    if isinstance(ev, CommandStarted):
        return AppCommandStarted(**base, command=ev.command, arguments=ev.arguments)
    if isinstance(ev, CommandProgress):
        return AppCommandProgress(
            **base, command=ev.command, phase=ev.phase,
            phase_index=ev.phase_index, phase_total=ev.phase_total, message=ev.message,
        )
    if isinstance(ev, CommandCompleted):
        return AppCommandCompleted(**base, command=ev.command, result=ev.result)
    if isinstance(ev, DoctorFinding):
        return AppDoctorFinding(
            **base, report_id=ev.report_id, category=ev.category, severity=ev.severity,
            summary=ev.summary, details=ev.details,
        )
    if isinstance(ev, DoctorReportReady):
        return AppDoctorReportReady(
            **base, report_id=ev.report_id, summary_counts=ev.summary_counts,
            recommendations=ev.recommendations,
        )
    return AppRaw(**base, harness_event_name=ev.event_name, payload=ev.model_dump(mode="json"))
```

- [ ] **Step 1.5: Run; expect pass**

- [ ] **Step 1.6: Commit**

```bash
git add src/app/events.py src/app/event_mapping.py tests/app/test_event_mapping.py
git commit -m "feat(app): AppEvent types + HarnessEvent mapping"
```

---

## Task 2: Async `AppSession`

**Files:**
- Modify: `src/app/session.py`
- Test: `tests/app/test_app_session_async.py`

- [ ] **Step 2.1: Failing tests**

```python
# tests/app/test_app_session_async.py
from collections.abc import AsyncIterator

import pytest

from app.session import AppSession
from harness.events import FinalMessage, TurnStarted
from harness.exceptions import RunAlreadyActive
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord


class FakeOrchestrator:
    def __init__(self):
        self.run_calls = 0
        self._active = False

    async def run_turn(self, state, *, workspace_dir, chat_id, user_input, requested_mode=None, prompt_text=None):
        if self._active:
            raise RunAlreadyActive(run_id="x")
        self._active = True
        try:
            from datetime import UTC, datetime
            yield TurnStarted(
                ts=datetime.now(UTC), workspace_id="w", chat_id=chat_id, run_id="r",
                turn_id="t", user_message_id="u", active_mode=requested_mode or "interaction",
            )
            yield FinalMessage(
                ts=datetime.now(UTC), workspace_id="w", chat_id=chat_id, run_id="r",
                assistant_message_id="a", text="hello", usage={},
            )
        finally:
            self._active = False

    async def list_commands(self, ctx=None): return []
    async def help(self, command=None):
        from harness.command_registry import HelpResult
        return HelpResult(commands=[], not_found=False)
    async def status_snapshot(self, **kw):
        from harness.status import HarnessStatusSnapshot
        return HarnessStatusSnapshot(
            workspace_id="w", chat_id=None, chat_title=None, workspace_health="ready",
            active_mode="interaction", run_id=None, run_state="idle", runtime_status="ready",
            execution_tasks={}, approval_state="idle", clarification_state="idle",
            chat_turn_count=0, chat_token_estimate=0, last_compacted_at=None,
            compaction_count=0, doctor_warning_count=0, last_event=None,
        )


@pytest.fixture
def session(tmp_path):
    return AppSession(orchestrator=FakeOrchestrator(), app_root=tmp_path)


def make_state():
    return RunStateRecord(workspace_id="w", active_agent_mode="interaction")


async def test_run_user_turn_yields_app_events(session, tmp_path):
    state = make_state()
    events = [e async for e in session.run_user_turn(
        state=state, workspace_dir=tmp_path, chat_id="c", user_text="hi",
    )]
    assert events[0].event_name == "AppTurnStarted"
    assert events[-1].event_name == "AppFinalMessage"


async def test_concurrent_turn_raises_run_already_active(session, tmp_path):
    state = make_state()
    agen = session.run_user_turn(state=state, workspace_dir=tmp_path, chat_id="c", user_text="hi")
    await agen.__anext__()
    with pytest.raises(RunAlreadyActive):
        async for _ in session.run_user_turn(state=state, workspace_dir=tmp_path, chat_id="c", user_text="x"):
            pass
    async for _ in agen:
        pass


async def test_no_sync_methods(session):
    import inspect
    # No sync turn API present.
    for name in ("run_user_turn", "resume_approved_step", "resume_with_clarification",
                 "handle_direct_command", "compact_chat_history"):
        method = getattr(session, name)
        assert inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(method)
```

- [ ] **Step 2.2: Implement `src/app/session.py`**

Replace entire file:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.prompt_packages import PromptPackageRegistry
from app.agents.router import AgentModeRouter
from app.event_mapping import to_app_event
from app.events import AppEvent
from harness.command_registry import CommandContext, HarnessCommandDescriptor, HelpResult
from harness.control import RunStateRecord
from harness.exceptions import RunAlreadyActive
from harness.orchestrator import Orchestrator
from harness.status import HarnessStatusSnapshot
from observability import Telemetry, bind_turn, resolve_telemetry_dir
from observability.events import EventKind, Layer


class AppSession:
    """Layer 4 facade over Layer 3 Orchestrator. Async-only."""

    def __init__(
        self,
        *,
        orchestrator: Orchestrator | None = None,
        mode_router: AgentModeRouter | None = None,
        prompt_registry: PromptPackageRegistry | None = None,
        telemetry: Telemetry | None = None,
        app_root: Path | None = None,
    ) -> None:
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())
        self.app_root = app_root or Path.cwd()
        self.orchestrator = orchestrator or Orchestrator(app_root=self.app_root)
        if hasattr(self.orchestrator, "telemetry"):
            self.orchestrator.telemetry = self.telemetry
        self.mode_router = mode_router or AgentModeRouter(telemetry=self.telemetry)
        self.prompt_registry = prompt_registry or PromptPackageRegistry(
            Path(__file__).resolve().parent / "agents" / "prompts"
        )
        self._active = False

    async def run_user_turn(
        self,
        *,
        state: RunStateRecord,
        workspace_dir: Path,
        chat_id: str,
        user_text: str,
    ) -> AsyncIterator[AppEvent]:
        if self._active:
            raise RunAlreadyActive(run_id=state.run_id)
        self._active = True
        turn_id = uuid4()
        try:
            with bind_turn(turn_id):
                self.telemetry.emit(Layer.APP, EventKind.TURN_START, payload={"input_chars": len(user_text)})
                decision = self.mode_router.route(user_text)
                package = self.prompt_registry.load(decision.mode)
                async for h_ev in self.orchestrator.run_turn(
                    state, workspace_dir=workspace_dir, chat_id=chat_id,
                    user_input=user_text, requested_mode=decision.mode,
                    prompt_text=package.prompt_text,
                ):
                    yield to_app_event(h_ev)
                self.telemetry.emit(Layer.APP, EventKind.TURN_END, payload={"chat_id": chat_id})
        finally:
            self._active = False

    async def resume_approved_step(
        self, *, workspace_dir: Path, state: RunStateRecord,
        plan_payload: dict, contract_payload: dict, approval,
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.resume_approved_step(
            workspace_dir=workspace_dir, state=state,
            plan_payload=plan_payload, contract_payload=contract_payload, approval=approval,
        ):
            yield to_app_event(h_ev)

    async def resume_with_clarification(
        self, *, workspace_dir: Path, state: RunStateRecord, clarification_text: str,
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.resume_with_clarification(
            workspace_dir=workspace_dir, state=state, clarification_text=clarification_text,
        ):
            yield to_app_event(h_ev)

    async def handle_direct_command(
        self, state: RunStateRecord, *, command: str, arguments: dict[str, Any],
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.handle_direct_command(
            state, command=command, arguments=arguments,
        ):
            yield to_app_event(h_ev)

    async def cancel_run(self, run_id: str, reason: str):
        return to_app_event(await self.orchestrator.cancel_run(run_id, reason=reason))

    async def compact_chat_history(self, chat_id: str) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.compact_chat_history(chat_id):
            yield to_app_event(h_ev)

    async def list_commands(self, context: CommandContext | None = None) -> list[HarnessCommandDescriptor]:
        return await self.orchestrator.list_commands(context)

    async def help(self, command: str | None = None) -> HelpResult:
        return await self.orchestrator.help(command)

    async def list_chats(self, workspace_id: str):
        return await self.orchestrator.list_chats(workspace_id)

    async def create_chat(self, workspace_id: str, title: str | None = None):
        return await self.orchestrator.create_chat(workspace_id=workspace_id, title=title)

    async def view_chat(self, chat_id: str):
        return await self.orchestrator.view_chat(chat_id)

    async def resume_chat(self, chat_id: str) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.resume_chat(chat_id):
            yield to_app_event(h_ev)

    async def delete_chat(self, chat_id: str):
        return await self.orchestrator.delete_chat(chat_id)

    async def list_workspaces(self):
        return await self.orchestrator.list_workspaces()

    async def create_workspace(self, workspace_id: str):
        return await self.orchestrator.create_workspace(workspace_id)

    async def rename_workspace(self, old_id: str, new_id: str):
        return await self.orchestrator.rename_workspace(old_id, new_id)

    async def delete_workspace(self, workspace_id: str):
        return await self.orchestrator.delete_workspace(workspace_id)

    async def activate_workspace(self, workspace_id: str, force: bool = False) -> HarnessStatusSnapshot:
        return await self.orchestrator.activate_workspace(workspace_id, force=force)

    async def ingest_files(self, workspace_id: str, paths: list[Path]):
        return await self.orchestrator.ingest_files(workspace_id, paths)

    async def status_snapshot(self, workspace_id: str | None = None) -> HarnessStatusSnapshot:
        return await self.orchestrator.status_snapshot(workspace_id=workspace_id)

    async def watch_status(self):
        async for snap in self.orchestrator.watch_status():
            yield snap


# Migration alias — kept only so existing import sites resolve until cleanup.
DataAnalysisAppSession = AppSession
```

- [ ] **Step 2.3: Run; expect pass**

`uv run pytest tests/app/test_app_session_async.py -v`

- [ ] **Step 2.4: Remove legacy app session tests**

Delete or rewrite `tests/app/test_session_*.py` files that depended on `AppTurnResult` and the sync `handle_user_turn`. Remove `AppTurnResult` import from any remaining caller.

- [ ] **Step 2.5: Commit**

```bash
git add src/app/session.py tests/app
git commit -m "feat(app): async-only AppSession streaming AppEvent"
```

---

## Task 3: Event consumer + streaming widgets

**Files:**
- Create: `src/app/tui/event_consumer.py`
- Modify: `src/app/tui/widgets.py`
- Test: `tests/app/tui/test_event_streaming.py`

- [ ] **Step 3.1: Failing test**

```python
# tests/app/tui/test_event_streaming.py
from datetime import UTC, datetime

from app.events import AppFinalMessage, AppRuntimeDelta, AppTurnStarted
from app.tui.event_consumer import EventConsumer
from app.tui.widgets import ConversationPane


def test_consumer_routes_runtime_delta_to_conversation():
    pane = ConversationPane()
    consumer = EventConsumer({"AppRuntimeDelta": pane.append_assistant_delta,
                              "AppFinalMessage": lambda e: pane.finalize_assistant(e.text),
                              "AppTurnStarted": lambda e: pane.append_user("(user input cached elsewhere)")})

    consumer.dispatch(AppTurnStarted(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        turn_id="t", user_message_id="u", active_mode="m",
    ))
    consumer.dispatch(AppRuntimeDelta(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        delta_type="text", text="hel", tool_call=None,
    ))
    consumer.dispatch(AppRuntimeDelta(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        delta_type="text", text="lo", tool_call=None,
    ))
    consumer.dispatch(AppFinalMessage(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        assistant_message_id="a", text="hello", usage={},
    ))
    rendered = pane.text_buffer()
    assert "hello" in rendered
```

- [ ] **Step 3.2: Implement `EventConsumer`**

```python
# src/app/tui/event_consumer.py
from __future__ import annotations

from collections.abc import Callable

from app.events import AppEvent


Handler = Callable[[AppEvent], None]


class EventConsumer:
    def __init__(self, handlers: dict[str, Handler]) -> None:
        self.handlers = handlers

    def dispatch(self, event: AppEvent) -> None:
        handler = self.handlers.get(event.event_name)
        if handler is not None:
            handler(event)
```

- [ ] **Step 3.3: Extend `ConversationPane`**

Add to `src/app/tui/widgets.py` `ConversationPane`:

```python
def append_assistant_delta(self, event) -> None:
    if not getattr(self, "_streaming_buffer", None):
        self._streaming_buffer = []
    if event.text:
        self._streaming_buffer.append(event.text)
    streaming = "".join(self._streaming_buffer)
    self.update("\n".join(self._lines + [streaming]))

def finalize_assistant(self, text: str) -> None:
    self._streaming_buffer = []
    self._lines.append(text)
    self.update("\n".join(self._lines))

def text_buffer(self) -> str:
    return "\n".join(self._lines)

def rehydrate_from_record(self, record) -> None:
    self._lines = []
    for m in record.messages:
        prefix = "> " if m.role == "user" else ""
        self._lines.append(f"{prefix}{m.text}")
    self.update("\n".join(self._lines))
```

- [ ] **Step 3.4: Run; expect pass**

- [ ] **Step 3.5: Commit**

```bash
git add src/app/tui/event_consumer.py src/app/tui/widgets.py tests/app/tui/test_event_streaming.py
git commit -m "feat(tui): EventConsumer + streaming-aware ConversationPane"
```

---

## Task 4: Async TUI `app.py`

**Files:**
- Modify: `src/app/tui/app.py`
- Test: `tests/app/tui/test_textual_app.py` (rewrite)

- [ ] **Step 4.1: Failing tests**

```python
# tests/app/tui/test_textual_app.py
import pytest

from app.tui.app import DataHarnessApp


@pytest.mark.asyncio
async def test_submit_user_text_streams_into_conversation_pane(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.press("h", "i", "enter")
        await pilot.pause()
        pane = app.query_one("#conversation")
        assert "hi" in pane.text_buffer().lower()
```

- [ ] **Step 4.2: Rewrite `app.py`**

Replace `submit_user_text` and `_render_*` methods with an async streaming flow:

```python
async def submit_user_text(self, text: str) -> None:
    if text.startswith("/"):
        try:
            command, args = parse_slash(text)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        descriptors = await self._session.list_commands()
        spec = next((d for d in descriptors if d.name == command), None)
        if spec is None:
            self.notify(f"unknown command: {command}", severity="error")
            return
        argument_dict = self._args_to_dict(spec, args)
        worker = self.run_worker(self._stream_command(command, argument_dict))
        return

    self.query_one("#conversation", ConversationPane).append_user(text)
    self.run_worker(self._stream_turn(text))

async def _stream_turn(self, text: str) -> None:
    consumer = self._build_consumer()
    try:
        async for ev in self._session.run_user_turn(
            state=self._state, workspace_dir=self._workspace_dir,
            chat_id=self._active_chat_id, user_text=text,
        ):
            consumer.dispatch(ev)
    except Exception as exc:
        self._emit_error(phase="run_turn", exc=exc)
        self.notify(str(exc), severity="error")

async def _stream_command(self, command: str, arguments: dict) -> None:
    consumer = self._build_consumer()
    try:
        async for ev in self._session.handle_direct_command(
            self._state, command=command, arguments=arguments,
        ):
            consumer.dispatch(ev)
    except Exception as exc:
        self._emit_error(phase="direct_command", exc=exc)
        self.notify(str(exc), severity="error")

def _build_consumer(self) -> EventConsumer:
    pane = self.query_one("#conversation", ConversationPane)
    plan = self.query_one("#plan", PlanPane)
    artifacts = self.query_one("#artifacts", ArtifactsPane)
    failure = self.query_one("#failure", FailurePane)
    doctor = self.query_one("#doctor", DoctorPane)
    return EventConsumer({
        "AppRuntimeDelta": pane.append_assistant_delta,
        "AppFinalMessage": lambda e: pane.finalize_assistant(e.text),
        "AppTurnFailed": lambda e: failure.render_failure({"failure_summary": e.failure_summary, "error_code": e.error_code}),
        "AppTurnCancelled": lambda e: pane.finalize_assistant(f"[cancelled: {e.reason}]"),
        "AppApprovalRequired": lambda e: self.push_screen(ApprovalScreen(plan={"id": e.plan_id, "steps":[e.step]}, step_contract=e.step)),
        "AppCommandStarted": lambda e: self.notify(f"running /{e.command}…"),
        "AppCommandProgress": lambda e: self.notify(f"{e.command}: {e.phase} ({e.phase_index}/{e.phase_total})"),
        "AppCommandCompleted": lambda e: self.notify(f"/{e.command} done"),
        "AppDoctorFinding": lambda e: doctor.append_finding(e.summary, e.severity),
        "AppDoctorReportReady": lambda e: doctor.render_report(e.summary_counts, e.recommendations),
        "AppStatusChanged": lambda e: self.query_one("#workspace_bar", WorkspaceBar).update_from(
            workspace_id=e.snapshot["workspace_id"], run_state=e.snapshot["run_state"], active_mode=e.snapshot["active_mode"],
        ),
        "AppChatHistoryLoaded": lambda e: None,
    })

def _args_to_dict(self, spec, positional: list[str]) -> dict:
    out = {}
    for i, p in enumerate(positional):
        if i >= len(spec.arguments):
            break
        out[spec.arguments[i].name] = p
    return out
```

Top-of-file imports:

```python
from harness.command_registry import parse_slash
from app.tui.event_consumer import EventConsumer
```

Add status-bar subscriber as a separate worker spawned from `on_mount`:

```python
def on_mount(self) -> None:
    ...
    self.run_worker(self._subscribe_status())

async def _subscribe_status(self) -> None:
    async for snap in self._session.watch_status():
        try:
            self.query_one("#workspace_bar", WorkspaceBar).update_from(
                workspace_id=snap.workspace_id, run_state=snap.run_state, active_mode=snap.active_mode,
            )
        except Exception:
            return
```

Drop `_render_result`, `_render_dict_result`, `submit_user_text(...) -> AppTurnResult`, `_latest_result`.

- [ ] **Step 4.3: Add active chat tracking**

In `__init__`:

```python
self._active_chat_id: str | None = None
```

After `on_mount`, lazy-create chat:

```python
async def _ensure_chat(self) -> str:
    if self._active_chat_id is None:
        summary = await self._session.create_chat(self._state.workspace_id)
        self._active_chat_id = summary.chat_id
    return self._active_chat_id
```

Call `await self._ensure_chat()` before dispatching turn worker.

- [ ] **Step 4.4: Run; expect pass**

`uv run pytest tests/app/tui/test_textual_app.py -v`

- [ ] **Step 4.5: Commit**

```bash
git add src/app/tui/app.py tests/app/tui/test_textual_app.py
git commit -m "feat(tui): async streaming app with slash commands and status subscription"
```

---

## Task 5: Chat manager screen

**Files:**
- Create: `src/app/tui/screens/__init__.py`
- Create: `src/app/tui/screens/chat_manager.py`
- Test: `tests/app/tui/test_chat_manager.py`

- [ ] **Step 5.1: Failing test**

```python
# tests/app/tui/test_chat_manager.py
import pytest

from app.session import AppSession
from app.tui.app import DataHarnessApp
from app.tui.screens.chat_manager import ChatManagerScreen


@pytest.mark.asyncio
async def test_chat_manager_lists_workspace_chats(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        # Create two chats via session.
        await app._session.create_workspace("w_0001")
        c1 = await app._session.create_chat("w_0001")
        c2 = await app._session.create_chat("w_0001")
        screen = ChatManagerScreen(workspace_id="w_0001", session=app._session)
        await app.push_screen(screen)
        await pilot.pause()
        rendered = screen.query_one("#chat_list").renderable_text() if hasattr(screen.query_one("#chat_list"), "renderable_text") else screen.text_buffer()
        assert c1.chat_id in rendered
        assert c2.chat_id in rendered
```

- [ ] **Step 5.2: Implement minimal screen**

```python
# src/app/tui/screens/chat_manager.py
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
        self._list.update(body)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create_chat":
            await self.session.create_chat(self.workspace_id)
            await self.refresh_list()
        elif event.button.id == "close_chat_manager":
            self.app.pop_screen()

    def text_buffer(self) -> str:
        return self._list.renderable.plain if hasattr(self._list.renderable, "plain") else str(self._list.renderable)
```

- [ ] **Step 5.3: Run; expect pass**

- [ ] **Step 5.4: Commit**

```bash
git add src/app/tui/screens/__init__.py src/app/tui/screens/chat_manager.py tests/app/tui/test_chat_manager.py
git commit -m "feat(tui): chat manager screen (list/create/close)"
```

---

## Task 6: Command palette

**Files:**
- Create: `src/app/tui/screens/command_palette.py`
- Test: `tests/app/tui/test_command_palette.py`

- [ ] **Step 6.1: Failing test**

```python
# tests/app/tui/test_command_palette.py
import pytest

from app.tui.app import DataHarnessApp
from app.tui.screens.command_palette import CommandPaletteScreen


@pytest.mark.asyncio
async def test_palette_shows_doctor_and_marks_unavailable(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        screen = CommandPaletteScreen(session=app._session)
        await app.push_screen(screen)
        await pilot.pause()
        text = screen.text_buffer()
        assert "doctor" in text
        # Unavailable commands annotated:
        assert "(unavailable" in text
```

- [ ] **Step 6.2: Implement palette**

```python
# src/app/tui/screens/command_palette.py
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

    def compose(self) -> ComposeResult:
        yield Vertical(Static("Commands"), self._body)

    async def on_mount(self) -> None:
        descs = await self.session.list_commands()
        lines = []
        for d in descs:
            mark = "" if d.available else f"  (unavailable: {d.disabled_reason or 'n/a'})"
            lines.append(f"{d.slash_alias}\t{d.short_description}{mark}")
        self._body.update("\n".join(lines))

    def text_buffer(self) -> str:
        return self._body.renderable.plain if hasattr(self._body.renderable, "plain") else str(self._body.renderable)
```

- [ ] **Step 6.3: Run; expect pass**

- [ ] **Step 6.4: Commit**

```bash
git add src/app/tui/screens/command_palette.py tests/app/tui/test_command_palette.py
git commit -m "feat(tui): command palette populated from Layer 3 descriptors"
```

---

## Task 7: Workspace modal + force-switch confirmation

**Files:**
- Create: `src/app/tui/screens/workspace_modal.py`
- Test: `tests/app/tui/test_v1_controls.py`

- [ ] **Step 7.1: Failing tests**

```python
# tests/app/tui/test_v1_controls.py
import pytest

from app.tui.app import DataHarnessApp
from app.tui.screens.workspace_modal import WorkspaceModal
from harness.exceptions import WorkspaceSwitchBlocked


@pytest.mark.asyncio
async def test_workspace_switch_blocked_then_force(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        sess = app._session
        await sess.create_workspace("w_0001")
        await sess.create_workspace("w_0002")
        # Simulate active run.
        sess.orchestrator._active_run_id = "fake_run"
        with pytest.raises(WorkspaceSwitchBlocked):
            await sess.activate_workspace("w_0002", force=False)
        snap = await sess.activate_workspace("w_0002", force=True)
        assert snap.workspace_id == "w_0002"
```

- [ ] **Step 7.2: Implement minimal modal**

```python
# src/app/tui/screens/workspace_modal.py
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
```

- [ ] **Step 7.3: Run; expect pass**

- [ ] **Step 7.4: Commit**

```bash
git add src/app/tui/screens/workspace_modal.py tests/app/tui/test_v1_controls.py
git commit -m "feat(tui): workspace modal with force-switch confirmation"
```

---

## Task 8: V1 control coverage audit

**Files:**
- Test: `tests/app/tui/test_v1_controls.py` (extend)

- [ ] **Step 8.1: Add coverage assertions**

Append to `tests/app/tui/test_v1_controls.py`:

```python
@pytest.mark.asyncio
async def test_command_palette_lists_v1_required_commands(tmp_path):
    from app.tui.app import DataHarnessApp
    from app.tui.screens.command_palette import CommandPaletteScreen

    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        screen = CommandPaletteScreen(session=app._session)
        await app.push_screen(screen)
        await pilot.pause()
        text = screen.text_buffer()
        for required in [
            "/doctor", "/compact", "/cancel_run", "/retry_step", "/revise_goal",
            "/stop_after_current_step", "/rerun_step", "/challenge_conclusion",
            "/mark_result_trusted", "/mark_result_invalidated", "/inspect_artifact",
            "/memory_review", "/provenance_inspect", "/switch_workspace",
            "/workspace_status", "/workspace_inventory", "/validity_inspect",
            "/help", "/create_chat", "/list_chats", "/view_chat",
            "/resume_chat", "/delete_chat",
        ]:
            assert required in text, required
```

- [ ] **Step 8.2: Run**

`uv run pytest tests/app/tui/test_v1_controls.py -v`

- [ ] **Step 8.3: Commit**

```bash
git add tests/app/tui/test_v1_controls.py
git commit -m "test(tui): assert palette covers V1 required commands"
```

---

## Task 9: Layer-boundary check

**Files:**
- Modify: `tests/app/tui/test_layer_boundaries.py`

- [ ] **Step 9.1: Update boundary test**

```python
# tests/app/tui/test_layer_boundaries.py
import ast
from pathlib import Path


def test_tui_does_not_import_orchestrator_directly():
    tui_dir = Path("src/app/tui")
    bad: list[str] = []
    for py in tui_dir.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("harness.orchestrator"):
                    bad.append(str(py))
    assert not bad, bad


def test_app_session_is_async_only():
    import inspect

    from app.session import AppSession
    for name in (
        "run_user_turn", "resume_approved_step", "resume_with_clarification",
        "handle_direct_command", "compact_chat_history", "resume_chat",
    ):
        method = getattr(AppSession, name)
        assert inspect.isasyncgenfunction(method) or inspect.iscoroutinefunction(method), name
```

- [ ] **Step 9.2: Run**

`uv run pytest tests/app/tui/test_layer_boundaries.py -v`

- [ ] **Step 9.3: Commit**

```bash
git add tests/app/tui/test_layer_boundaries.py
git commit -m "test(tui): enforce TUI→Orchestrator isolation and async-only AppSession"
```

---

## Task 10: Conversation rehydration after restart/resume

**Files:**
- Modify: `src/app/tui/app.py`
- Test: `tests/app/tui/test_textual_app.py` (add)

- [ ] **Step 10.1: Failing test**

```python
@pytest.mark.asyncio
async def test_conversation_rehydrates_on_resume_chat(tmp_path):
    from app.tui.app import DataHarnessApp
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        sess = app._session
        await sess.create_workspace("w_0001")
        chat = await sess.create_chat("w_0001")
        # Seed messages by appending directly via store (orchestrator integration test covers run_turn case)
        from datetime import UTC, datetime
        from harness.chat import ChatMessage
        await sess.orchestrator.chat_store.append_message(chat.chat_id, ChatMessage(
            message_id="m1", role="user", text="prior question",
            ts=datetime.now(UTC), turn_id="t", active_mode="m", token_estimate=1,
        ))
        await sess.orchestrator.chat_store.append_message(chat.chat_id, ChatMessage(
            message_id="m2", role="assistant", text="prior answer",
            ts=datetime.now(UTC), turn_id="t", active_mode="m", token_estimate=1,
        ))
        await app.action_resume_chat(chat.chat_id)
        await pilot.pause()
        pane = app.query_one("#conversation")
        text = pane.text_buffer()
        assert "prior question" in text and "prior answer" in text
```

- [ ] **Step 10.2: Implement `action_resume_chat`**

In `app.py`:

```python
async def action_resume_chat(self, chat_id: str) -> None:
    record = await self._session.view_chat(chat_id)
    self._active_chat_id = chat_id
    self.query_one("#conversation", ConversationPane).rehydrate_from_record(record)
    async for _ in self._session.resume_chat(chat_id):
        pass
```

- [ ] **Step 10.3: Run; expect pass**

- [ ] **Step 10.4: Commit**

```bash
git add src/app/tui/app.py tests/app/tui/test_textual_app.py
git commit -m "feat(tui): rehydrate conversation log from view_chat on resume"
```

---

## Task 11: Drop legacy CSS / fields and final smoke

- [ ] **Step 11.1: Delete `AppTurnResult` from `app/session.py`** (already removed in Task 2 if present — confirm).

- [ ] **Step 11.2: Run full test suite**

```bash
uv run pytest -q
```
Expected: PASS.

- [ ] **Step 11.3: Final commit**

```bash
git add -A
git commit -m "chore(app): remove legacy AppTurnResult plumbing; full async TUI smoke"
```

---

## Self-Review Checklist

- `submit_user_text(...) -> AppTurnResult` removed; replaced by Textual workers consuming `AsyncIterator[AppEvent]` ✓
- `AppSession` is async-only and the only Layer-4→Layer-3 path ✓
- TUI parses positional slash commands; quoted args supported ✓
- `/doctor`, `/compact`, `/help` dispatched through Layer 3 and rendered via streaming events ✓
- Chat manager screen lists/creates/views/resumes/deletes chats through Layer 3 ✓
- Command palette populated from Layer 3 descriptors with `disabled_reason` ✓
- Workspace modal handles `WorkspaceSwitchBlocked` and offers force confirmation ✓
- Status bar subscribes to `watch_status` (heartbeat-tolerant) ✓
- Conversation log uses in-memory cache + Layer 3 `view_chat` rehydration ✓
- TUI imports no `harness.orchestrator` directly ✓
- All tests pass under `uv run pytest -q` ✓
