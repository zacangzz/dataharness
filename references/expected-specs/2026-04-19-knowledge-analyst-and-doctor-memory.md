# Knowledge Analyst And Doctor Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the local knowledge bank, preference memory, saved-function freshness, analyst semantic delegation, and doctor maintenance flows on top of the migrated Agents SDK runtime.

**Architecture:** Build on the runtime/tool foundation from the earlier plans: `KnowledgeStore`, `data/` + `memory/` workspace layout, and the full tool surface already exist. This plan completes the analyst feedback loop, preference recall, semantic delegation, doctor maintenance behavior, and the end-to-end regressions that prove those contracts.

**Tech Stack:** Python 3.12, local filesystem JSON and Markdown state, `openai-agents`, Textual-driven clarification bus, pytest, workspace fixtures

---

### Task 1: Complete Knowledge Tool Semantics And Saved-Function Freshness

**Files:**
- Modify: `src/core/knowledge_store.py`
- Modify: `src/core/tools/knowledge.py`
- Modify: `src/core/tools/documents.py`
- Modify: `tests/core/tools/test_knowledge.py`
- Modify: `tests/core/tools/test_documents.py`

- [ ] **Step 1: Write the failing semantic-store tests**

```python
def test_update_user_preferences_merges_explicit_values(workspace_memory):
    with workspace_context("test", workspace_memory.parent):
        update_user_preferences({"answer_style": "concise"})
        update_user_preferences({"units": "percent"})
        payload = json.loads(get_user_preferences())
    assert payload["data"]["preferences"] == {"answer_style": "concise", "units": "percent"}


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

Run: `uv run pytest tests/core/tools/test_knowledge.py tests/core/tools/test_documents.py -q`
Expected: FAIL because the baseline tool surface exists, but the deeper freshness and preference semantics are not complete yet.

- [ ] **Step 3: Complete `KnowledgeStore` validation and merge semantics**

```python
class KnowledgeStore:
    def validate_saved_function(self, name: str, args: dict) -> ValidationResult:
        entry = self._function_index_entry(name)
        current_digests = {path: self.file_digest(path) for path in entry.source_files}
        if current_digests != entry.source_digests:
            return ValidationResult(ok=False, reason="stale_saved_function", details={"name": name})
        if self.schema_fingerprint(args["path"]) != entry.schema_fingerprint:
            return ValidationResult(ok=False, reason="schema_mismatch", details={"name": name})
        return ValidationResult(ok=True, reason="ok", details={"name": name})

    def update_preferences(self, preferences: dict) -> dict:
        current = self.read_preferences()
        current.update(preferences)
        self._write_json(self.root / "preferences.json", current)
        return current
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/core/tools/test_knowledge.py tests/core/tools/test_documents.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/knowledge_store.py src/core/tools/knowledge.py src/core/tools/documents.py tests/core/tools/test_knowledge.py tests/core/tools/test_documents.py
git commit -m "feat: complete knowledge store semantics"
```

### Task 2: Wire Analyst Decision Tree And Semantic Delegation

**Files:**
- Modify: `src/core/agents/data_analyst.py`
- Modify: `src/core/prompts/analyst.md`
- Modify: `src/core/tools/knowledge.py`
- Create: `tests/core/agents/test_data_analyst.py`

- [ ] **Step 1: Write the failing analyst behavior tests**

```python
@pytest.mark.asyncio
async def test_new_file_analysis_does_not_require_intake_first(analyst_runner, workspace_entry):
    result = await analyst_runner("What is the average salary?", workspace_entry)
    assert result.route == "data_analyst"
    assert result.used_tool("inspect_file_schema")


@pytest.mark.asyncio
async def test_stale_saved_function_falls_back_without_doctor_handoff(analyst_runner, workspace_entry):
    result = await analyst_runner("Reuse the saved salary function", workspace_entry)
    assert result.used_tool("run_saved_function")
    assert result.final_text
    assert "doctor" not in result.agent_trail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/agents/test_data_analyst.py -q`
Expected: FAIL because the analyst prompt and runtime do not yet implement the decision tree and feedback-loop branches.

- [ ] **Step 3: Add freshness preflight and same-turn analysis policy**

```python
if saved_match and preflight.status == "ok":
    return json.loads(run_saved_function(saved_match.name, saved_match.args))
if saved_match:
    emit_status("Saved function stale; recomputing")
    schema = json.loads(inspect_file_schema(saved_match.path))
    preview = json.loads(preview_file(saved_match.path))
    return await self._run_shell_analysis(
        question=user_question,
        schema=schema["data"],
        preview=preview["data"],
    )
```

- [ ] **Step 4: Add `call_knowledge()` sub-run support**

```python
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
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/core/agents/test_data_analyst.py tests/core/tools/test_knowledge.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/agents/data_analyst.py src/core/prompts/analyst.md src/core/tools/knowledge.py tests/core/agents/test_data_analyst.py
git commit -m "feat: add analyst feedback loop and semantic delegation"
```

### Task 3: Implement Knowledge And Doctor Behaviors

**Files:**
- Modify: `src/core/agents/knowledge.py`
- Modify: `src/core/agents/doctor.py`
- Modify: `src/core/prompts/knowledge.md`
- Modify: `src/core/prompts/doctor.md`
- Create: `tests/core/agents/test_knowledge_agent.py`
- Create: `tests/core/agents/test_doctor_agent.py`

- [ ] **Step 1: Write the failing knowledge and doctor tests**

```python
@pytest.mark.asyncio
async def test_knowledge_captures_preference_statement(knowledge_runner, workspace_entry):
    await knowledge_runner("Prefer concise answers and percentages by default", workspace_entry)
    store = KnowledgeStore(workspace_entry.dir / "memory")
    assert store.read_preferences()["answer_style"] == "concise"


@pytest.mark.asyncio
async def test_doctor_requires_explicit_maintenance_intent(doctor_runner, workspace_entry):
    result = await doctor_runner("What is average salary?", workspace_entry)
    assert result.status == "not_authorized_for_analysis"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/agents/test_knowledge_agent.py tests/core/agents/test_doctor_agent.py -q`
Expected: FAIL because the deep behaviors are not implemented yet.

- [ ] **Step 3: Implement the knowledge agent entry points**

```python
def build_knowledge_agent(model):
    return Agent(
        name="knowledge",
        instructions=_load_prompt("knowledge.md"),
        model=model,
        tools=[list_files, inspect_file_schema, preview_file, read_text, extract_document_text, search, file_digest, get_file_metadata, set_file_metadata, get_user_preferences, update_user_preferences, write_knowledge_note, save_python_function, list_saved_functions, user_input],
    )
```

- [ ] **Step 4: Implement doctor scan-first and maintenance-only rules**

```python
def build_doctor_agent(model):
    return Agent(
        name="doctor",
        instructions=_load_prompt("doctor.md"),
        model=model,
        tools=[list_knowledge, rebuild_index, delete_saved_function, delete_knowledge_note, delete_file_metadata, call_knowledge, user_input],
    )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/core/agents/test_knowledge_agent.py tests/core/agents/test_doctor_agent.py tests/core/agents/test_data_analyst.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/agents/knowledge.py src/core/agents/doctor.py src/core/prompts/knowledge.md src/core/prompts/doctor.md tests/core/agents/test_knowledge_agent.py tests/core/agents/test_doctor_agent.py
git commit -m "feat: add knowledge and doctor agent behaviors"
```

### Task 4: Add End-To-End Memory Regression Coverage

**Files:**
- Modify: `tests/core/test_pipeline.py`
- Create: `tests/integration/test_memory_workflows.py`
- Create: `tests/integration/budgets.json`

- [ ] **Step 1: Write the failing integration fixtures**

```python
@pytest.mark.integration
async def test_preference_recall_changes_later_answer(real_pipeline, workspace_entry):
    await real_pipeline.run("Prefer concise answers", on_event=lambda event: None, active_workspace=workspace_entry)
    result = await real_pipeline.run("What is average salary?", on_event=lambda event: None, active_workspace=workspace_entry)
    assert len(result.final_text) < 400


@pytest.mark.integration
async def test_drift_visible_but_no_doctor_hijack(real_pipeline, workspace_entry):
    result = await real_pipeline.run("Reuse my saved salary function", on_event=lambda event: None, active_workspace=workspace_entry)
    assert "doctor" not in result.agent_trail
```

- [ ] **Step 2: Run the failing targeted slice**

Run: `uv run pytest tests/core/test_pipeline.py tests/integration/test_memory_workflows.py -q`
Expected: FAIL until the full memory workflow is wired.

- [ ] **Step 3: Finish the pipeline hooks for drift, preferences, and same-turn file analysis**

```python
signals = TinySignals(
    has_data=has_data,
    new_files_present=new_files_present,
    gaps_open_present=gaps_open_present,
    drift_present=drift_present,
)
```

- [ ] **Step 4: Run the memory regression slice**

Run: `uv run pytest tests/core/test_pipeline.py tests/integration/test_memory_workflows.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/core/test_pipeline.py tests/integration/test_memory_workflows.py tests/integration/budgets.json
git commit -m "test: cover memory workflows and stale artifact handling"
```
