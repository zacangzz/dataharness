# M1 M2 M3 M5 Compatibility-Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore spec-aligned process-log rendering, tool contracts, model streaming/telemetry, and clarification boundaries for `M1`, `M2`, `M3`, and `M5` with a low-regression-risk, test-first sequence.

**Architecture:** Normalize activity timing and correlation at the model-wrapper and pipeline layers, then render and consume that contract in the UI and tools through explicit helpers. Keep the compatibility seam in the pipeline and shared tool-envelope helpers so the UI stops inferring state and the tools stop hand-rolling contract details.

**Tech Stack:** Python 3.12, Textual, OpenAI Agents SDK, pytest, pandas, stdlib `asyncio`, `fnmatch`, `re`, local JSON-line telemetry

**Git note:** User explicitly said `no git`. Skip commit steps even where the generic planning template would normally include them.

---

## File Structure

### Core runtime files

- Modify: `src/core/engine/agents_model.py`
  - Add malformed-tool-call retry, richer telemetry accounting, and early tool-call event emission support.
- Modify: `src/core/pipeline.py`
  - Enrich `PipelineEvent` payloads with `turn_id`.
  - Map early raw function-call lifecycle to `ToolCallStart` / `ToolCallComplete`.
  - Keep `StatusUpdate` pipeline-driven.
- Modify: `src/core/clarification_bus.py`
  - Add a public question-consumption API.
  - Make `cancel_all()` deterministic for tests and UI callers.
- Modify: `src/core/tools/workspace_files.py`
  - Centralize envelopes, truncation, path-out-of-scope errors, `columns_schema`, `column_stats(path, column)`, and telemetry.
- Modify: `src/core/knowledge_store.py`
  - Make `search(...)` honor `path_glob` and `regex`.

### UI files

- Modify: `src/cli/process_log.py`
  - Key blocks by `(turn_id, agent)`.
  - Track pending tool rows by `tool_call_id`.
  - Keep blocks collapsed by default.
- Modify: `src/cli/app.py`
  - Consume clarification questions via the bus public API instead of `_questions`.
  - Pass through richer process-log event payloads.

### Test files

- Modify: `tests/core/engine/test_agents_model.py`
- Modify: `tests/core/test_pipeline.py`
- Modify: `tests/core/test_clarification_bus.py`
- Add: `tests/core/test_knowledge_store.py`
- Modify: `tests/core/tools/test_workspace_files.py`
- Modify: `tests/cli/test_process_log.py`
- Modify: `tests/cli/test_app.py`

---

### Task 1: Expand the Process Log Contract Tests

**Files:**
- Modify: `tests/cli/test_process_log.py`
- Reference: `src/cli/process_log.py`

- [ ] **Step 1: Write failing tests for per-turn block identity and default collapse**

```python
from src.core.pipeline import AgentStarted


def test_process_log_keys_blocks_by_turn_and_agent():
    log = ProcessLog()
    log.handle_event(AgentStarted(agent="triage", turn_id="turn_1"))
    log.handle_event(AgentStarted(agent="triage", turn_id="turn_2"))
    assert log.has_block("triage", turn_id="turn_1")
    assert log.has_block("triage", turn_id="turn_2")
    assert len(log._blocks) == 2


def test_process_log_keeps_new_blocks_collapsed():
    log = ProcessLog()
    log.handle_event(AgentStarted(agent="triage", turn_id="turn_1"))
    block = log.get_block("triage", turn_id="turn_1")
    assert block is not None
    assert block.collapsed is True
    assert block.title == "+ triage"
```

- [ ] **Step 2: Write failing tests for in-place tool row updates and correlated output**

```python
from src.core.pipeline import ToolCallStart, ToolCallComplete, ToolOutput


def test_process_log_updates_pending_tool_row_in_place():
    log = ProcessLog()
    log.handle_event(AgentStarted(agent="triage", turn_id="turn_1"))
    log.handle_event(
        ToolCallStart(
            agent="triage",
            turn_id="turn_1",
            name="list_files",
            tool_call_id="call_1",
        )
    )
    log.handle_event(
        ToolCallComplete(
            agent="triage",
            turn_id="turn_1",
            name="list_files",
            tool_call_id="call_1",
            args='{"path":"employees.csv"}',
        )
    )

    block = log.get_block("triage", turn_id="turn_1")
    assert block is not None
    assert block.renderable_text.count("list_files") == 1
    assert '-> list_files({"path":"employees.csv"})' in block.renderable_text


def test_process_log_attaches_tool_output_to_matching_row():
    log = ProcessLog()
    log.handle_event(AgentStarted(agent="triage", turn_id="turn_1"))
    log.handle_event(
        ToolCallStart(
            agent="triage",
            turn_id="turn_1",
            name="list_files",
            tool_call_id="call_1",
        )
    )
    log.handle_event(
        ToolOutput(
            agent="triage",
            turn_id="turn_1",
            tool_call_id="call_1",
            output='{"files":["employees.csv"]}',
        )
    )

    block = log.get_block("triage", turn_id="turn_1")
    assert block is not None
    assert '-> list_files(...)' in block.renderable_text
    assert '<- {"files":["employees.csv"]}' in block.renderable_text
```

- [ ] **Step 3: Run the focused tests and verify they fail**

Run: `uv run pytest tests/cli/test_process_log.py -q`

Expected: FAIL because current `ProcessLog` only keys by agent, auto-expands on `AgentStarted`, and appends separate tool rows.

- [ ] **Step 4: Implement the minimal `ProcessLog` structure changes**

```python
@dataclass
class _ToolRow:
    name: str
    rendered_call: str
    output_lines: list[str] = field(default_factory=list)


class ProcessLog(Static):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._blocks: dict[tuple[str, str], AgentProcessBlock] = {}

    def has_block(self, agent: str, turn_id: str) -> bool:
        return (turn_id, agent) in self._blocks

    def get_block(self, agent: str, turn_id: str) -> AgentProcessBlock | None:
        return self._blocks.get((turn_id, agent))

    def handle_event(self, event) -> None:
        turn_id = getattr(event, "turn_id", "")
        agent = getattr(event, "agent", "")
        key = (turn_id, agent)
        if isinstance(event, AgentStarted) and key not in self._blocks:
            block = AgentProcessBlock(agent=agent)
            self._blocks[key] = block
            self._mount_block(block)
```

- [ ] **Step 5: Re-run the focused tests and verify they pass**

Run: `uv run pytest tests/cli/test_process_log.py -q`

Expected: PASS

---

### Task 2: Expand Clarification Bus and UI Contract Tests

**Files:**
- Modify: `tests/core/test_clarification_bus.py`
- Modify: `tests/cli/test_app.py`
- Reference: `src/core/clarification_bus.py`
- Reference: `src/cli/app.py`

- [ ] **Step 1: Write failing bus tests for public question consumption and deterministic cancellation**

```python
@pytest.mark.asyncio
async def test_clarification_bus_exposes_public_question_reader():
    bus = ClarificationBus()
    token, future = await bus.ask("Which file?")
    payload = bus.get_question_nowait()
    assert payload == {"token": token, "question": "Which file?"}


@pytest.mark.asyncio
async def test_clarification_bus_cancel_all_cancels_futures_before_returning():
    bus = ClarificationBus()
    _, future = await bus.ask("Which file?")
    bus.cancel_all()
    await asyncio.sleep(0)
    assert future.cancelled()
```

- [ ] **Step 2: Write failing UI tests that forbid private queue access and require workspace-switch cleanup**

```python
@patch("src.core.engine.llm.LlmModel")
@patch("src.core.pipeline_factory.build_pipeline")
@patch("src.core.terminal.repair_standard_streams")
async def test_poll_clarification_queue_uses_public_bus_api(
    mock_repair, mock_build_pipeline, mock_llm
):
    pipeline = _make_mock_pipeline()
    mock_build_pipeline.return_value = pipeline
    mock_llm.return_value = MagicMock()

    manager = _make_mock_manager()
    app = ChatApp(model_path="/fake/model.gguf", manager=manager)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        with patch.object(clarification_bus, "get_question_nowait", return_value={
            "token": "tok_1",
            "question": "Which file?",
        }):
            app._poll_clarification_queue()
        assert app._pending_clarification_token == "tok_1"
        assert app._awaiting_clarification is True


@patch("src.core.engine.llm.LlmModel")
@patch("src.core.pipeline_factory.build_pipeline")
@patch("src.core.terminal.repair_standard_streams")
async def test_workspace_switch_cancels_pending_clarification(
    mock_repair, mock_build_pipeline, mock_llm
):
    from src.cli.workspace_screen import WorkspaceScreen

    pipeline = _make_mock_pipeline()
    mock_build_pipeline.return_value = pipeline
    mock_llm.return_value = MagicMock()

    manager = _make_mock_manager()
    app = ChatApp(model_path="/fake/model.gguf", manager=manager)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        app._awaiting_clarification = True
        app._pending_clarification_token = "tok_1"
        app.post_message(WorkspaceScreen.WorkspaceSwitched("headcount"))
        await pilot.pause(0.2)
        assert app._awaiting_clarification is False
        assert app._pending_clarification_token is None
```

- [ ] **Step 3: Run the focused clarification tests and verify they fail**

Run: `uv run pytest tests/core/test_clarification_bus.py tests/cli/test_app.py -q`

Expected: FAIL because there is no public question reader and UI still reaches into `clarification_bus._questions`.

- [ ] **Step 4: Implement the public bus API and deterministic cancel behavior**

```python
@dataclass
class ClarificationBus:
    _pending: dict[str, asyncio.Future] = field(default_factory=dict)
    _questions: asyncio.Queue = field(default_factory=asyncio.Queue)

    def get_question_nowait(self) -> dict:
        return self._questions.get_nowait()

    def cancel_all(self) -> None:
        for token, future in list(self._pending.items()):
            if future.done():
                continue
            future.cancel()
        self._pending.clear()
        while True:
            try:
                self._questions.get_nowait()
            except asyncio.QueueEmpty:
                break
```

- [ ] **Step 5: Update `ChatApp` to consume only the public bus API**

```python
def _poll_clarification_queue(self) -> None:
    try:
        payload = clarification_bus.get_question_nowait()
    except asyncio.QueueEmpty:
        return
    question = payload["question"]
    self._pending_clarification_token = payload["token"]
    self._awaiting_clarification = True
    prompt_widget = Static(
        f"[bold]Agent needs clarification:[/] {question}",
        classes="clarification-prompt",
    )
    self.query_one("#message-log").mount(prompt_widget)
    self._enable_input(force=True)
```

- [ ] **Step 6: Re-run the focused clarification tests and verify they pass**

Run: `uv run pytest tests/core/test_clarification_bus.py tests/cli/test_app.py -q`

Expected: PASS

---

### Task 3: Enrich Pipeline Events With `turn_id` and Early Tool Lifecycle Tests

**Files:**
- Modify: `tests/core/test_pipeline.py`
- Reference: `src/core/pipeline.py`

- [ ] **Step 1: Write failing tests for `turn_id` propagation on process events**

```python
async def test_pipeline_events_include_turn_id(triage_agent, workspace_entry):
    seen = []

    async def on_event(event):
        seen.append(event)

    stream_result = FakeStreamResult(events=[], final_output="ok")
    with patch("src.core.pipeline.Runner.run_streamed", return_value=stream_result):
        pipeline = Pipeline(triage_agent=triage_agent, session_root=workspace_entry.dir / "memory")
        await pipeline.run("hello", on_event=on_event, active_workspace=workspace_entry, turn_id="turn_123")

    assert any(getattr(event, "turn_id", None) == "turn_123" for event in seen)
```

- [ ] **Step 2: Write failing tests for early function-call add/done mapping**

```python
from openai.types.responses import ResponseFunctionToolCall
from openai.types.responses import ResponseOutputItemAddedEvent, ResponseOutputItemDoneEvent


@pytest.mark.asyncio
async def test_pipeline_maps_raw_function_call_add_done_to_tool_events(
    triage_agent, workspace_entry
):
    tool_call = ResponseFunctionToolCall(
        id="fc_1",
        call_id="call_1",
        name="list_files",
        arguments='{"path":"employees.csv"}',
        type="function_call",
    )
    stream_result = FakeStreamResult(
        events=[
            RawResponsesStreamEvent(
                data=ResponseOutputItemAddedEvent(
                    item=tool_call.model_copy(update={"arguments": ""}),
                    output_index=0,
                    sequence_number=1,
                    type="response.output_item.added",
                )
            ),
            RawResponsesStreamEvent(
                data=ResponseOutputItemDoneEvent(
                    item=tool_call,
                    output_index=0,
                    sequence_number=2,
                    type="response.output_item.done",
                )
            ),
        ],
        final_output="ok",
    )

    seen = []

    async def on_event(event):
        seen.append(event)

    with patch("src.core.pipeline.Runner.run_streamed", return_value=stream_result):
        pipeline = Pipeline(
            triage_agent=triage_agent, session_root=workspace_entry.dir / "memory"
        )
        await pipeline.run(
            "show files",
            on_event=on_event,
            active_workspace=workspace_entry,
            turn_id="turn_123",
        )
    assert any(isinstance(event, ToolCallStart) and event.tool_call_id == "call_1" for event in seen)
    assert any(isinstance(event, ToolCallComplete) and event.args == '{"path":"employees.csv"}' for event in seen)
```

- [ ] **Step 3: Run the pipeline tests and verify they fail**

Run: `uv run pytest tests/core/test_pipeline.py -q`

Expected: FAIL because current events lack `turn_id` and the pipeline still depends on later `RunItemStreamEvent("tool_called")`.

- [ ] **Step 4: Add `turn_id` to pipeline event dataclasses and emitters**

```python
@dataclass
class ToolCallStart:
    kind: str = "tool_call_start"
    turn_id: str = ""
    agent: str = ""
    name: str = ""
    tool_call_id: str = ""
```

- [ ] **Step 5: Implement early raw function-call mapping in `Pipeline.run(...)`**

```python
elif isinstance(event, RawResponsesStreamEvent):
    raw = event.data
    if isinstance(raw, ResponseOutputItemAddedEvent) and getattr(raw.item, "type", "") == "function_call":
        await self._emit(
            on_event,
            ToolCallStart(
                turn_id=turn_id,
                agent=current_agent,
                name=getattr(raw.item, "name", ""),
                tool_call_id=getattr(raw.item, "call_id", ""),
            ),
        )
    elif isinstance(raw, ResponseOutputItemDoneEvent) and getattr(raw.item, "type", "") == "function_call":
        await self._emit(
            on_event,
            ToolCallComplete(
                turn_id=turn_id,
                agent=current_agent,
                name=getattr(raw.item, "name", ""),
                tool_call_id=getattr(raw.item, "call_id", ""),
                args=getattr(raw.item, "arguments", ""),
            ),
        )
```

- [ ] **Step 6: Re-run the pipeline tests and verify they pass**

Run: `uv run pytest tests/core/test_pipeline.py -q`

Expected: PASS

---

### Task 4: Repair the Model Wrapper Streaming and Telemetry Contract

**Files:**
- Modify: `tests/core/engine/test_agents_model.py`
- Modify: `src/core/engine/agents_model.py`

- [ ] **Step 1: Write failing tests for malformed tool-call retry**

```python
@pytest.mark.asyncio
async def test_agents_model_retries_once_on_malformed_tool_call(fake_llama_model):
    calls = {"count": 0}

    def fake_completion(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "choices": [{"message": {"content": '<tool_call>{"name":"hello","arguments":{'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        return {
            "choices": [{"message": {"content": '<tool_call>{"name":"hello","arguments":{"name":"Ada"}}</tool_call>'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    fake_llama_model._llama.create_chat_completion = fake_completion
    model = LlamaCppAgentsModel(fake_llama_model, ModelConfig(), agent_label="triage")
    response = await model.get_response(
        system_instructions="You are helpful.",
        input="hi",
        model_settings=ModelSettings(),
        tools=[hello],
        output_schema=None,
        handoffs=[],
        tracing=MagicMock(),
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
    )
    assert response.output[0].name == "hello"
    assert calls["count"] == 2
```

- [ ] **Step 2: Write failing tests for required telemetry fields and reasoning separation**

```python
@pytest.mark.asyncio
async def test_agents_model_emits_required_telemetry_fields(fake_llama_model):
    seen = []

    def fake_emit(component: str, event: str, **fields):
        seen.append((component, event, fields))

    model = LlamaCppAgentsModel(fake_llama_model, ModelConfig(), agent_label="triage")
    with patch("src.core.engine.agents_model.telemetry.emit_event", new=fake_emit):
        await model.get_response(
            system_instructions="You are helpful.",
            input="hi",
            model_settings=ModelSettings(max_tokens=111),
            tools=[],
            output_schema=None,
            handoffs=[],
            tracing=MagicMock(),
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )

    payload = next(fields for component, event, fields in seen if event == "get_response_complete")
    assert payload["input_messages"] >= 1
    assert payload["input_chars"] >= 2
    assert payload["effective_max_tokens"] == 111
```

- [ ] **Step 3: Run the model-wrapper tests and verify they fail**

Run: `uv run pytest tests/core/engine/test_agents_model.py -q`

Expected: FAIL because malformed tool-call retry and the richer telemetry fields are not implemented.

- [ ] **Step 4: Implement one constrained retry for malformed tool-call output**

```python
def _completion_with_retry(
    self,
    messages: list[dict],
    *,
    tools: list[Any],
    handoffs: list[Any],
    temperature: float,
    top_p: float,
    max_new_tokens: int,
    stop: list[str] | None,
):
    result = self._llm.completion(
        messages,
        temperature=temperature,
        top_p=top_p,
        max_new_tokens=max_new_tokens,
        stop=stop,
    )
    try:
        return self._parse_model_output(result.text, tools, handoffs), result
    except UserError:
        retry_messages = messages + [
            {"role": "system", "content": "Emit valid JSON tool_call only."}
        ]
        retry_result = self._llm.completion(
            retry_messages,
            temperature=temperature,
            top_p=top_p,
            max_new_tokens=max_new_tokens,
            stop=stop,
        )
        return self._parse_model_output(retry_result.text, tools, handoffs), retry_result
```

- [ ] **Step 5: Add required telemetry fields to success events**

```python
telemetry.emit_event(
    "engine",
    "get_response_complete",
    actor=self._agent_label,
    status="ok",
    elapsed_ms=elapsed,
    input_messages=len(messages),
    input_chars=sum(len(msg.get("content", "")) for msg in messages),
    input_tokens_est=sum(len(msg.get("content", "")) for msg in messages) // 4,
    output_chars=len(parsed.message),
    output_chunks=1,
    effective_max_tokens=max_tokens,
    compaction_triggered=_compacted,
    compaction_cache_hit=False,
    finish_reason="tool_calls" if parsed.tool_calls else result.finish_reason,
)
```

- [ ] **Step 6: Re-run the model-wrapper tests and verify they pass**

Run: `uv run pytest tests/core/engine/test_agents_model.py -q`

Expected: PASS

---

### Task 5: Finish the `ProcessLog` Runtime Implementation on Top of the New Event Contract

**Files:**
- Modify: `src/cli/process_log.py`
- Modify: `tests/cli/test_process_log.py`
- Reference: `src/core/pipeline.py`

- [ ] **Step 1: Add per-block tool-row state to `AgentProcessBlock`**

```python
class AgentProcessBlock(Collapsible):
    def __init__(self, agent: str) -> None:
        self.agent = agent
        self._lines: list[str] = []
        self._tool_rows: dict[str, _ToolRow] = {}
        self._content_widget = Static("", markup=False)
        super().__init__(self._content_widget, title=f"+ {agent}", collapsed=True)

    def start_tool(self, tool_call_id: str, name: str) -> None:
        self._tool_rows[tool_call_id] = _ToolRow(name=name, rendered_call=f"-> {name}(...)")
        self._rebuild()

    def complete_tool(self, tool_call_id: str, name: str, args: str) -> None:
        row = self._tool_rows.setdefault(tool_call_id, _ToolRow(name=name, rendered_call=f"-> {name}(...)"))
        row.rendered_call = f"-> {name}({args})"
        self._rebuild()

    def add_tool_output(self, tool_call_id: str, output: str) -> None:
        row = self._tool_rows.get(tool_call_id)
        if row is None:
            self._lines.append(f"<- {output}")
        else:
            row.output_lines.append(f"<- {output}")
        self._rebuild()
```

- [ ] **Step 2: Update `ProcessLog.handle_event(...)` to use `turn_id`-aware lookups**

```python
elif isinstance(event, ToolCallStart):
    block = self.get_block(event.agent, turn_id=event.turn_id)
    if block:
        block.start_tool(event.tool_call_id, event.name)
```

- [ ] **Step 3: Run the process-log tests and verify they pass against runtime code**

Run: `uv run pytest tests/cli/test_process_log.py -q`

Expected: PASS

---

### Task 6: Repair the Workspace Tool Contract and Telemetry Surface

**Files:**
- Modify: `tests/core/tools/test_workspace_files.py`
- Modify: `src/core/tools/workspace_files.py`

- [ ] **Step 1: Write failing tests for `columns_schema`, scoped errors, truncation, and `column_stats(path, column)`**

```python
def test_inspect_file_schema_returns_columns_schema(workspace_with_csv):
    _set_active_workspace(workspace_with_csv)
    payload = json.loads(
        asyncio.run(inspect_file_schema.on_invoke_tool(_ToolCtx(), '{"path":"employees.csv"}'))
    )
    assert payload["status"] == "ok"
    assert payload["data"]["columns_schema"]["salary"] == "int64"


def test_column_stats_accepts_path_and_column(workspace_with_csv):
    _set_active_workspace(workspace_with_csv)
    payload = json.loads(
        asyncio.run(column_stats.on_invoke_tool(_ToolCtx(), '{"path":"employees.csv","column":"salary"}'))
    )
    assert payload["status"] == "ok"
    assert payload["data"]["column"] == "salary"
    assert payload["data"]["stats"]["mean_value"] == 60000.0


def test_scope_violation_returns_path_out_of_scope_reason(workspace_with_csv):
    _set_active_workspace(workspace_with_csv)
    payload = json.loads(
        asyncio.run(inspect_file_schema.on_invoke_tool(_ToolCtx(), '{"path":"../secret.csv"}'))
    )
    assert payload["status"] == "error"
    assert payload["reason"] == "path_out_of_scope"
```

- [ ] **Step 2: Write failing telemetry and truncation tests**

```python
def test_preview_file_reports_truncation_metadata(workspace_with_csv):
    _set_active_workspace(workspace_with_csv)
    with patch("src.core.tools.workspace_files.get_obs_max_chars", return_value=20):
        payload = json.loads(
            asyncio.run(preview_file.on_invoke_tool(_ToolCtx(), '{"path":"employees.csv","nrows":2}'))
        )
    assert payload["truncated"]["preview"] > 0


def test_workspace_file_tools_emit_telemetry(workspace_with_csv):
    seen = []

    def fake_emit(component: str, event: str, **fields):
        seen.append((component, event, fields))

    with patch("src.core.tools.workspace_files.telemetry.emit_event", new=fake_emit):
        _set_active_workspace(workspace_with_csv)
        asyncio.run(inspect_file_schema.on_invoke_tool(_ToolCtx(), '{"path":"employees.csv"}'))
    assert any(event == "tool_invoked" and fields["tool"] == "inspect_file_schema" for _, event, fields in seen)
```

- [ ] **Step 3: Run the workspace tool tests and verify they fail**

Run: `uv run pytest tests/core/tools/test_workspace_files.py -q`

Expected: FAIL because `columns_schema`, `column_stats(path, column)`, truncation metadata, and telemetry are not present.

- [ ] **Step 4: Implement shared envelope and telemetry helpers**

```python
def get_obs_max_chars() -> int:
    return 4000


def _emit_tool_telemetry(tool_name: str, *, status: str, output_chars: int, truncated: dict | None = None) -> None:
    telemetry.emit_event(
        "tools",
        "tool_invoked",
        tool=tool_name,
        status=status,
        output_chars=output_chars,
        truncated=bool(truncated),
    )


def _payload(tool_name: str, *, status: str, data: dict | None = None, reason: str | None = None, truncated: dict | None = None, error: str | None = None) -> str:
    payload = {
        "status": status,
        "tool": tool_name,
        "schema_version": 1,
        "data": data or {},
    }
    if reason:
        payload["reason"] = reason
    if truncated:
        payload["truncated"] = truncated
    if error:
        payload["error"] = error
    rendered = json.dumps(payload, indent=2)
    _emit_tool_telemetry(tool_name, status=status, output_chars=len(rendered), truncated=truncated)
    return rendered
```

- [ ] **Step 5: Implement the spec-shaped tool responses**

```python
@function_tool
def inspect_file_schema(path: str) -> str:
    workspace = active_workspace()
    result = _load_workspace_df(workspace.dir / "data", path)
    if isinstance(result, str):
        return _payload("inspect_file_schema", status="error", error=result)
    _, df = result
    return _payload(
        "inspect_file_schema",
        status="ok",
        data={
            "path": path,
            "columns_schema": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "shape": list(df.shape),
        },
    )


@function_tool
def column_stats(path: str, column: str) -> str:
    workspace = active_workspace()
    result = _load_workspace_df(workspace.dir / "data", path)
    if isinstance(result, str):
        return _payload("column_stats", status="error", error=result)
    _, df = result
    series = df[column]
    if pd.api.types.is_numeric_dtype(series):
        stats = {"is_numeric": True, "mean_value": float(series.mean()), "min": float(series.min()), "max": float(series.max())}
    else:
        stats = {"is_numeric": False, "top_values": series.value_counts().head(5).to_dict()}
    return _payload("column_stats", status="ok", data={"path": path, "column": column, "stats": stats})
```

- [ ] **Step 6: Re-run the workspace tool tests and verify they pass**

Run: `uv run pytest tests/core/tools/test_workspace_files.py -q`

Expected: PASS

---

### Task 7: Repair `KnowledgeStore.search(...)` to Honor `path_glob` and `regex`

**Files:**
- Modify: `src/core/knowledge_store.py`
- Add: `tests/core/test_knowledge_store.py`

- [ ] **Step 1: Write failing tests for `path_glob` and `regex`**

```python
def test_search_honors_path_glob(tmp_path: Path):
    store = KnowledgeStore(tmp_path)
    (tmp_path / "memory" / "notes").mkdir(parents=True)
    (tmp_path / "memory" / "notes" / "a.md").write_text("headcount changed")
    (tmp_path / "memory" / "functions").mkdir(parents=True)
    (tmp_path / "memory" / "functions" / "calc.py").write_text("headcount changed")

    results = store.search("headcount", path_glob="notes/*.md")
    assert [item["path"] for item in results] == ["notes/a.md"]


def test_search_honors_regex(tmp_path: Path):
    store = KnowledgeStore(tmp_path)
    (tmp_path / "memory" / "notes").mkdir(parents=True)
    (tmp_path / "memory" / "notes" / "a.md").write_text("salary_band_3")

    results = store.search(r"salary_band_\\d+", regex=True)
    assert results[0]["match"] == "salary_band_3"
```

- [ ] **Step 2: Run the focused search tests and verify they fail**

Run: `uv run pytest tests/core/test_knowledge_store.py -q`

Expected: FAIL because current search ignores `path_glob` and `regex`.

- [ ] **Step 3: Implement `path_glob` and `regex` support**

```python
def search(self, query: str, path_glob: str = "**/*", regex: bool = False, max_matches: int = 50) -> list[dict]:
    self._ensure_dirs()
    pattern = re.compile(query) if regex else None
    results: list[dict] = []
    for path in sorted(self._memory_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_path = str(path.relative_to(self._memory_dir))
        if not fnmatch.fnmatch(rel_path, path_glob):
            continue
        text = path.read_text()
        if regex:
            match = pattern.search(text)
            if not match:
                continue
            results.append({"path": rel_path, "match": match.group(0)})
        elif query.lower() in text.lower():
            results.append({"path": rel_path, "match": query})
        if len(results) >= max_matches:
            break
    return results
```

- [ ] **Step 4: Re-run the focused search tests and verify they pass**

Run: `uv run pytest tests/core/test_knowledge_store.py -q`

Expected: PASS

---

### Task 8: Reconcile `ChatApp` With the New Process-Log and Clarification Contracts

**Files:**
- Modify: `src/cli/app.py`
- Modify: `tests/cli/test_app.py`
- Reference: `src/cli/process_log.py`

- [ ] **Step 1: Write or update failing UI tests for per-turn process-log reset behavior**

```python
@patch("src.core.engine.llm.LlmModel")
@patch("src.core.pipeline_factory.build_pipeline")
@patch("src.core.terminal.repair_standard_streams")
async def test_new_turn_process_log_uses_new_turn_id(
    mock_repair, mock_build_pipeline, mock_llm
):
    async def scripted_run(message, on_event, active_workspace, turn_id=None):
        await on_event(AgentStarted(agent="triage", turn_id=turn_id))
        await on_event(StatusUpdate(text="Thinking…", level="working", agent="triage", turn_id=turn_id))
        return PipelineResult(answer="done", used_agent=True, route="conversational")

    pipeline = MagicMock()
    pipeline.run = scripted_run
    mock_build_pipeline.return_value = pipeline
    mock_llm.return_value = MagicMock()

    manager = _make_mock_manager()
    app = ChatApp(model_path="/fake/model.gguf", manager=manager)
    async with app.run_test() as pilot:
        await pilot.pause(0.5)
        await _type_text(pilot, app, "chat-input", "hi")
        await pilot.press("enter")
        await pilot.pause(0.4)
        first_turn_id = app._active_turn_id
        assert app.query_one("#process-log").has_block("triage", turn_id=first_turn_id)

        await _type_text(pilot, app, "chat-input", "hello")
        await pilot.press("enter")
        await pilot.pause(0.4)
        second_turn_id = app._active_turn_id
        assert first_turn_id != second_turn_id
        assert app.query_one("#process-log").has_block("triage", turn_id=second_turn_id)
```

- [ ] **Step 2: Run the UI tests and verify they fail if the app still uses agent-only log lookups**

Run: `uv run pytest tests/cli/test_app.py tests/cli/test_process_log.py -q`

Expected: FAIL if `ChatApp` and `ProcessLog` are still mismatched on lookup shape.

- [ ] **Step 3: Update `ChatApp` process-log interactions to pass through the new event contract**

```python
turn_id = uuid.uuid4().hex[:12]
self._active_turn_id = turn_id
self.query_one("#process-log", ProcessLog).reset()
self._turn_started_at[turn_id] = time.perf_counter()
self._turn_in_flight = True
self._run_pipeline(turn_id, text)
```

- [ ] **Step 4: Re-run the UI tests and verify they pass**

Run: `uv run pytest tests/cli/test_app.py tests/cli/test_process_log.py -q`

Expected: PASS

---

### Task 9: Run the Full Targeted Verification Sweep

**Files:**
- No code changes expected

- [ ] **Step 1: Run the core targeted suite**

Run:

```bash
uv run pytest \
  tests/cli/test_process_log.py \
  tests/cli/test_app.py \
  tests/core/test_clarification_bus.py \
  tests/core/tools/test_workspace_files.py \
  tests/core/engine/test_agents_model.py \
  tests/core/test_pipeline.py \
  tests/core/test_knowledge_store.py -q
```

Expected: PASS

- [ ] **Step 2: Run the broader regression suite for touched areas**

Run:

```bash
uv run pytest -q
```

Expected: PASS, or any remaining failures are unrelated and documented with exact failure output before proceeding.

- [ ] **Step 3: Manual checkpoint**

Record in the implementation notes:

```text
M1: process log now per turn/per agent; pending tool row updates in place.
M2: tool envelopes, truncation, telemetry, and search contract aligned.
M3: wrapper retry + telemetry + early tool lifecycle mapping aligned.
M5: clarification flow uses public bus API; cancellation deterministic.
```

---

## Self-Review

### Spec coverage

- Spec 7 section 4.1 coverage:
  - Task 1 and Task 5 cover per-turn/per-agent blocks, default collapse state, and tool-row lifecycle.
- Spec 3 tool-surface coverage:
  - Task 6 covers `inspect_file_schema`, `column_stats`, truncation, scope envelopes, and telemetry.
  - Task 7 covers `search(path_glob, regex)`.
- Spec 1 model-wrapper coverage:
  - Task 4 covers malformed tool-call retry, telemetry fields, and tool-call protocol safety.
  - Task 3 covers earlier pipeline mapping from raw function-call events.
- Spec 3/7 clarification coverage:
  - Task 2 and Task 8 cover public bus consumption and deterministic cancellation.

### Placeholder scan

- No `TODO`, `TBD`, or “implement later” placeholders remain.
- Every task has exact files, commands, and concrete code examples.

### Type consistency

- `turn_id` is added consistently to pipeline events that the UI consumes.
- `column_stats(path, column)` is used consistently in tests and runtime examples.
- `tool_call_id` remains the correlation key between start, complete, and output events.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-m1-m2-m3-m5-compatibility-bridge.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
