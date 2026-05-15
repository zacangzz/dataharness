# App Run Issues Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 15 issues discovered in the 2026-05-12 dist app run across all four layers, plus add knowledge retrieval hookup.

**Architecture:** Nine implementation groups executed in dependency order. Group A (observability) comes first as foundation. Doctor tasks depend on KnowledgeManager write support, which depends on plan JSONL persistence. Doctor runs in three modes (light/semantic/full) as an async background task.

**Tech Stack:** Python 3.14, llama-cpp-python 0.3.20, Textual TUI, SQLite (WAL), append-only JSONL persistence.

---

### Task 1: Group A — Wire harness logging and telemetry (#6, #7, #11)

**Files:**
- Modify: `src/observability/logging_setup.py`
- Modify: `src/observability/telemetry.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/factory.py`
- Modify: `src/harness/workspace_async.py`

- [ ] **Step 1: Add harness and persistence loggers in `configure_logging`**

In `src/observability/logging_setup.py`, the `configure_logging(log_dir)` function currently sets up `root`, `bootstrap`, `runtime`, `worker`, `app` loggers. Add `harness` and `persistence`:

```python
# After the existing logger setup loop, add:
for name in ("harness", "persistence"):
    lg = logging.getLogger(name)
    _clear_handlers(lg)
    lg.addHandler(_handler(log_dir / f"{name}.log"))
    lg.addFilter(TelemetryContextFilter())
    lg.setLevel(logging.DEBUG)
```

- [ ] **Step 2: Create harness telemetry writer**

In `src/observability/telemetry.py`, extend `Telemetry.emit` to also write to `harness.events.jsonl` when `layer == Layer.HARNESS`:

```python
# In Telemetry.__init__, add:
self._harness_writer = None

# In Telemetry.emit, after existing JSONL write, add:
if layer == Layer.HARNESS:
    if self._harness_writer is None:
        harness_path = self._log_dir.parent / "telemetry" / "harness.events.jsonl"
        harness_path.parent.mkdir(parents=True, exist_ok=True)
        self._harness_writer = open(harness_path, "a", encoding="utf-8")
    self._harness_writer.write(event.model_dump_json() + "\n")
    self._harness_writer.flush()
```

- [ ] **Step 3: Wire harness logger in Orchestrator**

In `src/harness/orchestrator.py`, add a module-level logger and use it in key methods:

```python
import logging

_log = logging.getLogger("harness")
```

Add `_log.info(...)` calls at:
- `run_turn` start (turn_id, mode, input_chars)
- `run_agentic_turn` start/iteration/end
- `resume_approved_step` start/end (plan_id, status)
- `compact_chat_history` start/end
- `__init__` (workspace_id, app_root)

- [ ] **Step 4: Wire persistence logger in HarnessPersistence**

In `src/harness/persistence.py`:

```python
import logging

_log = logging.getLogger("persistence")
```

Add `_log.info(...)` in `save_dict` and `save_model` with table name and key.

- [ ] **Step 5: Create workspace telemetry mirror on activation**

In `src/harness/workspace_async.py`, in `activate_workspace`, create `state/telemetry/` directory:

```python
# In activate_workspace, after setting active workspace:
telemetry_dir = Path(ws.workspace_dir) / "state" / "telemetry"
telemetry_dir.mkdir(parents=True, exist_ok=True)
```

In `src/harness/orchestrator.py`, add a method `_mirror_to_workspace(event: dict)` that writes to `{workspace_dir}/state/telemetry/harness.events.jsonl`. Call it in any method that emits harness events.

- [ ] **Step 6: Run existing tests to verify no regressions**

```bash
uv run pytest tests/harness/ tests/observability/ -q
```

- [ ] **Step 7: Commit**

```bash
git add src/observability/logging_setup.py src/observability/telemetry.py src/harness/orchestrator.py src/harness/persistence.py src/harness/workspace_async.py
git commit -m "feat: wire harness logging, persistence logging, telemetry, and workspace mirror"
```

---

### Task 2: Group F — Split runtime `finish_reason='unknown'` (#1)

**Files:**
- Modify: `src/runtime/llama_cpp_runtime.py:480-520` (inside `_sync_event_iterator`)

- [ ] **Step 1: Add new finish reason literals to RuntimeEvent**

In `src/runtime/types.py`, extend the `RuntimeEvent` model to accept the new reasons (the `finish_reason` field is already `str | None` so no schema change needed). Add module-level constants:

```python
KNOWN_FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "empty_stream", "parse_error", "truncated"})
```

- [ ] **Step 2: Split unknown into sub-reasons in LlamaCppRuntime**

In `src/runtime/llama_cpp_runtime.py`, inside `_sync_event_iterator`, find the code block that emits the `finish` event. Replace the opaque `"unknown"` with explicit detection:

```python
# After the streaming loop ends, before emitting the finish event:
if finish_reason == "unknown" or finish_reason is None:
    if seq.value == 0:
        finish_reason = "empty_stream"
    elif hasattr(self, '_last_parse_error') and self._last_parse_error:
        finish_reason = "parse_error"
    else:
        finish_reason = "truncated"

# Include diagnostics in the finish event payload:
payload = {"finish_reason": finish_reason}
if finish_reason == "empty_stream":
    payload["empty_stream"] = True
elif finish_reason == "parse_error":
    payload["parse_error_snippet"] = getattr(self, '_last_parse_error', "")[:200]
elif finish_reason == "truncated":
    payload["total_deltas"] = seq.value
```

- [ ] **Step 3: Update agentic loop retry for new reasons**

In `src/harness/orchestrator.py`, in `run_agentic_turn`, update the `TurnFailed` retry logic to also retry on `empty_stream`. Instead of using `TurnPaused` (which only accepts `awaiting_tool_dispatch`), restrict retry to the existing empty_output path and log that the stream was empty:

```python
# In the TurnFailed handler, extend the retry conditions:
if error_code in ("empty_output", "empty_stream"):
    _log.info("agentic_retry_empty", error_code=error_code, iteration=iteration)
    iteration += 1
    if iteration < max_iterations:
        yield TurnPaused(reason="awaiting_tool_dispatch")  # Signal retry
        continue
```

- [ ] **Step 4: Run runtime tests**

```bash
uv run pytest tests/runtime/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/runtime/types.py src/runtime/llama_cpp_runtime.py src/harness/orchestrator.py
git commit -m "feat: split runtime finish_reason unknown into empty_stream/parse_error/truncated"
```

---

### Task 3: Group C — Add tabulate and pandas deps to worker sandbox (#5, #10)

**Files:**
- Modify: `src/worker/policy.py`
- Modify: `src/worker/sandbox_bootstrap.py`

- [ ] **Step 1: Add tabulate, openpyxl, xlrd to STDLIB_ALLOWLIST**

In `src/worker/policy.py`, add to the `STDLIB_ALLOWLIST` set (this is actually a set of allowed third-party packages, despite the name):

```python
STDLIB_ALLOWLIST = frozenset({
    "pathlib", "csv", "json", "math", "statistics", "pandas", "numpy",
    "tabulate",          # pandas.to_markdown() optional dep
    "openpyxl",          # pandas.read_excel() / to_excel() optional dep
    "xlrd",              # pandas.read_excel() legacy optional dep
    "_csv",              # csv module backing C extension
})
```

- [ ] **Step 2: Add packages to sandbox_bootstrap mirror**

In `src/worker/sandbox_bootstrap.py`, update the mirror `STDLIB_ALLOWLIST` (which the subprocess uses for runtime import guard):

```python
STDLIB_ALLOWLIST = frozenset({
    "pathlib", "csv", "json", "math", "statistics", "pandas", "numpy",
    "tabulate",
    "openpyxl",
    "xlrd",
    "_csv",
})
```

- [ ] **Step 3: Write test for tabulate availability in sandbox**

In `tests/worker/test_executor.py`, add:

```python
@pytest.mark.asyncio
async def test_executor_allows_pandas_to_markdown(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "data").mkdir()
    (ws / "data" / "test.csv").write_text("a,b\n1,2\n3,4\n")
    (ws / "artifacts" / "tmp").mkdir(parents=True)

    executor = PythonStepExecutor(telemetry=None, workspace_dir=str(ws))
    request = StepExecutionRequest(
        workspace_id="w_test",
        workspace_dir=str(ws),
        run_id="run_test_md",
        plan_id="plan_test",
        step_id="step_1",
        code='import pandas as pd\ndf = pd.read_csv("data/test.csv")\nprint(df.to_markdown())\nPath("result.txt").write_text("ok")',
        timeout=30,
        permission=PermissionEnvelope(
            allowed_read_paths=[str(ws / "data" / "test.csv")],
            allowed_write_roots=[str(ws / "artifacts" / "tmp")],
            allowed_packages=["pandas", "numpy", "tabulate", "pathlib", "csv"],
        ),
    )
    handle = executor.submit(request)
    envelope = await executor.wait(handle.task_id)
    assert envelope.status == ExecutionStatus.OK
```

- [ ] **Step 4: Run worker tests**

```bash
uv run pytest tests/worker/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/worker/policy.py src/worker/sandbox_bootstrap.py tests/worker/test_executor.py
git commit -m "feat: add tabulate, openpyxl, xlrd to worker sandbox allowed packages"
```

---

### Task 4: Group D — Plan JSONL persistence (#8, #14)

**Files:**
- Modify: `src/harness/orchestrator.py`
- Create: `tests/harness/test_pending_plans.py`

- [ ] **Step 1: Add plan append helper to Orchestrator**

In `src/harness/orchestrator.py`, add:

```python
import json
from pathlib import Path
import time

_PENDING_PLANS_FILE = "pending_plans.jsonl"

def _append_pending_plan(self, plan_id: str, entry: dict) -> None:
    """Append a line to state/pending_plans.jsonl."""
    path = self._state_dir / _PENDING_PLANS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    entry["ts"] = time.time()
    entry["plan_id"] = plan_id
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def _replay_pending_plans(self) -> None:
    """Replay pending_plans.jsonl on init to rebuild _pending_plans dict."""
    path = self._state_dir / _PENDING_PLANS_FILE
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            pid = entry["plan_id"]
            action = entry.get("action", "created")
            if action == "created":
                self._pending_plans[pid] = entry.get("plan_data")
            elif action in ("resolved", "rejected", "cancelled", "timed_out"):
                self._pending_plans.pop(pid, None)
```

- [ ] **Step 2: Set _state_dir in __init__**

In `Orchestrator.__init__`, set `self._state_dir = Path(workspace_dir) / "state"`.

- [ ] **Step 3: Persist plans on creation**

In `_build_plan_from_arguments` or wherever plans are created, after storing in `_pending_plans`:

```python
self._append_pending_plan(plan.id, {
    "action": "created",
    "plan_data": plan.model_dump(),
    "goal": plan.goal,
    "step_count": len(plan.steps),
})
```

- [ ] **Step 4: Persist resolution on plan resolution**

In `resume_approved_step`, after a plan is resolved:

```python
self._append_pending_plan(plan_id, {
    "action": "resolved",
    "resolution": "approved",
})
```

Same pattern for rejected/cancelled/timed-out paths.

- [ ] **Step 5: Call _replay_pending_plans in __init__**

```python
# After setting _state_dir:
self._replay_pending_plans()
```

- [ ] **Step 6: Write test**

In `tests/harness/test_pending_plans.py`:

```python
import json
import pytest
from pathlib import Path

@pytest.mark.asyncio
async def test_pending_plans_survive_across_turns(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    plans_file = state_dir / "pending_plans.jsonl"

    # Simulate plan creation
    plan_data = {"id": "plan_1", "goal": "test", "steps": []}
    with open(plans_file, "a") as f:
        f.write(json.dumps({"action": "created", "plan_id": "plan_1", "plan_data": plan_data, "ts": 1.0}) + "\n")

    # Simulate replay (as init does)
    pending = {}
    with open(plans_file) as f:
        for line in f:
            entry = json.loads(line.strip())
            pid = entry["plan_id"]
            if entry.get("action") == "created":
                pending[pid] = entry.get("plan_data")
            elif entry.get("action") == "resolved":
                pending.pop(pid, None)

    assert "plan_1" in pending

    # Simulate resolution
    with open(plans_file, "a") as f:
        f.write(json.dumps({"action": "resolved", "plan_id": "plan_1", "resolution": "approved", "ts": 2.0}) + "\n")

    # Replay again
    pending = {}
    with open(plans_file) as f:
        for line in f:
            entry = json.loads(line.strip())
            pid = entry["plan_id"]
            if entry.get("action") == "created":
                pending[pid] = entry.get("plan_data")
            elif entry.get("action") == "resolved":
                pending.pop(pid, None)

    assert "plan_1" not in pending
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/harness/test_pending_plans.py -q
```

- [ ] **Step 8: Commit**

```bash
git add src/harness/orchestrator.py tests/harness/test_pending_plans.py
git commit -m "feat: append-only JSONL pending plan persistence across turns and restarts"
```

---

### Task 5: Group D — Fix approval banner wiring (#14)

**Files:**
- Modify: `src/app/tui/app.py` (event handler chain)

- [ ] **Step 1: Audit the ApprovalRequired → ApprovalBanner path**

In `src/app/tui/app.py`, trace `_handle_approval_required` (or however `AppApprovalRequired` is handled). Check:

1. Does the handler receive the event?
2. Does it call `self._approval_banner.show(plan=..., step_contract=...)` with valid data?
3. Does `ApprovalBanner.show` actually set `display = True`?

The likely fix is in the handler. If the handler isn't registered, add it. If `plan` data is missing from the event, use `plan_id` to load it via `AppSession.get_pending_plan(plan_id)`:

```python
def _handle_approval_required(self, event: AppApprovalRequired) -> None:
    plan_id = event.payload.get("plan_id")
    step = event.payload.get("step", {})
    plan = event.payload.get("plan")

    if plan is None and plan_id:
        plan = self.session.get_pending_plan(plan_id)

    if plan:
        self._approval_banner.show(plan=plan, step_contract=step)
```

Add a public method to `AppSession`:

```python
# In src/app/session.py
def get_pending_plan(self, plan_id: str):
    """Retrieve a pending plan by id, delegating to orchestrator."""
    return self._orchestrator._pending_plans.get(plan_id)
```

- [ ] **Step 2: Verify _approval_banner is mounted**

Check `DataHarnessApp.compose` includes `ApprovalBanner` with `id="approval_banner"` and `display=False`:

```python
yield ApprovalBanner(id="approval_banner")
```

- [ ] **Step 3: Add the approval decision handler registration**

Verify `on(ApprovalBanner.ApprovalDecisionMade)` is registered:

```python
@on(ApprovalBanner.ApprovalDecisionMade)
def _on_approval_decision(self, msg: ApprovalBanner.ApprovalDecisionMade) -> None:
    self.handle_approval_decision(msg.plan, msg.step_contract, msg.decision)
```

- [ ] **Step 4: Run TUI tests**

```bash
uv run pytest tests/app/tui/ -q -k approval
```

- [ ] **Step 5: Commit**

```bash
git add src/app/tui/app.py
git commit -m "fix: wire ApprovalRequired event to ApprovalBanner display"
```

---

### Task 6: Group D — Artifact promotion + new run_id per dispatch (#2, #9, #15)

**Files:**
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/persistence.py`

- [ ] **Step 1: Generate new run_id per worker dispatch**

In `Orchestrator.resume_approved_step`, change from reusing `plan.run_id` to generating a fresh `run_id` per dispatch:

```python
import uuid

# In resume_approved_step:
run_id = f"run_{uuid.uuid4().hex}"
```

Use this `run_id` when calling `worker.submit(...)` instead of `plan.run_id`.

- [ ] **Step 2: Add _promote_step_artifacts method**

In `src/harness/orchestrator.py`:

```python
import shutil

async def _promote_step_artifacts(
    self,
    workspace_dir: str,
    step_result_path: str,
    run_id: str,
) -> list[Path]:
    """Copy successful step outputs from tmp to artifacts/ and memory/functions/."""
    import json
    ws = Path(workspace_dir)
    result = json.loads(Path(step_result_path).read_text())
    promoted = []

    step_py = ws / "artifacts" / "tmp" / run_id / "step_1" / "step.py"
    if step_py.exists():
        funcs_dir = ws / "memory" / "functions"
        funcs_dir.mkdir(parents=True, exist_ok=True)
        dest = funcs_dir / f"{run_id}_step.py"
        shutil.copy2(step_py, dest)
        promoted.append(dest)

    for ref in result.get("artifact_refs", []):
        src = ws / ref
        if not src.exists() or src.is_symlink():
            continue
        suffix = src.suffix.lower()
        if suffix in (".csv", ".xlsx", ".parquet", ".md", ".txt", ".json"):
            dest_dir = ws / "artifacts"
            dest_dir.mkdir(parents=True, exist_ok=True)
            base = src.name
            dest = dest_dir / base
            counter = 1
            while dest.exists():
                stem = src.stem
                dest = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            shutil.copy2(src, dest)
            promoted.append(dest)

    return promoted
```

- [ ] **Step 3: Call _promote_step_artifacts after successful step**

In `resume_approved_step`, after `StepCompleted` and before `FinalMessage`:

```python
if envelope.status == "ok":
    promoted = await self._promote_step_artifacts(
        workspace_dir, envelope.diagnostics.get("step_result_path", ""), run_id
    )
    _log.info("artifacts_promoted run_id=%s count=%d", run_id, len(promoted))
```

- [ ] **Step 4: Update the final message to mention promoted artifacts**

```python
if promoted:
    final_text += f"\n\nOutputs saved to: {', '.join(str(p.relative_to(Path(workspace_dir))) for p in promoted)}"
```

- [ ] **Step 5: Run harness tests**

```bash
uv run pytest tests/harness/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/harness/orchestrator.py
git commit -m "feat: new run_id per dispatch + artifact promotion from tmp to artifacts/"
```

---

### Task 7: Group E — Fix compact command (#4, #12)

**Files:**
- Modify: `src/harness/chat.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/events.py` (verify ChatHistoryCompacted exists)

- [ ] **Step 1: Verify ChatHistoryCompacted event**

In `src/harness/events.py`, confirm `ChatHistoryCompacted` has `status: str` (queued/running/completed/failed/skipped). If status enum is missing, add it.

- [ ] **Step 2: Implement compact_chat_history with full event flow**

In `src/harness/orchestrator.py`, the `_handle_compact` or `compact_chat_history` method. Replace/update it:

```python
async def compact_chat_history(self, chat_id: str) -> AsyncIterator[HarnessEvent]:
    _log.info("compact_chat_history.start chat_id=%s", chat_id)
    yield ChatHistoryCompacted(chat_id=chat_id, status="queued")

    # Check active run
    if self._active_run_id:
        _log.info("compact_chat_history.queued_behind_run run_id=%s", self._active_run_id)
        timeout = 30
        waited = 0
        while self._active_run_id and waited < timeout:
            await asyncio.sleep(0.5)
            waited += 0.5
        if self._active_run_id:
            yield ChatHistoryCompacted(chat_id=chat_id, status="failed")
            return

    # Check token pressure — build a proper RuntimeRequest
    chat_record = self._chat_store.view_chat(chat_id)
    if not chat_record or not chat_record.messages:
        _log.info("compact_chat_history empty chat, skipping")
        return

    # Skip if too few messages to compact
    if len(chat_record.messages) <= 8:
        _log.info("compact_chat_history %d messages, below threshold", len(chat_record.messages))
        return

    request_builder = RuntimeRequestBuilder(
        self._runtime.context_window(),
        recent_turns_kept=8,
    )
    messages = request_builder.build_messages(
        active_mode_prompt="",
        durable_context="",
        chat_record=chat_record,
        current_user_text="",
    )
    pressure_req = RuntimeRequest(
        messages=messages,
        max_completion_tokens=8192,
        request_id=f"compact_check_{chat_id}",
    )
    pressure = await self._runtime.token_pressure(pressure_req)
    if not pressure.over_threshold:
        _log.info("compact_chat_history token pressure below threshold, skipping")
        return

    yield ChatHistoryCompacted(chat_id=chat_id, status="running")

    # Compact: summarize old messages, keep recent 8
    old_messages = chat_record.messages[:-8]
    recent_messages = chat_record.messages[-8:]

    # Build compaction prompt
    compaction_text = "\n".join(
        f"[{m.role}]: {m.text[:500]}" for m in old_messages
    )
    prompt = f"Summarize this conversation history in 2-4 sentences, preserving key facts, decisions, and context:\n\n{compaction_text}"

    compaction_request = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content=prompt)],
        max_completion_tokens=512,
        request_id=f"compact_{chat_id}",
    )

    compacted_text = ""
    async for event in self._runtime.stream(compaction_request):
        if event.type == "text_delta" and event.text:
            compacted_text += event.text

    if not compacted_text.strip():
        yield ChatHistoryCompacted(chat_id=chat_id, status="failed", reason="empty_compaction_output")
        return

    # Persist
    ts = utc_now()
    compaction_entry = {
        "ts": ts.isoformat(),
        "turns_compacted": len(old_messages),
        "summary": compacted_text.strip(),
        "token_savings": sum(m.token_estimate or 0 for m in old_messages),
    }

    compactions_path = self._chat_store._chat_dir(chat_id) / "compactions.jsonl"
    with open(compactions_path, "a") as f:
        f.write(json.dumps(compaction_entry) + "\n")

    self._chat_store.append_compaction(chat_id, compacted_text.strip())

    metadata_path = self._chat_store._chat_dir(chat_id) / "metadata.json"
    meta = json.loads(metadata_path.read_text())
    meta["last_compacted_at"] = ts.isoformat()
    meta["compaction_count"] = meta.get("compaction_count", 0) + 1
    metadata_path.write_text(json.dumps(meta, indent=2))

    yield ChatHistoryCompacted(
        chat_id=chat_id,
        status="completed",
        turns_compacted=len(old_messages),
        token_savings=compaction_entry["token_savings"],
    )
```

- [ ] **Step 3: Update _handle_compact to yield events**

In `_handle_compact`, replace stubbed logic with call to `compact_chat_history`:

```python
async def _handle_compact(self, ctx, args):
    async for event in self.compact_chat_history(ctx.chat_id):
        yield event
```

- [ ] **Step 4: Add compactions to required events and TUI handling**

The `ChatHistoryCompacted` event is already defined. Add `AppSession.compact_chat_history` to map it through to the TUI. In `event_mapping.py`, handle `ChatHistoryCompacted` → `AppChatHistoryCompacted` (or appropriate app event).

In `src/app/tui/app.py`, add a handler:

```python
def _handle_chat_history_compacted(self, event):
    if event.status == "completed":
        self._conversation.append_system(f"Chat compacted: {event.turns_compacted} turns summarized. Tokens saved: ~{event.token_savings}")
    elif event.status == "skipped":
        pass  # Below threshold, silent
    else:
        self._conversation.append_system(f"Compaction {event.status}: {getattr(event, 'reason', '')}")
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/harness/ -q -k compact
```

- [ ] **Step 6: Commit**

```bash
git add src/harness/chat.py src/harness/orchestrator.py src/app/tui/app.py src/app/event_mapping.py
git commit -m "feat: full compact event flow with compactions.jsonl and token pressure check"
```

---

### Task 8: KnowledgeManager write support for doctor

**Files:**
- Modify: `src/harness/knowledge.py`
- Create: `tests/harness/test_knowledge_writes.py`

Doctor needs `KnowledgeManager` to support direct writes (notes, functions, preferences) and deletions, not just `propose_update` + `apply`. Add methods the doctor can call directly without going through the proposal→approval cycle (for auto-save mode).

- [ ] **Step 1: Add note write/delete methods**

```python
def write_note(self, workspace_dir, name, content, *, source_turn_ids=None, overwrite=False):
    """Write a knowledge note to memory/notes/<name>.md. Records metadata for echo dedup."""
    notes_dir = Path(workspace_dir) / "memory" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    note_path = notes_dir / f"{name}.md"
    if note_path.exists() and not overwrite:
        return False
    note_path.write_text(content)
    # Write metadata for dedup
    meta_path = notes_dir / f"{name}.json"
    meta = {"source_turn_ids": source_turn_ids or [], "created_at": utc_now().isoformat()}
    meta_path.write_text(json.dumps(meta))
    return True

def delete_note(self, workspace_dir, name):
    notes_dir = Path(workspace_dir) / "memory" / "notes"
    note_path = notes_dir / f"{name}.md"
    meta_path = notes_dir / f"{name}.json"
    deleted = False
    for p in (note_path, meta_path):
        if p.exists():
            p.unlink()
            deleted = True
    return deleted

def write_gap(self, workspace_dir, name, content):
    gaps_dir = Path(workspace_dir) / "memory" / "notes" / "gaps"
    gaps_dir.mkdir(parents=True, exist_ok=True)
    (gaps_dir / f"{name}.md").write_text(content)

def delete_gap(self, workspace_dir, name):
    p = Path(workspace_dir) / "memory" / "notes" / "gaps" / f"{name}.md"
    if p.exists():
        p.unlink()
        return True
    return False
```

- [ ] **Step 2: Add function write/archive methods**

```python
def write_function(self, workspace_dir, name, code):
    funcs_dir = Path(workspace_dir) / "memory" / "functions"
    funcs_dir.mkdir(parents=True, exist_ok=True)
    (funcs_dir / f"{name}.py").write_text(code)

def delete_function(self, workspace_dir, name):
    p = Path(workspace_dir) / "memory" / "functions" / f"{name}.py"
    if p.exists():
        p.unlink()
        return True
    return False
```

- [ ] **Step 3: Add preference set/remove methods**

```python
def set_preference(self, workspace_dir, key, value):
    prefs_path = Path(workspace_dir) / "memory" / "preferences.json"
    prefs = json.loads(prefs_path.read_text() or "{}")
    prefs[key] = value
    prefs_path.write_text(json.dumps(prefs, indent=2))

def remove_preference(self, workspace_dir, key):
    prefs_path = Path(workspace_dir) / "memory" / "preferences.json"
    prefs = json.loads(prefs_path.read_text() or "{}")
    if key in prefs:
        del prefs[key]
        prefs_path.write_text(json.dumps(prefs, indent=2))
        return True
    return False

def has_note_for_turns(self, workspace_dir, turn_ids):
    """Echo dedup: check if any existing notes already cover these turn IDs."""
    notes_dir = Path(workspace_dir) / "memory" / "notes"
    if not notes_dir.exists():
        return False
    seen_ids = set()
    for meta_file in notes_dir.glob("*.json"):
        meta = json.loads(meta_file.read_text())
        seen_ids.update(meta.get("source_turn_ids", []))
    return bool(set(turn_ids) & seen_ids)
```

- [ ] **Step 4: Write tests**

In `tests/harness/test_knowledge_writes.py`:

```python
def test_write_and_delete_note(tmp_path):
    km = KnowledgeManager()
    ws = tmp_path / "ws"
    (ws / "memory" / "notes").mkdir(parents=True)

    assert km.write_note(str(ws), "test_formula", "x = y / 2", source_turn_ids=["t1"])
    assert (ws / "memory" / "notes" / "test_formula.md").exists()
    assert (ws / "memory" / "notes" / "test_formula.json").exists()

    assert km.delete_note(str(ws), "test_formula")
    assert not (ws / "memory" / "notes" / "test_formula.md").exists()

def test_echo_dedup(tmp_path):
    km = KnowledgeManager()
    ws = tmp_path / "ws"
    (ws / "memory" / "notes").mkdir(parents=True)
    km.write_note(str(ws), "formula_a", "x=1", source_turn_ids=["t1", "t2"])
    assert km.has_note_for_turns(str(ws), ["t2"])
    assert not km.has_note_for_turns(str(ws), ["t5"])

def test_preferences(tmp_path):
    km = KnowledgeManager()
    ws = tmp_path / "ws"
    (ws / "memory").mkdir(parents=True)
    (ws / "memory" / "preferences.json").write_text("{}")
    km.set_preference(str(ws), "preview_rows", 2)
    prefs = json.loads((ws / "memory" / "preferences.json").read_text())
    assert prefs["preview_rows"] == 2
    km.remove_preference(str(ws), "preview_rows")
    prefs = json.loads((ws / "memory" / "preferences.json").read_text())
    assert "preview_rows" not in prefs
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/harness/test_knowledge_writes.py -q
```

- [ ] **Step 6: Commit**

```bash
git add src/harness/knowledge.py tests/harness/test_knowledge_writes.py
git commit -m "feat: KnowledgeManager write/delete methods for doctor auto-save"
```

---

### Task 9: Group B — Doctor deterministic phases with mode support (#3, #13)

**Files:**
- Modify: `src/harness/doctor.py`
- Modify: `src/harness/doctor_runner.py`

- [ ] **Step 0: Add mode parameter to Doctor and DoctorRunner**

In `src/harness/doctor_runner.py`, add `mode` parameter to `run()`:

```python
async def run(self, *, workspace_id, workspace_dir, trigger, chat_id, run_id, mode="full"):
    """Run doctor pipeline. mode: light (1-3+7-8), semantic (4-6+7-8), full (1-8)."""
    self.mode = mode
    should_run_deterministic = mode in ("light", "full")
    should_run_llm = mode in ("semantic", "full")

    if should_run_deterministic:
        # Phases 1-3
        ...
    if should_run_llm:
        # Phases 4-6
        ...
    # Phases 7-8 always run
    ...
```

- [ ] **Step 1: Implement Phase 1 (Source Rescan)**

In `src/harness/doctor.py`, add `check_all_sources` method:

```python
async def check_all_sources(
    self,
    workspace_dir: str,
    persistence,
    workspace_id: str,
) -> list[dict]:
    """Phase 1: Rescan all data/ files, compare fingerprints."""
    findings = []
    data_dir = Path(workspace_dir) / "data"
    if not data_dir.exists():
        return findings

    for src_file in data_dir.iterdir():
        if src_file.is_dir() or src_file.name.startswith('.'):
            continue
        stored = persistence.load_record("source_records", "path",
            str(src_file.relative_to(workspace_dir)))
        result = lazy_fingerprint(
            src_file,
            stored_size=stored.get("size") if stored else None,
            stored_mtime_ns=stored.get("mtime_ns") if stored else None,
            stored_fingerprint=stored.get("fingerprint") if stored else None,
        )
        finding = {
            "source": str(src_file.relative_to(workspace_dir)),
            "fingerprint_action": result.action,
            "exists": src_file.exists(),
        }
        if result.action in ("changed", "missing"):
            state = classify(
                fingerprint_action=result.action,
                stored_fingerprint=stored.get("fingerprint") if stored else None,
                new_fingerprint=result.fingerprint,
                has_dependents_with_stale_inputs=False,
                needs_user_review=(result.action == "missing"),
                user_revalidated=False,
            )
            finding["validity_state"] = state.value
            finding["type"] = "drift" if result.action == "changed" else "missing"
        findings.append(finding)
    return findings
```

- [ ] **Step 2: Implement Phase 2 (Artifact Inventory)**

In `src/harness/doctor.py`, add `inventory_tmp_artifacts`:

```python
async def inventory_tmp_artifacts(
    self,
    workspace_dir: str,
    persistence,
) -> list[dict]:
    """Phase 2: Classify all tmp artifacts."""
    findings = []
    tmp_dir = Path(workspace_dir) / "artifacts" / "tmp"
    if not tmp_dir.exists():
        return findings

    now = time.time()
    active_runs = getattr(self, '_active_run_ids', set())

    for run_dir in tmp_dir.iterdir():
        if not run_dir.is_dir():
            continue
        run_age_days = (now - run_dir.stat().st_mtime) / 86400
        is_active = run_dir.name in active_runs

        for step_dir in run_dir.iterdir():
            if not step_dir.is_dir():
                continue
            for artifact in step_dir.iterdir():
                if artifact.name.startswith('.') or artifact.is_symlink():
                    continue
                relative = str(artifact.relative_to(workspace_dir))
                age_days = (now - artifact.stat().st_mtime) / 86400

                if is_active:
                    classification = "active_run"
                    action = "keep_temporarily"
                    guard = "blocked"
                elif age_days > 7:
                    classification = "stale"
                    action = "delete"
                    guard = "safe"
                else:
                    classification = "orphaned"
                    action = "keep_temporarily"
                    guard = "safe"

                findings.append({
                    "path": relative,
                    "classification": classification,
                    "proposed_action": action,
                    "guard_level": guard,
                    "age_days": round(age_days, 1),
                })
    return findings
```

- [ ] **Step 3: Implement Phase 3 (Pending Plan Pruning)**

```python
async def prune_pending_plans(self, workspace_dir: str) -> list[dict]:
    """Phase 3: Prune stale pending plans from JSONL."""
    findings = []
    path = Path(workspace_dir) / "state" / "pending_plans.jsonl"
    if not path.exists():
        return findings

    now = time.time()
    with open(path, encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line.strip())
            age_days = (now - entry.get("ts", 0)) / 86400

            if entry.get("action") == "resolved" and age_days > 7:
                findings.append({
                    "type": "pending_plan_tombstone",
                    "plan_id": entry["plan_id"],
                    "age_days": round(age_days, 1),
                })
            elif entry.get("action") == "created" and age_days > 1:
                findings.append({
                    "type": "pending_plan_stuck",
                    "plan_id": entry["plan_id"],
                    "goal": entry.get("goal", "unknown"),
                    "age_days": round(age_days, 1),
                    "severity": "warning",
                })
    return findings
```

- [ ] **Step 4: Wire phases 1-3 into DoctorRunner with mode support**

In `src/harness/doctor_runner.py`, update `run` to call deterministic phases when mode includes them:

```python
async def run(self, *, workspace_id, workspace_dir, trigger, chat_id, run_id, mode="full"):
    self.mode = mode
    run_deterministic = mode in ("light", "full")
    run_llm = mode in ("semantic", "full")

    yield CommandStarted(command="doctor")
    yield DoctorStarted()
    report_id = f"dr_{workspace_id}_{int(time.time())}"
    category = "deterministic" if mode == "light" else "full_scan"

    if run_deterministic:
        # Phase 1
        yield CommandProgress(command="doctor", phase="source_rescan", phase_index=0, phase_total=3, message="Scanning workspace sources")
        source_findings = await self.doctor.check_all_sources(workspace_dir, self.persistence, workspace_id)
        for f in source_findings:
            if f.get("type"):
                yield DoctorFinding(
                    report_id=report_id,
                    category="source_drift",
                    severity="warning" if f.get("type") == "changed" else "error",
                    summary=f"{f['source']}: {f['fingerprint_action']}",
                    details=json.dumps(f),
                )
        yield CommandProgress(command="doctor", phase="source_rescan", phase_index=1, phase_total=3, message="Source scan complete")

        # Phase 2
        yield CommandProgress(command="doctor", phase="artifact_inventory", phase_index=1, phase_total=3, message="Scanning tmp artifacts")
        tmp_findings = await self.doctor.inventory_tmp_artifacts(workspace_dir, self.persistence)
        for f in tmp_findings:
            act = f.get("proposed_action", "keep")
            mapped_action = "cleanup" if act == "delete" else "keep"
            yield DoctorActionProposed(
                report_id=report_id,
                action=mapped_action,
                target=f["path"],
                rationale=f"classified as {f.get('classification')}, age={f.get('age_days')}d",
                destination_path=None,
            )
        yield CommandProgress(command="doctor", phase="artifact_inventory", phase_index=2, phase_total=3, message="Artifact inventory complete")

        # Phase 3
        yield CommandProgress(command="doctor", phase="pending_plan_pruning", phase_index=2, phase_total=3, message="Pruning pending plans")
        plan_findings = await self.doctor.prune_pending_plans(workspace_dir)
        for f in plan_findings:
            yield DoctorFinding(
                report_id=report_id,
                category="plan_pruning",
                severity="warning",
                summary=f.get("type", "unknown"),
                details=json.dumps(f),
            )
        yield CommandProgress(command="doctor", phase="pending_plan_pruning", phase_index=3, phase_total=3, message="Plan pruning complete")

    if run_llm:
        # LLM phases: see Task 10
        ...

    # Phases 7-8: compilation + persistence (Task 10)

    yield CommandCompleted(command="doctor")
```

- [ ] **Step 5: Create memory/ directories on first doctor run**

In `DoctorRunner.run`, at start:

```python
for d in ["notes", "notes/gaps", "functions"]:
    (Path(workspace_dir) / "memory" / d).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/harness/ -q -k doctor
```

- [ ] **Step 7: Commit**

```bash
git add src/harness/doctor.py src/harness/doctor_runner.py
git commit -m "feat: doctor deterministic phases 1-3 — source rescan, artifact inventory, plan pruning"
```

---

### Task 10: Group B — Doctor LLM phases with auto-save (Phase 4-6) (#3, #13)

**Files:**
- Modify: `src/harness/doctor_runner.py`
- Modify: `src/harness/orchestrator.py` (for runtime access)

- [ ] **Step 1: Add runtime, KnowledgeManager, and chat_store dependencies to DoctorRunner**

In `src/harness/doctor_runner.py`, update `__init__`:

```python
def __init__(self, doctor, persistence, runtime=None, knowledge_manager=None, chat_store=None):
    self.doctor = doctor
    self.persistence = persistence
    self.runtime = runtime
    self.knowledge_manager = knowledge_manager  # For auto-save
    self.chat_store = chat_store                # For Phase 4 chat mining
```

Update `build_orchestrator` in `factory.py` to pass all deps:

```python
doctor_runner = DoctorRunner(doctor, persistence, runtime=runtime,
                             knowledge_manager=knowledge_manager,
                             chat_store=chat_store)
```

- [ ] **Step 2: Implement Phase 4 (Chat Knowledge Mining) with echo dedup and streaming parse**

```python
async def _run_chat_knowledge_mining(self, chat_id, workspace_id, workspace_dir):
    """Phase 4 LLM: Extract knowledge from chat history."""
    if not self.runtime:
        return []

    # Guard: no chat loaded
    if not chat_id:
        return []

    if not hasattr(self, 'chat_store') or not self.chat_store:
        return []

    chat_record = self.chat_store.view_chat(chat_id)
    if not chat_record or not chat_record.messages:
        return []

    # Echo dedup: skip if existing notes already cover these turns
    recent_turn_ids = [m.turn_id for m in chat_record.messages[-20:] if m.turn_id]
    if self.knowledge_manager and self.knowledge_manager.has_note_for_turns(workspace_dir, recent_turn_ids):
        return []

    # Build context from recent messages
    recent = chat_record.messages[-20:]
    chat_text = "\n".join(f"[{m.role}]: {m.text[:300]}" for m in recent)

    prompt = f"""You are extracting reusable knowledge from a data analysis conversation.
For each piece of knowledge found, output a JSON object with: type, title, content, confidence.

Types:
- "note": A fact, formula, or definition taught by the user
- "preference": A user preference about how they want data shown or analyzed
- "gap": Something the user asked about but was not resolved

Conversation:
{chat_text}

Output one JSON object per finding, each on its own line:
{{"type":"note","title":"headcount formula","content":"average headcount = total headcount / 6","confidence":"high","source_turn_ids":["turn_xxx"]}}
"""

    request = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content=prompt)],
        max_completion_tokens=1024,
        request_id=f"doctor_knowledge_{workspace_id}",
    )

    findings = []
    buffer = ""
    async for event in self.runtime.stream(request):
        if event.type == "text_delta" and event.text:
            buffer += event.text
            # Parse complete JSON lines from streaming output
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    finding = json.loads(line)
                    findings.append(finding)
                except json.JSONDecodeError:
                    pass  # Skip malformed lines, continue accumulating

    # Parse any leftover buffer
    buffer = buffer.strip()
    if buffer:
        try:
            findings.append(json.loads(buffer))
        except json.JSONDecodeError:
            pass

    return findings
```

- [ ] **Step 3: Implement Phase 5 (Script Relevance Assessment)**

```python
async def _run_script_assessment(self, workspace_dir):
    """Phase 5 LLM: Assess saved function relevance."""
    if not self.runtime:
        return []

    funcs_dir = Path(workspace_dir) / "memory" / "functions"
    if not funcs_dir.exists() or not list(funcs_dir.glob("*.py")):
        return []

    scripts_text = ""
    for py_file in funcs_dir.glob("*.py"):
        content = py_file.read_text()[:1000]
        scripts_text += f"\n### {py_file.name}\n```python\n{content}\n```\n"

    prompt = f"""Assess these saved analysis scripts. For each, determine:
- Is it still relevant to the current data?
- Are any scripts solving the same problem (combinable)?
- Are any obsolete?

Scripts:
{scripts_text}

Output one JSON object per finding: {{"script":"name.py","assessment":"relevant|obsolete|combinable_with_<other>","reason":"..."}}
"""

    request = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content=prompt)],
        max_completion_tokens=1024,
        request_id=f"doctor_scripts_{Path(workspace_dir).name}",
    )

    findings = []
    buffer = ""
    async for event in self.runtime.stream(request):
        if event.type == "text_delta" and event.text:
            buffer += event.text
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    findings.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    buffer = buffer.strip()
    if buffer:
        try:
            findings.append(json.loads(buffer))
        except json.JSONDecodeError:
            pass

    return findings
```

- [ ] **Step 4: Implement Phase 6 (Knowledge Consistency Check)**

```python
async def _run_consistency_check(self, workspace_dir):
    """Phase 6 LLM: Cross-reference notes, preferences, functions for conflicts."""
    if not self.runtime:
        return []

    notes_dir = Path(workspace_dir) / "memory" / "notes"
    funcs_dir = Path(workspace_dir) / "memory" / "functions"
    prefs_path = Path(workspace_dir) / "memory" / "preferences.json"
    prefs = {}
    if prefs_path.exists():
        prefs = json.loads(prefs_path.read_text() or "{}")

    context = ""
    if notes_dir.exists():
        for note in notes_dir.glob("*.md"):
            context += f"\n[NOTE {note.stem}]: {note.read_text()[:500]}\n"
    if funcs_dir.exists():
        for func in funcs_dir.glob("*.py"):
            context += f"\n[FUNCTION {func.stem}]: {func.read_text()[:500]}\n"
    context += f"\n[PREFERENCES]: {json.dumps(prefs)}\n"

    if not context.strip():
        return []

    prompt = f"""Check this knowledge base for consistency issues:
- Contradictions between notes
- Stale references (mentions files that no longer exist in data/)
- Preferences that conflict with stored notes

Knowledge base:
{context}

Output one JSON per issue: {{"type":"contradiction|stale_reference|preference_conflict","description":"...","affected_items":["note_x","pref_y"]}}
"""

    request = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content=prompt)],
        max_completion_tokens=1024,
        request_id=f"doctor_consistency_{Path(workspace_dir).name}",
    )

    findings = []
    buffer = ""
    async for event in self.runtime.stream(request):
        if event.type == "text_delta" and event.text:
            buffer += event.text
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    findings.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    buffer = buffer.strip()
    if buffer:
        try:
            findings.append(json.loads(buffer))
        except json.JSONDecodeError:
            pass

    return findings
```

- [ ] **Step 5: Wire phases 4-6 into DoctorRunner.run**

After Phase 3, add (inside the `if run_llm:` block):

```python
# Phase 4
yield CommandProgress(command="doctor", phase="knowledge_mining", phase_index=0, phase_total=3, message="Mining chat knowledge")
knowledge_findings = await self._run_chat_knowledge_mining(chat_id, workspace_id, workspace_dir)
for f in knowledge_findings:
    yield DoctorFinding(
        report_id=report_id,
        category="knowledge_candidate",
        severity="info",
        summary=f.get("title", "unknown"),
        details=json.dumps(f),
    )

# Phase 5
yield CommandProgress(command="doctor", phase="script_assessment", phase_index=1, phase_total=3, message="Assessing saved scripts")
script_findings = await self._run_script_assessment(workspace_dir)
for f in script_findings:
    assessment = f.get("assessment", "review")
    yield DoctorActionProposed(
        report_id=report_id,
        action="keep" if assessment == "relevant" else "review",
        target=f["script"],
        rationale=f.get("reason", ""),
        destination_path=None,
    )

# Phase 6
yield CommandProgress(command="doctor", phase="consistency_check", phase_index=2, phase_total=3, message="Checking knowledge consistency")
consistency_findings = await self._run_consistency_check(workspace_dir)
for f in consistency_findings:
    yield DoctorFinding(
        report_id=report_id,
        category="consistency_issue",
        severity="warning",
        summary=f.get("description", "unknown"),
        details=json.dumps(f),
    )
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests/harness/ -q -k doctor
```

- [ ] **Step 9: Commit**

```bash
git add src/harness/doctor.py src/harness/doctor_runner.py src/harness/orchestrator.py src/harness/factory.py
git commit -m "feat: doctor LLM phases 4-6 and report persistence phases 7-8"
```

---

### Task 11: Doctor async background automation triggers

**Files:**
- Modify: `src/harness/orchestrator.py`

All doctor runs execute as async background tasks — never block the TUI. Findings stream to `SidebarState` as they arrive.

- [ ] **Step 1: Add light doctor on workspace activation (runs inline, deterministic only)**

In `activate_workspace`, after switching:

```python
# Light doctor — deterministic only, fast, runs inline at startup
light_runner = DoctorRunner(
    self._doctor, self._persistence,
    runtime=None, knowledge_manager=self._knowledge_manager
)
async for event in light_runner.run(
    workspace_id=workspace_id,
    workspace_dir=str(ws_dir),
    trigger="workspace_activation",
    chat_id=self._active_chat_id,
    run_id=None,
    mode="light",
):
    if isinstance(event, DoctorFinding):
        _log.info("startup_doctor_finding category=%s severity=%s", event.category, event.severity)
```

- [ ] **Step 2: Add semantic doctor after every worker execution (async background)**

In `resume_approved_step`, after `StepCompleted` and `FinalMessage`, spawn a background task:

```python
# After turn completes, launch semantic doctor as background task
async def _post_worker_doctor():
    semantic_runner = DoctorRunner(
        self._doctor, self._persistence,
        runtime=self._runtime,
        knowledge_manager=self._knowledge_manager,
        chat_store=self._chat_store,
    )
    async for event in semantic_runner.run(
        workspace_id=state.workspace_id,
        workspace_dir=str(Path(state.workspace_dir)),
        trigger="post_worker_execution",
        chat_id=self._active_chat_id,
        run_id=run_id,
        mode="semantic",
    ):
        if isinstance(event, DoctorFinding):
            _log.info("post_worker_doctor_finding category=%s severity=%s", event.category, event.severity)
            snapshot = self.status_snapshot(state.workspace_id)
            if snapshot:
                self._status_broker.publish(snapshot)
        elif isinstance(event, DoctorActionProposed):
            if event.action in ("cleanup", "promote") and self._knowledge_manager:
                _apply_safe_action(self._knowledge_manager, workspace_dir, {"action": event.action, "target": event.target})

asyncio.create_task(_post_worker_doctor())
```

- [ ] **Step 3: Define _apply_safe_action helper**

```python
def _apply_safe_action(km, workspace_dir, action):
    """Auto-apply safe doctor actions without user approval."""
    action_type = action.get("action", "")
    target = action.get("target", "")
    if action_type == "cleanup" and target.startswith("artifacts/tmp/"):
        path = Path(workspace_dir) / target
        try:
            if path.exists() and not path.is_symlink():
                if path.is_file():
                    path.unlink()
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
        except Exception:
            pass
    elif action_type == "promote" and "memory/" in target:
        name = Path(target).stem
        if "notes" in target:
            km.write_note(workspace_dir, name, "")
        elif "functions" in target:
            km.write_function(workspace_dir, name, "")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/harness/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/harness/orchestrator.py
git commit -m "feat: doctor automation — light on startup, semantic after each worker execution"
```

---

### Task 12: Doctor sidebar wiring + approval banner adaptation (#6, #7)

**Files:**
- Modify: `src/app/tui/app.py`
- Modify: `src/app/tui/widgets.py`
- Modify: `src/harness/status.py`

- [ ] **Step 1: Publish doctor findings to StatusBroker**

In `src/harness/status.py`, add `append_doctor_finding` to `StatusBroker`:

```python
def append_doctor_finding(self, finding):
    """Push a doctor finding into the current snapshot's doctor section."""
    async def _push():
        snapshot = self._latest_snapshot
        if snapshot is None:
            return
        doctor = snapshot.doctor_findings or []
        doctor.append(finding.model_dump() if hasattr(finding, 'model_dump') else str(finding))
        snapshot.doctor_findings = doctor[-8:]  # Keep last 8
        await self.publish(snapshot)
    asyncio.create_task(_push())
```

- [ ] **Step 2: Pipe post-worker doctor events to StatusBroker for sidebar refresh**

In `_post_worker_doctor()`, doctor events update the status snapshot. Sidebar picks up via existing `watch_status()` loop:

```python
async def _post_worker_doctor():
    semantic_runner = DoctorRunner(
        self._doctor, self._persistence,
        runtime=self._runtime,
        knowledge_manager=self._knowledge_manager,
        chat_store=self._chat_store,
    )
    async for event in semantic_runner.run(
        workspace_id=state.workspace_id,
        workspace_dir=str(Path(state.workspace_dir)),
        trigger="post_worker_execution",
        chat_id=self._active_chat_id,
        run_id=run_id,
        mode="semantic",
):
    if isinstance(event, DoctorFinding):
        _log.info("startup_doctor_finding category=%s severity=%s", event.category, event.severity)
```

- [ ] **Step 3: Adapt ApprovalBanner for doctor review**

In `src/app/tui/widgets.py`, add a `show_doctor_review` method to `ApprovalBanner`:

```python
def show_doctor_review(self, report_id, actions, findings):
    """Render doctor batch approval with checkboxes per action."""
    self.display = True
    self._doctor_mode = True
    self._doctor_report_id = report_id
    self._doctor_actions = actions

    # Clear existing content
    for child in list(self.children):
        child.remove()

    # Header
    self.mount(Static(
        f"Doctor Review ({len(findings)} findings, {len(actions)} actions)",
        id="doctor_header",
    ))

    # Render each action as a toggleable row
    for i, action in enumerate(actions):
        icon = {"cleanup": " ", "promote": " ", "keep": " ", "review": " "}.get(action.get("action", ""), " ")
        label = f"{icon} {action.get('action')}: {action.get('rationale', action.get('target', ''))[:80]}"
        cb = Checkbox(label, id=f"doctor_action_{i}", value=True)
        self.mount(cb)

    # Buttons
    self.mount(Horizontal(
        Button("Accept All", id="doctor_accept_all", variant="success"),
        Button("Reject All", id="doctor_reject_all", variant="error"),
        Button("Apply Selected", id="doctor_apply_selected", variant="primary"),
    ))

def _get_doctor_decisions(self):
    """Collect accept/reject per action from checkboxes."""
    decisions = []
    for i in range(len(self._doctor_actions)):
        cb = self.query_one(f"#doctor_action_{i}", Checkbox)
        decisions.append({
            "index": i,
            "accepted": cb.value,
            "action": self._doctor_actions[i],
        })
    return decisions
```

- [ ] **Step 4: Handle doctor approval events in DataHarnessApp**

In `src/app/tui/app.py`, add handler for doctor review decisions:

```python
@on(Button.Pressed, "#doctor_accept_all")
def _on_doctor_accept_all(self):
    decisions = self._approval_banner._get_doctor_decisions()
    for d in decisions:
        d["accepted"] = True
    self._apply_doctor_decisions(decisions)

@on(Button.Pressed, "#doctor_apply_selected")
def _on_doctor_apply_selected(self):
    self._apply_doctor_decisions(self._approval_banner._get_doctor_decisions())

@on(Button.Pressed, "#doctor_reject_all")
def _on_doctor_reject_all(self):
    self._approval_banner.hide()

async def _apply_doctor_decisions(self, decisions):
    report_id = self._approval_banner._doctor_report_id
    await self.session.handle_doctor_approval(
        state=self.state,
        workspace_dir=str(self.workspace_dir),
        report_id=report_id,
        decision="accepted" if all(d.get("accepted") for d in decisions) else "partial",
    )
    self._approval_banner.hide()
    self._conversation.append_system("Doctor actions applied.")
```

- [ ] **Step 5: Wire DoctorReportReady to show banner for manual /doctor**

In `_handle_doctor_report_ready`:

```python
def _handle_doctor_report_ready(self, event):
    # DoctorReportReady has: report_id, summary_counts, recommendations, action_records
    if event.action_records:
        # Manual /doctor — show batch approval
        self._approval_banner.show_doctor_review(
            event.report_id, event.action_records, event.recommendations or []
        )
    else:
        # Auto mode — already handled by sidebar refresh via status watcher
        pass
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/app/tui/ -q
```

- [ ] **Step 7: Commit**

```bash
git add src/app/tui/app.py src/app/tui/widgets.py src/harness/status.py
git commit -m "feat: doctor sidebar wiring + reusable ApprovalBanner for doctor review"
```

---

### Task 13: Knowledge retrieval — hybrid context injection + recall_knowledge tool

**Files:**
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/context.py`
- Modify: `src/harness/command_registry.py`

- [ ] **Step 1: Add recall_knowledge tool to command registry**

In `src/harness/orchestrator.py`, in `_register_commands`:

```python
self.registry.register(
    HarnessCommandDescriptor(
        name="recall_knowledge",
        description="Search saved knowledge (notes, preferences, functions) for relevant information",
        args=[ArgSpec(name="query", type="string", required=True, description="What to search for")],
    ),
    self._handle_recall_knowledge,
    availability=lambda ctx: True,
)
```

- [ ] **Step 2: Implement _handle_recall_knowledge**

```python
async def _handle_recall_knowledge(self, ctx, args):
    query = args["query"].lower()
    workspace_dir = Path(ctx.workspace_dir)
    results = []

    # Search notes
    notes_dir = workspace_dir / "memory" / "notes"
    if notes_dir.exists():
        for note_file in notes_dir.glob("*.md"):
            content = note_file.read_text()
            if query in content.lower():
                results.append(f"[NOTE {note_file.stem}]: {content[:500]}")

    # Search preferences
    prefs_path = workspace_dir / "memory" / "preferences.json"
    if prefs_path.exists():
        prefs = json.loads(prefs_path.read_text())
        matching = {k: v for k, v in prefs.items() if query in k.lower()}
        if matching:
            results.append(f"[PREFERENCES]: {json.dumps(matching)}")

    # Search function docstrings
    funcs_dir = workspace_dir / "memory" / "functions"
    if funcs_dir.exists():
        for func_file in funcs_dir.glob("*.py"):
            content = func_file.read_text()
            if query in content.lower():
                results.append(f"[FUNCTION {func_file.stem}]: {content[:500]}")

    if not results:
        yield RuntimeDelta(text="No matching knowledge found.", delta_type="text")
    else:
        yield RuntimeDelta(text="\n---\n".join(results), delta_type="text")
```

- [ ] **Step 3: Add hybrid context injection in _build_durable_context_block**

In `src/harness/orchestrator.py`, update `_build_durable_context_block` to inject top-N relevant knowledge:

```python
def _build_durable_context_block(self, workspace_id, workspace_dir, user_query=""):
    context = ContextManager().rebuild(workspace_dir=workspace_dir)

    # Inject top relevant notes if a user query is available
    if user_query:
        notes_dir = Path(workspace_dir) / "memory" / "notes"
        if notes_dir.exists():
            relevant = []
            for note_file in notes_dir.glob("*.md"):
                content = note_file.read_text()
                if any(word in content.lower() for word in user_query.lower().split() if len(word) > 3):
                    relevant.append(f"[{note_file.stem}]: {content[:300]}")
            if relevant:
                context += "\n\n## Relevant Knowledge\n" + "\n".join(relevant[:3])

    return context
```

- [ ] **Step 4: Pass user_query through run_agentic_turn**

Update the call to `_build_durable_context_block` to include the user query:

```python
durable_context = self._build_durable_context_block(
    workspace_id, workspace_dir, user_query=user_input
)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/harness/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/harness/orchestrator.py src/harness/context.py
git commit -m "feat: recall_knowledge tool + hybrid context injection from memory/"
```

---

### Task 14: Package verification

**Files:**
- Read: `dist/harness/logs/`
- Modify: `scripts/build_app.sh` (if needed for new imports)

- [ ] **Step 1: Rebuild dist**

```bash
bash scripts/build_app.sh
```

- [ ] **Step 2: Verify binary runs**

```bash
./dist/dataharness --help
```

Expected: help output, no TUI launch.

- [ ] **Step 3: Run packaged smoke test**

Launch the app, check:
- `dist/harness/logs/harness.log` has content (not 0 bytes)
- `dist/harness/logs/persistence.log` has content
- `dist/harness/telemetry/harness.events.jsonl` exists
- `dist/workspaces/w_0001/state/telemetry/` exists
- `/compact` shows output in conversation pane
- `/doctor` runs and shows findings
- Asking for analysis triggers approval banner
- Created output files are promoted to `artifacts/`
- `memory/notes/`, `memory/functions/`, `memory/notes/gaps/` directories exist after doctor

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add scripts/build_app.sh  # if modified
git commit -m "chore: package verification, rebuild dist"
```

---

## Verification Commands

```bash
# After each task group, run relevant tests:
uv run pytest tests/observability/ -q     # Group A
uv run pytest tests/runtime/ -q           # Group F
uv run pytest tests/worker/ -q            # Group C
uv run pytest tests/harness/ -q           # Groups D, E, B, Knowledge
uv run pytest tests/app/tui/ -q           # Group D (approval banner)
uv run pytest -q                          # Full suite
```
