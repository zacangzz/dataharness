# Tools Specialists Triage And Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current smolagents `Pipeline` with an Agents SDK orchestrator, the full spec-defined tool surface, specialist builders, triage routing, and the runtime workspace layout they depend on.

**Architecture:** Start by introducing the transparent `data/` + `memory/` workspace layout, `KnowledgeStore`, active-workspace context, and clarification bus. Then implement the full tool surface from spec 3, bind all five specialists with their documented tool sets, and finish with an async `Pipeline` that enforces the tiny triage signal block, sandbox manifest, and canonical event stream.

**Tech Stack:** Python 3.12, `openai-agents`, `pytest`, Textual-compatible async callbacks, local filesystem tools, existing workspace manager

---

### Task 1: Introduce Workspace Runtime Layout, Context, And Clarification Bus

**Files:**
- Create: `src/core/knowledge_store.py`
- Modify: `src/core/workspace.py`
- Create: `src/core/runtime_context.py`
- Create: `src/core/clarification_bus.py`
- Modify: `tests/core/test_workspace.py`
- Create: `tests/core/test_knowledge_store.py`
- Create: `tests/core/test_runtime_context.py`
- Create: `tests/core/test_clarification_bus.py`

- [ ] **Step 1: Write the failing storage, context, and bus tests**

```python
from pathlib import Path

from src.core.knowledge_store import KnowledgeStore
from src.core.runtime_context import active_workspace, workspace_context
from src.core.clarification_bus import ClarificationBus


def test_workspace_creates_data_and_memory_dirs(tmp_path):
    manager = WorkspaceManager(root=tmp_path)
    manager.create("headcount")
    workspace = tmp_path / "workspaces" / "headcount"
    assert (workspace / "data").is_dir()
    assert (workspace / "memory").is_dir()


def test_knowledge_store_bootstraps_indexes(tmp_path):
    store = KnowledgeStore(tmp_path / "workspace" / "memory")
    store.ensure_layout()
    assert (store.root / "functions" / "index.json").exists()
    assert (store.root / "notes" / "index.json").exists()


def test_workspace_context_sets_active_paths(tmp_path):
    with workspace_context("headcount", tmp_path):
        assert active_workspace().name == "headcount"
        assert active_workspace().dir == tmp_path


@pytest.mark.asyncio
async def test_clarification_bus_round_trip():
    bus = ClarificationBus()
    token, future = await bus.ask("Which file?")
    bus.answer(token, "employees.csv")
    assert await future == "employees.csv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_workspace.py tests/core/test_knowledge_store.py tests/core/test_runtime_context.py tests/core/test_clarification_bus.py -q`
Expected: FAIL because the workspace layout, store, and runtime context modules do not exist yet.

- [ ] **Step 3: Implement the workspace layout and knowledge store**

```python
class KnowledgeStore:
    def ensure_layout(self) -> None:
        (self.root / "files").mkdir(parents=True, exist_ok=True)
        (self.root / "functions").mkdir(parents=True, exist_ok=True)
        (self.root / "notes" / "gaps").mkdir(parents=True, exist_ok=True)
        self._write_json_if_missing(self.root / "functions" / "index.json", {"functions": []})
        self._write_json_if_missing(self.root / "notes" / "index.json", {"notes": []})
        self._write_json_if_missing(self.root / "preferences.json", {})


def _ensure_workspace_dirs(self, path: Path) -> None:
    (path / "data").mkdir(parents=True, exist_ok=True)
    (path / "memory").mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ActiveWorkspace:
    name: str
    dir: Path


def active_workspace() -> ActiveWorkspace:
    current = _ACTIVE_WORKSPACE.get()
    if current is None:
        raise RuntimeError("Active workspace is not set")
    return current


def pipeline_runtime() -> "Pipeline":
    runtime = _PIPELINE_RUNTIME.get()
    if runtime is None:
        raise RuntimeError("Pipeline runtime is not set")
    return runtime


class ClarificationBus:
    async def ask(self, question: str) -> tuple[str, asyncio.Future[str]]:
        token = uuid.uuid4().hex[:12]
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending[token] = future
        self._questions.put_nowait({"token": token, "question": question})
        return token, future

    def answer(self, token: str, text: str) -> None:
        future = self._pending.pop(token)
        future.set_result(text)

    def cancel_all(self) -> None:
        for token, future in list(self._pending.items()):
            future.cancel()
            self._pending.pop(token, None)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/core/test_workspace.py tests/core/test_knowledge_store.py tests/core/test_runtime_context.py tests/core/test_clarification_bus.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/knowledge_store.py src/core/workspace.py src/core/runtime_context.py src/core/clarification_bus.py tests/core/test_workspace.py tests/core/test_knowledge_store.py tests/core/test_runtime_context.py tests/core/test_clarification_bus.py
git commit -m "feat: add workspace runtime layout and turn context"
```

### Task 2: Implement The Full Agents SDK Tool Surface

**Files:**
- Modify: `src/core/tools/workspace_files.py`
- Modify: `src/core/tools/user_input.py`
- Create: `src/core/tools/knowledge.py`
- Create: `src/core/tools/documents.py`
- Create: `tests/core/tools/test_workspace_files.py`
- Create: `tests/core/tools/test_user_input.py`
- Create: `tests/core/tools/test_knowledge.py`
- Create: `tests/core/tools/test_documents.py`

- [ ] **Step 1: Write the failing tool tests**

```python
def test_list_files_returns_json_envelope(workspace_fixture):
    with workspace_context("test", workspace_fixture):
        payload = json.loads(list_files())
    assert payload["status"] == "ok"
    assert payload["tool"] == "list_files"


@pytest.mark.asyncio
async def test_user_input_awaits_bus_answer(clarification_bus):
    task = asyncio.create_task(user_input("Which file?"))
    token = clarification_bus.last_token
    clarification_bus.answer(token, "employees.csv")
    payload = json.loads(await task)
    assert payload["data"]["answer"] == "employees.csv"


def test_update_user_preferences_merges_explicit_values(workspace_memory):
    with workspace_context("test", workspace_memory.parent):
        update_user_preferences({"answer_style": "concise"})
        payload = json.loads(get_user_preferences())
    assert payload["data"]["preferences"]["answer_style"] == "concise"


def test_run_saved_function_blocks_stale_code(workspace_memory):
    store = KnowledgeStore(workspace_memory)
    store.save_python_function(
        name="mean_salary",
        code="def mean_salary(path): return 100.0",
        signature="mean_salary(path: str) -> float",
        docstring="Return mean salary",
        source_files=["data/employees.csv"],
        source_digests={"data/employees.csv": "old-digest"},
        schema_fingerprint="salary:int64",
    )
    payload = json.loads(run_saved_function("mean_salary", {"path": "employees.csv"}))
    assert payload["status"] == "error"
    assert payload["reason"] == "stale_saved_function"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/tools/test_workspace_files.py tests/core/tools/test_user_input.py tests/core/tools/test_knowledge.py tests/core/tools/test_documents.py -q`
Expected: FAIL because the old smolagents tool classes do not match the new surface and the knowledge/document tools do not exist yet.

- [ ] **Step 3: Replace tool classes with functions and add common envelopes**

```python
@function_tool
def list_files() -> str:
    workspace = active_workspace()
    files = _list_data_files(workspace.dir / "data")
    return _ok("list_files", {"files": files})


@function_tool
async def user_input(question: str) -> str:
    token, future = await clarification_bus.ask(question)
    answer = await future
    return _ok("user_input", {"token": token, "answer": answer})


@function_tool
def get_user_preferences() -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("get_user_preferences", {"preferences": store.read_preferences()})


@function_tool
def run_saved_function(name: str, args: dict) -> str:
    store = KnowledgeStore.for_active_workspace()
    preflight = store.validate_saved_function(name, args)
    if not preflight.ok:
        return _error("run_saved_function", reason=preflight.reason, data=preflight.as_dict())
    result = store.execute_saved_function(name, args)
    return _ok("run_saved_function", {"result": result, "validation_status": "ok"})
```

- [ ] **Step 4: Implement the remaining spec-3 tool set**

```python
def _reject_out_of_scope(path: Path) -> str:
    return _error("inspect_file_schema", reason="path_out_of_scope", path=str(path))


@function_tool
def read_text(path: str, max_bytes: int = 64_000) -> str:
    text = (active_workspace().dir / "data" / path).read_text()[:max_bytes]
    return _ok("read_text", {"path": path, "text": text})


@function_tool
def list_saved_functions() -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("list_saved_functions", {"functions": store.list_saved_functions()})

@function_tool
def save_python_function(name: str, code: str, signature: str, docstring: str, overwrite: bool = False) -> str:
    store = KnowledgeStore.for_active_workspace()
    entry = store.save_python_function(name, code, signature, docstring, overwrite=overwrite)
    return _ok("save_python_function", {"entry": entry})

@function_tool
def get_file_metadata(path: str) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("get_file_metadata", {"metadata": store.get_file_metadata(path)})

@function_tool
def set_file_metadata(path: str, metadata: dict) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("set_file_metadata", {"metadata": store.set_file_metadata(path, metadata)})

@function_tool
def update_user_preferences(preferences: dict) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("update_user_preferences", {"preferences": store.update_preferences(preferences)})

@function_tool
def write_knowledge_note(name: str, content: str, source_files: list[str] | None = None,
                         topic: str | None = None, overwrite: bool = False) -> str:
    store = KnowledgeStore.for_active_workspace()
    note = store.write_knowledge_note(name, content, source_files=source_files, topic=topic, overwrite=overwrite)
    return _ok("write_knowledge_note", {"note": note})

@function_tool
def search(query: str, path_glob: str = "**/*", regex: bool = False, max_matches: int = 50) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("search", {"matches": store.search(query, path_glob=path_glob, regex=regex, max_matches=max_matches)})

@function_tool
def file_digest(path: str) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("file_digest", {"digest": store.file_digest(path)})

@function_tool
def list_knowledge(verbosity: Literal["manifest", "detail"] = "manifest") -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("list_knowledge", {"knowledge": store.list_knowledge(verbosity=verbosity)})

@function_tool
async def call_knowledge(task: str, context: str) -> str:
    runtime = pipeline_runtime()
    child = await Runner.run_streamed(
        knowledge_agent,
        input=f"{task}\n\n{context}",
        session=runtime.session_for(active_workspace()),
        run_config=runtime.run_config_for(active_workspace()),
    )
    return _ok("call_knowledge", {"summary": child.final_output_text})

@function_tool
def delete_saved_function(name: str) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("delete_saved_function", {"deleted": store.delete_saved_function(name)})

@function_tool
def delete_knowledge_note(path: str) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("delete_knowledge_note", {"deleted": store.delete_knowledge_note(path)})

@function_tool
def delete_file_metadata(path: str) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("delete_file_metadata", {"deleted": store.delete_file_metadata(path)})

@function_tool
def rebuild_index(kind: Literal["functions", "notes"]) -> str:
    store = KnowledgeStore.for_active_workspace()
    return _ok("rebuild_index", {"rebuilt": store.rebuild_index(kind)})
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/core/tools/test_workspace_files.py tests/core/tools/test_user_input.py tests/core/tools/test_knowledge.py tests/core/tools/test_documents.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/tools/workspace_files.py src/core/tools/user_input.py src/core/tools/knowledge.py src/core/tools/documents.py tests/core/tools/test_workspace_files.py tests/core/tools/test_user_input.py tests/core/tools/test_knowledge.py tests/core/tools/test_documents.py
git commit -m "feat: add agents sdk tool surface"
```

### Task 3: Build Specialist Agents And Prompts

**Files:**
- Create: `src/core/agents/conversational.py`
- Create: `src/core/agents/data_analyst.py`
- Create: `src/core/agents/clarification.py`
- Create: `src/core/agents/knowledge.py`
- Create: `src/core/agents/doctor.py`
- Create: `src/core/agents/triage.py`
- Create: `src/core/prompts/triage.md`
- Create: `src/core/prompts/conversational.md`
- Create: `src/core/prompts/analyst.md`
- Create: `src/core/prompts/clarification.md`
- Create: `src/core/prompts/knowledge.md`
- Create: `src/core/prompts/doctor.md`
- Create: `tests/core/agents/test_specialists.py`
- Create: `tests/core/agents/test_triage.py`
- Delete: `src/core/agents/hr.py`
- Delete: `src/core/prompts/hr.md`

- [ ] **Step 1: Write the failing builder tests**

```python
def test_conversational_agent_has_no_tools(direct_model):
    agent = build_conversational_agent(direct_model)
    assert agent.name == "conversational"
    assert agent.tools == []


def test_triage_has_five_handoffs(direct_model, specialist_bundle):
    triage = build_triage_agent(direct_model, specialist_bundle)
    assert {handoff.agent_name for handoff in triage.handoffs} == {
        "conversational", "data_analyst", "clarification", "knowledge", "doctor"
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/agents/test_specialists.py tests/core/agents/test_triage.py -q`
Expected: FAIL because the new builders and prompts do not exist yet.

- [ ] **Step 3: Add prompt loaders and agent builders**

```python
def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / name).read_text()


def build_conversational_agent(model):
    return Agent(name="conversational", instructions=_load_prompt("conversational.md"), model=model, tools=[])
```

- [ ] **Step 4: Build analyst and triage with the documented tool sets**

```python
def build_data_analyst_agent(model):
    return SandboxAgent(
        name="data_analyst",
        instructions=_load_prompt("analyst.md"),
        model=model,
        tools=[
            list_files, inspect_file_schema, preview_file, column_stats,
            get_file_metadata, get_user_preferences,
            list_saved_functions, save_python_function, run_saved_function,
            read_text, extract_document_text,
            search, file_digest, list_knowledge,
            user_input, call_knowledge,
        ],
        capabilities=Capabilities.default(),
    )


def build_knowledge_agent(model):
    return Agent(
        name="knowledge",
        instructions=_load_prompt("knowledge.md"),
        model=model,
        tools=[
            list_files, inspect_file_schema, preview_file,
            read_text, extract_document_text, search, file_digest,
            get_file_metadata, set_file_metadata,
            get_user_preferences, update_user_preferences,
            write_knowledge_note, save_python_function, list_saved_functions,
            user_input,
        ],
    )


def build_doctor_agent(model):
    return Agent(
        name="doctor",
        instructions=_load_prompt("doctor.md"),
        model=model,
        tools=[
            list_files, inspect_file_schema, preview_file,
            read_text, search, file_digest,
            get_file_metadata, list_saved_functions, list_knowledge,
            set_file_metadata, write_knowledge_note, save_python_function,
            delete_saved_function, delete_knowledge_note, delete_file_metadata, rebuild_index,
            call_knowledge, user_input,
        ],
    )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/core/agents/test_specialists.py tests/core/agents/test_triage.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/agents/conversational.py src/core/agents/data_analyst.py src/core/agents/clarification.py src/core/agents/knowledge.py src/core/agents/doctor.py src/core/agents/triage.py src/core/prompts/triage.md src/core/prompts/conversational.md src/core/prompts/analyst.md src/core/prompts/clarification.md src/core/prompts/knowledge.md src/core/prompts/doctor.md tests/core/agents/test_specialists.py tests/core/agents/test_triage.py
git rm src/core/agents/hr.py src/core/prompts/hr.md
git commit -m "feat: add specialist and triage agent builders"
```

### Task 4: Replace The Old Pipeline With The Async Orchestrator

**Files:**
- Create: `src/core/pipeline.py`
- Modify: `src/core/pipeline_factory.py`
- Create: `tests/core/test_pipeline.py`
- Delete: `src/core/agents/pipeline.py`
- Delete: `tests/core/agents/test_pipeline.py`

- [ ] **Step 1: Write the failing pipeline-stream tests**

```python
@pytest.mark.asyncio
async def test_pipeline_streams_agent_lifecycle(fake_runner, workspace_entry):
    seen = []
    pipeline = Pipeline(triage_agent=fake_runner.agent, session_root=workspace_entry.dir / "memory")
    await pipeline.run("hello", on_event=seen.append, active_workspace=workspace_entry)
    assert [event.kind for event in seen] == [
        "agent_started",
        "status_update",
        "reasoning_summary",
        "handoff",
        "agent_started",
        "tool_call_start",
        "tool_call_complete",
        "tool_output",
        "token_delta",
        "final_message",
        "agent_finished",
        "status_update",
    ]


@pytest.mark.asyncio
async def test_pipeline_invalidate_workspace_cancels_inflight_turn(fake_runner, workspace_entry):
    pipeline = Pipeline(triage_agent=fake_runner.agent, session_root=workspace_entry.dir / "memory")
    task = asyncio.create_task(
        pipeline.run("long turn", on_event=lambda event: None, active_workspace=workspace_entry)
    )
    await pipeline.invalidate_workspace(workspace_entry.name)
    with pytest.raises(asyncio.CancelledError):
        await task
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_pipeline.py -q`
Expected: FAIL because the new orchestrator does not exist yet.

- [ ] **Step 3: Implement `PipelineEvent` and the thin orchestrator**

```python
@dataclass
class AgentStarted:
    kind: str = "agent_started"
    agent: str


@dataclass
class ToolCallStart:
    kind: str = "tool_call_start"
    agent: str
    name: str


@dataclass
class StatusUpdate:
    kind: str = "status_update"
    text: str
    level: str
    agent: str | None


class Pipeline:
    async def run(self, message: str, on_event, active_workspace) -> PipelineResult:
        async with self._turn_scope(active_workspace):
            await on_event(AgentStarted(agent="triage"))
            await on_event(StatusUpdate(text="Thinking...", level="working", agent="triage"))
            run_result = await Runner.run_streamed(
                self._triage_agent,
                input=self._prepend_tiny_signal_block(message, active_workspace),
                session=self._session_for(active_workspace),
                run_config=self._run_config_for(active_workspace),
            )
            return await self._forward_stream(run_result, on_event)
```

- [ ] **Step 4: Wire `build_pipeline()` to create agents once and sessions per workspace**

```python
def _run_config_for(self, active_workspace: WorkspaceEntry) -> RunConfig:
    manifest = Manifest(entries={
        "data": LocalDir(src=active_workspace.dir / "data", mode="ro"),
        "memory": LocalDir(src=active_workspace.dir / "memory", mode="rw"),
    })
    sandbox_client = UnixLocalSandboxClient()
    return RunConfig(sandbox=SandboxRunConfig(client=sandbox_client, manifest=manifest))


def _prepend_tiny_signal_block(self, message: str, active_workspace: WorkspaceEntry) -> str:
    signals = [
        f"has_data={self._has_data(active_workspace)}",
        f"new_files_present={self._new_files_present(active_workspace)}",
        f"gaps_open_present={self._gaps_open_present(active_workspace)}",
        f"drift_present={self._drift_present(active_workspace)}",
    ]
    return "[routing-signals]\n" + "\n".join(signals) + f"\n[/routing-signals]\n\n{message}"


def build_pipeline(model: LlmModel, workspace_manager: WorkspaceManager) -> Pipeline:
    direct_model = LlamaCppAgentsModel(model, direct_config, agent_label="direct", n_ctx=model.n_ctx)
    agent_model = LlamaCppAgentsModel(model, agent_config, agent_label="agent", n_ctx=model.n_ctx, compaction=Compaction(model, model.n_ctx))
    conversational = build_conversational_agent(direct_model)
    analyst = build_data_analyst_agent(agent_model)
    clarification = build_clarification_agent(direct_model)
    knowledge = build_knowledge_agent(direct_model)
    doctor = build_doctor_agent(agent_model)
    triage_agent = build_triage_agent(
        direct_model,
        conversational_agent=conversational,
        data_analyst_agent=analyst,
        clarification_agent=clarification,
        knowledge_agent=knowledge,
        doctor_agent=doctor,
    )
    return Pipeline(triage_agent=triage_agent, session_root=workspace_manager.active_dir() / "memory")
```

- [ ] **Step 5: Run the pipeline test slice**

Run: `uv run pytest tests/core/test_pipeline.py tests/core/agents/test_specialists.py tests/core/agents/test_triage.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/pipeline.py src/core/pipeline_factory.py tests/core/test_pipeline.py
git rm src/core/agents/pipeline.py tests/core/agents/test_pipeline.py
git commit -m "feat: add agents sdk pipeline orchestrator"
```
