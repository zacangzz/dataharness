# Spec 4 — Specialist agents

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3
**Blocks:** specs 5, 6, 7, 8

## 1. Purpose

Define the five specialist agents the triage hands off to: conversational, data analyst (SandboxAgent), clarification, knowledge, doctor. Each has its own prompt, tool set, and construction semantics.

The knowledge agent is deep-dived in **spec 11**; the doctor agent is deep-dived in **spec 12**. This spec lists their construction alongside the other specialists so all five builders ship together; full entry points, behavior, and prompts live in specs 11 and 12.

## 2. Agents

### 2.1 Conversational agent

- Handles simple greetings, direct chat, non-data answers, no-data-available messaging.
- Tool set: empty.
- Model: `LlamaCppAgentsModel` with `compaction=None`.
- Streaming: yes (assistant + reasoning tokens stream live; contract defined in spec 1 §8).
- Prompt: `src/core/prompts/conversational.md` (new).

### 2.2 Data analyst agent (SandboxAgent)

- Handles workspace file/schema/column/preview/stats/analysis queries.
- Backed by `agents.sandbox.SandboxAgent` with:
  - `default_manifest` bound at turn construction (spec 6 injects the active dir; mount split defined in spec 9 §9).
  - `capabilities=Capabilities.default()` for filesystem, shell, and file-search.
  - Tool set: data inspection + document ingest + saved-function lifecycle + `get_file_metadata` (read-only) + `get_user_preferences` (explicit preferences only) + `user_input` (in-turn clarification) + `call_knowledge` (Option D delegation to knowledge agent for semantic writes). Full list in §3 below.
  - **Ownership split (Option D).** Analyst owns `save_python_function` — code authored during analysis is an analysis artifact. Analyst does **not** call `set_file_metadata` or `write_knowledge_note` directly; semantic writes route through `call_knowledge(task, context)` which nests a `Runner.run_streamed(knowledge_agent, ...)` sub-run. Keeps prompt ownership, telemetry, and test surface clean. Rationale: code persistence is deterministic; semantic curation needs reasoning about naming, merging, overwrites — that's knowledge agent's job.
  - **Lazy retrieval by default.** Analyst does not depend on a preloaded manifest block on entry. It begins from the user ask plus on-demand tool lookups, which keeps triage fast and tolerates single-run handoff semantics.
- Model: `LlamaCppAgentsModel` with `compaction=<shared>`.
- Sandbox client: `UnixLocalSandboxClient` (injected per turn by Pipeline).
- Streaming: yes (assistant + reasoning tokens + tool_call start/complete + tool_output all stream live — contract defined in spec 1 §8).
- Prompt: `src/core/prompts/analyst.md`. This spec declares the filename only — **full prompt content, decision tree, retrieval pattern, output conventions, error recovery, and feedback-loop semantics live in spec 10** (analyst deep-dive).

### 2.3 Clarification agent

- Handles explicit clarification requests.
- Tool set: `[user_input]`.
- Model: `LlamaCppAgentsModel` with `compaction=None`.
- Streaming: yes (assistant + reasoning tokens + tool_call start/complete + tool_output all stream live — contract defined in spec 1 §8).
- Prompt: `src/core/prompts/clarification.md` (new).

### 2.4 Knowledge agent

- Owns every write into the persistent knowledge bank, including explicit user preference memory. Four entry points (spec 11 §4):
  1. **New file intake** — conversational column/metric/unit capture on fresh drops.
  2. **Mid-conversation capture** — user teaches a formula / column meaning / business rule during any turn; triage routes to knowledge for capture.
  3. **Gap resolution** — reads `memory/notes/gaps/*.md` at turn start and addresses prior analyst gap signals.
  4. **Sub-run via `call_knowledge`** — analyst or doctor delegates a semantic write without a triage handoff (spec 9 §5.12, spec 11 §4.4).
- Tool set: `[list_files, inspect_file_schema, preview_file, read_text, extract_document_text, search, file_digest, get_file_metadata, set_file_metadata, get_user_preferences, update_user_preferences, write_knowledge_note, save_python_function, list_saved_functions, user_input]`. No `call_knowledge` (recursion guard — spec 9 §5.12).
- Model: `LlamaCppAgentsModel` with `compaction=None` (knowledge turns are short; each capture is a single focused exchange).
- Streaming: yes (contract per spec 1 §8).
- Prompt: `src/core/prompts/knowledge.md` (new — full content in spec 11 §7).
- Persists to `<workspace>/memory/files/<path>.json` (metadata), `<workspace>/memory/functions/<name>.py` + `index.json` (reusable functions), and `<workspace>/memory/notes/<topic>.md` + `notes/index.json` (distilled notes + search index) before handing back.

### 2.5 Doctor agent

- Maintains `memory/` integrity — dedup, orphan cleanup, index rebuild, schema-drift resolution. Never answers analytical questions; never writes to `data/`; never sits on the first-answer hot path. Entry points (spec 12 §4):
  1. **Drift triage** — triage routes on user confirmation or explicit "clean up" intent.
  2. **Explicit user ask** — phrases like "clean up memory", "dedupe functions", "rebuild the index".
  3. **Background sweep (passive)** — Pipeline surfaces outstanding drift via `StatusUpdate`; no auto-invoke.
- Tool set (spec 12 §3):
  - Read: `list_files`, `inspect_file_schema`, `preview_file`, `read_text`, `search`, `file_digest`, `get_file_metadata`, `list_saved_functions`, `list_knowledge`.
  - Write (structural): `set_file_metadata` (timestamps + digest only), `write_knowledge_note` (via delegation normally), `save_python_function` (overwrite=True for merges).
  - Doctor-exclusive destructive: `delete_saved_function`, `delete_knowledge_note`, `delete_file_metadata`, `rebuild_index`. Caller-auth enforced by tool (spec 3 §5.3).
  - Collaboration: `call_knowledge` (delegate semantic writes — column meanings, metric definitions, merged note bodies).
  - Clarification: `user_input` (batched confirmations for bulk deletes).
- Model: `LlamaCppAgentsModel` with `compaction=<shared>` — doctor sweeps can span many files; budget `max_turns=12` per spec 12 §3.
- Streaming: yes (contract per spec 1 §8).
- Prompt: `src/core/prompts/doctor.md` (new — full content in spec 12 §8).
- **Scan-first, never-assume rule.** Every doctor turn begins with `list_knowledge(verbosity="detail")`. On ambiguous state (missing index, conflicting intake status, unclear orphan), doctor consults knowledge via `call_knowledge` before acting. No silent deletes. No guessed semantics.

## 3. Agent construction

Each agent is constructed once at Pipeline init (matching the current pattern: reusable `Agent` instance, per-turn bindings applied at `Runner.run`). Workspace mount and sandbox client are resolved per-turn via `RunConfig`, not baked into the agent.

```python
conversational_agent = Agent(
    name="conversational",
    instructions=_load_prompt("conversational.md"),
    model=custom_model_direct,
    tools=[],
)

data_analyst_agent = SandboxAgent(
    name="data_analyst",
    instructions=_load_prompt("analyst.md"),
    model=custom_model_agent,
    default_manifest=None,   # set per turn via run_config
    capabilities=Capabilities.default(),
    tools=[
        # data inspection
        list_files, inspect_file_schema,
        preview_file, column_stats,
        # knowledge read-only (lookups, metadata inspection)
        get_file_metadata,
        get_user_preferences,
        # saved-function lifecycle (analyst owns — code is an analysis artifact)
        list_saved_functions, save_python_function, run_saved_function,
        # document + text ingest
        read_text, extract_document_text,
        # cross-cutting
        search, file_digest,
        # aggregate (also Pipeline-invoked; kept on the agent for deeper reads via verbosity="detail")
        list_knowledge,
        # clarification + knowledge delegation (Option D, spec 3 §5.1, spec 10 §4)
        user_input, call_knowledge,
    ],
)

clarification_agent = Agent(
    name="clarification",
    instructions=_load_prompt("clarification.md"),
    model=custom_model_direct,
    tools=[user_input],
)

knowledge_agent = Agent(
    name="knowledge",
    instructions=_load_prompt("knowledge.md"),
    model=custom_model_direct,
    tools=[
        list_files, inspect_file_schema,
        preview_file,
        read_text, extract_document_text,
        search, file_digest,
        get_file_metadata, set_file_metadata,
        get_user_preferences, update_user_preferences,
        write_knowledge_note,
        save_python_function, list_saved_functions,
        user_input,
    ],
)

doctor_agent = Agent(
    name="doctor",
    instructions=_load_prompt("doctor.md"),
    model=custom_model_agent,
    tools=[
        # read
        list_files, inspect_file_schema, preview_file,
        read_text, search, file_digest,
        get_file_metadata, list_saved_functions,
        list_knowledge,
        # write (structural)
        set_file_metadata, write_knowledge_note,
        save_python_function,                    # overwrite=True for merges
        # doctor-exclusive destructive (spec 3 §5.3 caller-auth enforced by tool)
        delete_saved_function, delete_knowledge_note,
        delete_file_metadata, rebuild_index,
        # collaboration with knowledge agent
        call_knowledge,
        # batched deletion confirmations
        user_input,
    ],
)
```

## 4. Prompts

**New files:** `src/core/prompts/triage.md`, `src/core/prompts/conversational.md`, `src/core/prompts/analyst.md`, `src/core/prompts/clarification.md`, `src/core/prompts/knowledge.md`, `src/core/prompts/doctor.md`.

**Retire:** `src/core/prompts/hr.md`.

Each prompt is short, behavior-focused, and follows the current style (no hardcoded example data, no framework internals). Prompt content is drafted as part of this spec's implementation task and reviewed alongside code.

Key constraints per prompt:

- **conversational.md:** Answer directly; never claim to have accessed files; if user asks about data and no dataset is loaded, say so plainly; no `final_answer()` literal text.
- **analyst.md:** Full content + decision tree owned by spec 10. This spec declares only that the prompt exists at `src/core/prompts/analyst.md`.
- **clarification.md:** Ask exactly one question via `user_input`; integrate the answer and hand control back.
- **knowledge.md:** Four entry points (new-file intake, mid-convo capture, gap resolution, sub-run via `call_knowledge` — see spec 11 §4). Persist via `set_file_metadata` / `save_python_function` / `write_knowledge_note` before returning; never answer analytical questions (hand back if user veers). Full content in spec 11 §7.
- **doctor.md:** Scan-first rule (start every turn with `list_knowledge(verbosity="detail")`). Never assume state — consult knowledge via `call_knowledge` on ambiguous indexes. Batched `user_input` confirmation before every destructive op. End every turn with a summary of actions taken. Full content in spec 12 §8.
- **triage.md:** Decide whether the query is conversational, analyst-worthy (needs data), clarification-needed, knowledge-needed (new files / definitional content / open gaps), or doctor-needed (user explicitly asks to clean up memory); hand off, don't try to answer directly.

## 5. Sandbox mount binding (per turn)

Pipeline resolves at turn start:
```python
manifest = Manifest(entries={"workspace": LocalDir(src=workspace_manager.active_dir)})
sandbox_client = UnixLocalSandboxClient()  # ephemeral
run_config = RunConfig(sandbox=SandboxRunConfig(client=sandbox_client, manifest=manifest))
```
Passed as `Runner.run(..., run_config=run_config)`.

## 6. Telemetry

Each agent produces an `agent` span (via SDK tracing). Custom processor attaches `turn_id` and `run_id`.

Attributes:
- `agent.name`
- `agent.handoff_from` (for specialists)
- `agent.tools_available`
- For SandboxAgent: `agent.sandbox_client="unix_local"`, `agent.workspace_mount=<active_dir>`

## 7. Testing

**Unit:**
- Each agent loads its prompt from disk.
- SandboxAgent given correct tool list and capabilities.
- Conversational and clarification agents use direct model variant (no memory manager).
- Data analyst agent uses memory-managed model variant.

**Integration (with real LLM, small GGUF, fixture workspace):**
- Conversational: "hello" → greeting response, no tool calls.
- Data analyst: "list my files" → calls `list_files` tool → returns file names.
- Data analyst: novel question ("what's the avg of column X in file Y") → uses tools or shells to python inside sandbox, produces numeric answer grounded in the CSV.
- Clarification: "what did you mean?" → triggers `user_input`, receives answer from mocked queue, answers.

## 8. Files

**New:**
- `src/core/agents/conversational.py`
- `src/core/agents/data_analyst.py`
- `src/core/agents/clarification.py`
- `src/core/agents/knowledge.py` (spec 11)
- `src/core/agents/doctor.py` (spec 12)
- `src/core/prompts/conversational.md`
- `src/core/prompts/analyst.md` — filename only; content authored in spec 10 §8
- `src/core/prompts/clarification.md`
- `src/core/prompts/triage.md` (used by spec 5 but filed here since all prompts land together)
- `src/core/prompts/knowledge.md` (spec 11)
- `src/core/prompts/doctor.md` (spec 12)
- `tests/core/agents/test_specialists.py`

**Modified:**
- `hragent.spec` — prompt globs (tracked by spec 8).

**Retired:**
- `src/core/agents/hr.py`
- `src/core/prompts/hr.md`

**Tests retired:**
- `tests/core/agents/test_hr.py` — covered the retired smolagents `CodeAgent` builder.

## 9. Acceptance

- Each of the five agents (conversational, data_analyst, clarification, knowledge, doctor) constructs with correct prompt, model variant, and tool set.
- SandboxAgent receives workspace mount per turn.
- Doctor's tool set includes the four destructive tools; caller-auth guard enforced by tool implementation (spec 3 §5.3).
- Integration smoke tests pass on a local fixture workspace.
- Prompts reviewed and committed alongside code.
