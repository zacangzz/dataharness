# Spec 10 — Data analyst agent (deep-dive)

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3, 4, 5, 6, 7, 8, 9
**Blocks:** none

> **Note on examples.** Worked examples, fixture prompts, and gap topics below are **illustrative only**. The app is problem-agnostic — analyst behavior adapts to whatever domain the user brings (HR, finance, logistics, research, anything else). Specific names like "bonus formula", "average salary", "department", "attrition" that appear in tables and samples are placeholders; the decision tree, retrieval pattern, output contract, and feedback loop are all generic.

## 1. Purpose

Spec 04 declares the analyst agent's tool set + prompt filename; spec 09 defines the knowledge store the analyst reads + writes; **this spec** defines how the analyst actually *operates* at turn time: what it retrieves, how it decides which tool to use, what its output looks like, how it recovers from errors, and how it feeds knowledge gaps back to the **knowledge agent** (spec 09).

Kept separate because the analyst is the only agent with a meaningful decision tree and multiple optional paths. Conversational / clarification / knowledge are single-path prompts.

## 2. Scope

### In scope

- Per-turn knowledge retrieval pattern (minimal turn-entry context + on-demand deeper reads via `get_file_metadata` / `read_text` / `get_user_preferences`).
- Tool-selection decision tree (saved-function reuse/adapt/variant → deterministic tool → shell python → in-turn clarification → sub-run capture → deferred gap).
- Saved-function reuse patterns: exact match, close-args adapt, code-variant authoring.
- In-turn `user_input` clarification (simple intent ambiguity stays inside analyst turn — no triage handoff).
- In-turn `call_knowledge` sub-run (Option D — analyst delegates semantic writes to knowledge agent without leaving the turn).
- Output conventions (grounded numbers, source citation, structure).
- Error recovery (one retry with alternate path, then surface).
- Deferred gap signals written to `memory/notes/gaps/` (consumed by knowledge agent via spec 11 §4.3, gated by triage's `gaps_open` signal per spec 5 §4).
- Analyst prompt (`src/core/prompts/analyst.md`) full content.
- Analyst-specific telemetry.

### Out of scope

- Agent builder construction (spec 4 §2.2).
- Tool definitions (spec 3).
- Knowledge store schema + persistence (spec 9).
- Knowledge-agent-side consumption of gap notes (spec 11).
- Triage + handoff (spec 5).

## 3. Per-turn retrieval pattern

Analyst sees two context sources on every turn.

### 3.1 Turn-entry context is intentionally minimal

Analyst does **not** depend on a Pipeline-injected knowledge manifest on entry. Migration scope keeps triage fast by avoiding large context blocks before handoff, and the analyst compensates with on-demand retrieval.

Default assumptions in migration scope:

- one primary data file per workspace
- short conversations
- complex analytical asks

Operational consequences:

- if there is exactly one data file, analyst may treat "the data" as referring to that file unless the user clearly points elsewhere
- lack of prior intake does **not** block first-answer analysis; analyst may begin from `inspect_file_schema`, `preview_file`, or `column_stats`
- drift is informational, not actionable for analyst. If drift blocks confidence, analyst surfaces a caveat and falls back; doctor handles cleanup later on explicit maintenance turns
- `list_knowledge(verbosity="detail")` stays rare and opt-in. Normal operation uses targeted lookups below

### 3.2 On-demand lookups (the real retrieval)

When a branch in the decision tree (§4) needs depth:

| Need | Tool | Use case |
|---|---|---|
| Columns / units / metric definitions for a known file | `get_file_metadata(path)` | before `column_stats`, before shell python, before citing a metric by name |
| Explicit user-stated presentation / naming / unit preferences | `get_user_preferences()` | only when those preferences would materially affect the answer |
| Source of a saved function (for reuse / adapt / variant) | `read_text("memory/functions/<name>.py")` | branch 1b (adapt args) + branch 1c (author variant) |
| Body of a knowledge note | `read_text("memory/notes/<topic>.md")` | note topic aligns with the question |
| Body of an open gap | `read_text("memory/notes/gaps/<topic>.md")` | user's current turn matches an `gaps_open` topic (shouldn't happen — triage routed to knowledge — but safety net) |
| Structural schema when intake was skipped or no metadata exists yet | `inspect_file_schema(path)` | first analytical turn on a newly added file |
| List saved functions with docstrings | `list_saved_functions()` | when the question suggests prior reusable computation |

No large context block is always loaded. Every lookup is explicit and scoped. Context stays flat.

## 4. Decision tree

Evaluated top-down on every user question that requires analysis:

```
Q: user asks a data question
│
├── 0. Can analyst answer structurally right now, even if intake is missing?
│     ├── YES → use `inspect_file_schema` / `preview_file` / `column_stats` directly.
│     │        First-answer analysis on a newly added file is allowed. Continue if more depth is needed.
│     └── NO  ↓
│
├── 1. Does a saved function help?
│     ├── 1a. EXACT match — name/docstring + args align with the ask.
│     │        → run_saved_function(name, args).
│     │        → if preflight returns stale/schema_mismatch, do NOT execute blindly;
│     │          fall to branch 2 or 3 and surface a caveat. Otherwise DONE.
│     ├── 1b. CLOSE match — similar intent, args differ.
│     │        → read_text("memory/functions/<name>.py") to confirm logic.
│     │        → run_saved_function(name, adapted_args).
│     │        → if preflight fails, fall to branch 2 or 3. Otherwise DONE.
│     ├── 1c. CODE-VARIANT match — logic reusable, output schema differs.
│     │        → read_text("memory/functions/<name>.py") to read source.
│     │        → call_knowledge(task="save variant of <name> that returns <new thing>",
│     │                         context=<source + what to change>)
│     │        → sub-run persists new function via save_python_function (knowledge agent
│     │          owns the naming + index.json write; analyst stays in its lane).
│     │        → run_saved_function(<new_name>, args). DONE.
│     │     (Alternative: analyst authors the variant inline via its own save_python_function
│     │      when the change is trivially mechanical — one-line tweak. call_knowledge is for
│     │      variants where the naming / docstring / metadata merit curation.)
│     └── NO match → branch 2.
│
├── 2. Does a deterministic tool cover it?
│   (list_files / inspect_file_schema / preview_file / column_stats / search)
│     ├── YES → call it → answer. DONE if sufficient.
│     └── NO  ↓
│
├── 3. Does the question need ad-hoc analysis?
│     └── Shell out: `python -c "import pandas as pd; df = pd.read_csv('/workspace/data/<file>'); ..."`
│         ├── Non-trivial & likely reusable → before returning, call save_python_function(...)
│         │   (analyst owns this — it just ran the code and knows it works).
│         └── One-off → just return.
│
├── 3a. Is the user's intent ambiguous (not a knowledge gap)?
│     (e.g. two files could match "the data"; column name could be one of several)
│     → user_input("<one focused question>") — awaits user reply inside this turn.
│     → resume decision tree from the top with the clarified intent. No triage handoff.
│
├── 3b. Did the user just teach something semantic mid-turn?
│     (a formula definition, a column unit, a mapping, a business rule)
│     → call_knowledge(task="<what to capture>", context=<user quote + file/column scope>)
│     → sub-run returns; analyst resumes with updated memory/. DONE if the teach *was* the
│       ask; otherwise continue the decision tree for the remaining question.
│
└── 4. Is a knowledge prerequisite missing AND unresolvable this turn?
    (column meaning undefined, metric formula ambiguous, unit unclear,
     AND the user is not present to answer / no source can settle it right now)
      → write_knowledge_note('gaps/<topic>.md', <what's missing>) →
        return an answer labeled "partial — awaiting clarification on <topic>".
        Knowledge agent picks it up on its next turn (triaged via `gaps_open` — spec 5 §4).
```

Six branches, evaluated in order. One retry with an alternate path between adjacent branches (§6). No multi-step backtracking.

Invariant: analyst never calls doctor inline during a normal analysis turn. Drift may change confidence or path selection, but repair is a later explicit maintenance turn.

### 4.1 Branch 3a vs 4 — when to ask vs when to defer

| Situation | Branch |
|---|---|
| User is present, intent unclear but simple to clarify | 3a — `user_input` in turn |
| User just taught something, analyst needs to persist before proceeding | 3b — `call_knowledge` sub-run |
| A prerequisite is missing and the user *cannot* settle it this turn (out of scope, external source needed, domain expert needs to weigh in) | 4 — gap note, deferred |

Rule of thumb: if asking would take one sentence and the user can answer it, branch 3a. If the prerequisite is a larger semantic claim that needs structured capture (formula definition, schema of a related file, multiple columns' meanings), route via `call_knowledge` (3b) so the knowledge agent captures it properly. Gap note (4) is the last resort — deferred.

### 4.2 Worked examples

> Illustrative — any user domain substitutes cleanly. The point is the *branch chosen*, not the domain wording.

| User question (example) | Retrieval | Path | Output |
|---|---|---|---|
| metric already a saved function, exact match | `list_saved_functions()` or prior turn context exposes `<fn>`; lookup `get_file_metadata` for unit | 1a → `run_saved_function` | table + cite |
| same metric but on a different file | saved fn `<fn>(path)` exists; no new function needed | 1b → `read_text("memory/functions/<fn>.py")` → `run_saved_function(<fn>, {path: "<other>.csv"})` | table + cite |
| similar logic, different output shape ("also return stddev") | close fn exists | 1c → `read_text(<fn>.py)` → `call_knowledge("save variant returning mean+stddev", …)` → run variant | table + cite |
| row count / columns / sample | direct structural inspection is sufficient | 2 → `inspect_file_schema` | short answer |
| novel ad-hoc aggregation | no fn match | 3 → shell python, save fn if reusable | answer + cite |
| "which file do you mean — `a.csv` or `b.csv`?" | `list_files()` or prior turn context shows both; user said "the data" | 3a → `user_input` → resume | answer |
| user says "by the way, column X is in USD" mid-question | no prior metadata entry for X's unit | 3b → `call_knowledge("capture unit for column X", "user: 'column X is in USD'; file: data/a.csv")` → continue | answer + note "recorded unit" |
| formula undefined, user absent or cannot answer | no metric, no note, no fn | 4 → gap note | partial answer |

## 5. Output conventions

Every analyst final message follows this structure:

```
<direct answer — one sentence or a small table>

<if tabular: markdown table with at most 10 rows; note truncation if more>

<sources: list of file paths touched this turn>
```

Rules:
- **Grounded numbers only.** Every numeric claim must come from a tool or function call. No estimated, rounded, or recalled-from-training figures.
- **Cite sources.** End with `Sources:` listing every `data/` file read. Saved-function calls cite the function name too.
- **No filler openings.** Skip "Based on your data…", "Looking at the file…". The ack line was already emitted by triage (spec 5 §5).
- **No apologies.** If a tool errors, state the error and what the user can do; do not pad.
- **Markdown, no emojis** unless user uses them first.
- **Length.** Direct answer ≤ 2 sentences. Supporting table ≤ 10 rows (flag truncation when larger).

## 6. Error recovery

One retry with a different path, then surface.

| Error kind | First response | Fallback |
|---|---|---|
| `run_saved_function` non-zero exit | Try the deterministic tool or shell path for the same question. | If fallback also errors, surface `Error{kind="tool_failure", message=<stderr tail>}`. |
| `run_saved_function` preflight returns `stale_saved_function` or `schema_mismatch` | Do not execute the function. Fall back to deterministic tool or shell path immediately. | Surface caveat in final answer; doctor can clean up later on explicit maintenance turn. |
| `column_stats` missing column | `inspect_file_schema` to confirm column names, re-call with correct name. | If column truly absent, return final message naming the available columns. |
| Shell python raises | Try once with simpler code (smaller slice, no optional deps). | Surface error with the last stderr. |
| `inspect_file_schema` says file missing | Call `list_files` to confirm workspace contents. | If file truly absent, ask user which file to use (via triage handoff to clarification? No — inline question via final answer). |
| Sandbox write denial (for saved function) | Already means a bug — should not happen. Surface immediately. | — |
| Timeout (60 s per shell call) | Surface immediately; do not retry. User decides. | — |

No silent failures. No fallback agent (per umbrella decision A). Errors route through `PipelineEvent.Error` (spec 6 §7).

## 7. Feedback to knowledge agent

Two mechanisms, used in different situations.

### 7.1 `call_knowledge` (in-turn, inline)

For capture the analyst can complete *this turn*. The user just taught something, or the analyst read a note/file that contains a semantic claim worth persisting, and the analysis is mid-flight. Analyst calls `call_knowledge(task, context)`; nested sub-run (spec 3 §5.1, spec 9 §5.12) persists via knowledge agent's prompt-owned writes (`set_file_metadata` / `write_knowledge_note` / `save_python_function`). Returns a confirmation string. Analyst continues the decision tree with updated `memory/`.

Single-turn UX. Owner split preserved: knowledge agent's instructions are the only place that decides *where* a metadata entry lands, *what* note name to use, whether to overwrite.

### 7.2 Gap note (deferred)

When the analyst concludes a required piece of knowledge is missing **and cannot be resolved this turn** (branch 4 in the decision tree — user not present, external source needed, domain-expert answer required), it writes:

```
memory/notes/gaps/<topic>.md
```

Frontmatter + body shape (illustrative — the exact `topic`, `related_files`, and `blocked_question` come from the actual user turn):

```markdown
---
created_by: data_analyst
created_at: 2026-04-18T10:22:13Z
related_files: [data/<file>.csv]
blocked_question: "<user's exact question>"
---

# Gap: <short topic title>

The analyst needs to know <what is missing>. `<file>` does not contain <required thing>; no saved function defines it; no note covers it.

Suggested knowledge-agent prompts:
- <a focused question the knowledge agent could ask the user to fill the gap>
- <an alternative source the user might point at>
```

Knowledge agent consumes these per spec 11 §4.3 (re-read on its next turn, address, delete on resolution).

**Triage gate.** The knowledge agent only receives the gap as a turn when the user's next message topic-matches the open gap — triage routes on the `gaps_open` signal (spec 5 §4). Without this gate, analyst would keep re-flagging the same gap across unrelated turns. With it: analyst signals once, waits for the user's next related turn, knowledge agent handles it.

Topic slug is generated by the analyst from the user's question (sanitized to `^[a-z0-9_-]+$`). Collisions append a timestamp suffix.

The whole mechanism is **generic**: analyst emits a gap, knowledge agent responds. The topic string and body content are whatever the user's actual domain requires — the spec does not fix them.

## 8. Prompt

Full content of `src/core/prompts/analyst.md`:

```
You are the data analyst agent inside HR Agent. You answer the user's questions about data in the workspace. Your workspace has two parts:

- data/  — files the user has uploaded. Read-only to you.
- memory/ — persistent knowledge: metadata JSON, reusable Python functions, and distilled notes. You can read it freely; you can write only to memory/functions/ (via save_python_function) and memory/notes/gaps/ (via write_knowledge_note with a gaps/ path). All other memory/ writes route through call_knowledge.

Do not expect a preloaded knowledge manifest. Start from the user's ask and retrieve context lazily. For depth, use get_file_metadata(path) for column details, list_saved_functions() when the question suggests prior reusable computation, get_user_preferences() when explicit preferences would change the answer, and read_text(path) for note bodies or function source.

If there is exactly one data file, you may treat "the data" as referring to that file unless the user clearly points elsewhere.

Treat drift as informational: surface caveats if it affects confidence ("data/<file>.csv is marked stale — schema may have changed"), but do NOT run cleanup. Maintenance is the doctor agent's job; the user will ask doctor explicitly if they want a sweep.

## Decision order

1. If a saved function EXACTLY matches the question → run_saved_function.
1b. If a CLOSE match exists (similar intent, different args) → read_text("memory/functions/<name>.py") to confirm logic, then run_saved_function with adapted args.
1c. If a CODE-VARIANT match exists (reusable logic, different output) → read_text the source; for mechanical tweaks, save the variant yourself via save_python_function. For meaningful variants (new name, new docstring, new metadata) call call_knowledge("save variant of <name> that does <thing>", <source + delta>) so the knowledge agent owns the curation; then run the new function.
2. Else if a deterministic tool (list_files, inspect_file_schema, preview_file, column_stats, search) covers it → use it.
3. Else shell out to python over /workspace/data/<file>. If the analysis is likely reusable, call save_python_function before returning — you just ran the code, you own the save.
3a. If the user's intent is ambiguous and one focused question from the user would clarify it (and this is not a missing knowledge prerequisite), call user_input once to ask. Then resume from step 1 with the clarified intent. No handoff.
3b. If the user just taught you something semantic mid-turn (a formula, a column meaning, a unit, a business rule, a mapping) — call call_knowledge(task=<what to capture>, context=<user quote + file/column scope>) to persist it via the knowledge agent. Continue your analysis after the sub-run returns.
4. If a required piece of knowledge is missing AND cannot be resolved this turn (user not present, external source needed, domain-expert answer required), write a gap note to memory/notes/gaps/<topic>.md and return a partial answer labeled "awaiting clarification on <topic>". The knowledge agent will handle it when the user next asks about the same topic.

## Writing boundaries

- You write: memory/functions/*.py (via save_python_function), memory/notes/gaps/*.md (via write_knowledge_note).
- You do NOT write: memory/files/*.json, memory/notes/*.md (non-gap). For those, use call_knowledge — the knowledge agent owns semantic curation.
- You NEVER write to data/ — that's the user's.

## Output shape

- Direct answer first (one sentence or a small markdown table).
- Grounded numbers only — every number must come from a tool or function call. Never estimate.
- End with `Sources:` listing every data/ file you read and any saved function you called.
- At most 10 rows per table; note truncation when longer.
- No filler openings, no apologies, no emojis.

## Errors

- One retry with a different path.
- Then surface the error; do not hallucinate a workaround.
```

The prompt intentionally mirrors §4–§7 of this spec so the analyst's behavior is verifiable from a test harness by reading either one.

## 9. Telemetry

Analyst-specific span attributes (attached to the per-turn `agent.name="data_analyst"` span):

- `analyst.decision_path` — `saved_function_exact` | `saved_function_adapt` | `saved_function_variant` | `deterministic` | `shell` | `user_input` | `sub_run_capture` | `gap`
- `analyst.preferences_loaded` — bool (whether `get_user_preferences()` was consulted)
- `analyst.saved_function_preflight_failures` — count of `stale_saved_function` / `schema_mismatch` preflight failures
- `analyst.deeper_reads` — count of on-demand `get_file_metadata` / `read_text` opens during the turn
- `analyst.function_source_reads` — count of `read_text` calls targeting `memory/functions/*.py` (branch 1b/1c usage)
- `analyst.saved_functions_used` — list of function names called
- `analyst.new_functions_saved` — count of `save_python_function` calls authored by the analyst directly (not via sub-run)
- `analyst.call_knowledge_invocations` — count of `call_knowledge` sub-runs triggered this turn
- `analyst.user_input_invocations` — count of in-turn `user_input` calls
- `analyst.gaps_written` — count of `write_knowledge_note` calls targeting `gaps/`
- `analyst.retry_count` — 0 or 1
- `analyst.final_status` — `ok` | `partial` | `error`

## 10. Testing

**Unit (stub LLM + temp workspace):**
- Each decision-tree branch reachable with a scripted tool-call sequence; verify `analyst.decision_path` reports the expected branch.
- Gap-note write: branch 4 triggers a real file in `memory/notes/gaps/` with correct frontmatter.
- Retry logic: first tool call errors → second path invoked; both error → `PipelineEvent.Error` surfaces.
- Output-shape validator: `Sources:` present; no numeric tokens appear outside a cited tool's output (regex check).
- Prompt loader: `analyst.md` round-trips from disk unchanged.

**Integration (stub LLM, fixture workspace):**
- Saved-function happy path: injected knowledge names a function; analyst runs it; grounded answer.
- New-file analytical ask: no prior metadata; analyst still answers from structural tools in the same turn.
- Deterministic happy path: question answerable by `column_stats`; analyst uses it.
- Shell fallback: novel question; analyst shells to python; optionally saves a function.
- Gap signal: analyst writes `memory/notes/gaps/<topic>.md`; Pipeline telemetry shows `gaps_written=1`; knowledge-agent next-turn test (spec 9 §12 gap-signal fixture) consumes it.
- Preference recall: explicit stored preference changes output shape or units without being routed through triage.

**End-to-end real-model (`@pytest.mark.integration`, `HRAGENT_TEST_MODEL_PATH`):**

Shares the canonical-fixture runner with spec 6 §10 + spec 9 §12. Analyst-specific additions. Fixture prompts are illustrative — the point is the *branch exercised*, not the domain phrasing.

| Fixture | Input (example, after an intake fixture) | Expected branch | Quality assertion |
|---|---|---|---|
| analyst-saved-exact | a question matching an existing saved function | `saved_function_exact` | numeric output matches fixture; sources cite the function + source file |
| analyst-saved-stale | exact-match function exists but digest/schema changed | stale → deterministic or shell fallback | saved function does not execute blindly; final answer still grounded via fallback path |
| analyst-saved-adapt | same metric on a different file | `saved_function_adapt` | `read_text` of the function source recorded in telemetry; `run_saved_function` called with adapted `path` arg |
| analyst-saved-variant | "also include stddev" on top of an existing mean-only function | `saved_function_variant` | telemetry shows `call_knowledge_invocations=1`; new function present in `memory/functions/`; variant run returns mean + stddev |
| analyst-deterministic | a question about columns or row counts | `deterministic` | column list matches schema; ≤ 1 tool call |
| analyst-shell | a novel aggregation not covered by any saved function | `shell` | numeric grounding; optionally saves a function |
| analyst-user-input | ambiguous phrasing ("the data") with two candidate files | `user_input` | one `user_input` call; answer resolves to the chosen file; single turn in UI |
| analyst-sub-run | user teaches a unit mid-question ("column X is in USD") | `sub_run_capture` | `memory/files/<file>.json` updated with column unit; final answer uses unit; single turn in UI |
| analyst-preferences | stored preference requests tables or preferred units | `deterministic` or `shell` + `get_user_preferences` | final answer shape reflects preference; triage route unchanged |
| analyst-gap | a question whose required formula/mapping is undefined and user cannot answer | `gap` | `memory/notes/gaps/<topic>.md` exists after turn; final message labeled partial |
| analyst-retry | a question with a slightly wrong column reference | deterministic → retry deterministic | final message correctly resolves to the actual column and answers |

Latency budgets in `tests/integration/budgets.json` under the `analyst_*` keys.

## 11. Files

**New:**
- `src/core/prompts/analyst.md` — full prompt (§8). Spec 9 §13 referenced the filename but deferred content here.
- `tests/core/agents/test_analyst_decision.py` — decision-tree unit tests.
- `tests/integration/test_analyst_e2e.py` — real-model analyst fixtures.

**Modified:**
- `src/core/agents/data_analyst.py` — loads the prompt written here; no behavior changes beyond spec 4 §2.2. The agent builder stays in spec 4; this spec owns the *prompt* and *contract*.
- `src/core/pipeline.py` — supplies only tiny triage signals at turn start; analyst retrieval remains lazy (contract source: spec 6 + spec 9 §7; consumer shape: this spec §3).

**Retired:** none.

## 12. Acceptance

- Analyst does not depend on a preloaded knowledge prefix at turn start; first-answer analysis on a new file still works via structural tools.
- Each decision-tree branch hit at least once across the integration fixtures.
- `analyst.decision_path` populated in telemetry on every turn.
- Gap notes end up in `memory/notes/gaps/` when knowledge is missing; knowledge agent consumes them on the next turn (cross-spec test, spec 9 §12 `gap-signal` fixture).
- Output-shape validator passes across all fixtures (grounded numbers, sources cited).
- Retry logic covered; no silent failures.
- Real-model fixtures green within latency budgets.
