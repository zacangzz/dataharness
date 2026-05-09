# Spec 3 — Tools as Agents SDK `@function_tool`

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2
**Blocks:** specs 4, 5, 6, 7, 8, 9, 10

## 1. Purpose

Re-implement the current smolagents tool set as Agents SDK `@function_tool` callables, so that every specialist agent (conversational, data analyst, clarification) can bind them to a `Runner.run` invocation.

## 2. Scope

### In scope

Rewrites (also stripped of "workspace" prefix — scoping is framework-level via the active-workspace context var, not a naming concern):
- `list_files` (renamed from `list_workspace_files`)
- `inspect_file_schema` (renamed from `describe_workspace_file` — clearer contrast with semantic `get_file_metadata`)
- `preview_file` (renamed from `preview_workspace_file`)
- `column_stats`
- `user_input` (async — see §6)

**Dropped** (agents emit markdown directly; the tools added noise without value):
- `format_table` — removed
- `format_key_value_list` — removed

Knowledge + document tools added here but fully specified in spec 9 §5. Signatures listed in §5.1 below for reference; semantics + atomic writes + schema validation live in spec 9:
- `get_file_metadata`, `set_file_metadata`
- `list_saved_functions`, `save_python_function`, `run_saved_function`
- `read_text`, `extract_document_text`
- `write_knowledge_note`
- `search`, `file_digest`
- `list_knowledge` (manifest by default, optional detail mode — see §5.1)
- `call_knowledge` (sub-run entry: analyst- or doctor-initiated invocation of the knowledge agent for semantic capture — see §5.2)
- `delete_saved_function`, `delete_knowledge_note`, `delete_file_metadata`, `rebuild_index` (doctor-agent-exclusive maintenance tools — see §5.3)

### Out of scope

- SandboxAgent built-in shell/filesystem tools (provided by SDK; consumed in spec 4).
- Agent prompt wiring (spec 4).
- Knowledge-store filesystem layout, schema, and onboarding flow (spec 9).

## 3. Contract

All tools return a JSON string with this envelope (identical to current behavior):

```json
{
  "status": "ok" | "error",
  "tool": "<tool_name>",
  "schema_version": "<int>",
  "data": { ... }
}
```

Primary payload fields remain mirrored at the top level for backward-compatible observation parsing.

`@function_tool` decorates a plain function, so there is no per-instance constructor. `obs_max_chars` is read from a module-level config (set once at Pipeline init based on `n_ctx * chars_per_token * 0.1`) via a `get_obs_max_chars()` accessor. Each tool calls `_cap_output(payload, get_obs_max_chars())` before returning. When capped, the envelope includes `"truncated": true` and a note inside `data`. Tests set the config explicitly via the same accessor to keep truncation deterministic.

## 4. Workspace scoping (framework-level)

Tool names do **not** include the word "workspace" — scoping is enforced by framework machinery (the active-workspace context var set by Pipeline at turn start, spec 00 §11.1 Workspace contract), not by naming. Tools never import `WorkspaceManager`.

- Data-inspection tools (`list_files`, `inspect_file_schema`, `preview_file`, `column_stats`) scope paths to `<workspace>/data/**`. Any path outside returns `status="error"` with `reason="path_out_of_scope"`.
- Knowledge tools (§5.1) scope to `<workspace>/memory/**` for writes; reads may target either half of the workspace.

## 5. Tool signatures

```python
@function_tool
def list_files() -> str: ...

@function_tool
def inspect_file_schema(path: str) -> str: ...

@function_tool
def preview_file(path: str, n_rows: int = 10) -> str: ...

@function_tool
def column_stats(path: str, column: str) -> str: ...

@function_tool
async def user_input(question: str) -> str: ...
```

Each tool's docstring is the prompt-visible description for Agents SDK. It must be accurate (Agents SDK injects these into the tool schema).

### 5.1 Knowledge + document tools (spec 9)

```python
# Metadata (files/*.json)
@function_tool
def get_file_metadata(path: str) -> str: ...

@function_tool
def set_file_metadata(path: str, metadata: dict) -> str: ...

# Explicit user preferences (memory/preferences.json)
@function_tool
def get_user_preferences() -> str: ...

@function_tool
def update_user_preferences(preferences: dict) -> str: ...

# Saved functions (functions/*.py + index.json)
@function_tool
def list_saved_functions() -> str: ...

@function_tool
def save_python_function(name: str, code: str, signature: str, docstring: str, overwrite: bool = False) -> str: ...

@function_tool
def run_saved_function(name: str, args: dict) -> str: ...

# Text + document ingest (data/*.md, .txt, .json, .docx, .pdf)
@function_tool
def read_text(path: str, max_bytes: int = 64_000) -> str: ...

@function_tool
def extract_document_text(path: str, max_pages: int = 50, page_range: tuple[int, int] | None = None) -> str: ...

# Distilled notes (memory/notes/*.md)
@function_tool
def write_knowledge_note(name: str, content: str, source_files: list[str] | None = None,
                         topic: str | None = None, overwrite: bool = False) -> str: ...

# Cross-cutting
@function_tool
def search(query: str, path_glob: str = "**/*", regex: bool = False, max_matches: int = 50) -> str: ...

@function_tool
def file_digest(path: str) -> str: ...

# Aggregate summary (used by doctor / explicit orientation turns; not injected into triage hot path)
@function_tool
def list_knowledge(verbosity: Literal["manifest", "detail"] = "manifest") -> str: ...

# Sub-run entry — analyst- or doctor-initiated knowledge capture (spec 11 §4.4, spec 12 §6, spec 10 §4)
@function_tool
async def call_knowledge(task: str, context: str) -> str: ...

# Doctor-exclusive destructive maintenance (spec 12, spec 9 §5.13–§5.16)
@function_tool
def delete_saved_function(name: str) -> str: ...

@function_tool
def delete_knowledge_note(path: str) -> str: ...

@function_tool
def delete_file_metadata(path: str) -> str: ...

@function_tool
def rebuild_index(kind: Literal["functions", "notes"]) -> str: ...
```

`list_knowledge` default `verbosity="manifest"` returns only names + one-line summaries + paths — no `columns`, no function bodies, no note bodies. `verbosity="detail"` opts into the richer shape (columns, signatures, docstrings) with a hard byte cap enforced by `get_obs_max_chars()` (envelope carries `"truncated": {<field>: <chars_dropped>}` per list). It is **not** part of the triage hot path in migration scope; agents escalate to detail on demand. Full contract in spec 9 §5.11.

`call_knowledge` is the Option D knowledge-as-tool pattern: analyst invokes it to delegate a semantic write (metadata, notes, teaching capture) to the knowledge agent without triage handoff. Implementation nests `Runner.run_streamed(knowledge_agent, input=task + context, ...)` inside the tool body; child events proxy to the parent's stream via the shared `on_event` channel; child span nests under the parent turn's `turn_id`/`run_id`. Returns a short confirmation string summarizing what was persisted. Probed in spec 1 §10 (nested sub-run probe); falls back to strict handoff (drops this tool) if the SDK does not support the pattern reliably.

Live in `src/core/tools/knowledge.py` (metadata, functions, notes, search, digest, aggregate, `call_knowledge`, `delete_*`, `rebuild_index`) and `src/core/tools/documents.py` (text + document ingest). Delegate to `src/core/knowledge_store.py` (spec 9 §13). Write operations scope writes to `<workspace>/memory/**` and rely on the per-volume mount + write-guard from spec 8 §5 + spec 9 §9.

**Doctor-exclusive tools** (`delete_saved_function`, `delete_knowledge_note`, `delete_file_metadata`, `rebuild_index`): enforcement via the `agent_name` context var (spec 00 §11). If the caller is not the doctor agent, the tool returns `status="error"`, `reason="not_authorized"` and emits a telemetry warning. Keeps destructive surface area out of analyst / knowledge prompts by construction, not just convention. Full semantics in spec 9 §5.13–§5.16.

## 6. `user_input` (clarification) async semantics

Current behavior: smolagents tool blocks on `queue.get()` synchronously inside a worker thread.

Target behavior under Agents SDK + async Textual UI:

1. Tool is declared `async`.
2. `user_input(question)` calls `clarification_bus.ask(question)` (in `src/core/clarification_bus.py`), which creates an `asyncio.Future`, assigns a token, and posts `{question, token}` to the UI queue.
3. Tool awaits that future.
4. UI receives the posted question, displays it, captures the user's next submission, and calls `clarification_bus.answer(token, text)` which resolves the future.
5. On workspace switch or app shutdown, the Pipeline calls `clarification_bus.cancel_all()`, which cancels every pending future; each awaiting tool re-raises `CancelledError`.
6. No timeout is enforced by the tool (matches current behavior).

## 7. `inspect_file_schema` + `column_stats` data fields

Preserve existing fields:

- `inspect_file_schema`: includes `columns_schema` with dtype per column.
- `column_stats`: includes `is_numeric` and `mean_value` for numeric columns (supports grounded synthesis).

## 8. Telemetry

- Tool span per invocation: `tool.name`, `tool.arguments`, `tool.output_chars`, `tool.truncated`, `tool.status`, `turn_id`, `run_id`.
- `user_input` emits wait-time telemetry (queued_at, answered_at) for parity with current clarification telemetry.

## 9. Testing

**Unit (temp workspace fixtures):**
- Each tool returns the envelope with all required fields.
- `obs_max_chars` truncation is deterministic given fixed input.
- Active-workspace scoping rejects paths outside the active dir.
- `inspect_file_schema` yields `columns_schema` entries.
- `column_stats` yields `is_numeric` + `mean_value` for numeric columns.
- `user_input`: posts to queue, awaits on a resolved future, returns the answer; cancellation raises `CancelledError`.

## 10. Files

**New:**
- `src/core/clarification_bus.py` — async future registry (`ask`, `answer`, `cancel_all`). Consumed by `user_input` tool (here) and by `src/cli/app.py` (spec 7).
- `tests/core/test_clarification_bus.py` — unit tests for the bus.

**Modified (full rewrite, same paths):**
- `src/core/tools/workspace_files.py` — `@function_tool` callables, active-workspace context var, `get_obs_max_chars()` accessor.
- `src/core/tools/formatting.py` — `@function_tool` callables.
- `src/core/tools/user_input.py` — async `@function_tool`, delegates to `clarification_bus`.

**New (spec 9):**
- `src/core/tools/knowledge.py` — metadata, saved-functions, notes, search, digest, aggregate.
- `src/core/tools/documents.py` — `read_text`, `extract_document_text` (Gemma multimodal backend).
- Unit tests in `tests/core/tools/test_knowledge.py` and `tests/core/tools/test_documents.py` (spec 9 §13).
- `tests/core/tools/test_workspace_files.py` — rewritten for new surface + envelope.
- `tests/core/tools/test_formatting.py` — rewritten for new surface.
- `tests/core/tools/test_user_input.py` — rewritten for async semantics + cancellation via bus.

**Retired:** smolagents `Tool` subclasses inside those same source files, if any remain.

**Tests retired:** none at file level (the three tool test files are rewritten in place).

## 11. Acceptance

- All tools registered with `@function_tool` and produce the documented envelope.
- `grep -rn "smolagents" src/core/tools` returns zero matches.
- Unit tests green.
- Telemetry spans emitted correctly.
