# OpenAI Agents SDK Migration — Umbrella Design

**Date:** 2026-04-17
**Status:** Draft — awaiting user review
**Scope:** Replace smolagents `CodeAgent` stack with OpenAI Agents SDK (`openai-agents-python`). Single big-bang branch, decomposed into ten interconnected child specs.

## 1. Goals

- Replace smolagents with OpenAI Agents SDK as the orchestration layer for HR Agent.
- Adopt a triage + specialist-agents topology (conversational, data analyst via SandboxAgent, clarification, knowledge, doctor).
- Preserve workspace concept as an app-level feature with a transparent two-folder split: user uploads land in `<workspace>/data/` (read-only to agents); agent-synthesized knowledge, saved functions, notes, and session state live in `<workspace>/memory/` (read/write). Workspace scaffolding, drop routing, and active-dir propagation are owned by the **Workspace contract** (§11) — agents operate inside workspaces but do not own them.
- Preserve offline, local-first guarantees. No network egress. No OpenAI-hosted calls. No trace upload.
- Preserve the Textual UI surface while upgrading the process view: workspace modal, clarification flow, status bar, token streaming for assistant output, and streamed per-agent collapsible process blocks in place of the old single post-hoc Agent Steps dump.
- Keep llama_cpp (GGUF Gemma) as the single underlying LLM engine, reused across all agents via a custom Agents SDK `Model` subclass. Gemma multimodal additionally backs `.pdf`/`.docx` text extraction (spec 9 §5.7) — no extra extraction libraries.
- Capture and persist file-level metadata, reusable functions, and distilled notes in a workspace-local, file-based store (spec 9), so agents learn incrementally instead of re-asking. The **knowledge agent** owns writes into this store (new-file intake, mid-conversation capture, gap resolution). Analyst consumes + may extend it inline (spec 10).

## 2. Non-goals

- No input/output guardrails in this migration (deferred).
- No unscoped write-back: agents may write only under `<workspace>/memory/**`. User data files (under `<workspace>/data/**`) remain read-only (enforced by sandbox write-guard — spec 8 §5 + spec 9 §9).
- No handoff-driven fallback agents. On agent failure, error surfaces directly to user.
- No multi-agent parallel execution.
- No hybrid coexistence with smolagents. Cut is total.
- No Docker sandbox backend. `UnixLocalSandboxClient` only.
- No cloud/hybrid model path. Offline only.
- No broad UI redesign beyond the migration work. The only sanctioned UI surface change in scope is replacing the old single post-hoc Agent Steps dump with streamed per-agent collapsible process blocks aligned to Pipeline activity events (spec 7).
- No cross-workspace knowledge sharing. Each workspace is self-contained.

## 3. Motivation

Consolidates multiple concerns:
- Current smolagents stack has known rough edges (agent drift, weak tool-calling on Gemma, grounded-fallback heuristics).
- Agents SDK provides a more structured tool-calling and handoff model, plus native tracing.
- SandboxAgent gives a first-class filesystem + shell execution surface, matching the data-analyst role better than the python-code-writing `CodeAgent`.
- Standardizing on OpenAI Agents SDK keeps a future cloud/hybrid option open without rewriting again.

## 4. Global architecture

```
Textual UI (src/cli/)
  ChatApp  ──async @work──► Pipeline.run(message, history, active_workspace)
      ▲                               │
      │ RunItem stream + StatusUpdate │
      └───────────────────────────────┘
                                      │
Pipeline orchestrator (spec 6)
  ├─ SQLiteSession           (per workspace, at <workspace>/memory/session.db)
  ├─ Manifest                (per turn; two volumes — see below)
  ├─ UnixLocalSandboxClient  (per turn, write-guarded)
  └─ Runner.run(triage_agent, msg, session, run_config)
                                      │
Triage agent (spec 5)
  handoffs: [conversational, data_analyst, clarification, knowledge, doctor]
                                      │
  ┌───────────────┬───────────────┬───────────────────┬──────────────────┬───────────────┐
conversational    data_analyst    clarification       knowledge          doctor
(spec 4)          (SandboxAgent,  (spec 4)            (spec 4 + 11)      (spec 4 + 12)
tools: []         specs 4 + 10)   tools: user_input   tools: inspect/    tools: read +
                  tools: spec 3 +                       preview + text +   structural writes +
                    knowledge                           docs + metadata +  4 doctor-exclusive
                    + documents                         notes + save_fn    delete/rebuild +
                    (spec 9) +                                             call_knowledge +
                    shell + fs mount                                       user_input
                                      │
              Custom Model (spec 1, Agents SDK Model subclass)
                   ├─ Compaction hook (summarize oldest history)
                   └─ LlmModel (spec 2, thin llama_cpp holder)

Workspace mount (two volumes per turn — see §11 Workspace contract)
  <workspace>/data/   → /workspace/data    (read-only)   — user files (CSV, XLSX, PDF, DOCX, MD, JSON)
  <workspace>/memory/ → /workspace/memory  (read-write)  — agent knowledge store

Knowledge store (spec 9; analyst behavior in spec 10)
  <workspace>/memory/
    ├─ session.db               (SQLiteSession)
    ├─ files/<path>.json        (per-file metadata: columns, units, metrics)
    ├─ preferences.json         (explicit user-stated preferences)
    ├─ functions/<name>.py      (reusable callables) + index.json
    └─ notes/
        ├─ <topic>.md           (distilled notes from user uploads + analysis)
        └─ gaps/<topic>.md      (analyst → knowledge feedback signals)
  Specialists read lazily via tools; no aggregate is injected into triage.
  Tools (spec 3 §5.1) write under sandbox write-guard (spec 8 §5 / spec 9 §9).
```

## 5. Agentic workflow

Six agents collaborate across four interaction patterns. Numbered §5.1–§5.7 below cover per-turn flow, patterns, feedback loops, and the ownership matrix. Everything described here is load-bearing; specialists implement specific slices of it.

### 5.1 Per-turn data flow

1. User submits text in Textual UI.
2. `ChatApp` async `@work` calls `Pipeline.run(msg, history, active_workspace)`.
3. Pipeline constructs per-turn `Manifest` with two volumes (`/workspace/data` RO + `/workspace/memory` RW — spec 8 §5 / spec 9 §9), per-turn `UnixLocalSandboxClient` (wrapped by write-guard if per-volume mode unavailable), and retrieves workspace-scoped `SQLiteSession` at `<workspace>/memory/session.db`.
4. Pipeline precomputes pre-triage routing signals (spec 5 §4): `has_data`, `new_files_present`, `gaps_open_present`, `drift_present`. Injected as a tiny system prefix on the triage turn.
5. `Runner.run(triage_agent, msg, session, run_config)` starts streaming. Triage emits a short status-ack line, then a single handoff tool_call (spec 5 §5).
6. Control transfers to one specialist (conversational, data_analyst, clarification, knowledge, doctor). Pipeline emits `StatusUpdate` on each lifecycle transition (spec 6 §3.1). Doctor routes require explicit user maintenance intent — drift alone never triggers.
7. Specialist LLM calls route through the Custom Model (spec 1) with `Compaction.maybe_compact()` before each dispatch — summarizes oldest history when near `n_ctx`.
8. Tools execute locally. Analyst follows spec 10 §4 decision tree (structural-first on new-file analysis → saved-fn → deterministic → shell python → sub-run → gap). Knowledge persists to `memory/files/*.json`, `memory/functions/*.py`, `memory/notes/*.md` + `notes/index.json`. Doctor reads `memory/` + invokes destructive tools under caller-auth (spec 3 §5.3). Document ingestion via Gemma multimodal (spec 9 §5.7) or `read_text`.
9. `RunItem`s stream to UI → per-agent process blocks + live token stream. `StatusUpdate`s → status-bar widget and active process block (spec 7).
10. Custom `TracingProcessor` writes SDK spans to `hragent-telemetry.log` (SDK-native JSON).
11. Final assistant message renders in conversation pane.
12. On workspace switch, Pipeline cancels in-flight `Runner.run`, invalidates `SQLiteSession`, closes sandbox client, clears chat history.

### 5.2 Handoff pattern (triage → specialist)

```
User → Triage ─handoff─→ Specialist → final answer → User
```

- One handoff per turn. Triage never reclassifies mid-turn.
- `SQLiteSession` retains specialist's messages + tool outputs — follow-ups route via session context, not Python state.
- Status-ack line streams *before* the handoff tool_call — UI shows activity while specialist spins up (spec 5 §1 latency lever).

### 5.3 Sub-run pattern (analyst / doctor → knowledge)

Option D delegation (spec 9 §5.12): analyst or doctor invokes `call_knowledge(task, context)` inside its own turn. Tool body nests `Runner.run_streamed(knowledge_agent, ...)`; child streams proxy to parent's consumer; child's final text returns as the tool's string output.

```
Parent turn  ─tool_call─→ call_knowledge  ┐
                           │              ├── single UI turn
                           ↓              │
                   Knowledge sub-run      │
                           │              │
              persists to memory/  ←──────┘
                           ↓
                 Parent resumes w/ fresh memory/
```

- Caller allow-list: `data_analyst` + `doctor`. Recursion guard: `sub_run_depth` context var, max 1.
- Child span nests under parent `turn_id` / `run_id`. Attribute `agent.invocation="sub_run"` distinguishes from handoffs.
- UX: single-turn to user. No handoff ceremony for one-sentence semantic captures.
- Fallback: if nested-sub-run probe (spec 1 §10) fails, tool drops from both callers' tool sets → analyst falls back to triage handoff; doctor runs as a multi-turn sweep with handbacks between steps.

### 5.4 Gap-note feedback loop (analyst ↔ knowledge)

Async, file-based handoff. No in-memory queue.

```
Turn N (analyst):
  question needs missing knowledge (formula / column meaning)
  + user absent OR resolvable later
    → write memory/notes/gaps/<topic>.md
    → return partial answer: "awaiting clarification on <topic>"

Turn N+k (user re-asks matching question):
  Pipeline precomputes gaps_open=[<topic>, …]
  Triage matches current turn to open gap → hands off to knowledge
  Knowledge reads gap file, asks user, persists semantic claim
  Knowledge deletes gap file
  User re-asks → analyst now finds the capture and answers fully
```

Why it works: `gaps_open` signal is the counter-pressure that stops the gap-loop. Without it, analyst would re-flag the same gap every turn.

### 5.5 Drift-detection feedback loop (tools → Pipeline → triage → doctor)

Lazy, self-healing. Doctor never runs uninvited.

```
Turn N (any agent reads data/):
  Read-path tools (inspect_file_schema, preview_file, column_stats,
  read_text, extract_document_text) compute file_digest once per turn per path.
  If digest ≠ memory/files/<path>.json source_digest:
    → stamp intake_status="stale" atomically
    → emit telemetry knowledge.stale_detected
  Tool returns its normal result. No user interruption.

Turn N+1 (next Pipeline pass):
  list_knowledge(verbosity="manifest") includes drift block (stale / minimal / orphan / index_missing counts)
  Pre-triage helper summarize_drift(...) surfaces counts as drift_detected signal
  Pipeline injects into triage prefix

Turn N+1 triage decision:
  User asks analytical question → route to analyst. Drift ignored for routing; analyst may caveat.
  User says "clean up" / "tidy memory" / "yes doctor" → route to doctor.
  No explicit user intent → drift backlog sits. Background sweep (spec 12 §4.3) surfaces a StatusUpdate after N turns.

Doctor turn (when invoked):
  Scan-first via list_knowledge(verbosity="detail").
  Ambiguous state (missing index, unclear intake status) → call_knowledge(task="status", …) to consult knowledge. Never assume.
  Resolve each drift class via the doctor collaboration matrix (spec 12 §5.3 — stale restamp, minimal → call_knowledge resume, orphan → user_input batched y/n → delete_*, dedup → user_input merge, index missing → rebuild_index).
```

### 5.6 Lazy knowledge retrieval

- Pipeline injects only tiny routing signals into triage.
- Specialists retrieve durable context on demand via `get_file_metadata`, `list_saved_functions`, `get_user_preferences`, `read_text`, and `list_knowledge` when explicit orientation is needed.
- Bodies (columns, function signatures, note text) are **never** injected into triage. Agents open them on demand.
- Keeps the first-token path fast while still preserving long-term memory under `memory/`.

### 5.7 Collaboration matrix

| Scope | Owner | Collaboration entry points |
|---|---|---|
| Triage routing decision | triage | reads pre-triage signals; emits handoff |
| Direct chat / no-data messaging | conversational | handoff target only |
| Focused clarification | clarification | `user_input`; returns answer; handoff target only |
| Data inspection + analysis + shell python | data_analyst | handoff target; can sub-run `call_knowledge` |
| Saved `.py` authoring | data_analyst + knowledge | both call `save_python_function` (analyst for analysis artifacts; knowledge for teach-paths) |
| Semantic writes (file metadata, distilled notes) | knowledge only | direct from knowledge turn; OR via `call_knowledge` sub-run from analyst / doctor |
| Gap notes (write) | data_analyst only | `write_knowledge_note` to `gaps/` path |
| Gap notes (resolve + delete) | knowledge only | next triage pass with matching `gaps_open` signal |
| Structural stamps (stale / digest / timestamps) | tool read-paths (auto) + doctor | lazy write; doctor restamps on resolution |
| Destructive maintenance (deletes + rebuild) | doctor only | handoff on user ack; caller-auth enforced by tool |
| Knowledge-store audit (`git log memory/`) | user | every agent write is a file mutation — visible in diff |

Writing rule (absolute): **users only write `data/`; agents only write `memory/`**. Enforced at the sandbox mount layer (spec 8 §5 + spec 9 §9). No code path bypasses.

## 6. Offline enforcement contract

- `OPENAI_API_KEY` is set programmatically to a sentinel (`"sk-offline-dummy"`) if unset, so the `openai` client initializes without raising.
- `set_tracing_disabled(False)` with a custom processor only — no OpenAI upload processor is ever registered.
- `set_tracing_export_api_key(None)` (or equivalent) to guarantee no hosted-trace upload even if the default processor list mutates.
- All `Agent(model=...)` parameters hold the Custom Model instance (spec 1). A model-ID string that resolves to hosted OpenAI is never accepted.
- Startup assertion / unit test: patch `socket.socket` to fail any connection to `api.openai.com` and confirm a smoke turn completes.
- CI lint check: `grep -rn '"gpt-[0-9]"\|"o[0-9]"' src/` must be empty in agent construction files.

## 7. Dependency changes

### `pyproject.toml`

**Remove:**
```
smolagents>=1.0.0
```

**Add:**
```
openai-agents>=0.1.0
```

(`openai-agents` minimum version pinned after probing SDK surface during spec 1 kickoff. **No** `python-docx` / `pypdf` dependencies — `.pdf` and `.docx` text extraction goes through the already-loaded Gemma multimodal model, spec 9 §5.7.)

**Deferred:** `openai-agents[docker]` extra. `UnixLocalSandboxClient` is the default backend.

### Tool inventory changes (spec 3)

- **Renamed (v1 strip "workspace" prefix — scoping is framework-level, not a naming concern):**
  - `describe_workspace_file` → `inspect_file_schema` (clearer contrast with the semantic `get_file_metadata`)
  - `list_workspace_files` → `list_files`
  - `preview_workspace_file` → `preview_file`
  - `read_workspace_text` → `read_text`
  - `search_workspace` → `search`
  - `list_workspace_knowledge` → `list_knowledge`
- **Dropped:** `format_table`, `format_key_value_list` (agents emit markdown directly; tools added noise without value).
- **Added (knowledge + documents, spec 3 §5.1 + spec 9):** `get_file_metadata`, `set_file_metadata`, `list_saved_functions`, `save_python_function`, `run_saved_function`, `read_text`, `extract_document_text`, `write_knowledge_note`, `search`, `file_digest`, `list_knowledge(verbosity)`, `call_knowledge(task, context)` (Option D sub-run — analyst-initiated delegation to the knowledge agent for semantic writes; spec 9 §5.12).

### `hragent.spec`

- Replace `hiddenimports` entry `smolagents` (and subpackages) with `agents`, `agents.sandbox`, `agents.sandbox.entries`, `agents.sandbox.capabilities`, `agents.sandbox.sandboxes.unix_local`, `agents.tracing`. (No `docx` or `pypdf` — Gemma backend handles document extraction.)
- Prompt globs: add `triage.md`, `conversational.md`, `analyst.md`, `clarification.md`, `knowledge.md` (spec 11, renamed from `onboarding.md`), `doctor.md` (spec 12). Rename `memory_summarize.md` → `compaction_summarize.md` (contents unchanged). Drop `hr.md`.
- Verify `openai`, `agents.sandbox`, `agents.tracing` submodules collect.
- Bundle any auxiliary shell/runtime glue shipped by `UnixLocalSandboxClient` (probed in spec 8).

## 8. Build sequencing

Ordered child specs. Each child owns its own tests and acceptance criteria. Dependency edges are strictly linear.

1. `2026-04-17-01-llama-cpp-agents-model.md`
2. `2026-04-17-02-model-core-refactor.md`
3. `2026-04-17-03-hragent-tools.md`
4. `2026-04-17-04-specialist-agents.md`
5. `2026-04-17-05-triage-routing.md`
6. `2026-04-17-06-pipeline-orchestrator.md`
7. `2026-04-17-07-ui-telemetry-integration.md`
8. `2026-04-17-08-packaging-sandbox-runtime.md`
9. `2026-04-17-09-knowledge-agent.md` — **knowledge store + tool contracts only** (layout, schemas, tool bodies, caller-auth, sandbox write-guard)
10. `2026-04-17-10-data-analyst-agent.md` — analyst deep-dive
11. `2026-04-17-11-knowledge-agent.md` — knowledge **agent** deep-dive (entry points, prompt, skip+resume, gap loop, sub-run)
12. `2026-04-17-12-doctor-agent.md` — doctor agent deep-dive (scan-first, never-assume, resolution matrix, drift feedback loop)

Spec 9 depends on specs 1–8 and defines the `<workspace>/memory/` store layout, the 11 knowledge + document `@function_tool` callables declared in spec 3 §5.1, caller-auth + recursion guards, lazy stale-digest detection, and the sandbox write-guard used by spec 8. Spec 10 depends on specs 1–9 and is the analyst deep-dive. Specs 11 and 12 depend on specs 1–10 and own the knowledge and doctor specialist agents respectively — construction + prompts + entry points + integration fixtures. Spec 4 still constructs all five agents; specs 11 and 12 deep-dive behavior and prompt content for the two memory-curating specialists.

## 9. Retirements

The following are deleted or gutted in this migration. Tracked here so no child spec has to repeat the list.

### Source files

- `src/core/model.py` — content moved to `src/core/engine/llm.py` (shrunk); old path deleted
- `src/core/agents/model_adapter.py` (smolagents adapter) — deleted, retired by spec 1
- `src/core/agents/memory_manager.py` — moved + renamed to `src/core/engine/compaction.py` (class `MemoryManager` → `Compaction`); old path deleted
- `src/core/agents/hr.py` (smolagents `CodeAgent` builder) — deleted, retired by spec 4
- `src/core/agents/pipeline.py` (old route-selection pipeline) — deleted, retired by spec 6
- `src/core/pipeline_factory.py` — deleted, retired by spec 6
- `src/core/prompts/hr.md` — deleted, retired by spec 4

### Test files

- `tests/core/test_model.py` — retired by spec 2 (new location: `tests/core/engine/test_llm.py`)
- `tests/core/agents/test_memory_manager.py` — moved + renamed to `tests/core/engine/test_compaction.py` by spec 1
- `tests/core/agents/test_model_adapter.py` — deleted by spec 1 (smolagents adapter retired)
- `tests/core/agents/test_hr.py` — deleted by spec 4 (smolagents CodeAgent retired)
- `tests/core/agents/test_pipeline.py` — deleted by spec 6 (new location: `tests/core/test_pipeline.py`)
- `tests/cli/test_app.py` — deleted by spec 7 (new location: `tests/cli/test_app_async.py`)

### Test migration matrix

Paths reflect the new Option B layout (`engine/`, top-level `pipeline.py`, `clarification_bus.py`).

| Current test | Action | Owning spec | New location / notes |
|---|---|---|---|
| `tests/test_main.py` | keep (spot-update) | — | Spot-update only if `main.py` entry imports change |
| `tests/cli/test_app.py` | delete | 7 | Replaced by `tests/cli/test_app_async.py` |
| `tests/cli/test_status_bar.py` | update | 7 | Add cases for `StatusUpdate` → status-bar widget routing (level → style class) |
| `tests/core/test_model.py` | delete | 2 | Replaced by `tests/core/engine/test_llm.py` at new path |
| `tests/core/test_terminal.py` | keep | — | Untouched |
| `tests/core/test_workspace.py` | keep | — | Untouched |
| `tests/core/test_workspace_screen.py` | keep | — | Untouched |
| `tests/core/agents/conftest.py` | update | 1 | Strip smolagents fixtures; agents-folder tests now cover specialist/triage agents only |
| `tests/core/agents/test_hr.py` | delete | 4 | Smolagents `CodeAgent` retired |
| `tests/core/agents/test_memory_manager.py` | move + rename + update | 1 | Moved + renamed to `tests/core/engine/test_compaction.py`; integration point swapped to `LlamaCppAgentsModel` |
| `tests/core/agents/test_model_adapter.py` | delete | 1 | Smolagents adapter retired |
| `tests/core/agents/test_pipeline.py` | delete | 6 | Replaced by `tests/core/test_pipeline.py` |
| `tests/core/tools/test_formatting.py` | rewrite | 3 | Re-target against `@function_tool` callables |
| `tests/core/tools/test_user_input.py` | rewrite | 3 | Async semantics via `clarification_bus` |
| `tests/core/tools/test_workspace_files.py` | rewrite | 3 | `@function_tool` envelope, active-workspace context var |

### New test files

| New file | Owning spec |
|---|---|
| `tests/core/engine/__init__.py` | 1 |
| `tests/core/engine/conftest.py` | 1 |
| `tests/core/engine/test_agents_model.py` | 1 |
| `tests/core/engine/test_llm.py` | 2 |
| `tests/core/test_clarification_bus.py` | 3 |
| `tests/core/agents/test_specialists.py` | 4 |
| `tests/core/agents/test_triage.py` | 5 |
| `tests/core/test_pipeline.py` | 6 |
| `tests/cli/test_app_async.py` | 7 |
| `tests/core/test_telemetry_processor.py` | 7 |
| `tests/integration/__init__.py` | 1 |
| `tests/integration/conftest.py` | 1 | — shared fixtures: `HRAGENT_TEST_MODEL_PATH` resolver, socket-patch, fixture workspaces, budget loader
| `tests/integration/budgets.json` | 1 | — machine-tier latency budgets (first-token / total) per canonical fixture
| `tests/integration/test_model_conversation.py` | 1 | — spec 1 §10 real-model tests
| `tests/integration/test_pipeline_e2e.py` | 6 | — spec 6 §10 real-model end-to-end conversation suite
| `tests/integration/test_ui_e2e.py` | 7 | — spec 7 real-UI + real-model turn
| `scripts/smoke_packaged.sh` (not pytest) | 8 |
| `tests/core/test_knowledge_store.py` | 9 | — atomic write, schema validation |
| `tests/core/tools/test_knowledge.py` | 9 | — knowledge `@function_tool` callables (metadata, functions, notes, search, digest, aggregate) |
| `tests/core/tools/test_documents.py` | 9 | — `read_text` + `extract_document_text` (Gemma multimodal backend, plain text, .docx, .pdf) |
| `tests/core/agents/test_knowledge.py` | 9 | — knowledge-agent prompt + tool flow (intake, mid-convo capture, gap resolution) |
| `tests/integration/test_knowledge_e2e.py` | 9 | — spec 9 §12 fixtures: onboard-csv, onboard-pdf-short, onboard-pdf-long, onboard-skip, onboard-resume, teach-inline, reuse-metadata, save-function, run-saved, write-guard, gap-signal |
| `tests/core/agents/test_data_analyst.py` | 10 | — analyst decision-tree branches + retrieval injection |
| `tests/integration/test_analyst_e2e.py` | 10 | — spec 10 §10 fixtures: saved-function reuse, deterministic, shell python, gap-signal write |

## 10. Retained

- `src/core/workspace.py` (`WorkspaceManager`, `WorkspaceEntry`) — no change
- `src/cli/workspace_screen.py`, `src/cli/file_browser.py` — no change
- `src/cli/filedrop.py` — minor update (spec 9 §8.1): after drop, posts synthetic "I just added <filename>" to the turn queue so the normal triage → knowledge flow fires (owned by §11 Workspace contract)
- `src/cli/status_bar.py` — minor update: subscribes to Pipeline `StatusUpdate` events (spec 6 §3.1) via the app's event dispatcher; widget internals unchanged
- `src/cli/app.py` — modified internally (async refactor) but stays in `src/cli/`
- `src/core/terminal.py` — no change
- `src/core/prompts/compaction_summarize.md` — renamed from `memory_summarize.md`, content unchanged (file stays under `src/core/prompts/`)
- `src/core/telemetry.py` — repurposed as thin logger backing the custom `TracingProcessor` (spec 7)

## 10a. New directory layout (Option B)

```
src/core/
├── pipeline.py                      [NEW — orchestrator, spec 6]
├── workspace.py                     [unchanged]
├── telemetry.py                     [MODIFIED — HrAgentTracingProcessor, spec 7]
├── terminal.py                      [unchanged]
├── clarification_bus.py             [NEW — future registry, spec 3/7]
├── knowledge_store.py               [NEW — filesystem layer for metadata + functions, spec 9]
├── sandbox_guard.py                 [NEW — path-allow-list write guard, spec 8 / spec 9]
├── engine/
│   ├── __init__.py
│   ├── llm.py                       [MOVED from src/core/model.py, shrunk — spec 2]
│   ├── agents_model.py              [NEW — LlamaCppAgentsModel, spec 1]
│   └── compaction.py                [MOVED + RENAMED from src/core/agents/memory_manager.py — spec 1]
├── agents/
│   ├── __init__.py
│   ├── triage.py                    [NEW — spec 5]
│   ├── conversational.py            [NEW — spec 4]
│   ├── data_analyst.py              [NEW — spec 4]
│   ├── clarification.py             [NEW — spec 4]
│   └── knowledge.py                 [NEW — spec 4 + spec 9]
├── prompts/
│   ├── triage.md                    [NEW — spec 5 prompt, filed via spec 4]
│   ├── conversational.md            [NEW — spec 4]
│   ├── analyst.md                   [NEW — spec 4]
│   ├── clarification.md             [NEW — spec 4]
│   ├── knowledge.md                 [NEW — spec 9, filed via spec 4]
│   └── compaction_summarize.md      [RENAMED from memory_summarize.md — contents unchanged]
└── tools/
    ├── workspace_files.py           [REWRITE — spec 3; renames per §7]
    ├── formatting.py                [RETIRED — format_table + format_key_value_list dropped, spec 3]
    ├── user_input.py                [REWRITE — spec 3; imports clarification_bus]
    ├── knowledge.py                 [NEW — metadata, saved functions, notes, search, digest, aggregate, spec 3 §5.1 + spec 9]
    └── documents.py                 [NEW — read_text + extract_document_text (Gemma multimodal), spec 3 §5.1 + spec 9]
```

CLI layer (`src/cli/`) structure unchanged; only `app.py` internals are modified by spec 7.

### Import path changes (consumed by callers across the tree)

| Old path | New path | Moved by spec |
|---|---|---|
| `src.core.model.LlmModel` | `src.core.engine.llm.LlmModel` | 2 |
| `src.core.agents.memory_manager.MemoryManager` | `src.core.engine.compaction.Compaction` | 1 |
| `src.core.agents.pipeline.Pipeline` (retired) | `src.core.pipeline.Pipeline` | 6 |
| `src.core.agents.model_adapter.*` (retired) | `src.core.engine.agents_model.LlamaCppAgentsModel` | 1 |

## 11. Cross-cutting contracts

Consumed by multiple child specs. Authoritative here.

### 11.1 Workspace contract (consolidated)

The workspace is an **app-level feature**, not a knowledge-agent internal. This contract is the single source of truth; specs 06, 07, and 09 reference it rather than redefining.

- **Ownership.** `src/core/workspace.py` (`WorkspaceManager`, `WorkspaceEntry`) owns lifecycle; `src/cli/filedrop.py` owns drop routing; `src/cli/workspace_screen.py` owns the UI modal. No agent imports these.
- **Scaffold on create.** `WorkspaceManager.create(name)` creates `<workspace>/data/` and `<workspace>/memory/`. `memory/` subfolders (`files/`, `functions/`, `notes/`, `notes/gaps/`) created lazily by the knowledge store (spec 9 §3) on first write.
- **Lazy migration.** On first open of an existing pre-migration workspace (single flat dir), `WorkspaceManager` moves user data files into `data/` and creates `memory/` empty. Idempotent.
- **Active-dir propagation.** `WorkspaceManager.active_dir` is a module-level property. Pipeline reads it at turn start and publishes the resolved path into an `active_workspace_path` context var (spec 6) that `@function_tool` callables consult to resolve relative paths — no tool imports `WorkspaceManager` directly.
- **Two-volume mount (per turn).** Pipeline binds `active_dir` as a `Manifest`: `/workspace/data` → `<active_dir>/data/` (read-only), `/workspace/memory` → `<active_dir>/memory/` (read-write). Spec 8 §5 is authoritative for the mount mechanism (per-volume modes preferred, path-guard fallback acceptable).
- **Filedrop.** `src/cli/filedrop.py` copies dropped files into `<active_dir>/data/` and posts a synthetic user input (`I just added <filename>.<ext>`) to the turn queue. If a turn is in flight, queue the prompt until completion.
- **Workspace switch.** `WorkspaceManager.switch(name)` cancels any in-flight `Runner.run`, invalidates the current `SQLiteSession`, closes the sandbox client, and clears chat history (spec 6).
- **Workspace delete.** `WorkspaceManager.delete(name)` removes the workspace directory in full (user data + memory + session.db).
- **Path invariants.**
  - User data → `<workspace>/data/` only. Agents read but never write here.
  - Agent state → `<workspace>/memory/` only. Users may inspect/edit; sandbox write-guard enforces the boundary for agent code.
- **Separate spec?** No — workspace mgmt is small enough to stay distributed across the existing touchpoints (spec 06 context var, spec 07 UI, spec 09 scaffold coupling). This sub-section is the consolidated contract; if scope grows later, split into a dedicated spec 11.

### 11.2 Other cross-cutting contracts

- **Tool output envelope:** All `@function_tool` returns are JSON strings with top-level `status`, `tool`, `schema_version`, `data`. Identical to current smolagents tool envelope.
- **`obs_max_chars`:** Computed from `n_ctx * chars_per_token * 0.1` at Pipeline init, read by each tool via a module-level accessor (spec 3 §3).
- **Prompt path resolution:** All prompts loaded from `src/core/prompts/` via the same helper used today, so `hragent.spec` packaging still works.
- **Telemetry `run_id` / `turn_id`:** Retained as context variables. Attached to every SDK span via the custom processor.
- **Session file:** `SQLiteSession` database lives at `<workspace>/memory/session.db`. Cleaned up automatically by `WorkspaceManager.delete(name)` via the existing `shutil.rmtree` call.
- **Knowledge store path:** `<workspace>/memory/` is the sole persistent location for agent-authored state: `files/<path>.json` (per-file metadata), `functions/<name>.py` + `index.json` (reusable callables), `notes/<topic>.md` (distilled notes), `notes/gaps/<topic>.md` (analyst → knowledge feedback signals). Spec 9 §3 is authoritative for layout + schema. Writes allowed only under `<workspace>/memory/` (enforced by sandbox write-guard, spec 8 §5 + spec 9 §9).
- **Triage hot-path contract:** triage is a speed layer, not a retrieval layer. Triage sees only tiny routing signals (`has_data`, `new_files_present`, `gaps_open_present`, `drift_present`, optional `last_active_specialist`). It does **not** receive the knowledge manifest, saved-function lists, note summaries, or user preferences.
- **Specialist retrieval contract:** specialists retrieve context lazily after handoff via tools. Migration scope does **not** depend on a post-handoff Pipeline injection step; the one-run handoff path must remain valid even if specialist context is fetched entirely on demand.
- **Doctor isolation contract:** doctor is maintenance-only. Doctor may surface backlog via `StatusUpdate`, but never blocks, hijacks, or front-runs the user's first analytical answer. Drift is informative during normal analysis turns; repair requires explicit maintenance intent.
- **Shared activity contract:** Pipeline, UI, and telemetry share one activity vocabulary (`agent_started`, `reasoning_summary`, `tool_call_start`, `tool_call_complete`, `tool_output`, `handoff`, `status_update`, `agent_finished`, `final_message`, `error`). UI renders live `PipelineEvent`s from that vocabulary; telemetry records the same lifecycle for correlation. Raw chain-of-thought is not required in either surface.
- **Migration scope assumption:** migration scope optimizes for one primary data file per workspace and shorter conversations with complex questions. Multi-file relationship memory, semantic retrieval, and revision-history UX are deferred follow-up specs.
- **Agent interplay contract:**
  - `triage` chooses the route fast.
  - `data_analyst` owns first answers on data questions.
  - `knowledge` owns semantic capture and preference memory.
  - `doctor` owns structural repair only.

## 12. Open risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | SandboxAgent API is beta, may change | Pin `openai-agents` exact version; wrap SandboxAgent behind internal `AnalystAgent` so a version bump touches one file |
| R2 | `UnixLocalSandboxClient` needs python+pandas inside packaged-binary runtime | Spec 8 probes: confirm sandbox uses host python. If not, bundle mini-runtime or fall back to Docker with clear docs |
| R3 | Custom Model subclass may not be compatible with SandboxAgent | Spec 1 kickoff probe: run SandboxAgent with a stub Custom Model against local fixture, confirm tool_call routing |
| R4 | Agents SDK default egress (tracing upload, OpenAI client init) | Umbrella offline-enforcement contract; socket assertion test in CI |
| R5 | Gemma GGUF tool-calling quality under Agents SDK message format | Reuse current llama_cpp `chat_with_tools` prompt/format layer inside Custom Model; fall back to prompted JSON schema parse if needed |
| R6 | Textual async refactor introduces cancellation or clarification bugs | Spec 7 has explicit cancellation and clarification tests under Textual test harness |
| R7 | Per-turn sandbox teardown is too slow | Spec 8 benchmarks; if >1s, consider persistent sandbox per workspace |
| R8 | `SQLiteSession` file location + packaging | Placed under `<workspace>/memory/session.db` (colocated with knowledge store); documented in APP.MD |
| R9 | Sandbox write-guard feasibility depends on `UnixLocalSandboxClient` per-volume mount support | Spec 8 §5 probe: prefer per-volume modes (data RO + memory RW). Fallback to `src/core/sandbox_guard.py` path-allow-list wrapper. Blocking only spec 9 if neither route works; core migration ships without knowledge writes in that case |
| R10 | Dropping fallbacks reduces resilience | Accepted by user; telemetry will track turn-failure rate after ship |
| R11 | SDK ships `agents.sandbox.capabilities.compaction` which we do not use | Custom-model-level `Compaction` (spec 1 §5) covers all agents and is offline-verifiable. Revisit if upstream adds a cross-agent `CompactionProvider` that accepts a custom `Model` for the summarization pass. See spec 1 §6. |
| R12 | Saved `.py` functions could run malicious code | All writes originate from the local LLM itself; no remote author. Subprocess execution is inside `UnixLocalSandboxClient` (same isolation as shell exec), bounded to 60 s, scoped to the workspace. User can inspect `<workspace>/memory/functions/*.py` directly. Follow-up mitigation deferred: per-function allowlist or signature before re-run |
| R13 | Knowledge store could accumulate stale metadata as user data evolves | `set_file_metadata` is last-write-wins; knowledge agent re-runs intake when file hash changes (deferred detail in spec 9 — currently: explicit user request re-onboards) |
| R14 | Gemma multimodal extraction is slower and less deterministic than dedicated libraries for long docs | Spec 9 §5.7 phased-reading contract bounds per-call pages; spec 9 §12 `onboard-pdf-long` fixture gates acceptance. Failure mode: tool returns `status="error"` with `reason="extraction_failed"`; agent reports limitation. Exact phase chunk size, prompt template, and total-pages budget pinned during spec 9 probe task. |

## 13. Acceptance criteria

- All current behaviors still work: workspace CRUD, file drop, chat, clarification, per-agent process blocks, workspace modal, file browser.
- No regression in grounded data-analysis turns (list files, inspect schema, column stats, row counts, preview).
- SandboxAgent path supports ad-hoc python analysis of workspace CSV/XLSX/parquet/JSON files.
- Offline verified: zero network traffic during any turn (automated socket test).
- Telemetry log populated with SDK-native spans. No OpenAI upload.
- `grep -r smolagents src/ tests/` returns no matches.
- Packaged binary builds and runs the smoke suite (spec 8 §6) successfully; recorded latencies within 1.5× budget.
- End-to-end streaming verified: every canonical fixture (spec 6 §10) produces multiple streamed events (text deltas, ToolCallStart/Complete, ToolOutput) before the final message — no batched-at-end deliveries.
- Integration suite (`tests/integration/`) passes on real GGUF with all quality and latency assertions.
- Workspace scaffold: fresh workspace contains `data/` and `memory/` subfolders; file drop lands user files under `data/`; agent writes never touch `data/`.
- File intake flow: pure onboarding or pure teaching turns trigger the knowledge specialist; a concrete analytical question on a newly dropped file still routes to the analyst and may be answered structurally in the same turn.
- Mid-conversation capture: user teaching a formula/definition mid-turn triggers knowledge handoff; `save_python_function` + `set_file_metadata` persist the captured knowledge (spec 9 §12 `teach-inline` fixture).
- Document ingest: dropping a `.pdf` or `.docx` triggers knowledge, `extract_document_text` (Gemma multimodal) yields plain-text content for short docs in one phase and long docs across multiple phases, and a distilled note is written to `<workspace>/memory/notes/<topic>.md`.
- Write-guard: sandbox rejects writes outside `<workspace>/memory/**` (spec 9 `write-guard` fixture + spec 8 smoke §5a).
- Saved functions: analyst can `save_python_function` and later `run_saved_function` across sessions (spec 9 §12 `save-function` + `run-saved` fixtures).
- Saved-function freshness: stale or schema-incompatible saved functions fail preflight, do not execute blindly, and force analyst fallback to deterministic or shell paths in the same turn.
- Analyst decision tree: saved-function path preferred over shell when applicable; shell python fallback grounded in workspace data; unresolved questions emit a gap note to `memory/notes/gaps/<topic>.md` (spec 10 §10 fixtures).
- Preference recall: explicit user-stated preferences persist under `memory/` and are available to the relevant specialist without being injected into triage.
- Status bar reflects turn lifecycle via `StatusUpdate` events (spec 6 §3.1 + spec 7).

## 14. CI gates

- `uv run pytest` green
- `uv run ruff check src/ tests/` green
- Offline assertion test (socket monkey-patch fails on `api.openai.com`) passes
- `grep -r smolagents src/ tests/` returns zero matches
- Packaging smoke via `scripts/build_app.sh` (or equivalent) succeeds

## 15. Rollback plan

- Big-bang branch rebased on current `main`.
- If post-merge regressions are severe, revert the single merge commit. No coexistence glue was added, so revert is clean.
- Telemetry comparison (pre/post) tracked manually for the first 72 hours after merge.
