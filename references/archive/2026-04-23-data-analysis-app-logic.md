# Data Analysis Agentic App Logic — Comprehensive Specification

**Date:** 2026-04-23
**Status:** Superseded by `2026-04-23-custom-data-analysis-llm-v1-main-spec.md`

**Canonical spec:** `2026-04-23-custom-data-analysis-llm-v1-main-spec.md`

This document provides a detailed technical specification of the LLM-powered Data Analysis App, capturing all logic, contracts, and system behaviors described across the project's foundational specifications.

---

## 1. System Architecture & Topology

Uses a **Triage + Specialist** model powered by the **OpenAI Agents SDK** and a local **llama_cpp** engine (Gemma GGUF: `gemma-4-E4B-it-Q4_K_M`).

### 1.1 The Six Agents

1. **Triage Agent:** Routing engine. No tools — only SDK handoffs. Uses the direct model (no compaction). Emits a short status-ack line (≤ 12 words) before each handoff to reduce perceived latency. Commits to exactly one handoff per turn.
2. **Conversational Agent:** Handles general interaction. No tools. Uses the direct model.
3. **Data Analyst Agent:** A `SandboxAgent` with shell and filesystem capabilities. Follows a branching decision tree for data queries. Uses the compacted model.
4. **Knowledge Agent:** Semantic authority. Owns all writes to file metadata, reusable functions, and distilled notes. Uses the direct model (no compaction — capture turns are short).
5. **Doctor Agent:** Structural maintenance specialist. Resolves drift, orphans, index corruption. Uses the compacted model (sweeps may span many files). Follows a scan-first, never-assume protocol.
6. **Clarification Agent:** Dedicated to resolving turn-level ambiguity when triage cannot commit to a specialist route.

Two model variants are constructed:
- **Direct model** (`compaction=None`): triage, conversational, knowledge, clarification.
- **Agent model** (with shared `Compaction` instance): analyst, doctor.

All routing is performed by the triage agent via SDK handoffs. No Python-side route heuristic exists.

---

## 2. Workspace & File System Logic

Workspaces enforce a strict **Two-Volume Mount** policy within a sandbox.

### 2.1 Directory Layout

```
<workspace>/
├── data/                           # User writes; RO to agents
└── memory/                         # Agent writes; user may inspect
    ├── session.db                  # SQLite SDK conversation state
    ├── preferences.json            # Explicit user-stated preferences only
    ├── files/<path>.json           # Semantic metadata per data file
    ├── functions/
    │   ├── index.json              # Signatures, docstrings, freshness metadata
    │   └── <fn_name>.py           # Reusable Python functions (one run(**kwargs) each)
    └── notes/
        ├── index.json              # Search-guidance index: summary + keywords per note
        ├── <topic>.md              # Agent-distilled knowledge notes
        └── gaps/
            └── <topic>.md         # Analyst → knowledge deferred signals
```

The workspace is an app-level concept — agents operate inside it but do not own it. Workspace scaffolding, filedrop routing, and active-directory propagation are managed by dedicated workspace code, not agents.

Writing rules are absolute:
- **User** writes only to `data/` (via filedrop or OS file manager).
- **Agents** write only to `memory/` (enforced at sandbox mount layer).

### 2.2 File Metadata Schema (`files/<path>.json`)

Key fields: `path`, `source_digest` (sha256), `summary`, `intake_status`, `columns[]` (name, dtype, meaning, unit, notes), `metrics[]` (name, definition), `notes_refs[]`.

**`intake_status` values** (drives `drift_detected` triage signal):

| Value | Meaning | Set by |
|---|---|---|
| `complete` | Full intake done; columns/metrics captured | Knowledge agent |
| `minimal` | User said "skip"; only path + digest stored | Knowledge agent |
| `stale` | `source_digest` no longer matches file on disk | Lazy detection in read-path tools |
| `orphan` | `path` no longer exists in `data/` | Detected at `list_knowledge` assembly |

All writes are atomic (`.tmp` → rename).

### 2.3 Notes Index (`notes/index.json`)

Per-entry: path, topic, title (≤ 120 chars), summary (≤ 200 chars), keywords (≤ 10, each ≤ 32 chars). Lets agents decide relevance without loading note bodies. `write_knowledge_note` atomically updates both the `.md` file and `index.json` as a paired write.

### 2.4 Saved Functions Index (`functions/index.json`)

Per-entry: name, file, signature, docstring, source_files, source_digests, schema_fingerprint, created_by, validation_status (`valid` | `stale` | `schema_mismatch`).

### 2.5 Sandbox Security

- **UnixLocalSandboxClient** executes Python/Shell commands.
- **Write Guard:** Enforced at mount layer. Agents can only write under `/workspace/memory/**`.
- **Timeouts:** Shell commands capped at 60s; total turn wall-clock at 300s.
- **Session file:** `<workspace>/memory/session.db`. Created on first turn; persists across turns in the same workspace; dropped on workspace switch.

---

## 3. LLM Infrastructure (The "Custom Model")

Every agent uses `LlamaCppAgentsModel`, a custom `Model` subclass bridging the Agents SDK to the `llama_cpp` engine.

### 3.1 Compaction (Summarization)

Analyst- and doctor-route calls share a `Compaction` instance. Triage, conversational, knowledge, and clarification use `compaction=None`.

- **Trigger:** Input tokens cross ~70% of `n_ctx`. Oldest messages summarized; summary replaces them.
- **Summary cache:** Keyed by `(prefix_hash, tail_len)`. Avoids re-summarization when `Runner` replays a long `SQLiteSession` across many turns. Cache is per-Pipeline-instance; dropped on workspace switch.
- **Atomic pairs:** Compaction never splits a `tool_call` message from its matching `tool_output`. Walks back to the nearest clean `user`/`assistant` boundary before cutting.

### 3.2 Thinking Mode

Gemma thinking tokens captured via `<|channel>thought...<channel|>` regex. Routed to the process log as `ReasoningSummary` events; never surfaced raw in the conversation pane.

### 3.3 Streaming Events (emitted live, no batching)

- Assistant text tokens: one delta event per token, rendered live.
- Reasoning deltas: tagged `output_type="reasoning"` — converted to `ReasoningSummary` by Pipeline.
- Tool-call start: emitted the moment the tool name is decoded, before args are complete.
- Tool-call complete: emitted when the full args JSON validates.
- Finish event: terminal event with `usage` and `finish_reason` (`stop` | `tool_calls` | `length`).

### 3.4 Tool-Call Protocol

Model output parsed for `<tool_call>JSON</tool_call>`. Malformed JSON triggers exactly **one** retry with a "Fix JSON" prompt. On second failure → `ModelBehaviorError`.

### 3.5 Multimodal Document Extraction

Gemma directly handles `.pdf` and `.docx` text extraction via the already-loaded GGUF model. Long documents are processed in phases (default 10 pages/phase); `page_range` arg lets the caller target specific ranges. No separate extraction libraries.

---

## 4. Pipeline & Event Orchestration

The `Pipeline` owns the turn lifecycle and is the single source of truth for UI state.

### 4.1 Per-Turn Lifecycle

1. Compute tiny triage signals (non-LLM helpers).
2. Retrieve or create `SQLiteSession` at `<workspace>/memory/session.db`.
3. Build two-volume sandbox manifest: `data/` (RO) + `memory/` (RW).
4. Instantiate `UnixLocalSandboxClient`.
5. Prepend only the tiny signal block to the triage input. No knowledge manifest, note summaries, saved-function listings, or preferences are injected at triage time.
6. Call `Runner.run_streamed(triage_agent, ...)` with session and sandbox.
7. Forward each `RunItem` as a `PipelineEvent` via `on_event` callback.
8. Emit `StatusUpdate` events at each lifecycle transition.
9. Assemble `PipelineResult` (final text, token counts, wall time, agent trail).

On completion: emit `AgentFinished` + `StatusUpdate("Ready", level="idle")`.
On exception: emit `AgentFinished(outcome="error")` + `PipelineEvent.Error` + `StatusUpdate("Error …", level="error")`.
On `CancelledError`: emit `AgentFinished(outcome="cancelled")` + `StatusUpdate("Cancelled", level="idle")`.
In all cases: close sandbox client in `finally`.

### 4.2 Pre-Triage Routing Signals

Injected as a compact system prefix:
```
[context] workspace "<name>" has_data=<bool> new_files_present=<bool> gaps_open_present=<bool> drift_present=<bool>
```
`has_data`: any usable files in `data/`. `new_files_present`: files in `data/` with no matching `memory/files/` entry. `gaps_open_present`: any files in `memory/notes/gaps/`. `drift_present`: any of stale/minimal/orphan/missing-index conditions.

Only booleans reach triage. Counts, paths, manifests, and preferences are never passed through.

### 4.3 Activity Vocabulary (PipelineEvent)

Tagged union:

| Event | Description |
|---|---|
| `AgentStarted(agent)` | Agent begins handling turn |
| `AgentFinished(agent, outcome)` | `completed` \| `handoff` \| `cancelled` \| `error` |
| `TokenDelta(text, output_type)` | Streamed assistant token; `"message"` or `"reasoning"` |
| `FinalMessage(text)` | Turn complete; final assistant text |
| `ReasoningSummary(text, agent)` | Coalesced thought tokens, user-visible summary only |
| `ToolCallStart(id, name)` | Tool invocation started (before args complete) |
| `ToolCallComplete(id, name, args)` | Tool args fully decoded |
| `ToolOutput(id, output)` | Tool return value |
| `Handoff(from, to)` | Triage hands off to specialist |
| `StatusUpdate(text, level, agent)` | Status bar update; levels: `idle` \| `working` \| `tool` \| `handoff` \| `warn` \| `error` |
| `Error(kind, message)` | Turn-level error |

### 4.4 Error Handling

| Exception | Event emitted | User sees |
|---|---|---|
| `AgentsException` (max turns, tool failure) | `Error{kind="agent_exception"}` | "Agent error: …" |
| `ModelBehaviorError` (bad tool JSON after retry) | `Error{kind="model_behavior"}` | "Model output error" |
| `ContextLengthExceeded` | `Error{kind="context_exceeded"}` | "Context exceeded, clear chat to continue" |
| `SandboxInitError` | `Error{kind="sandbox_unavailable"}` | "Sandbox unavailable, analyst disabled this turn" |
| `CancelledError` (workspace switch) | `AgentFinished{outcome="cancelled"}` + `StatusUpdate("Cancelled")` | New workspace UI; no error rendered |
| `TimeoutError` | `Error{kind="timeout"}` | "Operation timed out" |

No fallback agents. Errors surface directly.

### 4.5 Turn Budgets

- Max turns: 8 (default `RunConfig`); doctor gets 12.
- Turn wall-clock: 300s (`asyncio.wait_for`).
- Sandbox shell: 60s per command.

---

## 5. Specialized Agent Logic & Feedback Loops

### 5.1 Triage Routing Rules

| Signal + context | Route |
|---|---|
| `has_data=false` + data question | Conversational (explain dataset needed) |
| `new_files_present=true` + onboarding / teaching intent | Knowledge |
| `new_files_present=true` + immediate analytical question | Analyst (intake not a gateway) |
| Definitional content (user teaches formula/rule/meaning) | Knowledge |
| `gaps_open_present=true` + user turn matches open gap topic | Knowledge (gap resolution) |
| `drift_present=true` + explicit maintenance intent | Doctor |
| `drift_present=true` + analytical question | Analyst (drift never hijacks routing) |
| Ambiguous intent | Clarification |
| Otherwise | Conversational or analyst per session context |

### 5.2 The Analyst Decision Tree

Evaluated top-down on every data question:

**Branch 0 — Structural answer available right now?**
→ `inspect_file_schema` / `preview_file` / `column_stats` directly. First-answer analysis on a newly added file is allowed without prior intake.

**Branch 1 — Saved function helps?**
- **1a. Exact match** (name/docstring + args align) → `run_saved_function(name, args)`.
- **1b. Close match** (similar intent, different args) → `read_text` function source → `run_saved_function` with adapted args.
- **1c. Code-variant match** (reusable logic, different output shape) → `read_text` source → `call_knowledge` to save the variant → run new function. (For mechanical one-line tweaks, analyst saves the variant directly via `save_python_function`.)
- If preflight returns `stale_saved_function` or `schema_mismatch`: do not execute. Fall to branch 2 or 3.

**Branch 2 — Deterministic tool covers it?**
(`list_files`, `inspect_file_schema`, `preview_file`, `column_stats`, `search`) → call → answer.

**Branch 3 — Ad-hoc shell analysis needed?**
→ Shell Python. If result is likely reusable → `save_python_function` before returning (analyst owns this — it just ran the code).

**Branch 3a — Intent ambiguous (not a knowledge gap)?**
→ `user_input("<one focused question>")` — awaits reply inside this turn → resume from branch 0.

**Branch 3b — User taught something semantic mid-turn?**
→ `call_knowledge(task, context)` sub-run → continue with updated `memory/`.

**Branch 4 — Knowledge prerequisite missing AND unresolvable this turn?**
→ Write gap note to `memory/notes/gaps/<topic>.md` → return partial answer labeled "awaiting clarification on \<topic\>".

Invariant: analyst never calls doctor inline during a normal analysis turn.

### 5.3 Analyst On-Demand Retrieval

No Pipeline-injected manifest. Analyst pulls lazily:

| Need | Tool |
|---|---|
| Columns / units / metric definitions for a file | `get_file_metadata(path)` |
| Explicit user presentation / unit preferences | `get_user_preferences()` |
| Function source (for adapt or variant) | `read_text("memory/functions/<name>.py")` |
| Note body | `read_text("memory/notes/<topic>.md")` |
| Structural schema when no metadata exists | `inspect_file_schema(path)` |
| Prior saved functions with docstrings | `list_saved_functions()` |

### 5.4 Analyst Output Conventions

- Direct answer first (one sentence or a small markdown table).
- Grounded numbers only — every numeric claim must come from a tool or function call.
- End with `Sources:` listing every `data/` file read and any saved function called.
- Max 10 rows per table; flag truncation when larger.
- No filler openings, no apologies, no emojis.
- One retry with a different path on tool errors; then surface.

### 5.5 Knowledge Agent Entry Points

Four triggers — three via triage handoff, one via sub-run:

1. **New-file intake** (`new_files_present`): `inspect_file_schema`/`extract_document_text`/`read_text` → ask one focused question at a time via `user_input` → `set_file_metadata`/`write_knowledge_note`/`save_python_function`.
2. **Mid-conversation capture** (`definitional_content`): acknowledge → persist → return. Mapping: formula → `save_python_function`; column meaning/unit → `set_file_metadata`; business rule → `write_knowledge_note`; column-value mapping → `set_file_metadata` under `columns[].notes`; user preference → `update_user_preferences`.
3. **Gap resolution** (`gaps_open_present` + matching topic): read gap file → ask user → persist via matching tool → delete gap file.
4. **Sub-run via `call_knowledge`**: no `user_input` allowed; persist and return a short confirmation. Child budget: `max_turns=3`.

On every knowledge turn: scan `memory/notes/gaps/` and resolve any latent gap sharing context with the current task.

**Skip path:** User says "skip" → write minimal `files/<name>.json` with `intake_status="minimal"`. **Resume:** re-enter intake on existing minimal JSON. If triggered via doctor drift signal, entry is via sub-run rather than triage handoff.

**Boundary:** If user veers into analysis during a handoff turn, knowledge hands back to triage via final answer with "ready for analysis." Sub-run invocations cannot trigger a handoff.

### 5.6 Doctor Agent Behavior

**Entry points:**

- **Drift-triggered handoff:** Only on user acknowledgment of a drift `StatusUpdate` or explicit maintenance intent ("clean up", "tidy up", "dedupe", "fix memory", "yes doctor"). Drift alone never triggers handoff — analytical questions continue to route to analyst even when drift exists.
- **Explicit user ask:** Phrases explicitly requesting maintenance.
- **Background sweep:** After N turns (configurable; default 20) or workspace open, Pipeline emits `StatusUpdate(warn)` noting drift count. No auto-invoke; user remains in control.

**Scan-first rule:** Every doctor turn begins with `list_knowledge(verbosity="detail")`. Enumerate drift by class. Summarize backlog to user before acting.

**Never-assume rule:** If `functions/index.json` or `notes/index.json` is missing or corrupted, do not assume intake hasn't begun. Always `call_knowledge("status", …)` first. Rebuild only after knowledge confirms the store is in a stable terminal state.

**Resolution matrix:**

| Drift class | Doctor action | Knowledge delegation |
|---|---|---|
| Stale, schema unchanged | Restamp `source_digest` + `intake_status="complete"` | — |
| Stale, schema changed | — | `call_knowledge("re-intake <file>", "<schema diff>")` |
| Minimal intake | — | `call_knowledge("resume intake for <file>", ...)` |
| Orphan metadata | Batched `user_input` → on y → `delete_file_metadata` | — |
| Orphan note | Batched `user_input` → on y → `delete_knowledge_note` | — |
| Orphan function | Batched `user_input` → on "rewrite" → delegate; on "delete" → `delete_saved_function` | `call_knowledge("rewrite <fn> against current schema", ...)` |
| Stale/schema_mismatch function | Batched proposal → on "rewrite" → delegate; on "delete" → `delete_saved_function` | `call_knowledge("refresh <fn>", ...)` |
| Duplicate functions | Keep higher `last_used_at`; `delete_saved_function` on loser; near-identical overlap → batched `user_input` | — |
| Notes consolidation | Batched `user_input` proposes merge → on y → knowledge writes merged note; delete originals | `call_knowledge("write merged note ...", ...)` |
| Index missing/corrupt | Only after never-assume check → `rebuild_index(kind)` | — |

Every destructive operation preceded by `user_input` (batched where possible). Final message summarizes all actions taken, deferred, or skipped.

### 5.7 The Gap Feedback Loop

1. Analyst writes `memory/notes/gaps/<topic>.md` (branch 4 of decision tree).
2. Next Pipeline pre-triage pass flags `gaps_open_present=true`.
3. Triage routes to knowledge only when the user's next message topic-matches the open gap.
4. Knowledge reads the gap file, asks the user, persists via matching tool, deletes the gap file.

### 5.8 The Drift Feedback Loop

1. Read-path tools detect changed file hash — stamp `intake_status="stale"` atomically on the metadata file + emit `knowledge.stale_detected` telemetry. Tool call still returns its result.
2. Next Pipeline pre-triage pass flags `drift_present=true`.
3. Background sweep `StatusUpdate` prompts the user ("memory/ has N drift items — say `clean up` to address").
4. On user explicit intent → triage routes to doctor → doctor resolves.

### 5.9 Sub-Run Pattern (`call_knowledge`)

Analyst or doctor invokes `call_knowledge(task, context)` as a tool. This nests `Runner.run_streamed(knowledge_agent, ...)` inside the parent turn:
- Child inherits parent's sandbox manifest and `run_config`.
- Child session is ephemeral (no cross-contamination with parent session).
- Child events proxy to the parent UI stream.
- Child budget: `max_turns=3`.
- Recursion blocked: `sub_run_depth` context var enforced at max depth 1.
- Caller allow-list: `data_analyst` + `doctor` only. Other callers → `status="error"`, `reason="not_authorized"`.
- Returns a short confirmation string (knowledge agent's final text becomes the tool's return value).

---

## 6. Tool Contracts & Responses

All `@function_tool` callables return a standardized JSON envelope:
```json
{
  "status": "ok" | "error",
  "tool": "<name>",
  "schema_version": 1,
  "data": { ... },
  "truncated": { "<field>": <chars_dropped> }
}
```
`obs_max_chars` cap = `n_ctx × chars_per_token × 0.1`. Applied via `_cap_output()` before every return.

### 6.1 Data Inspection Tools (scope: `data/`)

- **`list_files()`** — Lists all files in `data/`.
- **`inspect_file_schema(path)`** — Returns `columns_schema` (dtypes) + shape.
- **`preview_file(path, n_rows=10)`** — First N rows of a tabular file.
- **`column_stats(path, column)`** — `is_numeric`, `mean_value` (numeric); top values (categorical).

### 6.2 Knowledge Store Tools

- **`get_file_metadata(path)`** — Reads `memory/files/<path>.json`. Returns `{status: "missing"}` if absent.
- **`set_file_metadata(path, metadata)`** — Schema-validated merge + atomic write. Knowledge agent only.
- **`get_user_preferences()`** — Reads `memory/preferences.json`. Returns `{}` on absence.
- **`update_user_preferences(preferences)`** — Merges explicit user-stated preferences atomically. Knowledge agent only.
- **`list_saved_functions()`** — Returns parsed `functions/index.json`.
- **`save_python_function(name, code, signature, docstring, overwrite=False)`** — Validates name regex (`^[a-z][a-z0-9_]{0,62}$`), `ast.parse`, `run(...)` top-level signature. Atomic write. Both knowledge and analyst can call.
- **`run_saved_function(name, args)`** — Freshness preflight first: if `source_digest` or `schema_fingerprint` mismatch → `status="error"`, `reason="stale_saved_function"` or `"schema_mismatch"` (no execution). Subprocess inside sandbox; 60s timeout; captures stderr on non-zero exit.
- **`read_text(path, max_bytes=64_000)`** — `.md`, `.txt`, `.json` from anywhere in the workspace. Hard byte cap. Binary/unknown extensions → `status="error"`, `reason="unsupported_file_type"`.
- **`extract_document_text(path, max_pages=50, page_range=None)`** — Gemma multimodal for `.pdf` and `.docx`. Phased reading (default 10 pages/phase). Returns `pages[]`, `total_pages`, `phase.remaining` hint for caller to loop.
- **`write_knowledge_note(name, content, source_files, topic, summary, keywords, overwrite=False)`** — Atomic dual write: `.md` + `notes/index.json`. `summary` (≤ 200 chars) and `keywords` (≤ 10) required; absent → `status="error"`, `reason="missing_index_fields"`. Gap notes (`gaps/` prefix) exempt from index write.
- **`search(query, path_glob="**/*", regex=False, max_matches=50)`** — Literal or regex search across `data/` + `memory/`. Returns `{path, line, snippet}` list.
- **`file_digest(path)`** — Returns sha256 + size + mtime.
- **`list_knowledge(verbosity="manifest"|"detail")`** — Aggregate workspace view. **Manifest** (default): names + one-liners + `drift` block; no column arrays, no note bodies. **Detail**: columns, signatures, docstrings. Not on triage hot path; agents call on demand. Budget-capped; truncation reported per list.
- **`call_knowledge(task, context)`** — Async sub-run entry. See §5.9.

### 6.3 Doctor-Exclusive Destructive Tools

Caller-auth enforced via `agent_name` context var. Non-doctor callers → `status="error"`, `reason="not_authorized"`.

- **`delete_saved_function(name)`** — Removes `.py` + index entry atomically.
- **`delete_knowledge_note(path)`** — Removes `.md` + index entry + cleans `notes_refs` backlinks atomically.
- **`delete_file_metadata(path)`** — Removes `files/<path>.json`. Never touches `data/`.
- **`rebuild_index(kind)`** — Regenerates `functions/index.json` or `notes/index.json` from filesystem. Atomic write. Reports entries restored/skipped.

### 6.4 Clarification Tool

- **`user_input(question)`** — Async. Posts question to `ClarificationBus`; awaits `asyncio.Future`. UI renders question, captures submission, resolves future. Cancelled on workspace switch or shutdown (`ClarificationBus.cancel_all()`). No timeout enforced by the tool.

### 6.5 Write Ownership

| Memory area | Primary owner | Delegation |
|---|---|---|
| `files/*.json` semantic fields | Knowledge only | Analyst/doctor delegate via `call_knowledge` |
| `files/*.json` structural stamps (stale, digest) | Tool read-paths (automatic) + doctor | — |
| `preferences.json` | Knowledge only | Other agents route via `call_knowledge` |
| `functions/*.py` (new + updates) | Analyst (primary) + knowledge | Both call `save_python_function` directly |
| `functions/*.py` (deletions + index rebuild) | Doctor only | — |
| `notes/*.md` + `notes/index.json` (new + updates) | Knowledge only | Analyst/doctor delegate via `call_knowledge` |
| `notes/*.md` + `notes/index.json` (deletions + rebuild) | Doctor only | — |
| `notes/gaps/*.md` (write) | Analyst only | — |
| `notes/gaps/*.md` (delete on resolve) | Knowledge only | — |

---

## 7. Terminal UI & UX (Textual)

### 7.1 Async Architecture

UI runs on the Textual event loop (`@work` coroutines). Workspace switches cancel in-flight tasks via `task.cancel()` → `CancelledError` propagation → Pipeline cleanup. No background thread blocks.

### 7.2 Process Log

One collapsible block per `(turn, agent)`. Blocks created from `AgentStarted` events, not transcript heuristics.
- Default: collapsed (`+` title prefix). Expanded: `-` title prefix.
- Entries stream in append order; pending tool-call row updated in-place on `ToolCallComplete`.
- Old single-agent post-hoc "Agent Steps" dump is replaced by this streaming surface.

| Event | Process log action |
|---|---|
| `AgentStarted(agent)` | Create agent's collapsible block for the turn |
| `ReasoningSummary(text, agent)` | Append `thinking:` line inside that agent's block |
| `ToolCallStart(id, name)` | Append `→ tool_name(…)` with pending marker |
| `ToolCallComplete(id, name, args)` | Update pending entry in-place: `→ tool_name(args)` |
| `ToolOutput(id, output)` | Append `← <truncated output>` below tool entry |
| `Handoff(from, to)` | Append `↦ handoff to=<to>` inside source agent block |
| `AgentFinished(agent, outcome)` | Append final status row inside that agent block |
| `StatusUpdate(text, level, agent)` | Append lifecycle row inside the current agent block (when `agent` is present) |

### 7.3 Conversation Pane

`TokenDelta(output_type="message")` → appended to the streaming assistant-message widget. Raw reasoning deltas are never rendered directly.

### 7.4 Status Bar

Pipeline-driven: UI mirrors `StatusUpdate` events. Color-coded by `level` (idle=dim, working=default, tool=accent, handoff=accent, warn=yellow, error=red). Single-line — replaced on each update, not appended.

Lifecycle progression: `Thinking…` → `Handed off to <specialist>` → `Calling <tool>…` → `Reading tool output` → `Streaming answer` → `Ready`.

### 7.5 Filedrop

Dropped files are copied to active workspace `data/`. After copy, a synthetic user input fires: `"I just added <filename>.<ext>"`. If a turn is in flight, queued and fired on completion.

### 7.6 Clarification Flow

`user_input` tool posts question to `ClarificationBus` → UI renders question and re-enables input → user submits → UI calls `bus.answer(token, text)` → future resolves → tool resumes. On workspace switch: `bus.cancel_all()` cancels all pending futures.

---

## 8. Telemetry & Performance

### 8.1 Tracing

Custom `HrAgentTracingProcessor` emits SDK spans to `hragent-telemetry.log` as JSON lines (`span_start` and `span_end` records). Default OpenAI trace upload disabled at startup. Every generation span records:

- `model.name`, `model.input_chars`, `model.output_chars`, `model.finish_reason`
- `model.effective_max_new_tokens`, `model.compaction_triggered`, `model.compaction_cache_hit`
- `turn_id`, `run_id`

Tool spans: `tool.name`, `tool.arguments`, `tool.output_chars`, `tool.truncated`, `tool.status`.
`run_saved_function` span: adds `preflight_status`, `wall_time_ms`, `exit_code`.
`call_knowledge` span: adds `caller`, `sub_run_depth_at_entry`, `child_turn_id`, `child_tool_count`, `wall_time_ms`.
Doctor destructive tools: add `caller`, `authorized`, `target_path`, `atomic_success`.

### 8.2 Performance Budgets

| Metric | Warn | Hard-fail |
|---|---|---|
| Triage first-token latency | > 1000ms | > 2000ms |
| Triage handoff latency | > 2500ms | > 5000ms |
| Conversational turn first-token | — | < 3s |
| Analyst total turn | — | < 120s |

Machine-tier baselines stored in `tests/integration/budgets.json`. Budget overruns log a warning; > 1.5× hard-fail.

### 8.3 Offline Guarantee

- All tests run with `socket.socket` monkey-patched to block `api.openai.com`.
- `OPENAI_API_KEY` set to `sk-offline-dummy`.
- `verify_offline()` at UI startup asserts no `BackendSpanProcessor` (OpenAI uploader) is registered.
