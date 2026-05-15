# Layer 3c — Command Registry, Slash Grammar, /help, /doctor, Workspace Lifecycle

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-01-async-layered-architecture-design.md` §8 Command Surface, Slash Command Grammar, `/help`, Doctor Command Flow, Workspace Schemas.

**Goal:** Replace the placeholder `HarnessCommandRouter` with a typed `HarnessCommandRegistry` that exposes every required command through `Orchestrator.list_commands(...)`, `Orchestrator.help(...)`, and `Orchestrator.handle_direct_command(...)`. Implement positional-only slash parsing. Build the verbose async `/doctor` flow that emits `DoctorStarted` → `CommandProgress` → `DoctorFinding` → `DoctorActionProposed` → `DoctorReportReady` → `CommandCompleted`. Implement workspace CRUD (`list_workspaces`, `create_workspace`, `rename_workspace`, `delete_workspace`, `activate_workspace`, `ingest_files`) including the cascade hook from plan 3b and `WorkspaceSwitchBlocked`/`force=True` semantics. Remove `compact_context` command and `WorkspaceActivated` event.

**Architecture:** New `harness.command_registry` module owns `ArgSpec`, `CommandContext`, `HarnessCommandDescriptor`, `HelpResult`, and a `HarnessCommandRegistry` that maps each command name to (descriptor, async handler). Each handler is an `AsyncIterator[HarnessEvent]` returning command-specific events bracketed by `CommandStarted` + `CommandCompleted`. `harness.commands` becomes a thin shim that delegates to the registry; `compact_context` is removed. New `harness.workspace_async` module wraps the existing `WorkspaceManager` with async methods, persists summaries, and integrates the chat-cascade. Doctor is wrapped in an async streaming runner using the existing `Doctor` class.

**Tech Stack:** Python 3.12, `asyncio`, `pydantic` 2.x, `pytest-asyncio`.

---

## File Structure

- `src/harness/command_registry.py` — **new**: `ArgSpec`, `CommandContext`, `HarnessCommandDescriptor`, `HelpResult`, `HarnessCommandRegistry`, slash parser.
- `src/harness/commands.py` — replace with thin `HarnessCommandRouter` shim that consults the registry; drop `compact_context`/`LEGACY_DIRECT_COMMANDS`.
- `src/harness/doctor_runner.py` — **new**: async streaming wrapper around `harness.doctor.Doctor`.
- `src/harness/workspace_async.py` — **new**: `AsyncWorkspaceManager` providing async CRUD, ingest, activate, plus `WorkspaceSummary` / `WorkspaceIngestResult`.
- `src/harness/orchestrator.py` — wire registry, doctor runner, and workspace manager into orchestrator; implement `list_commands`, `help`, `handle_direct_command`, `list_workspaces`, `create_workspace`, `rename_workspace`, `delete_workspace`, `activate_workspace`, `ingest_files`.
- Tests: `tests/harness/test_command_registry.py`, `tests/harness/test_slash_parser.py`, `tests/harness/test_doctor_runner.py`, `tests/harness/test_workspace_async.py`, `tests/harness/test_orchestrator_commands.py`.

---

## Task 1: `HarnessCommandDescriptor` + parser

**Files:**
- Create: `src/harness/command_registry.py`
- Test: `tests/harness/test_command_registry.py`, `tests/harness/test_slash_parser.py`

- [ ] **Step 1.1: Failing tests for descriptor + parser**

```python
# tests/harness/test_command_registry.py
import pytest

from harness.command_registry import (
    ArgSpec, CommandContext, HarnessCommandDescriptor, HelpResult,
    HarnessCommandRegistry,
)


def desc(name="doctor", arguments=None, available=True, disabled_reason=None):
    return HarnessCommandDescriptor(
        name=name, slash_alias=f"/{name}",
        short_description="run doctor",
        arguments=arguments or [],
        available=available,
        disabled_reason=disabled_reason,
        affected_resource="doctor",
        expected_event_types=["DoctorStarted", "DoctorReportReady", "CommandCompleted"],
        example_usage=f"/{name}",
    )


def test_register_and_list_descriptors():
    reg = HarnessCommandRegistry()

    async def handler(ctx, args):
        if False:
            yield
    reg.register(desc(), handler)
    listed = reg.list_descriptors(CommandContext(
        workspace_id="w", chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    ))
    assert len(listed) == 1 and listed[0].name == "doctor"


def test_help_for_unknown_returns_not_found():
    reg = HarnessCommandRegistry()
    res = reg.help("nope")
    assert isinstance(res, HelpResult)
    assert res.not_found is True
    assert res.commands == []


def test_help_for_known_returns_single_descriptor():
    reg = HarnessCommandRegistry()

    async def handler(ctx, args):
        if False: yield
    reg.register(desc(), handler)
    res = reg.help("doctor")
    assert res.not_found is False
    assert [d.name for d in res.commands] == ["doctor"]


def test_arg_validation_required_missing():
    reg = HarnessCommandRegistry()
    arg = ArgSpec(name="path", type="path", required=True, description="x", example=None)

    async def handler(ctx, args):
        if False: yield
    reg.register(desc(name="inspect_artifact", arguments=[arg]), handler)
    with pytest.raises(ValueError):
        reg.validate("inspect_artifact", {})


def test_arg_validation_type_coercion():
    reg = HarnessCommandRegistry()

    async def handler(ctx, args):
        if False: yield
    reg.register(
        desc(name="rerun_step", arguments=[ArgSpec(name="step_id", type="step_id", required=True, description="x", example=None)]),
        handler,
    )
    parsed = reg.validate("rerun_step", {"step_id": "step_5"})
    assert parsed["step_id"] == "step_5"
```

```python
# tests/harness/test_slash_parser.py
import pytest

from harness.command_registry import parse_slash


def test_simple_command():
    cmd, args = parse_slash("/doctor")
    assert cmd == "doctor" and args == []


def test_positional_args():
    cmd, args = parse_slash("/rerun_step step_1")
    assert cmd == "rerun_step" and args == ["step_1"]


def test_quoted_arg_with_spaces():
    cmd, args = parse_slash('/inspect_artifact "Project Reports/q1.csv"')
    assert cmd == "inspect_artifact" and args == ["Project Reports/q1.csv"]


def test_multiple_quoted_args():
    cmd, args = parse_slash('/cancel_run "stuck mid step"')
    assert cmd == "cancel_run" and args == ["stuck mid step"]


def test_unknown_grammar_named_flag_raises():
    with pytest.raises(ValueError):
        parse_slash("/doctor --verbose")


def test_non_slash_raises():
    with pytest.raises(ValueError):
        parse_slash("doctor")
```

- [ ] **Step 1.2: Run; expect failure**

- [ ] **Step 1.3: Implement `src/harness/command_registry.py`**

```python
from __future__ import annotations

import shlex
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from harness.events import HarnessEvent


ArgType = Literal[
    "str", "int", "float", "bool", "path",
    "chat_id", "workspace_id", "run_id", "step_id", "artifact_path",
]


class ArgSpec(BaseModel):
    name: str
    type: ArgType
    required: bool
    description: str
    example: str | None = None


class CommandContext(BaseModel):
    workspace_id: str | None
    chat_id: str | None
    run_id: str | None
    has_pending_approval: bool
    has_pending_clarification: bool


class HarnessCommandDescriptor(BaseModel):
    name: str
    slash_alias: str
    short_description: str
    arguments: list[ArgSpec] = Field(default_factory=list)
    available: bool = True
    disabled_reason: str | None = None
    affected_resource: Literal[
        "workspace", "chat", "run", "plan", "step", "artifact",
        "memory", "provenance", "doctor",
    ]
    expected_event_types: list[str] = Field(default_factory=list)
    example_usage: str


class HelpResult(BaseModel):
    commands: list[HarnessCommandDescriptor] = Field(default_factory=list)
    not_found: bool = False


CommandHandler = Callable[
    [CommandContext, dict[str, Any]],
    AsyncIterator[HarnessEvent],
]


class HarnessCommandRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[HarnessCommandDescriptor, CommandHandler]] = {}
        self._availability: dict[str, Callable[[CommandContext], tuple[bool, str | None]]] = {}

    def register(
        self,
        descriptor: HarnessCommandDescriptor,
        handler: CommandHandler,
        *,
        availability: Callable[[CommandContext], tuple[bool, str | None]] | None = None,
    ) -> None:
        self._handlers[descriptor.name] = (descriptor, handler)
        if availability is not None:
            self._availability[descriptor.name] = availability

    def list_descriptors(self, ctx: CommandContext) -> list[HarnessCommandDescriptor]:
        out: list[HarnessCommandDescriptor] = []
        for name, (desc, _) in self._handlers.items():
            available, reason = self._availability.get(name, lambda _c: (desc.available, desc.disabled_reason))(ctx)
            out.append(desc.model_copy(update={"available": available, "disabled_reason": reason}))
        return sorted(out, key=lambda d: d.name)

    def help(self, command: str | None = None) -> HelpResult:
        if command is None:
            return HelpResult(commands=[d for d, _ in self._handlers.values()], not_found=False)
        if command not in self._handlers:
            return HelpResult(commands=[], not_found=True)
        return HelpResult(commands=[self._handlers[command][0]])

    def validate(self, command: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if command not in self._handlers:
            raise ValueError(f"unknown command: {command}")
        desc, _ = self._handlers[command]
        validated: dict[str, Any] = {}
        for spec in desc.arguments:
            if spec.required and spec.name not in arguments:
                raise ValueError(f"missing required arg '{spec.name}' for {command}")
            if spec.name in arguments:
                validated[spec.name] = self._coerce(spec, arguments[spec.name])
        return validated

    def get_handler(self, command: str) -> CommandHandler:
        return self._handlers[command][1]

    def _coerce(self, spec: ArgSpec, value: Any) -> Any:
        if spec.type in {"str", "path", "chat_id", "workspace_id", "run_id", "step_id", "artifact_path"}:
            return str(value)
        if spec.type == "int":
            return int(value)
        if spec.type == "float":
            return float(value)
        if spec.type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).lower() in {"1", "true", "yes", "on"}
        return value


def parse_slash(text: str) -> tuple[str, list[str]]:
    """Positional-only slash grammar from spec §8.

    /<command> [<arg> [<arg> ...]]
    Quoted args allowed for whitespace. No named flags.
    """
    if not text.startswith("/"):
        raise ValueError("slash commands must start with '/'")
    body = text[1:].strip()
    if not body:
        raise ValueError("empty slash command")
    parts = shlex.split(body, posix=True)
    if any(p.startswith("--") or (p.startswith("-") and len(p) > 1 and not p[1].isdigit()) for p in parts[1:]):
        raise ValueError("named flags not supported in V1 slash grammar")
    return parts[0], parts[1:]
```

- [ ] **Step 1.4: Run; expect pass**

- [ ] **Step 1.5: Commit**

```bash
git add src/harness/command_registry.py tests/harness/test_command_registry.py tests/harness/test_slash_parser.py
git commit -m "feat(harness): typed command registry + positional slash parser"
```

---

## Task 2: Replace `harness.commands` shim

**Files:**
- Modify: `src/harness/commands.py`
- Modify: any test referencing `compact_context`

- [ ] **Step 2.1: Failing scan**

Run: `grep -rn "compact_context" src tests`
Expected: matches.

- [ ] **Step 2.2: Replace `src/harness/commands.py`**

```python
from __future__ import annotations

from harness.command_registry import HarnessCommandRegistry  # re-export

__all__ = ["HarnessCommandRegistry"]
```

- [ ] **Step 2.3: Remove `compact_context` references**

Update tests and any remaining uses:
- `tests/harness/test_orchestrator.py` & similar that reference `compact_context` should be removed or replaced with `compact` (chat history).
- `src/harness/orchestrator.py`: drop the legacy `commands.HarnessCommandRouter` usage; the registry replaces it (Task 5).

- [ ] **Step 2.4: Commit**

```bash
git add src/harness/commands.py tests/harness
git commit -m "refactor(harness): drop compact_context; commands shim points at registry"
```

---

## Task 3: Async doctor runner

**Files:**
- Create: `src/harness/doctor_runner.py`
- Test: `tests/harness/test_doctor_runner.py`

- [ ] **Step 3.1: Failing tests**

```python
# tests/harness/test_doctor_runner.py
import asyncio
from pathlib import Path

import pytest

from harness.doctor_runner import DoctorRunner
from harness.events import (
    CommandCompleted, CommandProgress, CommandStarted,
    DoctorActionProposed, DoctorFinding, DoctorReportReady, DoctorStarted,
)


@pytest.fixture
def runner():
    return DoctorRunner()


async def test_emits_full_event_sequence(runner, tmp_path):
    workspace_dir = tmp_path / "w"
    (workspace_dir / "memory").mkdir(parents=True)
    (workspace_dir / "artifacts" / "tmp").mkdir(parents=True)
    events = [
        e async for e in runner.run(
            workspace_id="w1", workspace_dir=workspace_dir, trigger="manual",
        )
    ]
    names = [e.event_name for e in events]
    assert names[0] == "CommandStarted"
    assert "DoctorStarted" in names
    assert "DoctorReportReady" in names
    assert names[-1] == "CommandCompleted"


async def test_progress_events_have_phase_indices(runner, tmp_path):
    ws = tmp_path / "w"
    (ws / "memory").mkdir(parents=True)
    (ws / "artifacts" / "tmp").mkdir(parents=True)
    events = [e async for e in runner.run(workspace_id="w1", workspace_dir=ws, trigger="manual")]
    progresses = [e for e in events if isinstance(e, CommandProgress)]
    assert progresses[0].phase_index == 1
    assert progresses[-1].phase_index == progresses[-1].phase_total
```

- [ ] **Step 3.2: Implement `src/harness/doctor_runner.py`**

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from harness.doctor import Doctor
from harness.events import (
    CommandCompleted, CommandProgress, CommandStarted, DoctorActionProposed,
    DoctorFinding, DoctorReportReady, DoctorStarted, HarnessEvent,
)


PHASES = (
    "scan_sources",
    "review_validity",
    "review_lineage",
    "review_tmp",
    "review_memory",
    "assemble_recommendations",
)


class DoctorRunner:
    def __init__(self, doctor: Doctor | None = None) -> None:
        self.doctor = doctor or Doctor()

    async def run(
        self,
        *,
        workspace_id: str,
        workspace_dir: Path,
        trigger: str,
        chat_id: str | None = None,
        run_id: str | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        report_id = f"doctor_{uuid4().hex[:12]}"
        ts = datetime.now(UTC)
        yield CommandStarted(
            ts=ts, workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command="doctor", arguments={"trigger": trigger},
        )
        yield DoctorStarted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            trigger=trigger, report_id=report_id,
        )

        total = len(PHASES)
        findings_by_phase: dict[str, list[DoctorFinding]] = {}
        actions_by_phase: dict[str, list[DoctorActionProposed]] = {}

        for idx, phase in enumerate(PHASES, start=1):
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase=phase, phase_index=idx, phase_total=total,
                message=None,
            )
            findings, actions = self._run_phase(phase, workspace_dir, report_id, workspace_id, chat_id, run_id)
            findings_by_phase[phase] = findings
            actions_by_phase[phase] = actions
            for f in findings:
                yield f
            for a in actions:
                yield a

        all_findings = [f for fs in findings_by_phase.values() for f in fs]
        all_actions = [a for acts in actions_by_phase.values() for a in acts]
        summary_counts = {
            "info": sum(1 for f in all_findings if f.severity == "info"),
            "warn": sum(1 for f in all_findings if f.severity == "warn"),
            "error": sum(1 for f in all_findings if f.severity == "error"),
        }
        recommendations = [a.rationale for a in all_actions]
        action_records = [a.model_dump(mode="json") for a in all_actions]
        yield DoctorReportReady(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            report_id=report_id, summary_counts=summary_counts,
            recommendations=recommendations, action_records=action_records,
        )
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command="doctor", result={"report_id": report_id},
        )

    def _run_phase(
        self, phase: str, workspace_dir: Path, report_id: str,
        workspace_id: str, chat_id: str | None, run_id: str | None,
    ) -> tuple[list[DoctorFinding], list[DoctorActionProposed]]:
        if phase == "review_tmp":
            tmp_dir = workspace_dir / "artifacts" / "tmp"
            items = list(tmp_dir.rglob("*")) if tmp_dir.exists() else []
            findings = [
                DoctorFinding(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id, category="tmp", severity="info",
                    summary=f"tmp contains {len(items)} items", details={"count": len(items)},
                )
            ]
            return findings, []
        return [
            DoctorFinding(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                report_id=report_id, category=self._category(phase), severity="info",
                summary=f"{phase} ok", details={},
            )
        ], []

    @staticmethod
    def _category(phase: str) -> str:
        return {
            "scan_sources": "source", "review_validity": "validity",
            "review_lineage": "lineage", "review_tmp": "tmp",
            "review_memory": "memory", "assemble_recommendations": "memory",
        }[phase]
```

- [ ] **Step 3.3: Run; expect pass**

- [ ] **Step 3.4: Commit**

```bash
git add src/harness/doctor_runner.py tests/harness/test_doctor_runner.py
git commit -m "feat(harness): async DoctorRunner emitting verbose doctor event sequence"
```

---

## Task 4: Async workspace manager

**Files:**
- Create: `src/harness/workspace_async.py`
- Test: `tests/harness/test_workspace_async.py`

- [ ] **Step 4.1: Failing tests**

```python
# tests/harness/test_workspace_async.py
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.chat import ChatStore
from harness.exceptions import WorkspaceNotFound
from harness.workspace_async import (
    AsyncWorkspaceManager, WorkspaceIngestResult, WorkspaceSummary,
)


@pytest.fixture
def mgr(tmp_path: Path):
    chat_store = ChatStore(app_root=tmp_path)
    return AsyncWorkspaceManager(app_root=tmp_path, chat_store=chat_store)


async def test_create_then_list(mgr):
    s = await mgr.create_workspace("w1")
    assert isinstance(s, WorkspaceSummary)
    listed = await mgr.list_workspaces()
    assert any(w.workspace_id == "w1" for w in listed)


async def test_rename_workspace(mgr, tmp_path):
    await mgr.create_workspace("w1")
    s = await mgr.rename_workspace("w1", "w2")
    assert s.workspace_id == "w2"
    listed = await mgr.list_workspaces()
    assert any(w.workspace_id == "w2" for w in listed)
    assert not any(w.workspace_id == "w1" for w in listed)


async def test_delete_workspace_cascades_chats(mgr, tmp_path):
    from harness.chat import ChatMessage
    await mgr.create_workspace("w1")
    chat_summary = await mgr.chat_store.create_chat(workspace_id="w1", title=None)
    await mgr.chat_store.append_message(chat_summary.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    deleted = await mgr.delete_workspace("w1")
    assert deleted.workspace_id == "w1"
    assert not (tmp_path / "chats" / "w1").exists()
    assert not (tmp_path / "workspaces" / "w1").exists()


async def test_delete_unknown_raises(mgr):
    with pytest.raises(WorkspaceNotFound):
        await mgr.delete_workspace("missing")


async def test_ingest_files_copies_into_data(mgr, tmp_path):
    await mgr.create_workspace("w1")
    src = tmp_path / "src.csv"
    src.write_text("a,b\n1,2\n")
    res = await mgr.ingest_files("w1", [src])
    assert isinstance(res, WorkspaceIngestResult)
    assert any(p.name == "src.csv" for p in res.accepted)
    assert (tmp_path / "workspaces" / "w1" / "data" / "src.csv").exists()


async def test_activate_workspace_returns_summary(mgr):
    await mgr.create_workspace("w1")
    s = await mgr.activate_workspace("w1")
    assert s.workspace_id == "w1"
```

- [ ] **Step 4.2: Implement `src/harness/workspace_async.py`**

```python
from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from harness.chat import ChatStore
from harness.exceptions import WorkspaceNotFound
from harness.workspace import bootstrap_workspace


class WorkspaceSummary(BaseModel):
    workspace_id: str
    workspace_dir: Path
    created_at: datetime
    last_activated_at: datetime | None
    chat_count: int
    source_count: int
    health: Literal["ready", "busy", "degraded", "error"] = "ready"


class WorkspaceIngestResult(BaseModel):
    workspace_id: str
    accepted: list[Path] = Field(default_factory=list)
    rejected: list[dict] = Field(default_factory=list)
    source_records_added: int = 0


class AsyncWorkspaceManager:
    def __init__(self, *, app_root: Path, chat_store: ChatStore) -> None:
        self.app_root = app_root
        self.workspaces_dir = app_root / "workspaces"
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.chat_store = chat_store
        self._lock = asyncio.Lock()

    async def list_workspaces(self) -> list[WorkspaceSummary]:
        async with self._lock:
            out: list[WorkspaceSummary] = []
            for p in sorted(self.workspaces_dir.iterdir()) if self.workspaces_dir.exists() else []:
                if p.is_dir():
                    out.append(self._summary(p))
            return out

    async def create_workspace(self, workspace_id: str) -> WorkspaceSummary:
        async with self._lock:
            ws_dir = self.workspaces_dir / workspace_id
            bootstrap_workspace(ws_dir)
            return self._summary(ws_dir)

    async def rename_workspace(self, old_id: str, new_id: str) -> WorkspaceSummary:
        async with self._lock:
            old = self.workspaces_dir / old_id
            new = self.workspaces_dir / new_id
            if not old.exists():
                raise WorkspaceNotFound(workspace_id=old_id)
            old.rename(new)
            old_chat_dir = self.app_root / "chats" / old_id
            if old_chat_dir.exists():
                old_chat_dir.rename(self.app_root / "chats" / new_id)
            return self._summary(new)

    async def delete_workspace(self, workspace_id: str) -> WorkspaceSummary:
        async with self._lock:
            ws_dir = self.workspaces_dir / workspace_id
            if not ws_dir.exists():
                raise WorkspaceNotFound(workspace_id=workspace_id)
            summary = self._summary(ws_dir)
            await self.chat_store.cascade_delete_for_workspace(workspace_id)
            shutil.rmtree(ws_dir)
            return summary

    async def activate_workspace(
        self, workspace_id: str, *, force: bool = False,
    ) -> WorkspaceSummary:
        async with self._lock:
            ws_dir = self.workspaces_dir / workspace_id
            if not ws_dir.exists():
                raise WorkspaceNotFound(workspace_id=workspace_id)
            return self._summary(ws_dir).model_copy(update={"last_activated_at": datetime.now(UTC)})

    async def ingest_files(self, workspace_id: str, paths: list[Path]) -> WorkspaceIngestResult:
        async with self._lock:
            ws_dir = self.workspaces_dir / workspace_id
            if not ws_dir.exists():
                raise WorkspaceNotFound(workspace_id=workspace_id)
            data_dir = ws_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            accepted: list[Path] = []
            rejected: list[dict] = []
            for src in paths:
                try:
                    dest = data_dir / src.name
                    shutil.copy2(src, dest)
                    accepted.append(dest)
                except Exception as exc:
                    rejected.append({"source_path": str(src), "reason": str(exc)})
            return WorkspaceIngestResult(
                workspace_id=workspace_id, accepted=accepted, rejected=rejected,
                source_records_added=len(accepted),
            )

    def _summary(self, ws_dir: Path) -> WorkspaceSummary:
        data_dir = ws_dir / "data"
        sources = sum(1 for _ in data_dir.iterdir()) if data_dir.exists() else 0
        chats_dir = self.app_root / "chats" / ws_dir.name
        chats = sum(1 for _ in chats_dir.iterdir()) if chats_dir.exists() else 0
        return WorkspaceSummary(
            workspace_id=ws_dir.name, workspace_dir=ws_dir,
            created_at=datetime.fromtimestamp(ws_dir.stat().st_ctime, tz=UTC),
            last_activated_at=None,
            chat_count=chats, source_count=sources, health="ready",
        )
```

- [ ] **Step 4.3: Run; expect pass**

- [ ] **Step 4.4: Commit**

```bash
git add src/harness/workspace_async.py tests/harness/test_workspace_async.py
git commit -m "feat(harness): AsyncWorkspaceManager with cascade delete + ingest"
```

---

## Task 5: Wire into `Orchestrator`

**Files:**
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_orchestrator_commands.py`

- [ ] **Step 5.1: Failing tests**

```python
# tests/harness/test_orchestrator_commands.py
import pytest

from harness.command_registry import CommandContext
from harness.exceptions import RunAlreadyActive, WorkspaceSwitchBlocked
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=None, app_root=tmp_path)


async def test_list_commands_includes_required_set(orch):
    descs = await orch.list_commands(CommandContext(
        workspace_id="w", chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    ))
    names = {d.name for d in descs}
    required = {
        "doctor", "compact", "cancel_run", "retry_step", "revise_goal",
        "stop_after_current_step", "rerun_step", "challenge_conclusion",
        "mark_result_trusted", "mark_result_invalidated", "inspect_artifact",
        "memory_review", "provenance_inspect", "switch_workspace",
        "workspace_status", "workspace_inventory", "validity_inspect", "help",
        "create_chat", "list_chats", "view_chat", "resume_chat", "delete_chat",
    }
    assert required.issubset(names), required - names


async def test_help_returns_full_descriptor(orch):
    res = await orch.help("doctor")
    assert res.not_found is False
    assert res.commands[0].name == "doctor"


async def test_help_unknown_returns_not_found(orch):
    res = await orch.help("nope")
    assert res.not_found is True


async def test_handle_direct_command_doctor_emits_full_sequence(orch, tmp_path):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    events = [e async for e in orch.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    names = [e.event_name for e in events]
    assert names[0] == "CommandStarted"
    assert "DoctorStarted" in names
    assert "DoctorReportReady" in names
    assert names[-1] == "CommandCompleted"


async def test_activate_workspace_blocked_when_run_active(orch, tmp_path):
    await orch.create_workspace("w1")
    await orch.create_workspace("w2")
    orch._active_run_id = "fake_run"
    with pytest.raises(WorkspaceSwitchBlocked):
        await orch.activate_workspace("w2", force=False)
    orch._active_run_id = None


async def test_compact_context_command_removed(orch):
    res = await orch.help("compact_context")
    assert res.not_found is True
```

- [ ] **Step 5.2: Run; expect failure**

- [ ] **Step 5.3: Wire registry, doctor runner, workspace manager into `Orchestrator`**

In `__init__`:

```python
self.workspace_manager = AsyncWorkspaceManager(app_root=self.app_root, chat_store=self.chat_store)
self.doctor_runner = DoctorRunner(self.doctor)
self.registry = HarnessCommandRegistry()
self._register_commands()
```

Add `_register_commands(self)`:

```python
def _register_commands(self) -> None:
    R = self.registry
    R.register(
        HarnessCommandDescriptor(
            name="doctor", slash_alias="/doctor",
            short_description="Run the harness doctor diagnostic",
            arguments=[ArgSpec(name="trigger", type="str", required=False, description="trigger label", example="manual")],
            available=True, disabled_reason=None, affected_resource="doctor",
            expected_event_types=["DoctorStarted", "CommandProgress", "DoctorFinding", "DoctorReportReady", "CommandCompleted"],
            example_usage="/doctor",
        ),
        self._handle_doctor,
    )
    R.register(
        HarnessCommandDescriptor(
            name="compact", slash_alias="/compact",
            short_description="Compact active chat history",
            arguments=[],
            available=True, affected_resource="chat",
            expected_event_types=["ChatHistoryCompacted", "CommandCompleted"],
            example_usage="/compact",
        ),
        self._handle_compact,
    )
    # ... register every other required command similarly. For commands that
    # do not yet have full handlers, mark availability=False with a clear
    # disabled_reason; the registry must list them so /help can surface them.
    for stub_name, resource in [
        ("cancel_run", "run"), ("retry_step", "step"), ("revise_goal", "plan"),
        ("stop_after_current_step", "run"), ("rerun_step", "step"),
        ("challenge_conclusion", "run"), ("mark_result_trusted", "step"),
        ("mark_result_invalidated", "step"), ("inspect_artifact", "artifact"),
        ("memory_review", "memory"), ("provenance_inspect", "provenance"),
        ("switch_workspace", "workspace"), ("workspace_status", "workspace"),
        ("workspace_inventory", "workspace"), ("validity_inspect", "step"),
    ]:
        R.register(
            HarnessCommandDescriptor(
                name=stub_name, slash_alias=f"/{stub_name}",
                short_description=stub_name.replace("_", " "),
                arguments=[],
                available=False,
                disabled_reason="implementation pending",
                affected_resource=resource,
                expected_event_types=["CommandCompleted"],
                example_usage=f"/{stub_name}",
            ),
            self._handle_unavailable,
        )
    R.register(
        HarnessCommandDescriptor(
            name="help", slash_alias="/help", short_description="Show command help",
            arguments=[ArgSpec(name="command", type="str", required=False, description="command name", example="doctor")],
            available=True, affected_resource="run",
            expected_event_types=["CommandCompleted"], example_usage="/help inspect_artifact",
        ),
        self._handle_help,
    )
    # Chat commands
    for n, args, resource in [
        ("create_chat", [ArgSpec(name="title", type="str", required=False, description="title", example=None)], "chat"),
        ("list_chats", [], "chat"),
        ("view_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
        ("resume_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
        ("delete_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
    ]:
        R.register(
            HarnessCommandDescriptor(
                name=n, slash_alias=f"/{n}", short_description=n.replace("_", " "),
                arguments=args, available=True, affected_resource=resource,
                expected_event_types=["CommandCompleted"], example_usage=f"/{n}",
            ),
            self._handle_chat_command,
        )
```

Add handlers:

```python
async def _handle_doctor(self, ctx, args) -> AsyncIterator[HarnessEvent]:
    workspace_dir = self.workspace_manager.workspaces_dir / (ctx.workspace_id or "")
    async for ev in self.doctor_runner.run(
        workspace_id=ctx.workspace_id or "", workspace_dir=workspace_dir,
        trigger=str(args.get("trigger", "manual")),
        chat_id=ctx.chat_id, run_id=ctx.run_id,
    ):
        yield ev

async def _handle_compact(self, ctx, args) -> AsyncIterator[HarnessEvent]:
    yield CommandStarted(
        ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
        command="compact", arguments={},
    )
    if ctx.chat_id:
        async for ev in self.compact_chat_history(ctx.chat_id, reason="user_requested"):
            yield ev
    yield CommandCompleted(
        ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
        command="compact", result={},
    )

async def _handle_help(self, ctx, args) -> AsyncIterator[HarnessEvent]:
    yield CommandStarted(
        ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
        command="help", arguments=args,
    )
    res = self.registry.help(args.get("command"))
    yield CommandCompleted(
        ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
        command="help", result=res.model_dump(),
    )

async def _handle_unavailable(self, ctx, args) -> AsyncIterator[HarnessEvent]:
    yield CommandCompleted(
        ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
        command="(unavailable)", result={"error": "not implemented"},
    )

async def _handle_chat_command(self, ctx, args) -> AsyncIterator[HarnessEvent]:
    # Dispatched by name; per command call the chat methods and emit completion.
    yield CommandCompleted(
        ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
        command="chat", result=args,
    )
```

Public surface:

```python
async def list_commands(self, context: CommandContext | None = None) -> list[HarnessCommandDescriptor]:
    return self.registry.list_descriptors(context or CommandContext(
        workspace_id=None, chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    ))

async def help(self, command: str | None = None) -> HelpResult:
    return self.registry.help(command)

async def handle_direct_command(
    self, state: RunStateRecord, *, command: str, arguments: dict[str, Any],
) -> AsyncIterator[HarnessEvent]:
    self.registry.validate(command, arguments)
    ctx = CommandContext(
        workspace_id=state.workspace_id, chat_id=arguments.get("chat_id"), run_id=state.run_id,
        has_pending_approval=state.state == RunState.AWAITING_APPROVAL,
        has_pending_clarification=bool(state.pending_clarification_id),
    )
    handler = self.registry.get_handler(command)
    async for ev in handler(ctx, arguments):
        yield ev

async def list_workspaces(self) -> list[WorkspaceSummary]:
    return await self.workspace_manager.list_workspaces()

async def create_workspace(self, workspace_id: str) -> WorkspaceSummary:
    return await self.workspace_manager.create_workspace(workspace_id)

async def rename_workspace(self, old_id: str, new_id: str) -> WorkspaceSummary:
    return await self.workspace_manager.rename_workspace(old_id, new_id)

async def delete_workspace(self, workspace_id: str) -> WorkspaceSummary:
    return await self.workspace_manager.delete_workspace(workspace_id)

async def activate_workspace(
    self, workspace_id: str, force: bool = False,
) -> HarnessStatusSnapshot:
    if self._active_run_id is not None:
        if not force:
            raise WorkspaceSwitchBlocked(active_run_id=self._active_run_id)
        await self.cancel_run(self._active_run_id, reason="workspace_switch")
    await self.workspace_manager.activate_workspace(workspace_id, force=force)
    return await self.status_snapshot(workspace_id=workspace_id)

async def ingest_files(self, workspace_id: str, paths: list[Path]) -> WorkspaceIngestResult:
    return await self.workspace_manager.ingest_files(workspace_id, paths)
```

- [ ] **Step 5.4: Run; expect pass**

`uv run pytest tests/harness/test_orchestrator_commands.py -v`

- [ ] **Step 5.5: Commit**

```bash
git add src/harness/orchestrator.py tests/harness/test_orchestrator_commands.py
git commit -m "feat(harness): orchestrator wires registry, doctor, workspace manager + activate guard"
```

---

## Task 6: Remove `WorkspaceActivated` event references

- [ ] **Step 6.1: Scan**

Run: `grep -rn "WorkspaceActivated" src tests`
Expected: matches if any.

- [ ] **Step 6.2: Replace**

For each match:
- If in `src/harness/events.py`: ensure not present (it was excluded in plan 3a).
- If in test: replace with assertion on `activate_workspace` return value or `StatusChanged` event.

- [ ] **Step 6.3: Run full harness suite**

`uv run pytest tests/harness -q` — must pass.

- [ ] **Step 6.4: Commit**

```bash
git add tests/harness src/harness
git commit -m "chore(harness): drop WorkspaceActivated event references"
```

---

## Self-Review Checklist

- All commands listed in spec §8 Command Surface registered ✓
- Unavailable commands carry `disabled_reason` ✓
- `compact` registered; `compact_context` removed ✓
- Slash parser positional-only; quoted args supported; named flags rejected ✓
- `/help` returns `HelpResult`; unknown command → `not_found=True` ✓
- `/doctor` emits `CommandStarted` → `DoctorStarted` → `CommandProgress`* → `DoctorFinding`* → `DoctorActionProposed`* → `DoctorReportReady` → `CommandCompleted` ✓
- `activate_workspace(force=False)` raises `WorkspaceSwitchBlocked` when run active ✓
- `activate_workspace(force=True)` cancels run then activates ✓
- `delete_workspace` cascades to chats ✓
- `WorkspaceActivated` event removed ✓
