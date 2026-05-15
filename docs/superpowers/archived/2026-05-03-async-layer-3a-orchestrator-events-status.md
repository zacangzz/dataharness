# Layer 3a — Async Orchestrator, Events, Status Snapshot

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-01-async-layered-architecture-design.md` §8 (event types, status snapshot, async orchestrator interface, removals, tests).

**Goal:** Build the async event-streaming spine of `Orchestrator`. This plan delivers: typed `HarnessEvent` hierarchy, `HarnessStatusSnapshot`, typed exceptions, `Orchestrator.run_turn` as `AsyncIterator[HarnessEvent]`, integration with the new async runtime + worker, single-active-run invariant, `cancel_run`, `status_snapshot`, `watch_status` with 50 ms coalescing and 2 s heartbeat, and removal of the sync `handle_turn(...) -> dict`. Chat-session persistence, command registry, workspace lifecycle, and doctor flow live in plans 3b and 3c — this plan introduces the event types and orchestrator hooks they will use.

**Architecture:** New `harness.events` module owns the `HarnessEvent` discriminated union (Pydantic models) and `HarnessStatusSnapshot`. New `harness.exceptions` defines typed exceptions. `harness.status` owns a `StatusBroker` that aggregates Layer 1 runtime status + Layer 2 task counts + Layer 3 run/workspace/chat state into snapshots, fans them out to subscribers with 50 ms coalescing + 2 s heartbeat. `Orchestrator` becomes an async iterator producer: `run_turn` yields `TurnStarted` → `RuntimeDelta`* → optional `PlanReady`/`ApprovalRequired` (pause; resumed by `resume_approved_step`) → `StepTaskSubmitted` → `StepTaskStatusChanged` → `StepCompleted` → `ArtifactsReady` → `FinalMessage` → terminal. `cancel_run` is non-streaming and returns `TurnCancelled` directly.

**Tech Stack:** Python 3.12, `asyncio`, `pydantic` 2.x, `pytest-asyncio`.

---

## File Structure

- `src/harness/events.py` — **new**: `HarnessEvent` base + every concrete event class + `HarnessEventRef`.
- `src/harness/status.py` — **new**: `HarnessStatusSnapshot`, `StatusBroker` with watch_status semantics.
- `src/harness/exceptions.py` — **new**: typed exceptions per §10.
- `src/harness/orchestrator.py` — **rewrite** to async; keep current persistence + plan/approval/dispatch helpers; remove `handle_turn(...) -> dict`; add async `run_turn`, `resume_approved_step`, `resume_with_clarification`, `cancel_run`, `status_snapshot`, `watch_status`; add single-active-run gate.
- `src/harness/control.py` — add `SessionConfig` (move out of `app/session.py`) with `status_heartbeat_seconds: float = 2.0`. Drop `max_parallel_runs`.
- `tests/harness/test_events_schema.py` — **new**: every event type round-trips.
- `tests/harness/test_status_broker.py` — **new**: snapshot fields, watch_status coalescing, heartbeat.
- `tests/harness/test_orchestrator_async.py` — **new**: event order for non-execution turn; runtime deltas; approval pause; `RunAlreadyActive`; cancel.
- Convert: `tests/harness/test_orchestrator.py`, `tests/harness/test_full_turn_integration.py`, `tests/harness/test_token_pressure_gate.py`, `tests/harness/test_runtime_bridge.py`.

---

## Prep

- [ ] **Step 0.1: Verify Layer 1 + 2 plans complete**

Run: `uv run pytest tests/runtime tests/worker -q`
Expected: PASS.

- [ ] **Step 0.2: Branch check**

Run: `git status` — clean.

---

## Task 1: Typed exceptions

**Files:**
- Create: `src/harness/exceptions.py`
- Test: `tests/harness/test_exceptions.py` (new)

- [ ] **Step 1.1: Failing tests**

```python
# tests/harness/test_exceptions.py
import pytest

from harness.exceptions import (
    ChatNotFound, ChatWorkspaceMismatch, ChatActiveDeletionBlocked,
    WorkspaceNotFound, RunAlreadyActive, WorkspaceSwitchBlocked,
)


def test_chat_not_found_carries_id():
    with pytest.raises(ChatNotFound) as ei:
        raise ChatNotFound(chat_id="chat_x")
    assert ei.value.chat_id == "chat_x"


def test_workspace_mismatch_holds_actual_and_expected():
    e = ChatWorkspaceMismatch(chat_id="c", expected_workspace="w1", actual_workspace="w2")
    assert e.expected_workspace == "w1"
    assert e.actual_workspace == "w2"


def test_run_already_active_holds_run_id():
    e = RunAlreadyActive(run_id="run_1")
    assert e.run_id == "run_1"


def test_workspace_switch_blocked_holds_active_run():
    e = WorkspaceSwitchBlocked(active_run_id="run_z")
    assert e.active_run_id == "run_z"
```

- [ ] **Step 1.2: Run; expect failure**

`uv run pytest tests/harness/test_exceptions.py -v` — FAIL (no module).

- [ ] **Step 1.3: Implement `src/harness/exceptions.py`**

```python
from __future__ import annotations


class HarnessError(Exception):
    pass


class ChatNotFound(HarnessError):
    def __init__(self, *, chat_id: str) -> None:
        super().__init__(f"chat not found: {chat_id}")
        self.chat_id = chat_id


class ChatWorkspaceMismatch(HarnessError):
    def __init__(self, *, chat_id: str, expected_workspace: str, actual_workspace: str) -> None:
        super().__init__(
            f"chat {chat_id} belongs to workspace {actual_workspace}, expected {expected_workspace}"
        )
        self.chat_id = chat_id
        self.expected_workspace = expected_workspace
        self.actual_workspace = actual_workspace


class ChatActiveDeletionBlocked(HarnessError):
    def __init__(self, *, chat_id: str) -> None:
        super().__init__(f"cannot delete active chat: {chat_id}")
        self.chat_id = chat_id


class WorkspaceNotFound(HarnessError):
    def __init__(self, *, workspace_id: str) -> None:
        super().__init__(f"workspace not found: {workspace_id}")
        self.workspace_id = workspace_id


class RunAlreadyActive(HarnessError):
    def __init__(self, *, run_id: str) -> None:
        super().__init__(f"run already active: {run_id}")
        self.run_id = run_id


class WorkspaceSwitchBlocked(HarnessError):
    def __init__(self, *, active_run_id: str) -> None:
        super().__init__(f"workspace switch blocked while run {active_run_id} active")
        self.active_run_id = active_run_id
```

- [ ] **Step 1.4: Run; expect pass**

- [ ] **Step 1.5: Commit**

```bash
git add src/harness/exceptions.py tests/harness/test_exceptions.py
git commit -m "feat(harness): typed exceptions per spec §10"
```

---

## Task 2: `HarnessEvent` hierarchy

**Files:**
- Create: `src/harness/events.py`
- Test: `tests/harness/test_events_schema.py` (new)

- [ ] **Step 2.1: Failing schema test**

```python
# tests/harness/test_events_schema.py
from datetime import UTC, datetime
from pathlib import Path

from harness.events import (
    HarnessEvent, HarnessEventRef,
    TurnStarted, StatusChanged, WorkspaceHealthChanged,
    ChatCreated, ChatSelected, ChatDeleted, ChatHistoryLoaded,
    CommandStarted, CommandProgress, CommandCompleted,
    RuntimeStatusChanged, ModeActivated, ContextReloaded, PromptBuilt,
    ChatHistoryCompacted, RuntimeDelta,
    PlanReady, ApprovalRequired, ApprovalResolved,
    StepTaskSubmitted, StepTaskStatusChanged, StepCompleted, ArtifactsReady,
    DoctorStarted, DoctorFinding, DoctorActionProposed, DoctorReportReady,
    FinalMessage, TurnFailed, TurnCancelled,
)
from harness.status import HarnessStatusSnapshot
from worker.models import StepExecutionEnvelope, StepTaskStatus


def base_kwargs():
    return {
        "event_id": "ev_1", "ts": datetime.now(UTC),
        "workspace_id": "w1", "chat_id": "c1", "run_id": "run_1",
    }


def test_turn_started_fields():
    e = TurnStarted(**base_kwargs(), turn_id="t1", user_message_id="m1", active_mode="analyst")
    assert e.event_name == "TurnStarted"


def test_runtime_delta_text():
    e = RuntimeDelta(
        **base_kwargs(), request_id="req1", seq=3, delta_type="text", text="hi", tool_call=None,
    )
    assert e.delta_type == "text"


def test_chat_history_compacted_status_terminals():
    for s in ("queued", "running", "completed", "failed"):
        ChatHistoryCompacted(
            **base_kwargs(), chat_id="c1", status=s,
            summary_token_estimate=None, replaced_turn_count=None, compaction_count=1,
        )


def test_doctor_finding_categories():
    for cat in ("source", "validity", "lineage", "tmp", "memory"):
        DoctorFinding(
            **base_kwargs(), report_id="r1", category=cat, severity="info",
            summary="x", details={},
        )


def test_event_ref_round_trip():
    ref = HarnessEventRef(event_id="e", event_name="TurnStarted", ts=datetime.now(UTC), run_id="r")
    assert ref.run_id == "r"


def test_event_discriminator_present():
    e = TurnStarted(**base_kwargs(), turn_id="t1", user_message_id="m1", active_mode="analyst")
    assert e.model_dump()["event_name"] == "TurnStarted"
```

- [ ] **Step 2.2: Run; expect failure**

- [ ] **Step 2.3: Implement `src/harness/events.py`**

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from harness.status import HarnessStatusSnapshot
from runtime.types import RuntimeStatus
from worker.models import StepExecutionEnvelope, StepTaskStatus


def _new_event_id() -> str:
    return f"ev_{uuid4().hex[:12]}"


class HarnessEvent(BaseModel):
    event_id: str = Field(default_factory=_new_event_id)
    event_name: str
    ts: datetime
    workspace_id: str | None = None
    chat_id: str | None = None
    run_id: str | None = None


class HarnessEventRef(BaseModel):
    event_id: str
    event_name: str
    ts: datetime
    run_id: str | None = None


# --- turn lifecycle ---

class TurnStarted(HarnessEvent):
    event_name: Literal["TurnStarted"] = "TurnStarted"
    turn_id: str
    user_message_id: str
    active_mode: str


class FinalMessage(HarnessEvent):
    event_name: Literal["FinalMessage"] = "FinalMessage"
    assistant_message_id: str
    text: str
    usage: dict[str, int] = Field(default_factory=dict)


class TurnFailed(HarnessEvent):
    event_name: Literal["TurnFailed"] = "TurnFailed"
    failure_summary: str
    error_code: str
    details: dict[str, Any] = Field(default_factory=dict)


class TurnCancelled(HarnessEvent):
    event_name: Literal["TurnCancelled"] = "TurnCancelled"
    reason: str
    cancelled_at: datetime


# --- status / health ---

class StatusChanged(HarnessEvent):
    event_name: Literal["StatusChanged"] = "StatusChanged"
    snapshot: HarnessStatusSnapshot


class WorkspaceHealthChanged(HarnessEvent):
    event_name: Literal["WorkspaceHealthChanged"] = "WorkspaceHealthChanged"
    health: Literal["ready", "busy", "degraded", "error"]
    reason: str | None = None


class RuntimeStatusChanged(HarnessEvent):
    event_name: Literal["RuntimeStatusChanged"] = "RuntimeStatusChanged"
    runtime_status: RuntimeStatus
    reason: str | None = None


class ModeActivated(HarnessEvent):
    event_name: Literal["ModeActivated"] = "ModeActivated"
    mode: str
    prior_mode: str | None
    decided_at: datetime


class ContextReloaded(HarnessEvent):
    event_name: Literal["ContextReloaded"] = "ContextReloaded"
    workspace_id: str
    source_count: int
    memory_token_estimate: int


class PromptBuilt(HarnessEvent):
    event_name: Literal["PromptBuilt"] = "PromptBuilt"
    request_id: str
    prompt_token_estimate: int
    breakdown: dict[str, int] = Field(default_factory=dict)


# --- chat ---

class ChatCreated(HarnessEvent):
    event_name: Literal["ChatCreated"] = "ChatCreated"
    chat: dict[str, Any]  # ChatSummary serialized


class ChatSelected(HarnessEvent):
    event_name: Literal["ChatSelected"] = "ChatSelected"
    chat_id: str


class ChatDeleted(HarnessEvent):
    event_name: Literal["ChatDeleted"] = "ChatDeleted"
    chat_id: str


class ChatHistoryLoaded(HarnessEvent):
    event_name: Literal["ChatHistoryLoaded"] = "ChatHistoryLoaded"
    chat_id: str
    message_count: int
    token_estimate: int
    source: Literal["new", "resumed"]


class ChatHistoryCompacted(HarnessEvent):
    event_name: Literal["ChatHistoryCompacted"] = "ChatHistoryCompacted"
    chat_id: str
    status: Literal["queued", "running", "completed", "failed"]
    summary_token_estimate: int | None = None
    replaced_turn_count: int | None = None
    compaction_count: int = 0


# --- commands ---

class CommandStarted(HarnessEvent):
    event_name: Literal["CommandStarted"] = "CommandStarted"
    command: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class CommandProgress(HarnessEvent):
    event_name: Literal["CommandProgress"] = "CommandProgress"
    command: str
    phase: str
    phase_index: int
    phase_total: int
    message: str | None = None


class CommandCompleted(HarnessEvent):
    event_name: Literal["CommandCompleted"] = "CommandCompleted"
    command: str
    result: dict[str, Any] = Field(default_factory=dict)


# --- runtime stream ---

class RuntimeDelta(HarnessEvent):
    event_name: Literal["RuntimeDelta"] = "RuntimeDelta"
    request_id: str
    seq: int
    delta_type: Literal["text", "reasoning", "tool_call"]
    text: str | None = None
    tool_call: dict[str, Any] | None = None


# --- plans / approval ---

class PlanReady(HarnessEvent):
    event_name: Literal["PlanReady"] = "PlanReady"
    plan_id: str
    plan: dict[str, Any]


class ApprovalRequired(HarnessEvent):
    event_name: Literal["ApprovalRequired"] = "ApprovalRequired"
    plan_id: str
    step_id: str
    step: dict[str, Any]
    prompt: str


class ApprovalResolved(HarnessEvent):
    event_name: Literal["ApprovalResolved"] = "ApprovalResolved"
    plan_id: str
    step_id: str
    decision: Literal["approved", "rejected", "clarified"]


# --- worker tasks ---

class StepTaskSubmitted(HarnessEvent):
    event_name: Literal["StepTaskSubmitted"] = "StepTaskSubmitted"
    task_id: str
    step_id: str
    plan_id: str


class StepTaskStatusChanged(HarnessEvent):
    event_name: Literal["StepTaskStatusChanged"] = "StepTaskStatusChanged"
    task_id: str
    status: StepTaskStatus


class StepCompleted(HarnessEvent):
    event_name: Literal["StepCompleted"] = "StepCompleted"
    task_id: str
    envelope: StepExecutionEnvelope


class ArtifactsReady(HarnessEvent):
    event_name: Literal["ArtifactsReady"] = "ArtifactsReady"
    step_id: str
    artifacts: list[Path]


# --- doctor ---

class DoctorStarted(HarnessEvent):
    event_name: Literal["DoctorStarted"] = "DoctorStarted"
    trigger: str
    report_id: str


class DoctorFinding(HarnessEvent):
    event_name: Literal["DoctorFinding"] = "DoctorFinding"
    report_id: str
    category: Literal["source", "validity", "lineage", "tmp", "memory"]
    severity: Literal["info", "warn", "error"]
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class DoctorActionProposed(HarnessEvent):
    event_name: Literal["DoctorActionProposed"] = "DoctorActionProposed"
    report_id: str
    action: Literal["cleanup", "promote", "keep", "review"]
    target: str
    rationale: str


class DoctorReportReady(HarnessEvent):
    event_name: Literal["DoctorReportReady"] = "DoctorReportReady"
    report_id: str
    summary_counts: dict[str, int] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    action_records: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 2.4: Run; expect pass**

- [ ] **Step 2.5: Commit**

```bash
git add src/harness/events.py tests/harness/test_events_schema.py
git commit -m "feat(harness): typed HarnessEvent hierarchy per spec §8"
```

---

## Task 3: Status snapshot + broker

**Files:**
- Create: `src/harness/status.py`
- Test: `tests/harness/test_status_broker.py` (new)

- [ ] **Step 3.1: Failing tests**

```python
# tests/harness/test_status_broker.py
import asyncio
from datetime import UTC, datetime

import pytest

from harness.status import HarnessStatusSnapshot, StatusBroker


def make_snapshot(**overrides):
    base = dict(
        workspace_id="w1", chat_id="c1", chat_title="t",
        workspace_health="ready", active_mode="analyst",
        run_id=None, run_state="idle", runtime_status="ready",
        execution_tasks={}, approval_state="idle", clarification_state="idle",
        chat_turn_count=0, chat_token_estimate=0,
        last_compacted_at=None, compaction_count=0,
        doctor_warning_count=0, last_event=None,
    )
    base.update(overrides)
    return HarnessStatusSnapshot(**base)


def test_snapshot_schema_fields():
    s = make_snapshot()
    assert s.workspace_id == "w1"
    assert s.execution_tasks == {}


async def test_watch_status_yields_initial_snapshot():
    broker = StatusBroker(make_snapshot(), heartbeat_seconds=10.0)
    agen = broker.watch()
    first = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert first.workspace_id == "w1"
    await broker.close()


async def test_watch_status_yields_on_change_with_coalesce():
    broker = StatusBroker(make_snapshot(), heartbeat_seconds=10.0, coalesce_seconds=0.05)
    agen = broker.watch()
    await agen.__anext__()  # initial
    # Burst three updates within coalesce window
    broker.publish(make_snapshot(active_mode="m2"))
    broker.publish(make_snapshot(active_mode="m3"))
    broker.publish(make_snapshot(active_mode="m4"))
    coalesced = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert coalesced.active_mode == "m4"
    await broker.close()


async def test_watch_status_heartbeat_re_yields():
    broker = StatusBroker(make_snapshot(), heartbeat_seconds=0.1, coalesce_seconds=0.01)
    agen = broker.watch()
    await agen.__anext__()
    tick = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert tick.workspace_id == "w1"
    await broker.close()


async def test_publish_no_change_no_yield_until_heartbeat():
    broker = StatusBroker(make_snapshot(), heartbeat_seconds=10.0, coalesce_seconds=0.05)
    agen = broker.watch()
    await agen.__anext__()
    # Publish identical snapshots
    broker.publish(make_snapshot())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(agen.__anext__(), timeout=0.3)
    await broker.close()
```

- [ ] **Step 3.2: Run; expect failure**

- [ ] **Step 3.3: Implement `src/harness/status.py`**

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from runtime.types import RuntimeStatus


class HarnessEventRefPayload(BaseModel):
    event_id: str
    event_name: str
    ts: datetime
    run_id: str | None = None


class HarnessStatusSnapshot(BaseModel):
    workspace_id: str
    chat_id: str | None
    chat_title: str | None
    workspace_health: Literal["ready", "busy", "degraded", "error"]
    active_mode: str
    run_id: str | None
    run_state: str
    runtime_status: RuntimeStatus
    execution_tasks: dict[str, int] = Field(default_factory=dict)
    approval_state: Literal["idle", "awaiting_user", "resolved"] | None
    clarification_state: Literal["idle", "awaiting_user", "resolved"] | None
    chat_turn_count: int
    chat_token_estimate: int
    last_compacted_at: datetime | None
    compaction_count: int
    doctor_warning_count: int
    last_event: HarnessEventRefPayload | None = None


class StatusBroker:
    def __init__(
        self,
        initial: HarnessStatusSnapshot,
        *,
        heartbeat_seconds: float = 2.0,
        coalesce_seconds: float = 0.05,
    ) -> None:
        self._latest = initial
        self._heartbeat = heartbeat_seconds
        self._coalesce = coalesce_seconds
        self._subscribers: list[asyncio.Queue[HarnessStatusSnapshot]] = []
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def snapshot(self) -> HarnessStatusSnapshot:
        return self._latest

    def publish(self, snapshot: HarnessStatusSnapshot) -> None:
        if snapshot == self._latest:
            return
        self._latest = snapshot
        for q in self._subscribers:
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:
                pass

    async def close(self) -> None:
        self._closed = True
        for q in self._subscribers:
            with contextlib_suppress():
                q.put_nowait(_CLOSE)

    async def watch(self) -> AsyncIterator[HarnessStatusSnapshot]:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers.append(q)
        last_yielded = self._latest
        # Initial snapshot
        yield last_yielded
        try:
            while not self._closed:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=self._heartbeat)
                except asyncio.TimeoutError:
                    yield self._latest  # heartbeat
                    continue
                if item is _CLOSE:
                    return
                # Coalesce burst
                await asyncio.sleep(self._coalesce)
                while not q.empty():
                    item = q.get_nowait()
                    if item is _CLOSE:
                        return
                if self._latest != last_yielded:
                    last_yielded = self._latest
                    yield last_yielded
        finally:
            async with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)


_CLOSE: object = object()


class contextlib_suppress:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return True
```

- [ ] **Step 3.4: Run; expect pass**

- [ ] **Step 3.5: Commit**

```bash
git add src/harness/status.py tests/harness/test_status_broker.py
git commit -m "feat(harness): HarnessStatusSnapshot + StatusBroker (50ms coalesce, 2s heartbeat)"
```

---

## Task 4: `SessionConfig` + remove `max_parallel_runs`

**Files:**
- Modify: `src/harness/control.py`, `src/app/session.py`
- Test: `tests/harness/test_session_config.py` (new)

- [ ] **Step 4.1: Failing test**

```python
# tests/harness/test_session_config.py
from harness.control import SessionConfig


def test_defaults():
    c = SessionConfig()
    assert c.status_heartbeat_seconds == 2.0
    assert not hasattr(c, "max_parallel_runs")
```

- [ ] **Step 4.2: Run; expect failure** — `SessionConfig` not in `control`.

- [ ] **Step 4.3: Add to `harness/control.py`**

```python
class SessionConfig(BaseModel):
    status_heartbeat_seconds: float = 2.0
    status_coalesce_seconds: float = 0.05
```

- [ ] **Step 4.4: Remove old `SessionConfig` from `src/app/session.py`**

Delete the `SessionConfig` class block defining `max_parallel_runs`. Update imports anywhere that referenced it (the new `AppSession` in plan 6 will import from `harness.control`).

- [ ] **Step 4.5: Run; expect pass + downstream test breakage**

`uv run pytest tests/harness/test_session_config.py -v` PASS.
`uv run pytest tests/app -v` will FAIL on the legacy session tests; fix by deleting `tests/app/test_session_concurrency.py` (its `max_parallel_runs` premise is removed by spec) and noting in commit. Other app/session tests are migrated in plan 6.

- [ ] **Step 4.6: Commit**

```bash
git rm tests/app/test_session_concurrency.py
git add src/harness/control.py src/app/session.py tests/harness/test_session_config.py
git commit -m "feat(harness): SessionConfig moved to harness; drop max_parallel_runs (spec §5)"
```

---

## Task 5: Async `Orchestrator` skeleton + run guard

**Files:**
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_orchestrator_async.py` (new)

The rewrite is large. Scope of this task: replace `handle_turn(...) -> dict` with `async def run_turn(...) -> AsyncIterator[HarnessEvent]` covering the non-execution path (analyst→llm→FinalMessage), single-active-run gate, and `cancel_run`. Plan/approval pause + worker dispatch land in Task 6. Chat history assembly + persistence land in plan 3b.

- [ ] **Step 5.1: Failing tests**

```python
# tests/harness/test_orchestrator_async.py
import asyncio
from collections.abc import AsyncIterator

import pytest

from harness.events import (
    HarnessEvent, TurnStarted, RuntimeDelta, FinalMessage,
)
from harness.exceptions import RunAlreadyActive
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord
from runtime.types import RuntimeEvent, RuntimeRequest


class FakeRuntime:
    def __init__(self, deltas):
        self._deltas = deltas

    async def stream(self, request):
        seq = 0
        for d in self._deltas:
            yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=seq, text=d)
            seq += 1
        yield RuntimeEvent(
            type="finish", request_id=request.request_id, seq=seq,
            finish_reason="stop", usage={"prompt_tokens": 1, "completion_tokens": len(self._deltas)},
        )

    async def context_window(self): return 4096
    async def token_pressure(self, request):
        from runtime.types import TokenPressure
        return TokenPressure(
            request_id=request.request_id, context_window=4096,
            prompt_tokens=10, reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=10 + request.max_completion_tokens,
            pressure_ratio=0.05, over_threshold=False,
        )
    async def validate_request(self, request): return None
    async def status(self): return "ready"


@pytest.fixture
def orch(tmp_path):
    rt = FakeRuntime(["hel", "lo"])
    o = Orchestrator(runtime=rt, app_root=tmp_path)
    return o


def make_state():
    return RunStateRecord(workspace_id="w1", active_agent_mode="interaction")


async def collect(agen: AsyncIterator[HarnessEvent]):
    return [ev async for ev in agen]


async def test_run_turn_emits_turnstarted_then_deltas_then_final(orch, tmp_path):
    state = make_state()
    events = await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id="c1", user_input="hi",
    ))
    types = [e.event_name for e in events]
    assert types[0] == "TurnStarted"
    assert "RuntimeDelta" in types
    assert types[-1] == "FinalMessage"
    final = events[-1]
    assert final.text == "hello"


async def test_concurrent_run_raises_run_already_active(orch, tmp_path):
    state = make_state()
    agen = orch.run_turn(state, workspace_dir=tmp_path, chat_id="c1", user_input="hi")
    await agen.__anext__()
    with pytest.raises(RunAlreadyActive):
        async for _ in orch.run_turn(state, workspace_dir=tmp_path, chat_id="c1", user_input="hi2"):
            pass
    async for _ in agen:
        pass


async def test_cancel_run_returns_turncancelled(orch, tmp_path):
    state = make_state()
    agen = orch.run_turn(state, workspace_dir=tmp_path, chat_id="c1", user_input="hi")
    first = await agen.__anext__()
    cancelled = await orch.cancel_run(first.run_id, reason="user")
    assert cancelled.event_name == "TurnCancelled"
    assert cancelled.reason == "user"
    # Drain
    async for _ in agen:
        pass
```

- [ ] **Step 5.2: Run; expect failure**

- [ ] **Step 5.3: Rewrite `src/harness/orchestrator.py` — async skeleton**

Replace top of file:

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from harness.context import ContextManager
from harness.control import (
    ApprovalRecord, DoctorReport, ModeSwitchEvent, Plan, PlanStep, PromptPackage,
    RunState, RunStateRecord, SessionConfig, StepContract, TmpAction,
)
from harness.doctor import Doctor
from harness.events import (
    ApprovalRequired, ApprovalResolved, ArtifactsReady, ChatHistoryLoaded,
    CommandCompleted, CommandStarted, FinalMessage, HarnessEvent, ModeActivated,
    PlanReady, PromptBuilt, RuntimeDelta, RuntimeStatusChanged, StatusChanged,
    StepCompleted, StepTaskStatusChanged, StepTaskSubmitted, TurnCancelled,
    TurnFailed, TurnStarted,
)
from harness.exceptions import RunAlreadyActive
from harness.persistence import HarnessPersistence
from harness.state_machine import HarnessStateMachine
from harness.status import HarnessStatusSnapshot, StatusBroker
from observability import Telemetry, bind_step, resolve_telemetry_dir
from observability.events import EventKind, Layer
from runtime.protocol import Runtime
from runtime.types import RuntimeMessage, RuntimeRequest
from worker.executor import PythonStepExecutor
from worker.models import PermissionEnvelope, ResourceLimits, StepExecutionRequest
```

Replace class body with async-only API (keep `_build_v1_analysis_plan`, `prepare_worker_dispatch`):

```python
class Orchestrator:
    def __init__(
        self,
        *,
        runtime: Runtime | None = None,
        context_manager: ContextManager | None = None,
        worker: PythonStepExecutor | None = None,
        persistence: HarnessPersistence | None = None,
        doctor: Doctor | None = None,
        telemetry: Telemetry | None = None,
        config: SessionConfig | None = None,
        app_root: Path | None = None,
    ) -> None:
        self.telemetry = telemetry or getattr(persistence, "telemetry", None) or Telemetry(resolve_telemetry_dir())
        self.state_machine = HarnessStateMachine()
        self.runtime = runtime
        self.context_manager = context_manager or ContextManager()
        self.worker = worker or PythonStepExecutor()
        self.doctor = doctor or Doctor()
        if hasattr(self.worker, "telemetry"):
            self.worker.telemetry = self.telemetry
        self.persistence = persistence
        if self.persistence is not None:
            self.persistence.telemetry = self.telemetry
        self.config = config or SessionConfig()
        self.app_root = app_root or Path.cwd()
        self._active_run_id: str | None = None
        self._cancel_flags: dict[str, asyncio.Event] = {}
        self._run_lock = asyncio.Lock()
        self._status_broker: StatusBroker | None = None

    # ---- single-active-run guard ----
    async def _acquire_run(self, run_id: str) -> asyncio.Event:
        async with self._run_lock:
            if self._active_run_id is not None:
                raise RunAlreadyActive(run_id=self._active_run_id)
            self._active_run_id = run_id
            cancel = asyncio.Event()
            self._cancel_flags[run_id] = cancel
            return cancel

    async def _release_run(self, run_id: str) -> None:
        async with self._run_lock:
            if self._active_run_id == run_id:
                self._active_run_id = None
            self._cancel_flags.pop(run_id, None)

    # ---- public ----
    async def run_turn(
        self,
        state: RunStateRecord,
        *,
        workspace_dir: Path,
        chat_id: str,
        user_input: str,
        requested_mode: str | None = None,
        prompt_text: str | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        run_id = state.run_id
        cancel = await self._acquire_run(run_id)
        active_mode = requested_mode or state.active_agent_mode
        turn_id = f"turn_{uuid4().hex[:12]}"
        user_msg_id = f"msg_{uuid4().hex[:12]}"
        ts = datetime.now(UTC)
        try:
            yield TurnStarted(
                ts=ts, workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                turn_id=turn_id, user_message_id=user_msg_id, active_mode=active_mode,
            )
            yield ModeActivated(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                mode=active_mode, prior_mode=state.active_agent_mode, decided_at=datetime.now(UTC),
            )
            if cancel.is_set():
                yield TurnCancelled(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id,
                    run_id=run_id, reason="cancel_before_runtime", cancelled_at=datetime.now(UTC),
                )
                return

            # Runtime stream
            if self.runtime is None:
                yield FinalMessage(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id,
                    run_id=run_id, assistant_message_id=f"asg_{uuid4().hex[:8]}",
                    text="", usage={},
                )
                return
            request = RuntimeRequest(
                messages=[
                    RuntimeMessage(role="system", content=prompt_text or "You are the harness."),
                    RuntimeMessage(role="user", content=user_input),
                ],
                max_completion_tokens=512,
                request_id=f"req_{uuid4().hex[:12]}",
                correlation_id=run_id,
            )
            pressure = await self.runtime.token_pressure(request)
            yield PromptBuilt(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                request_id=request.request_id, prompt_token_estimate=pressure.prompt_tokens,
                breakdown={"prompt": pressure.prompt_tokens, "reserved": pressure.reserved_completion_tokens},
            )

            buffer: list[str] = []
            usage: dict[str, int] = {}
            async for ev in self.runtime.stream(request):
                if cancel.is_set():
                    yield TurnCancelled(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id,
                        run_id=run_id, reason="user", cancelled_at=datetime.now(UTC),
                    )
                    return
                if ev.type == "text_delta":
                    buffer.append(ev.text or "")
                    yield RuntimeDelta(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                        request_id=ev.request_id, seq=ev.seq, delta_type="text", text=ev.text, tool_call=None,
                    )
                elif ev.type == "reasoning_delta":
                    yield RuntimeDelta(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                        request_id=ev.request_id, seq=ev.seq, delta_type="reasoning", text=ev.text, tool_call=None,
                    )
                elif ev.type == "tool_call":
                    yield RuntimeDelta(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                        request_id=ev.request_id, seq=ev.seq, delta_type="tool_call",
                        text=None, tool_call=ev.tool_call,
                    )
                elif ev.type == "finish":
                    usage = ev.usage or {}
                elif ev.type == "error":
                    yield TurnFailed(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                        failure_summary=ev.error_message or "runtime error",
                        error_code=ev.error_code or "runtime_error",
                        details={"finish_reason": ev.finish_reason},
                    )
                    return

            yield FinalMessage(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                assistant_message_id=f"asg_{uuid4().hex[:12]}",
                text="".join(buffer), usage=usage,
            )
        finally:
            await self._release_run(run_id)

    async def cancel_run(self, run_id: str, reason: str) -> TurnCancelled:
        async with self._run_lock:
            cancel = self._cancel_flags.get(run_id)
        if cancel is not None:
            cancel.set()
        # Also cancel any outstanding worker tasks tagged with this run.
        try:
            tasks = await self.worker.list_tasks()
            for t in tasks:
                if t.run_id == run_id and t.status in ("queued", "running"):
                    await self.worker.cancel(t.task_id, reason=reason)
        except Exception:
            pass
        return TurnCancelled(
            ts=datetime.now(UTC), run_id=run_id, reason=reason, cancelled_at=datetime.now(UTC),
        )

    async def status_snapshot(self, workspace_id: str | None = None) -> HarnessStatusSnapshot:
        runtime_status = await self.runtime.status() if self.runtime else "not_loaded"
        tasks = await self.worker.list_tasks()
        counts: dict[str, int] = {}
        for t in tasks:
            counts[t.status] = counts.get(t.status, 0) + 1
        return HarnessStatusSnapshot(
            workspace_id=workspace_id or "",
            chat_id=None, chat_title=None,
            workspace_health="ready",
            active_mode="interaction",
            run_id=self._active_run_id,
            run_state="running" if self._active_run_id else "idle",
            runtime_status=runtime_status,
            execution_tasks=counts,
            approval_state="idle", clarification_state="idle",
            chat_turn_count=0, chat_token_estimate=0,
            last_compacted_at=None, compaction_count=0,
            doctor_warning_count=0, last_event=None,
        )

    async def watch_status(self) -> AsyncIterator[HarnessStatusSnapshot]:
        if self._status_broker is None:
            self._status_broker = StatusBroker(
                await self.status_snapshot(),
                heartbeat_seconds=self.config.status_heartbeat_seconds,
                coalesce_seconds=self.config.status_coalesce_seconds,
            )
        async for snap in self._status_broker.watch():
            yield snap
```

Keep helpers (`_build_v1_analysis_plan`, `prepare_worker_dispatch`, `dispatch_step`, `switch_workspace`) but rename `dispatch_step` to call `await self.worker.submit(...)` + `await self.worker.wait(...)` in Task 6. The plan/approval & resume paths land in Task 6.

- [ ] **Step 5.4: Run; expect pass on the new tests**

Run: `uv run pytest tests/harness/test_orchestrator_async.py -v`
Expected: PASS.

- [ ] **Step 5.5: Commit**

```bash
git add src/harness/orchestrator.py tests/harness/test_orchestrator_async.py
git commit -m "feat(harness): async run_turn skeleton + cancel_run + status_snapshot/watch_status"
```

---

## Task 6: Plan / approval / worker dispatch through async events

**Files:**
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_orchestrator_approval_flow.py` (new)

- [ ] **Step 6.1: Failing tests**

```python
# tests/harness/test_orchestrator_approval_flow.py
import asyncio

import pytest

from harness.events import (
    ApprovalRequired, ApprovalResolved, ArtifactsReady, PlanReady,
    StepCompleted, StepTaskStatusChanged, StepTaskSubmitted,
)
from harness.control import ApprovalRecord, RunStateRecord
from harness.orchestrator import Orchestrator


class _NoRuntime: ...


def make_state():
    return RunStateRecord(workspace_id="w1", active_agent_mode="analyst")


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=None, app_root=tmp_path)


async def collect(agen):
    return [ev async for ev in agen]


async def test_compare_input_emits_planready_then_approvalrequired(orch, tmp_path):
    state = make_state()
    events = await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id="c1",
        user_input="please compare A and B",
    ))
    names = [e.event_name for e in events]
    assert "PlanReady" in names
    assert "ApprovalRequired" in names
    assert names[-1] == "ApprovalRequired"  # paused on approval


async def test_resume_approved_step_emits_submitted_status_completed(orch, tmp_path):
    state = make_state()
    events = await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id="c1",
        user_input="please compare A and B",
    ))
    plan_event = next(e for e in events if e.event_name == "PlanReady")
    appr_event = next(e for e in events if e.event_name == "ApprovalRequired")
    approval = ApprovalRecord(
        workspace_id="w1", run_id=state.run_id, target_type="step",
        target_id=appr_event.step_id, approval_kind="code_execution",
        decision="approved", decided_by="user",
        decided_at=datetime_now(),
    )
    resume_events = await collect(orch.resume_approved_step(
        workspace_dir=tmp_path, state=state,
        plan_payload=plan_event.plan, contract_payload={"_step_id": appr_event.step_id},
        approval=approval,
    ))
    names = [e.event_name for e in resume_events]
    assert "ApprovalResolved" in names
    assert "StepTaskSubmitted" in names
    assert "StepTaskStatusChanged" in names
    assert "StepCompleted" in names
    assert "ArtifactsReady" in names


def datetime_now():
    from datetime import UTC, datetime
    return datetime.now(UTC)
```

- [ ] **Step 6.2: Run; expect failure**

- [ ] **Step 6.3: Wire plan + approval pause into `run_turn`**

In `run_turn`, after `ModeActivated`, branch on the existing `_build_v1_analysis_plan` heuristic (kept from old code):

```python
if active_mode == "analyst" and "compare" in user_input.lower():
    plan, contract = self._build_v1_analysis_plan(state, user_input)
    yield PlanReady(
        ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
        plan_id=plan.id, plan=plan.model_dump(mode="json"),
    )
    yield ApprovalRequired(
        ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
        plan_id=plan.id, step_id="step_1",
        step=plan.steps[0].model_dump(mode="json"),
        prompt="Approval required before running code.",
    )
    self._pending_contracts[(state.run_id, "step_1")] = contract
    return
```

Add `self._pending_contracts: dict[tuple[str,str], StepContract] = {}` in `__init__`.

- [ ] **Step 6.4: Implement `resume_approved_step` as async iterator**

```python
async def resume_approved_step(
    self,
    *,
    workspace_dir: Path,
    state: RunStateRecord,
    plan_payload: dict,
    contract_payload: dict,
    approval: ApprovalRecord,
) -> AsyncIterator[HarnessEvent]:
    plan = Plan.model_validate(plan_payload)
    step_id = str(contract_payload.get("_step_id") or contract_payload.get("step_id") or "step_1")
    contract = self._pending_contracts.pop((state.run_id, step_id), None)
    if contract is None:
        contract = StepContract.model_validate(contract_payload)
    yield ApprovalResolved(
        ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
        plan_id=plan.id, step_id=step_id, decision="approved",
    )
    cancel = await self._acquire_run(state.run_id)
    try:
        request = StepExecutionRequest(
            id=contract.id,
            workspace_id=contract.workspace_id, run_id=contract.run_id,
            plan_id=contract.plan_id, step_id=contract.step_id,
            workspace_dir=workspace_dir,
            code=contract.code,
            declared_inputs={p: p for p in contract.declared_inputs},
            workspace_paths=contract.workspace_paths,
            permission_envelope=PermissionEnvelope(**contract.permission_envelope),
            expected_output_contract=list(contract.expected_output_contract.get("files", [])),
            run_metadata=contract.run_metadata,
            resource_limits=ResourceLimits(),
        )
        handle = await self.worker.submit(request)
        yield StepTaskSubmitted(
            ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
            task_id=handle.task_id, step_id=contract.step_id, plan_id=plan.id,
        )
        # Initial running status
        running_status = await self.worker.get_task(handle.task_id)
        if running_status is not None:
            yield StepTaskStatusChanged(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
                task_id=handle.task_id, status=running_status,
            )
        envelope = await self.worker.wait(handle.task_id)
        yield StepTaskStatusChanged(
            ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
            task_id=handle.task_id, status=envelope.status,
        )
        yield StepCompleted(
            ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
            task_id=handle.task_id, envelope=envelope,
        )
        yield ArtifactsReady(
            ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
            step_id=contract.step_id, artifacts=envelope.artifacts,
        )
        yield FinalMessage(
            ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
            assistant_message_id=f"asg_{uuid4().hex[:12]}",
            text=f"Analysis complete. See {envelope.artifacts[0] if envelope.artifacts else 'artifacts'}.",
            usage={},
        )
    finally:
        await self._release_run(state.run_id)
```

- [ ] **Step 6.5: Implement `resume_with_clarification` as async iterator**

```python
async def resume_with_clarification(
    self,
    *,
    workspace_dir: Path,
    state: RunStateRecord,
    clarification_text: str,
) -> AsyncIterator[HarnessEvent]:
    cleared = state.model_copy(update={"state": RunState.CLARIFYING, "pending_clarification_id": None})
    async for ev in self.run_turn(
        cleared, workspace_dir=workspace_dir, chat_id=state.run_id,
        user_input=clarification_text, requested_mode=state.active_agent_mode,
    ):
        yield ev
```

(`chat_id` placeholder — chat-id propagation lands in plan 3b.)

- [ ] **Step 6.6: Run; expect pass**

Run: `uv run pytest tests/harness/test_orchestrator_approval_flow.py -v`
Expected: PASS.

- [ ] **Step 6.7: Commit**

```bash
git add src/harness/orchestrator.py tests/harness/test_orchestrator_approval_flow.py
git commit -m "feat(harness): async plan/approval/dispatch via worker.submit/wait"
```

---

## Task 7: Convert legacy harness tests

**Files:**
- Modify: `tests/harness/test_orchestrator.py`
- Modify: `tests/harness/test_full_turn_integration.py`
- Modify: `tests/harness/test_token_pressure_gate.py`
- Modify: `tests/harness/test_runtime_bridge.py`

- [ ] **Step 7.1: Inspect failures**

`uv run pytest tests/harness -v` — expect many failures referencing `handle_turn(...) -> dict`, sync runtime, `Message`, `max_new_tokens`.

- [ ] **Step 7.2: Convert each test file**

Apply per file:
- Mark tests `async def`, replace `result = orch.handle_turn(state, ...)` with `events = [e async for e in orch.run_turn(state, workspace_dir=..., chat_id="c", user_input=...)]`.
- Replace assertions on `result["assistant_text"]` with `next(e.text for e in events if e.event_name == "FinalMessage")`.
- Replace assertions on `result["requires_approval"]` with `any(e.event_name == "ApprovalRequired" for e in events)`.
- Replace assertions on `result["process_events"]` with assertions on event-name sequences.
- Replace `runtime.complete(...)` mocks with `FakeRuntime` from §5.

- [ ] **Step 7.3: Run harness suite**

`uv run pytest tests/harness -q` — must pass.

- [ ] **Step 7.4: Commit**

```bash
git add tests/harness
git commit -m "test(harness): migrate orchestrator tests to async event consumption"
```

---

## Self-Review Checklist

- `Orchestrator.handle_turn(...)` removed; replaced by `run_turn` async iterator ✓
- All event types from spec §8 modeled and round-trippable ✓
- `HarnessStatusSnapshot` matches schema ✓
- `watch_status` yields initial + on-change with 50 ms coalesce + 2 s heartbeat ✓
- Single-active-run gate raises `RunAlreadyActive` ✓
- `cancel_run(...)` returns `TurnCancelled` directly (non-streaming) ✓
- Worker integrated via `submit` + `wait` ✓
- Plan/approval pause emits `PlanReady` then `ApprovalRequired`, then run released ✓
- `resume_approved_step` emits resolved → submitted → status → completed → artifacts → final ✓
- `SessionConfig.max_parallel_runs` removed ✓
- Layer 3 imports no Layer 4 modules ✓ (verify with `grep -rn "from app" src/harness`)
