# Issues Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the currently OPEN issues in `Issues.md`: doctor review UI/action application, runtime reasoning flag enforcement, reasoning-safe app rendering, and final packaged-run verification.

**Architecture:** Keep the layer boundary intact. Runtime reasoning gating stays in Layer 1 (`src/runtime`); reasoning presentation policy stays in Layer 4 (`src/app/tui`). Doctor action persistence and application remain Layer 3 (`src/harness/orchestrator.py`), while the TUI only gathers user intent and routes it through `AppSession`.

**Tech Stack:** Python 3.12+, Pydantic, Textual, llama-cpp-python runtime wrapper, pytest/pytest-asyncio, uv.

**Repo Rules:** Do not commit unless the user explicitly approves. Read `CODEMAP.md` before edits. After structural changes, update `CODEMAP.md`. Use `uv run pytest`; do not use `pip`.

---

## File Structure

- Modify: `src/harness/orchestrator.py`
  - Add selected doctor-action support to `apply_doctor_actions(...)`.
- Modify: `src/app/session.py`
  - Pass optional selected doctor action ids from Layer 4 to Layer 3.
- Modify: `src/app/tui/app.py`
  - Remove duplicate doctor handlers.
  - Schedule doctor action application through Textual workers.
  - Pass selected action ids from `ApprovalBanner` to `AppSession`.
- Modify: `src/app/tui/widgets.py`
  - Remove duplicate doctor-state initialization.
  - Make doctor review checkbox collection explicit and stable.
- Modify: `src/app/events.py`
  - Remove duplicate `action_records` field.
- Modify: `src/runtime/llama_cpp_runtime.py`
  - Enforce `RuntimeConfig.enable_reasoning_stream` for llama reasoning deltas and Gemma `<|think|>` blocks.
- Modify: `src/app/tui/widgets.py`
  - Ensure non-text `AppRuntimeDelta` events do not append to the assistant transcript.
- Modify: `CODEMAP.md`
  - Update changed signatures/call paths.
- Modify: `Issues.md`
  - Mark fixed issues with dated fix notes after verification.
- Test: `tests/harness/test_doctor_apply.py`
- Test: `tests/app/test_doctor_flow.py`
- Test: `tests/app/tui/test_approval_banner.py`
- Test: `tests/app/tui/test_event_streaming.py`
- Test: `tests/runtime/test_runtime_tool_call_integration.py`
- Test: `tests/runtime/test_runtime_async_streaming.py`

---

### Task 1: Add Selected Doctor Action Application in Layer 3

**Files:**
- Modify: `src/harness/orchestrator.py`
- Modify: `src/app/session.py`
- Test: `tests/harness/test_doctor_apply.py`
- Test: `tests/app/test_doctor_flow.py`

- [ ] **Step 1: Write failing harness test for selected action ids**

Append this test to `tests/harness/test_doctor_apply.py`:

```python
async def test_apply_doctor_actions_selected_ids_only_applies_chosen(tmp_path: Path) -> None:
    orchestrator, workspace_dir, report_id = await _setup_orchestrator_with_tmp(tmp_path)
    second_file = workspace_dir / "artifacts" / "tmp" / "run_1" / "step_2" / "other.py"
    second_file.parent.mkdir(parents=True)
    second_file.write_text("y = 2\n")

    # Re-run doctor so both tmp files are persisted as tmp_actions for one report.
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in orchestrator.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    report_id = next(e.report_id for e in events if e.event_name == "DoctorReportReady")
    rows = [
        r for r in orchestrator.persistence.db.list_records("tmp_actions")
        if r["doctor_report_id"] == report_id
    ]
    assert len(rows) >= 2
    selected_id = rows[0]["id"]
    selected_path = workspace_dir / rows[0]["item_path"]
    unselected = [r for r in rows if r["id"] != selected_id][0]
    unselected_path = workspace_dir / unselected["item_path"]

    events = [e async for e in orchestrator.apply_doctor_actions(
        report_id=report_id,
        decision="yes",
        workspace_id="w_0001",
        workspace_dir=workspace_dir,
        action_ids=[selected_id],
    )]

    applied = next(e for e in events if e.event_name == "DoctorActionsApplied")
    assert applied.applied_count == 1
    assert applied.skipped_count >= 1
    assert not selected_path.exists()
    assert unselected_path.exists()
```

- [ ] **Step 2: Run test and confirm it fails**

Run:

```bash
uv run pytest tests/harness/test_doctor_apply.py::test_apply_doctor_actions_selected_ids_only_applies_chosen -q
```

Expected: fails with `TypeError` because `apply_doctor_actions()` does not accept `action_ids`.

- [ ] **Step 3: Implement optional action id filtering**

In `src/harness/orchestrator.py`, change the signature and loop shape:

```python
    async def apply_doctor_actions(
        self, *, report_id: str, decision: str, workspace_id: str, workspace_dir: Path,
        chat_id: str | None = None, action_ids: list[str] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        normalized = "yes" if str(decision).strip().lower() == "yes" else "no"
        selected_ids = set(action_ids or [])
        rows: list[dict[str, Any]] = []
        if self.persistence is not None:
            try:
                all_actions = self.persistence.db.list_records("tmp_actions")
                rows = [r for r in all_actions if r.get("doctor_report_id") == report_id]
            except Exception:
                rows = []
        if normalized == "no":
            yield DoctorActionsApplied(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=None,
                report_id=report_id, applied_count=0, skipped_count=len(rows),
                details=[{"id": r.get("id"), "action": r.get("action"), "applied": False} for r in rows],
            )
            return
        applied_count = 0
        skipped_count = 0
        details: list[dict[str, Any]] = []
        for record in rows:
            record_id = str(record.get("id") or "")
            if selected_ids and record_id not in selected_ids:
                skipped_count += 1
                details.append({
                    "id": record.get("id"),
                    "action": record.get("action"),
                    "applied": False,
                    "note": "not_selected",
                })
                continue
            if record.get("applied"):
                skipped_count += 1
                details.append({
                    "id": record.get("id"),
                    "action": record.get("action"),
                    "applied": True,
                    "note": "already_applied",
                })
                continue
            try:
                updated = self.doctor.apply_tmp_action(record, workspace_dir=workspace_dir)
                if self.persistence is not None:
                    self.persistence.db.save_record("tmp_actions", "id", str(updated["id"]), updated)
                applied_count += 1
                details.append({"id": updated.get("id"), "action": updated.get("action"), "applied": True})
            except Exception as exc:
                skipped_count += 1
                details.append({
                    "id": record.get("id"),
                    "action": record.get("action"),
                    "applied": False,
                    "error": str(exc),
                })
        yield DoctorActionsApplied(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=None,
            report_id=report_id, applied_count=applied_count, skipped_count=skipped_count,
            details=details,
        )
```

- [ ] **Step 4: Pass selected ids through AppSession**

In `src/app/session.py`, update `handle_doctor_approval`:

```python
    async def handle_doctor_approval(
        self,
        *,
        state: RunStateRecord,
        workspace_dir: Path,
        report_id: str,
        decision: str,
        action_ids: list[str] | None = None,
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.apply_doctor_actions(
            report_id=report_id,
            decision=decision,
            workspace_id=state.workspace_id,
            workspace_dir=workspace_dir,
            action_ids=action_ids,
        ):
            yield to_app_event(h_ev)
```

- [ ] **Step 5: Add session-level test for selected ids**

Append to `tests/app/test_doctor_flow.py`:

```python
async def test_doctor_session_flow_selected_actions_only_apply_selected(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    session = AppSession(orchestrator=orchestrator, app_root=tmp_path)
    await orchestrator.create_workspace("w_0001")
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    first = workspace_dir / "artifacts" / "tmp" / "run_3" / "step_1" / "first.py"
    second = workspace_dir / "artifacts" / "tmp" / "run_3" / "step_2" / "second.py"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("x = 1\n")
    second.write_text("y = 2\n")

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in session.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    report = next(e for e in events if e.event_name == "AppDoctorReportReady")
    action_id = report.action_records[0]["id"]
    selected_path = workspace_dir / report.action_records[0]["item_path"]
    unselected = next(r for r in report.action_records if r["id"] != action_id)
    unselected_path = workspace_dir / unselected["item_path"]

    apply_events = [e async for e in session.handle_doctor_approval(
        state=state,
        workspace_dir=workspace_dir,
        report_id=report.report_id,
        decision="yes",
        action_ids=[action_id],
    )]
    applied = next(e for e in apply_events if e.event_name == "AppDoctorActionsApplied")
    assert applied.applied_count == 1
    assert not selected_path.exists()
    assert unselected_path.exists()
```

- [ ] **Step 6: Run focused doctor tests**

Run:

```bash
uv run pytest tests/harness/test_doctor_apply.py tests/app/test_doctor_flow.py -q
```

Expected: all selected doctor tests pass.

---

### Task 2: Clean Up Doctor Review UI and Wire Worker-Scheduled Actions

**Files:**
- Modify: `src/app/events.py`
- Modify: `src/app/tui/widgets.py`
- Modify: `src/app/tui/app.py`
- Test: `tests/app/tui/test_approval_banner.py`
- Test: `tests/app/tui/test_textual_app.py`

- [ ] **Step 1: Add failing banner test for doctor decisions**

Append to `tests/app/tui/test_approval_banner.py`:

```python
@pytest.mark.asyncio
async def test_doctor_review_collects_checkbox_decisions():
    actions = [
        {"id": "a1", "action": "cleanup", "target": "artifacts/tmp/a.py", "rationale": "stale"},
        {"id": "a2", "action": "cleanup", "target": "artifacts/tmp/b.py", "rationale": "orphaned"},
    ]
    async with _Host().run_test() as pilot:
        banner = pilot.app.query_one("#approval_banner", ApprovalBanner)
        banner.show_doctor_review("report_1", actions, ["finding"])
        await pilot.pause()
        checkbox = banner.query_one("#doctor_action_1")
        checkbox.value = False
        decisions = banner.get_doctor_decisions()
        assert decisions == [
            {"index": 0, "accepted": True, "action": actions[0]},
            {"index": 1, "accepted": False, "action": actions[1]},
        ]
```

Expected first failure: `ApprovalBanner` has `_get_doctor_decisions`, not public `get_doctor_decisions`.

- [ ] **Step 2: Remove duplicate event field**

In `src/app/events.py`, keep exactly one `action_records` line:

```python
class AppDoctorReportReady(AppEvent):
    event_name: Literal["AppDoctorReportReady"] = "AppDoctorReportReady"
    report_id: str
    summary_counts: dict[str, int] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    action_records: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 3: Clean `ApprovalBanner` doctor state**

In `src/app/tui/widgets.py`, replace duplicate initialization with:

```python
    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", "approval_banner")
        super().__init__(**kwargs)
        self._plan: dict = {}
        self._step_contract: dict = {}
        self._doctor_mode = False
        self._doctor_report_id: str = ""
        self._doctor_actions: list[dict] = []
        self.display = False
```

Rename `_get_doctor_decisions` to public `get_doctor_decisions`:

```python
    def get_doctor_decisions(self) -> list[dict]:
        """Collect accept/reject per doctor action from checkboxes."""
        decisions: list[dict] = []
        for i in range(len(self._doctor_actions)):
            cb = self.query_one(f"#doctor_action_{i}", Checkbox)
            decisions.append({
                "index": i,
                "accepted": cb.value,
                "action": self._doctor_actions[i],
            })
        return decisions
```

- [ ] **Step 4: Replace duplicate doctor button handlers in `DataHarnessApp`**

In `src/app/tui/app.py`, keep only one handler set. Use this shape:

```python
    @on(Button.Pressed, "#doctor_accept_all")
    def _on_doctor_accept_all(self, event: Button.Pressed) -> None:
        event.stop()
        decisions = self._approval_banner.get_doctor_decisions()
        accepted_ids = [
            str(d["action"].get("id"))
            for d in decisions
            if d["action"].get("id")
        ]
        self.run_worker(self._stream_doctor_approval(
            self._approval_banner._doctor_report_id,
            "yes",
            accepted_ids,
        ))

    @on(Button.Pressed, "#doctor_apply_selected")
    def _on_doctor_apply_selected(self, event: Button.Pressed) -> None:
        event.stop()
        decisions = self._approval_banner.get_doctor_decisions()
        accepted_ids = [
            str(d["action"].get("id"))
            for d in decisions
            if d.get("accepted") and d["action"].get("id")
        ]
        decision = "yes" if accepted_ids else "no"
        self.run_worker(self._stream_doctor_approval(
            self._approval_banner._doctor_report_id,
            decision,
            accepted_ids,
        ))

    @on(Button.Pressed, "#doctor_reject_all")
    def _on_doctor_reject_all(self, event: Button.Pressed) -> None:
        event.stop()
        self.run_worker(self._stream_doctor_approval(
            self._approval_banner._doctor_report_id,
            "no",
            None,
        ))
```

Update `_stream_doctor_approval`:

```python
    async def _stream_doctor_approval(
        self,
        report_id: str,
        decision: str,
        action_ids: list[str] | None = None,
    ) -> None:
        self._approval_banner.hide()
        consumer = self._build_consumer()
        try:
            async for ev in self._session.handle_doctor_approval(
                state=self._state,
                workspace_dir=self._workspace_dir,
                report_id=report_id,
                decision=decision,
                action_ids=action_ids,
            ):
                consumer.dispatch(ev)
        except Exception as exc:
            self._emit_error(phase="doctor_approval", exc=exc)
            self.notify(str(exc), severity="error")
```

Update `handle_clarification_response` to pass `None` for action ids:

```python
            self.run_worker(self._stream_doctor_approval(report_id, decision, None))
```

Delete the duplicate async `_apply_doctor_decisions` methods.

- [ ] **Step 5: Add app-level regression test for scheduled selected doctor actions**

Append to `tests/app/tui/test_textual_app.py`. Also extend that file's widget import to include `ApprovalBanner`:

```python
from app.tui.widgets import ApprovalBanner, ConversationPane, SidebarPane
```

```python
@pytest.mark.asyncio
async def test_doctor_apply_selected_schedules_doctor_approval(tmp_path):
    class FakeSession:
        def __init__(self):
            self.calls = []

        async def watch_status(self):
            if False:
                yield None

        async def list_chats(self, workspace_id):
            return []

        async def handle_doctor_approval(self, *, state, workspace_dir, report_id, decision, action_ids=None):
            self.calls.append((report_id, decision, action_ids))
            from app.events import AppDoctorActionsApplied
            from datetime import UTC, datetime
            yield AppDoctorActionsApplied(
                ts=datetime.now(UTC),
                workspace_id=state.workspace_id,
                chat_id=None,
                run_id=None,
                report_id=report_id,
                applied_count=len(action_ids or []),
                skipped_count=0,
                details=[],
            )

    fake = FakeSession()
    app = DataHarnessApp(session=fake, workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        banner = app.query_one("#approval_banner", ApprovalBanner)
        actions = [
            {"id": "a1", "action": "cleanup", "target": "artifacts/tmp/a.py", "rationale": "stale"},
            {"id": "a2", "action": "cleanup", "target": "artifacts/tmp/b.py", "rationale": "orphaned"},
        ]
        banner.show_doctor_review("report_1", actions, [])
        banner.query_one("#doctor_action_1").value = False
        await pilot.click("#doctor_apply_selected")
        await pilot.pause()
        assert fake.calls == [("report_1", "yes", ["a1"])]
```

- [ ] **Step 6: Run focused TUI tests**

Run:

```bash
uv run pytest tests/app/tui/test_approval_banner.py tests/app/tui/test_textual_app.py -q
```

Expected: all pass.

---

### Task 3: Enforce `enable_reasoning_stream` in Layer 1 Runtime

**Files:**
- Modify: `src/runtime/llama_cpp_runtime.py`
- Test: `tests/runtime/test_runtime_async_streaming.py`
- Test: `tests/runtime/test_runtime_tool_call_integration.py`

- [ ] **Step 1: Add failing test for direct llama reasoning_content suppression**

Append to `tests/runtime/test_runtime_async_streaming.py`:

```python
async def test_reasoning_content_is_suppressed_when_config_disabled(monkeypatch, tmp_path):
    from runtime import config as cfg_mod, llama_cpp_runtime as rt_mod
    cfg = cfg_mod.RuntimeConfig(
        model_path=str(tmp_path / "m.gguf"),
        chat_format="gemma",
        enable_reasoning_stream=False,
    )
    monkeypatch.setattr(rt_mod, "Llama", lambda **kw: FakeLlama([
        fake_chunk(reasoning="hidden thought"),
        fake_chunk(content="visible"),
        fake_chunk(finish="stop", usage={}),
    ]))
    rt = rt_mod.LlamaCppRuntime(cfg)
    events = []
    async for ev in rt.stream(make_request("reasoning-off")):
        events.append(ev)
    assert [e.type for e in events] == ["text_delta", "finish"]
    assert events[0].text == "visible"
```

- [ ] **Step 2: Add failing test for Gemma think block suppression**

Append to `tests/runtime/test_runtime_tool_call_integration.py`:

```python
async def test_stream_drops_gemma_think_block_when_reasoning_disabled() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<|think|>inspect columns</|think|>Ready."}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(
        FakeLlama(chunks=chunks),
        enable_reasoning_stream=False,
    )
    events = await collect_events(runtime, make_request())
    assert [event.type for event in events] == ["text_delta", "finish"]
    assert events[0].text == "Ready."
```

If `make_runtime(...)` does not yet accept `enable_reasoning_stream`, update its helper in that test file:

```python
def make_runtime(fake_llama, *, enable_reasoning_stream: bool = True):
    runtime = LlamaCppRuntime.__new__(LlamaCppRuntime)
    runtime._llama = fake_llama
    runtime._config = RuntimeConfig(
        model_path="fake.gguf",
        n_ctx=128,
        enable_reasoning_stream=enable_reasoning_stream,
    )
    runtime._status = "ready"
    runtime._status_lock = threading.Lock()
    runtime._last_parse_error = ""
    runtime.telemetry = NoopTelemetry()
    return runtime
```

- [ ] **Step 3: Implement runtime gating**

In `src/runtime/llama_cpp_runtime.py`, update signatures:

```python
def split_gemma_think_text(
    text: str,
    request_id: str,
    seq: _SeqGen,
    *,
    enable_reasoning_stream: bool = True,
) -> tuple[list[RuntimeEvent], str]:
```

Inside that function, only append reasoning events when enabled:

```python
        if reasoning.strip() and enable_reasoning_stream:
            events.append(RuntimeEvent(
                type="reasoning_delta", request_id=request_id, seq=seq.next(), text=reasoning.strip(),
            ))
```

Update `emit_content_events`:

```python
def emit_content_events(
    content: str,
    stream_buffer: str,
    request_id: str,
    seq: _SeqGen,
    *,
    enable_reasoning_stream: bool = True,
) -> tuple[list[RuntimeEvent], str]:
```

Call:

```python
    think_events, pending = split_gemma_think_text(
        pending,
        request_id,
        seq,
        enable_reasoning_stream=enable_reasoning_stream,
    )
```

In `_sync_event_iterator`, gate both direct reasoning and content parsing:

```python
            if delta.get("reasoning_content") and self._config.enable_reasoning_stream:
                yield RuntimeEvent(
                    type="reasoning_delta", request_id=rid, seq=seq.next(),
                    text=delta["reasoning_content"],
                )
```

And:

```python
                        events, stream_buffer = emit_content_events(
                            content,
                            stream_buffer,
                            rid,
                            seq,
                            enable_reasoning_stream=self._config.enable_reasoning_stream,
                        )
```

Apply the same keyword argument in the finish-buffer flush call.

- [ ] **Step 4: Run focused runtime tests**

Run:

```bash
uv run pytest tests/runtime/test_runtime_async_streaming.py tests/runtime/test_runtime_tool_call_integration.py -q
```

Expected: all pass, with existing reasoning-enabled tests still emitting `reasoning_delta`.

---

### Task 4: Prevent Reasoning Deltas from Polluting the TUI Transcript

**Files:**
- Modify: `src/app/tui/widgets.py`
- Test: `tests/app/tui/test_event_streaming.py`

- [ ] **Step 1: Add failing TUI event-streaming test**

Append to `tests/app/tui/test_event_streaming.py`:

```python
def test_reasoning_delta_does_not_append_to_conversation():
    pane = ConversationPane()
    pane.append_assistant_delta(AppRuntimeDelta(
        ts=datetime.now(UTC),
        workspace_id="w1",
        chat_id="c1",
        run_id="r1",
        delta_type="reasoning",
        text="hidden chain of thought",
        tool_call=None,
    ))
    assert "hidden chain of thought" not in pane.text_buffer()
```

Ensure the imports exist at the top of that file:

```python
from datetime import UTC, datetime
from app.events import AppRuntimeDelta
from app.tui.widgets import ConversationPane
```

- [ ] **Step 2: Implement text-only append policy**

In `src/app/tui/widgets.py`, change `ConversationPane.append_assistant_delta`:

```python
    def append_assistant_delta(self, event) -> None:
        if getattr(event, "delta_type", "text") != "text":
            return
        if self._streaming_block is None:
            self._streaming_block = AssistantMessageBlock("")
            self._blocks.append(self._streaming_block)
            self._safe_mount(self._streaming_block)
        self._streaming_block.append_delta(event.text or "")
        self._safe_scroll_end()
```

Keep `DataHarnessApp._handle_runtime_delta` trace updates unchanged so reasoning activity can still appear as phase telemetry without entering the transcript.

- [ ] **Step 3: Run focused app tests**

Run:

```bash
uv run pytest tests/app/tui/test_event_streaming.py tests/app/tui/test_run_trace.py -q
```

Expected: conversation tests pass and run trace still records runtime delta phases.

---

### Task 5: Verify Packaged-Run Issue and Update Project Records

**Files:**
- Modify: `Issues.md`
- Modify: `Lessons.md` only if a new project-specific lesson is learned.
- Modify: `CODEMAP.md` if any structural signatures/imports changed in earlier tasks.

- [ ] **Step 1: Run targeted regression set**

Run:

```bash
uv run pytest \
  tests/runtime/test_runtime_async_streaming.py \
  tests/runtime/test_runtime_tool_call_integration.py \
  tests/app/tui/test_event_streaming.py \
  tests/app/tui/test_run_trace.py \
  tests/app/tui/test_approval_banner.py \
  tests/app/tui/test_textual_app.py \
  tests/app/test_doctor_flow.py \
  tests/harness/test_doctor_apply.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Run package/build verification**

Run:

```bash
uv run pytest tests/packaging/test_build_app_script.py -q
```

Expected: pass.

Run:

```bash
bash scripts/build_app.sh
```

Expected: exits 0 and updates `dist/dataharness`.

- [ ] **Step 3: Verify frozen private worker dispatch still intercepts before TUI startup**

Run this intentionally-invalid worker config path. The command should fail quickly from the worker bootstrap path; it must not launch the Textual app or hang until a worker timeout.

Run:

```bash
./dist/dataharness -m worker.sandbox_bootstrap /private/tmp/dataharness-missing-sandbox.json
```

Expected: nonzero exit within a few seconds with an error about the missing sandbox config path. There should be no Textual UI render and no long-running timeout.

- [ ] **Step 4: Update `Issues.md`**

Update these entries after evidence is available:

```markdown
## Doctor review UI has duplicate fields/handlers and unawaited async apply path (RESOLVED 2026-05-13)
- Fix: removed duplicate `action_records`, duplicate banner state initialization, and duplicate doctor button handlers. Doctor review buttons now schedule `_stream_doctor_approval(...)` through Textual workers and selected checkbox ids flow through `AppSession` to `Orchestrator.apply_doctor_actions(..., action_ids=...)`.
- Verification: `uv run pytest tests/app/tui/test_approval_banner.py tests/app/tui/test_textual_app.py tests/app/test_doctor_flow.py tests/harness/test_doctor_apply.py -q`.

## Runtime `enable_reasoning_stream` flag is not enforced (RESOLVED 2026-05-13)
- Fix: `LlamaCppRuntime` now gates both llama `reasoning_content` deltas and Gemma `<|think|>` parsing through `RuntimeConfig.enable_reasoning_stream`.
- Verification: `uv run pytest tests/runtime/test_runtime_async_streaming.py tests/runtime/test_runtime_tool_call_integration.py -q`.

## Reasoning deltas are not consumed by a reasoning-aware app path (RESOLVED 2026-05-13)
- Fix: Layer 4 treats reasoning deltas as trace/status information only; `ConversationPane.append_assistant_delta` appends only text deltas, preventing reasoning text from entering the visible assistant transcript.
- Verification: `uv run pytest tests/app/tui/test_event_streaming.py tests/app/tui/test_run_trace.py -q`.
```

For `Latest dist analysis run...`, only mark RESOLVED if the package build and frozen checks pass:

```markdown
- Verification pass 2026-05-13: rebuilt `dist/dataharness`, ran packaging tests, and verified the frozen private worker path still dispatches to `worker.sandbox_bootstrap` instead of launching the TUI.
```

- [ ] **Step 5: Update `CODEMAP.md`**

Because this plan changes function signatures and call paths, update:

- `src/harness/orchestrator.py` inventory for `apply_doctor_actions(..., action_ids=None)`.
- `src/app/session.py` inventory for `handle_doctor_approval(..., action_ids=None)`.
- `src/app/tui/app.py` inventory for doctor review handlers and `_stream_doctor_approval(..., action_ids=None)`.
- `src/runtime/llama_cpp_runtime.py` inventory for `emit_content_events(..., enable_reasoning_stream=True)` and `split_gemma_think_text(..., enable_reasoning_stream=True)`.
- `src/app/tui/widgets.py` inventory for `ApprovalBanner.get_doctor_decisions()` and text-only runtime delta rendering.

- [ ] **Step 6: Final verification**

Run:

```bash
git diff --check CODEMAP.md Issues.md src tests
```

Expected: no whitespace errors.

Run:

```bash
uv run pytest -q
```

Expected: full suite passes. If the full suite is too slow or blocked by local model/package constraints, record the exact failing/blocking command output in `Issues.md` and report it.

---

## Self-Review

- Spec coverage: all OPEN issues in `Issues.md` are covered. Resolved/FIXED historical issues are not reworked except the packaged-run verification note.
- Placeholder scan: no `TBD`, `TODO`, or unspecified test steps remain.
- Type consistency: selected doctor actions use `list[str] | None` as `action_ids` in `DataHarnessApp`, `AppSession`, and `Orchestrator`.
- Layer consistency: runtime flag behavior stays Layer 1; transcript policy stays Layer 4; doctor action mutation stays Layer 3.
