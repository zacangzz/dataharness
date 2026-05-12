# Layer 3b — Chat Sessions, Persistence, Runtime Request Assembly, Compaction

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-01-async-layered-architecture-design.md` §8 Chat Management, Runtime Request Assembly, Chat Compaction.

**Goal:** Make chats first-class harness records persisted under `<app_root>/chats/<workspace_id>/<chat_id>/`, integrated into runtime requests so prior turns flow back into the model. Lazy creation on first user message. Resume from disk. Workspace-deletion cascade. Token-pressure-driven compaction with status events. Explicit `/compact` queues behind in-flight runtime stream.

**Architecture:** New `harness.chat` module owns `ChatSession`, `ChatStore`, `RuntimeRequestBuilder`, and `ChatCompactor`. `ChatStore` writes `metadata.json`, `messages.jsonl`, `compactions.jsonl` lazily on first message. `Orchestrator` gains chat-aware methods (`list_chats`, `create_chat`, `view_chat`, `resume_chat`, `delete_chat`, `compact_chat_history`) that use the store. `run_turn` consults `RuntimeRequestBuilder` to assemble the prompt with active-mode system + durable workspace context + chat summary + recent turns + current user message, honoring 25% completion reserve and 80% compaction trigger.

**Tech Stack:** Python 3.12, `asyncio`, `pydantic` 2.x, `pytest-asyncio`.

---

## File Structure

- `src/harness/chat.py` — **new**: `ChatMessage`, `ChatRecord`, `ChatSummary`, `ChatDeleteResult`, `ChatStore`, `ChatSession`, `RuntimeRequestBuilder`, `ChatCompactor`.
- `src/harness/orchestrator.py` — extend with chat methods, plumb `RuntimeRequestBuilder` into `run_turn`.
- `src/harness/workspace.py` — `WorkspaceManager.delete_workspace(...)` cascades to `<app_root>/chats/<workspace_id>/` (full implementation lives in plan 3c; this plan only declares the interface and updates `ChatStore.cascade_delete_for_workspace`).
- `tests/harness/test_chat_store.py` — **new**.
- `tests/harness/test_chat_session_persistence.py` — **new**.
- `tests/harness/test_runtime_request_builder.py` — **new**.
- `tests/harness/test_chat_compaction.py` — **new**.
- `tests/harness/test_orchestrator_chat_integration.py` — **new**.

---

## Prep

- [ ] **Step 0.1: Verify plan 3a complete**

Run: `uv run pytest tests/harness -q`
Expected: PASS.

---

## Task 1: Chat schemas + store

**Files:**
- Create: `src/harness/chat.py`
- Test: `tests/harness/test_chat_store.py`

- [ ] **Step 1.1: Failing tests**

```python
# tests/harness/test_chat_store.py
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.chat import ChatMessage, ChatStore, ChatSummary
from harness.exceptions import ChatNotFound


@pytest.fixture
def store(tmp_path: Path):
    return ChatStore(app_root=tmp_path)


async def test_create_chat_does_not_write_to_disk(store, tmp_path):
    summary = await store.create_chat(workspace_id="w1", title="t")
    assert summary.workspace_id == "w1"
    assert summary.message_count == 0
    chat_dir = tmp_path / "chats" / "w1" / summary.chat_id
    assert not chat_dir.exists()


async def test_first_message_creates_files(store, tmp_path):
    summary = await store.create_chat(workspace_id="w1", title=None)
    msg = ChatMessage(
        message_id="m1", role="user", text="hi",
        ts=datetime.now(UTC), turn_id="t1", active_mode="analyst", token_estimate=1,
    )
    await store.append_message(summary.chat_id, msg)
    chat_dir = tmp_path / "chats" / "w1" / summary.chat_id
    assert (chat_dir / "metadata.json").exists()
    assert (chat_dir / "messages.jsonl").exists()


async def test_view_chat_returns_full_record(store):
    summary = await store.create_chat(workspace_id="w1", title="t")
    msg = ChatMessage(message_id="m1", role="user", text="hi", ts=datetime.now(UTC),
                      turn_id="t1", active_mode="m", token_estimate=1)
    await store.append_message(summary.chat_id, msg)
    rec = await store.view_chat(summary.chat_id)
    assert rec.chat_id == summary.chat_id
    assert len(rec.messages) == 1
    assert rec.messages[0].text == "hi"


async def test_view_chat_unknown_raises_chat_not_found(store):
    with pytest.raises(ChatNotFound):
        await store.view_chat("missing")


async def test_list_chats_filters_by_workspace(store):
    a = await store.create_chat(workspace_id="w1", title=None)
    await store.append_message(a.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    b = await store.create_chat(workspace_id="w2", title=None)
    await store.append_message(b.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    listed_w1 = await store.list_chats("w1")
    assert {s.chat_id for s in listed_w1} == {a.chat_id}


async def test_delete_chat_removes_files(store, tmp_path):
    s = await store.create_chat(workspace_id="w1", title=None)
    await store.append_message(s.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    chat_dir = tmp_path / "chats" / "w1" / s.chat_id
    assert chat_dir.exists()
    result = await store.delete_chat(s.chat_id)
    assert result.deleted is True
    assert result.files_removed >= 2
    assert not chat_dir.exists()


async def test_cascade_delete_for_workspace(store, tmp_path):
    a = await store.create_chat(workspace_id="w1", title=None)
    await store.append_message(a.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    b = await store.create_chat(workspace_id="w1", title=None)
    await store.append_message(b.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    removed = await store.cascade_delete_for_workspace("w1")
    assert {r.chat_id for r in removed} == {a.chat_id, b.chat_id}
    assert not (tmp_path / "chats" / "w1").exists()
```

- [ ] **Step 1.2: Run; expect failure**

- [ ] **Step 1.3: Implement `src/harness/chat.py`**

```python
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from harness.exceptions import ChatNotFound, ChatWorkspaceMismatch
from runtime.types import RuntimeMessage


class ChatMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "compacted_summary"]
    text: str
    ts: datetime
    turn_id: str | None
    active_mode: str | None
    token_estimate: int


class ChatRecord(BaseModel):
    chat_id: str
    workspace_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    last_active_mode: str | None
    last_run_id: str | None
    message_count: int
    token_estimate: int
    last_compacted_at: datetime | None
    compaction_count: int
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatSummary(BaseModel):
    chat_id: str
    workspace_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    token_estimate: int
    last_compacted_at: datetime | None


class ChatDeleteResult(BaseModel):
    chat_id: str
    workspace_id: str
    deleted: bool
    files_removed: int


def _new_chat_id() -> str:
    return f"chat_{uuid4().hex[:12]}"


def _estimate_tokens(text: str) -> int:
    return max(len(text) // 4, 1)


class ChatStore:
    """Workspace-scoped chat persistence under <app_root>/chats/<workspace_id>/<chat_id>/."""

    def __init__(self, app_root: Path) -> None:
        self.app_root = app_root
        self._chats_dir = app_root / "chats"
        self._lock = asyncio.Lock()
        # Pending (lazy) chats not yet flushed to disk.
        self._pending: dict[str, ChatRecord] = {}

    def _chat_dir(self, workspace_id: str, chat_id: str) -> Path:
        return self._chats_dir / workspace_id / chat_id

    async def create_chat(self, *, workspace_id: str, title: str | None) -> ChatSummary:
        chat_id = _new_chat_id()
        now = datetime.now(UTC)
        rec = ChatRecord(
            chat_id=chat_id, workspace_id=workspace_id, title=title,
            created_at=now, updated_at=now,
            last_active_mode=None, last_run_id=None,
            message_count=0, token_estimate=0,
            last_compacted_at=None, compaction_count=0, messages=[],
        )
        async with self._lock:
            self._pending[chat_id] = rec
        return self._summary(rec)

    async def append_message(self, chat_id: str, message: ChatMessage) -> None:
        async with self._lock:
            rec = await self._load_record(chat_id)
            rec.messages.append(message)
            rec.message_count += 1
            rec.token_estimate += message.token_estimate
            rec.updated_at = datetime.now(UTC)
            if message.active_mode:
                rec.last_active_mode = message.active_mode
            await self._flush_record(rec)

    async def append_compaction(
        self, chat_id: str, *, summary_text: str, replaced_turn_count: int, token_estimate: int,
    ) -> ChatMessage:
        marker = ChatMessage(
            message_id=f"sum_{uuid4().hex[:12]}", role="compacted_summary",
            text=summary_text, ts=datetime.now(UTC),
            turn_id=None, active_mode=None, token_estimate=token_estimate,
        )
        async with self._lock:
            rec = await self._load_record(chat_id)
            rec.messages = [marker] + rec.messages[replaced_turn_count:]
            rec.message_count = len(rec.messages)
            rec.token_estimate = sum(m.token_estimate for m in rec.messages)
            rec.last_compacted_at = datetime.now(UTC)
            rec.compaction_count += 1
            rec.updated_at = datetime.now(UTC)
            await self._flush_record(rec)
            chat_dir = self._chat_dir(rec.workspace_id, rec.chat_id)
            line = json.dumps({
                "ts": datetime.now(UTC).isoformat(),
                "summary_text": summary_text,
                "replaced_turn_count": replaced_turn_count,
                "summary_token_estimate": token_estimate,
            }) + "\n"
            (chat_dir / "compactions.jsonl").open("a").write(line)
        return marker

    async def view_chat(self, chat_id: str) -> ChatRecord:
        async with self._lock:
            return await self._load_record(chat_id)

    async def list_chats(self, workspace_id: str) -> list[ChatSummary]:
        async with self._lock:
            ws_dir = self._chats_dir / workspace_id
            summaries: list[ChatSummary] = []
            if ws_dir.exists():
                for chat_dir in sorted(ws_dir.iterdir()):
                    meta = chat_dir / "metadata.json"
                    if not meta.exists():
                        continue
                    rec = ChatRecord.model_validate_json(meta.read_text())
                    summaries.append(self._summary(rec))
            return summaries

    async def delete_chat(self, chat_id: str) -> ChatDeleteResult:
        async with self._lock:
            pending = self._pending.pop(chat_id, None)
            if pending is not None:
                return ChatDeleteResult(
                    chat_id=chat_id, workspace_id=pending.workspace_id,
                    deleted=True, files_removed=0,
                )
            for ws_dir in self._chats_dir.iterdir() if self._chats_dir.exists() else []:
                cdir = ws_dir / chat_id
                if cdir.exists():
                    files = sum(1 for _ in cdir.rglob("*") if _.is_file())
                    shutil.rmtree(cdir)
                    return ChatDeleteResult(
                        chat_id=chat_id, workspace_id=ws_dir.name,
                        deleted=True, files_removed=files,
                    )
            raise ChatNotFound(chat_id=chat_id)

    async def cascade_delete_for_workspace(self, workspace_id: str) -> list[ChatDeleteResult]:
        async with self._lock:
            results: list[ChatDeleteResult] = []
            ws_dir = self._chats_dir / workspace_id
            if ws_dir.exists():
                for cdir in sorted(ws_dir.iterdir()):
                    if cdir.is_dir():
                        files = sum(1 for _ in cdir.rglob("*") if _.is_file())
                        results.append(ChatDeleteResult(
                            chat_id=cdir.name, workspace_id=workspace_id,
                            deleted=True, files_removed=files,
                        ))
                shutil.rmtree(ws_dir)
            for chat_id, rec in list(self._pending.items()):
                if rec.workspace_id == workspace_id:
                    self._pending.pop(chat_id)
                    results.append(ChatDeleteResult(
                        chat_id=chat_id, workspace_id=workspace_id,
                        deleted=True, files_removed=0,
                    ))
            return results

    def _summary(self, rec: ChatRecord) -> ChatSummary:
        return ChatSummary(
            chat_id=rec.chat_id, workspace_id=rec.workspace_id, title=rec.title,
            created_at=rec.created_at, updated_at=rec.updated_at,
            message_count=rec.message_count, token_estimate=rec.token_estimate,
            last_compacted_at=rec.last_compacted_at,
        )

    async def _load_record(self, chat_id: str) -> ChatRecord:
        if chat_id in self._pending:
            return self._pending[chat_id]
        if self._chats_dir.exists():
            for ws_dir in self._chats_dir.iterdir():
                meta = ws_dir / chat_id / "metadata.json"
                if meta.exists():
                    rec = ChatRecord.model_validate_json(meta.read_text())
                    msgs_path = ws_dir / chat_id / "messages.jsonl"
                    if msgs_path.exists():
                        rec.messages = [
                            ChatMessage.model_validate_json(line)
                            for line in msgs_path.read_text().splitlines() if line.strip()
                        ]
                    return rec
        raise ChatNotFound(chat_id=chat_id)

    async def _flush_record(self, rec: ChatRecord) -> None:
        chat_dir = self._chat_dir(rec.workspace_id, rec.chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        meta = rec.model_copy(update={"messages": []})  # metadata excludes messages
        (chat_dir / "metadata.json").write_text(meta.model_dump_json(indent=2))
        (chat_dir / "messages.jsonl").write_text(
            "\n".join(m.model_dump_json() for m in rec.messages) + ("\n" if rec.messages else "")
        )
        self._pending.pop(rec.chat_id, None)
```

- [ ] **Step 1.4: Run; expect pass**

- [ ] **Step 1.5: Commit**

```bash
git add src/harness/chat.py tests/harness/test_chat_store.py
git commit -m "feat(harness): ChatStore with lazy create + cascade delete + jsonl persistence"
```

---

## Task 2: `RuntimeRequestBuilder`

**Files:**
- Modify: `src/harness/chat.py` (append builder class)
- Test: `tests/harness/test_runtime_request_builder.py`

- [ ] **Step 2.1: Failing tests**

```python
# tests/harness/test_runtime_request_builder.py
from datetime import UTC, datetime

from harness.chat import (
    ChatMessage, ChatRecord, RuntimeRequestBuilder,
)


def make_msg(role, text, mode=None):
    return ChatMessage(
        message_id="m", role=role, text=text, ts=datetime.now(UTC),
        turn_id=None, active_mode=mode, token_estimate=max(len(text)//4, 1),
    )


def make_record(messages):
    return ChatRecord(
        chat_id="c", workspace_id="w", title=None,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        last_active_mode=None, last_run_id=None,
        message_count=len(messages),
        token_estimate=sum(m.token_estimate for m in messages),
        last_compacted_at=None, compaction_count=0, messages=messages,
    )


def test_builder_includes_system_then_durable_then_chat_then_user():
    b = RuntimeRequestBuilder(context_window=4096)
    msgs = b.build_messages(
        active_mode_prompt="ANALYST",
        durable_context="MEMORY",
        chat_record=make_record([
            make_msg("user", "first"), make_msg("assistant", "answer"),
        ]),
        current_user_text="latest",
    )
    roles = [m.role for m in msgs]
    contents = [m.content for m in msgs]
    assert roles[0] == "system" and "ANALYST" in contents[0]
    assert any("MEMORY" in c for c in contents)
    assert msgs[-1].role == "user" and msgs[-1].content == "latest"


def test_builder_keeps_recent_8_turns_only():
    older = [make_msg("user" if i % 2 == 0 else "assistant", f"old{i}") for i in range(20)]
    b = RuntimeRequestBuilder(context_window=4096)
    msgs = b.build_messages(
        active_mode_prompt="P", durable_context="",
        chat_record=make_record(older), current_user_text="now",
    )
    user_msgs = [m for m in msgs if m.role == "user"]
    # 8 recent (4u/4a) + final user input
    assert sum(1 for m in user_msgs if m.content != "now") <= 4


def test_builder_respects_completion_reservation_25_pct():
    b = RuntimeRequestBuilder(context_window=1000)
    assert b.completion_reservation == 250


def test_builder_includes_compacted_summary_marker():
    msgs_in = [
        make_msg("compacted_summary", "OLD-SUMMARY"),
        make_msg("user", "after"),
        make_msg("assistant", "ok"),
    ]
    b = RuntimeRequestBuilder(context_window=4096)
    msgs = b.build_messages(
        active_mode_prompt="P", durable_context="",
        chat_record=make_record(msgs_in), current_user_text="now",
    )
    assert any("OLD-SUMMARY" in m.content for m in msgs if m.role == "system")
```

- [ ] **Step 2.2: Run; expect failure**

- [ ] **Step 2.3: Add `RuntimeRequestBuilder` to `src/harness/chat.py`**

```python
class RuntimeRequestBuilder:
    def __init__(
        self,
        context_window: int,
        *,
        completion_reserve_pct: float = 0.25,
        durable_pct: float = 0.30,
        summary_pct: float = 0.15,
        recent_pct: float = 0.25,
        recent_turns_kept: int = 8,
    ) -> None:
        self.context_window = context_window
        self.completion_reservation = int(context_window * completion_reserve_pct)
        self.durable_budget = int((context_window - self.completion_reservation) * (durable_pct / 0.75))
        self.summary_budget = int((context_window - self.completion_reservation) * (summary_pct / 0.75))
        self.recent_budget = int((context_window - self.completion_reservation) * (recent_pct / 0.75))
        self.recent_turns_kept = recent_turns_kept

    @staticmethod
    def _truncate(text: str, max_tokens: int) -> str:
        max_chars = max_tokens * 4
        return text if len(text) <= max_chars else text[-max_chars:]

    def build_messages(
        self,
        *,
        active_mode_prompt: str,
        durable_context: str,
        chat_record: ChatRecord | None,
        current_user_text: str,
    ) -> list[RuntimeMessage]:
        out: list[RuntimeMessage] = [RuntimeMessage(role="system", content=active_mode_prompt)]
        if durable_context.strip():
            out.append(RuntimeMessage(
                role="system",
                content=self._truncate(f"WORKSPACE CONTEXT:\n{durable_context}", self.durable_budget),
            ))
        if chat_record is not None and chat_record.messages:
            summaries = [m for m in chat_record.messages if m.role == "compacted_summary"]
            recent = [m for m in chat_record.messages if m.role != "compacted_summary"][-self.recent_turns_kept:]
            for s in summaries:
                out.append(RuntimeMessage(
                    role="system",
                    content=self._truncate(f"PRIOR CHAT SUMMARY:\n{s.text}", self.summary_budget),
                ))
            for m in recent:
                role = "user" if m.role == "user" else "assistant"
                out.append(RuntimeMessage(role=role, content=m.text))
        out.append(RuntimeMessage(role="user", content=current_user_text))
        return out
```

- [ ] **Step 2.4: Run; expect pass**

- [ ] **Step 2.5: Commit**

```bash
git add src/harness/chat.py tests/harness/test_runtime_request_builder.py
git commit -m "feat(harness): RuntimeRequestBuilder with 25% completion reserve and recent-8-turn policy"
```

---

## Task 3: `ChatCompactor` (queues behind in-flight stream)

**Files:**
- Modify: `src/harness/chat.py` (append `ChatCompactor`)
- Test: `tests/harness/test_chat_compaction.py`

- [ ] **Step 3.1: Failing tests**

```python
# tests/harness/test_chat_compaction.py
import asyncio
from datetime import UTC, datetime

import pytest

from harness.chat import (
    ChatCompactor, ChatMessage, ChatRecord, ChatStore,
)


class FakeRuntime:
    def __init__(self): self.calls = 0
    async def status(self): return "ready"
    async def stream(self, request):
        self.calls += 1
        from runtime.types import RuntimeEvent
        yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0, text="SUMMARY: short")
        yield RuntimeEvent(type="finish", request_id=request.request_id, seq=1, finish_reason="stop", usage={})


@pytest.fixture
def store(tmp_path): return ChatStore(app_root=tmp_path)


async def test_compactor_writes_summary_marker(store):
    s = await store.create_chat(workspace_id="w", title=None)
    for i in range(20):
        await store.append_message(s.chat_id, ChatMessage(
            message_id=f"m{i}", role="user" if i%2==0 else "assistant", text=f"turn-{i}",
            ts=datetime.now(UTC), turn_id=None, active_mode=None, token_estimate=3,
        ))
    runtime = FakeRuntime()
    compactor = ChatCompactor(store=store, runtime=runtime, recent_turns_kept=8)
    statuses = []
    async for status in compactor.compact(s.chat_id, reason="user"):
        statuses.append(status)
    assert statuses[0] == "queued"
    assert statuses[-1] == "completed"
    rec = await store.view_chat(s.chat_id)
    assert any(m.role == "compacted_summary" for m in rec.messages)


async def test_compactor_serializes_with_runtime_lock(store):
    """Compaction must wait for runtime lock if a stream is active."""
    s = await store.create_chat(workspace_id="w", title=None)
    await store.append_message(s.chat_id, ChatMessage(
        message_id="m", role="user", text="hi", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    runtime = FakeRuntime()
    lock = asyncio.Lock()
    compactor = ChatCompactor(store=store, runtime=runtime, runtime_lock=lock, recent_turns_kept=8)
    await lock.acquire()
    seen_running = asyncio.Event()

    async def consume():
        async for st in compactor.compact(s.chat_id, reason="user"):
            if st == "running":
                seen_running.set()
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    assert not seen_running.is_set()
    lock.release()
    await asyncio.wait_for(task, timeout=2.0)
    assert seen_running.is_set()
```

- [ ] **Step 3.2: Run; expect failure**

- [ ] **Step 3.3: Append `ChatCompactor` to `src/harness/chat.py`**

```python
from collections.abc import AsyncIterator

from runtime.protocol import Runtime
from runtime.types import RuntimeRequest


class ChatCompactor:
    """Replaces older chat turns with a summary, queueing behind any in-flight runtime stream."""

    def __init__(
        self,
        *,
        store: ChatStore,
        runtime: Runtime | None,
        runtime_lock: asyncio.Lock | None = None,
        recent_turns_kept: int = 8,
        max_summary_tokens: int = 256,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.runtime_lock = runtime_lock or asyncio.Lock()
        self.recent_turns_kept = recent_turns_kept
        self.max_summary_tokens = max_summary_tokens

    async def compact(
        self, chat_id: str, *, reason: str,
    ) -> AsyncIterator[Literal["queued", "running", "completed", "failed"]]:
        yield "queued"
        async with self.runtime_lock:
            yield "running"
            try:
                rec = await self.store.view_chat(chat_id)
                non_summary = [m for m in rec.messages if m.role != "compacted_summary"]
                if len(non_summary) <= self.recent_turns_kept:
                    yield "completed"
                    return
                older = non_summary[: -self.recent_turns_kept]
                replaced = len(older)
                if self.runtime is None:
                    summary_text = "\n".join(f"- {m.role}: {m.text[:120]}" for m in older)
                else:
                    summary_text = await self._summarize_via_runtime(older)
                token_est = max(len(summary_text) // 4, 1)
                await self.store.append_compaction(
                    chat_id, summary_text=summary_text,
                    replaced_turn_count=replaced, token_estimate=token_est,
                )
                yield "completed"
            except Exception:
                yield "failed"

    async def _summarize_via_runtime(self, older: list[ChatMessage]) -> str:
        from uuid import uuid4
        joined = "\n".join(f"{m.role}: {m.text}" for m in older)
        request = RuntimeRequest(
            messages=[
                RuntimeMessage(role="system", content=(
                    "Summarize the following chat turns in 6-10 bullet points, preserving "
                    "decisions, user preferences, and outstanding tasks."
                )),
                RuntimeMessage(role="user", content=joined),
            ],
            max_completion_tokens=self.max_summary_tokens,
            request_id=f"req_compact_{uuid4().hex[:8]}",
        )
        chunks: list[str] = []
        async for ev in self.runtime.stream(request):
            if ev.type == "text_delta":
                chunks.append(ev.text or "")
        return "".join(chunks).strip() or "(empty summary)"
```

Add `from typing import Literal` import if missing.

- [ ] **Step 3.4: Run; expect pass**

- [ ] **Step 3.5: Commit**

```bash
git add src/harness/chat.py tests/harness/test_chat_compaction.py
git commit -m "feat(harness): ChatCompactor queues behind runtime lock; emits queued/running/completed/failed"
```

---

## Task 4: Wire chat into `Orchestrator`

**Files:**
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_orchestrator_chat_integration.py`

- [ ] **Step 4.1: Failing tests**

```python
# tests/harness/test_orchestrator_chat_integration.py
import pytest

from harness.events import ChatHistoryLoaded, ChatHistoryCompacted
from harness.exceptions import ChatNotFound
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord


class FakeRuntime:
    async def context_window(self): return 4096
    async def status(self): return "ready"
    async def validate_request(self, r): return None
    async def token_pressure(self, r):
        from runtime.types import TokenPressure
        return TokenPressure(
            request_id=r.request_id, context_window=4096,
            prompt_tokens=10, reserved_completion_tokens=r.max_completion_tokens,
            total_tokens=10 + r.max_completion_tokens, pressure_ratio=0.05, over_threshold=False,
        )
    async def stream(self, r):
        from runtime.types import RuntimeEvent
        yield RuntimeEvent(type="text_delta", request_id=r.request_id, seq=0, text="ack")
        yield RuntimeEvent(type="finish", request_id=r.request_id, seq=1, finish_reason="stop", usage={})


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=FakeRuntime(), app_root=tmp_path)


def make_state():
    return RunStateRecord(workspace_id="w1", active_agent_mode="interaction")


async def collect(agen):
    return [e async for e in agen]


async def test_first_user_message_lazy_creates_chat(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    chat_dir = tmp_path / "chats" / "w1" / summary.chat_id
    assert not chat_dir.exists()
    await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input="hi",
    ))
    assert chat_dir.exists()


async def test_run_turn_emits_chat_history_loaded_for_new_chat(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    events = await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input="hi",
    ))
    chl = next(e for e in events if e.event_name == "ChatHistoryLoaded")
    assert chl.source == "new"
    assert chl.message_count == 0


async def test_resume_chat_emits_chat_history_loaded_resumed(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input="first",
    ))
    events = await collect(orch.resume_chat(summary.chat_id))
    chl = next(e for e in events if e.event_name == "ChatHistoryLoaded")
    assert chl.source == "resumed"
    assert chl.message_count >= 2  # user + assistant


async def test_chat_history_persisted_across_runs(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    await collect(orch.run_turn(state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input="first"))
    rec = await orch.view_chat(summary.chat_id)
    assert [m.role for m in rec.messages] == ["user", "assistant"]


async def test_compact_emits_chat_history_compacted_status(orch, tmp_path):
    state = make_state()
    summary = await orch.create_chat(workspace_id="w1", title=None)
    for i in range(20):
        await collect(orch.run_turn(state, workspace_dir=tmp_path, chat_id=summary.chat_id, user_input=f"msg-{i}"))
    events = await collect(orch.compact_chat_history(summary.chat_id))
    statuses = [e.status for e in events if e.event_name == "ChatHistoryCompacted"]
    assert statuses[0] == "queued"
    assert statuses[-1] == "completed"


async def test_view_chat_unknown_raises(orch):
    with pytest.raises(ChatNotFound):
        await orch.view_chat("missing")
```

- [ ] **Step 4.2: Run; expect failure**

- [ ] **Step 4.3: Extend `Orchestrator`**

In `__init__` add:

```python
self.chat_store = ChatStore(self.app_root)
self.request_builder: RuntimeRequestBuilder | None = None
self._runtime_lock = asyncio.Lock()
self.compactor: ChatCompactor | None = None
```

Add chat methods:

```python
async def create_chat(self, *, workspace_id: str, title: str | None = None) -> "ChatSummary":
    summary = await self.chat_store.create_chat(workspace_id=workspace_id, title=title)
    return summary

async def list_chats(self, workspace_id: str) -> list["ChatSummary"]:
    return await self.chat_store.list_chats(workspace_id)

async def view_chat(self, chat_id: str) -> "ChatRecord":
    return await self.chat_store.view_chat(chat_id)

async def delete_chat(self, chat_id: str) -> "ChatDeleteResult":
    return await self.chat_store.delete_chat(chat_id)

async def resume_chat(self, chat_id: str) -> AsyncIterator[HarnessEvent]:
    rec = await self.chat_store.view_chat(chat_id)
    yield ChatHistoryLoaded(
        ts=datetime.now(UTC), workspace_id=rec.workspace_id, chat_id=chat_id,
        message_count=rec.message_count, token_estimate=rec.token_estimate,
        source="resumed",
    )

async def compact_chat_history(
    self, chat_id: str, reason: str = "user_requested",
) -> AsyncIterator[HarnessEvent]:
    rec = await self.chat_store.view_chat(chat_id)
    if self.compactor is None:
        self.compactor = ChatCompactor(
            store=self.chat_store, runtime=self.runtime, runtime_lock=self._runtime_lock,
        )
    count = 0
    async for status in self.compactor.compact(chat_id, reason=reason):
        count += 1
        snapshot = await self.chat_store.view_chat(chat_id)
        yield ChatHistoryCompacted(
            ts=datetime.now(UTC), workspace_id=rec.workspace_id, chat_id=chat_id,
            status=status,
            summary_token_estimate=None,
            replaced_turn_count=None,
            compaction_count=snapshot.compaction_count,
        )
```

In `run_turn`, after `TurnStarted`:

```python
chat_record = await self.chat_store.view_chat(chat_id)
yield ChatHistoryLoaded(
    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
    message_count=chat_record.message_count, token_estimate=chat_record.token_estimate,
    source="new" if chat_record.message_count == 0 else "resumed",
)
# Append user message lazily
await self.chat_store.append_message(chat_id, ChatMessage(
    message_id=user_msg_id, role="user", text=user_input,
    ts=datetime.now(UTC), turn_id=turn_id, active_mode=active_mode,
    token_estimate=max(len(user_input)//4, 1),
))
```

Replace the in-line `RuntimeRequest` construction with builder + runtime lock + compaction:

```python
ctx_window = await self.runtime.context_window()
if self.request_builder is None or self.request_builder.context_window != ctx_window:
    self.request_builder = RuntimeRequestBuilder(context_window=ctx_window)
durable_context = ""  # plan 3c plumbs ContextManager output here
chat_record_after_user = await self.chat_store.view_chat(chat_id)
messages = self.request_builder.build_messages(
    active_mode_prompt=prompt_text or "You are the harness.",
    durable_context=durable_context,
    chat_record=chat_record_after_user,
    current_user_text=user_input,
)
request = RuntimeRequest(
    messages=messages,
    max_completion_tokens=self.request_builder.completion_reservation,
    request_id=f"req_{uuid4().hex[:12]}",
    correlation_id=run_id,
)
pressure = await self.runtime.token_pressure(request)
if pressure.over_threshold:
    async for _ in self.compact_chat_history(chat_id, reason="token_pressure"):
        pass
    chat_record_after_compact = await self.chat_store.view_chat(chat_id)
    messages = self.request_builder.build_messages(
        active_mode_prompt=prompt_text or "You are the harness.",
        durable_context=durable_context,
        chat_record=chat_record_after_compact,
        current_user_text=user_input,
    )
    request = RuntimeRequest(
        messages=messages,
        max_completion_tokens=self.request_builder.completion_reservation,
        request_id=f"req_{uuid4().hex[:12]}",
        correlation_id=run_id,
    )

async with self._runtime_lock:
    async for ev in self.runtime.stream(request):
        ...  # same handling as plan 3a Task 5
```

After the assistant text is captured, persist it:

```python
assistant_text = "".join(buffer)
await self.chat_store.append_message(chat_id, ChatMessage(
    message_id=f"asg_{uuid4().hex[:12]}",
    role="assistant", text=assistant_text, ts=datetime.now(UTC),
    turn_id=turn_id, active_mode=active_mode,
    token_estimate=max(len(assistant_text)//4, 1),
))
yield FinalMessage(...)
```

- [ ] **Step 4.4: Run; expect pass**

`uv run pytest tests/harness/test_orchestrator_chat_integration.py -v`

- [ ] **Step 4.5: Commit**

```bash
git add src/harness/orchestrator.py tests/harness/test_orchestrator_chat_integration.py
git commit -m "feat(harness): chat-aware run_turn + chat CRUD + compaction events"
```

---

## Task 5: Workspace deletion cascade hook

**Files:**
- Modify: `src/harness/workspace.py` — add async `delete_workspace_with_chat_cascade` helper used by plan 3c.
- Test: `tests/harness/test_workspace_chat_cascade.py` (new)

- [ ] **Step 5.1: Failing test**

```python
# tests/harness/test_workspace_chat_cascade.py
from datetime import UTC, datetime
from pathlib import Path

from harness.chat import ChatMessage, ChatStore


async def test_cascade_removes_directory(tmp_path: Path):
    store = ChatStore(app_root=tmp_path)
    s = await store.create_chat(workspace_id="w42", title=None)
    await store.append_message(s.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    res = await store.cascade_delete_for_workspace("w42")
    assert len(res) == 1
    assert not (tmp_path / "chats" / "w42").exists()
```

- [ ] **Step 5.2: Run; expect pass**

(`cascade_delete_for_workspace` already implemented in Task 1.)

- [ ] **Step 5.3: Commit**

```bash
git add tests/harness/test_workspace_chat_cascade.py
git commit -m "test(harness): chat directory cascade on workspace delete"
```

---

## Self-Review Checklist

- Lazy chat creation: no files written until first message ✓
- `metadata.json`, `messages.jsonl`, `compactions.jsonl` written under `<app_root>/chats/<workspace_id>/<chat_id>/` ✓
- `view_chat` reloads from disk; `resume_chat` emits `ChatHistoryLoaded(source="resumed")` ✓
- Workspace deletion cascades chat files ✓
- Runtime request builder honors 25% completion reserve, recent-8-turn cap, summary marker as system-message ✓
- Compaction queues behind runtime lock; emits queued→running→completed/failed status events ✓
- `/compact` only writes to `<app_root>/chats`, never to `memory/` ✓
- Active chat history flows back into next runtime request ✓
- `ChatNotFound` raised for unknown chat ids ✓
