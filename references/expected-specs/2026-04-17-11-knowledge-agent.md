# Spec 11 — Knowledge agent

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3, 4, 5, 6, 7, 8, 9
**Blocks:** spec 12 (doctor collaborates via `call_knowledge`)

> **Examples are illustrative.** JSON blobs, markdown samples, topic names, and fixture prompts use generic placeholders. The app is problem-agnostic; nothing in the runtime hardcodes domain terms.

## 1. Purpose

Define the **knowledge agent** — the fourth specialist triage hands off to. Owns every semantic write into the persistent knowledge store defined in spec 9 (files metadata, saved functions authored via capture, distilled notes + `notes/index.json`). Does not answer analytical questions; hands back if user veers into analysis.

## 2. Scope

### In scope

- Agent construction (referenced from spec 4 §2.4).
- Four entry points (new-file intake, mid-conversation capture, gap resolution, sub-run via `call_knowledge`).
- Behavior per entry point.
- Skip + resume flow.
- `src/core/prompts/knowledge.md` content.
- Agent-specific telemetry.
- Integration fixtures for knowledge paths.

### Out of scope

- Knowledge-store layout, schemas, tool contracts — spec 9.
- Tool implementations — spec 3 (+ semantic delta in spec 9 §5).
- Doctor agent — spec 12.
- Data analyst decision tree — spec 10.
- Triage signal computation — spec 5.

## 3. Agent construction

```python
knowledge_agent = Agent(
    name="knowledge",
    instructions=_load_prompt("knowledge.md"),
    model=custom_model_direct,
    tools=[
        list_files, inspect_file_schema, preview_file,
        read_text, extract_document_text,
        search, file_digest,
        get_file_metadata, set_file_metadata,
        write_knowledge_note,
        save_python_function, list_saved_functions,
        user_input,
    ],
)
```

- No `call_knowledge` in tool set — recursion guard (spec 9 §5.12).
- No `run_saved_function` — knowledge captures; analyst runs.
- No doctor-exclusive destructive tools.
- `compaction=None` — capture turns are short; single focused exchange per invocation.

## 4. Entry points

Four situations invoke the agent — three via triage handoff, one via sub-run.

### 4.1 New-file intake (triage `new_files`)

A file exists under `data/` with no matching `memory/files/<name>.json` (or a stale `source_digest`) **and** the user turn is primarily onboarding / teaching / capture-oriented. Triage hands off.

If the user asks a concrete analytical question about a newly added file, triage routes to analyst instead; knowledge is not a mandatory gateway before the first answer.

Behavior:

- Lead by inspecting: `inspect_file_schema` for tabular; `extract_document_text` for `.pdf` / `.docx`; `read_text` for `.md` / `.txt` / `.json`.
- Ask one focused question at a time via `user_input`. Accept volunteered detail without re-asking.
- Before returning:
  - Tabular → `set_file_metadata` with confirmed columns + metrics.
  - Document → `write_knowledge_note` summary; cross-link via any related tabular file's `notes_refs`.
  - User teaches a computation → `save_python_function`.

### 4.2 Mid-conversation capture (triage `definitional_content`)

User teaches a formula / column meaning / unit / mapping / business rule during any turn. Triage routes to knowledge (rather than analyst) so the agent captures before anything else happens.

Behavior — acknowledge briefly, persist, return control. No long questions:

| Teaching shape | Tool |
|---|---|
| Formula / computation | `save_python_function` (agent generates working code from user's description) |
| Column meaning / unit | `set_file_metadata` |
| Business rule / policy | `write_knowledge_note` |
| Column-value mapping ("status = 'A' means active") | `set_file_metadata` under `columns[].notes` |
| User preference ("show tables by default", "use USD labels") | `update_user_preferences` |

### 4.3 Gap resolution (triage `gaps_open`)

`memory/notes/gaps/*.md` exists from a prior analyst turn AND current user turn topic-matches an open gap (spec 5 §4).

Behavior:

- Read the matching gap file.
- Ask the user the gap's deferred question.
- Persist via whichever tool fits (same mapping as §4.2).
- **Delete the gap file** on resolution.

Additionally: on *any* knowledge turn (regardless of trigger), scan `memory/notes/gaps/*.md` as a sanity check — if a latent gap shares context with the current task, resolve it too before returning.

### 4.4 Sub-run via `call_knowledge`

Analyst (spec 10 §4) or doctor (spec 12 §4) invokes `call_knowledge(task, context)`. Tool body nests `Runner.run_streamed(knowledge_agent, input=task + context, session=<ephemeral>, run_config=<parent turn's>, on_event=<proxy to parent>)`. Session scope is ephemeral — no cross-contamination with analyst's main session. Agent sees a single focused prompt.

Behavior:

- `task` names what to persist; `context` carries raw material (user quote, file/column scope, analysis excerpt).
- Persist via the matching tool (`set_file_metadata` / `write_knowledge_note` / `save_python_function`).
- **No `user_input`.** The parent agent already has whatever the user said; asking again is a UX failure.
- Return a short one-line confirmation. Knowledge's final text becomes the tool's return value.
- Scope is narrow: persist and return. Do not hand back via "ready for analysis" — sub-run ends when the tool function returns.
- Child budget: `max_turns=3` (spec 9 §5.12).

## 5. Behavior invariants (all entry points)

- **Always confirm in a short final message.** What was saved, where. User-readable one-liner.
- **Boundary.** If the user veers into analysis during a handoff entry point, hand back to triage via final-answer with an explicit "ready for analysis" line. Knowledge agent does not do the numbers. Sub-run invocations cannot trigger a handoff — they complete and return to the parent inline.
- **Minimal ceremony.** For teach paths, one acknowledgment + one persistence call + one confirmation. Do not re-ask what the user just stated.
- **Not an intake gate.** Knowledge capture improves later turns, but does not own the user's first analytical answer on a newly added file.

## 6. Skip + resume

- User says "skip" (or equivalent) during intake → agent writes a minimal `files/<name>.json` with `path` + `source_digest` + `last_onboarded_at` only. `intake_status="minimal"` (spec 9 §3.1). Returns. Analyst falls back to structural inspection.
- User resumes anytime ("let's finish onboarding `<file>`") → triage routes back to knowledge. Agent reads existing minimal JSON and picks up where it left off. On the `intake_status="minimal"` case triggered via doctor drift signal, entry is via sub-run (spec 12 §4) rather than triage handoff — same behavior body.

## 7. Prompt (`src/core/prompts/knowledge.md`)

Short, behavior-focused. Constraints:

- State the agent's job in one sentence: "You capture knowledge about the user's files and domain; you do not run analysis."
- Four entry points with one-line trigger + one-line behavior each.
- Persistence tool map (§4.2 table).
- Boundary rule: hand back if user veers into analysis (handoff paths only).
- Confirmation rule: short final message naming what was saved.
- Skip + resume rule.
- Sub-run rule: no `user_input`; persist and return.
- Gap sanity-check rule: scan `memory/notes/gaps/*.md` every turn.

No hardcoded domain terms. No framework internals. No example data values.

## 8. Telemetry

- `agent.knowledge` span attributes: `trigger=<new_file|definitional|gap|sub_run>`, `invocation=<handoff|sub_run>`, `files_captured`, `columns_documented`, `metrics_documented`, `notes_written`, `functions_saved`, `gaps_resolved`, `wall_time_ms`.
- Child span nests under parent `turn_id` / `run_id` when `invocation="sub_run"` (spec 9 §5.12).
- Tool spans per spec 3 §8 + spec 9 §11.

## 9. Testing

**Unit:**

- Agent constructs with the declared tool set (including absence of `call_knowledge`, `run_saved_function`, doctor-exclusive tools).
- Prompt loads from disk.

**Integration (stub LLM, temp workspace):**

- `onboard-csv` — drop CSV → triage handoff → `inspect_file_schema` + `set_file_metadata` chain → confirmation.
- `onboard-pdf-short` — 3-page PDF → single-phase `extract_document_text` → `write_knowledge_note`.
- `onboard-pdf-long` — 40-page PDF → multi-phase extraction; final summary covers ≥ 80% of pages.
- `onboard-skip` — "skip for now" → minimal `files/<name>.json`; no notes.
- `onboard-resume` — after skip, "let's finish onboarding <file>" → re-enters intake on existing minimal JSON.
- `teach-inline` — "<metric> is computed as <formula>; <column> means <meaning>" → `save_python_function` + `set_file_metadata`.
- `reuse-metadata` — later analytical question references a captured metric → analyst retrieves the needed metadata lazily and uses the canonical metric name (cross-spec with spec 10).
- `save-function` — "save that as `<fn_name>`".
- `run-saved` — fresh session; "run `<fn_name>`" → `run_saved_function` (cross-spec with spec 10).
- `preference-capture` — user says "show percentages by default" or "prefer concise answers" → `update_user_preferences`; later specialist read path sees the stored preference (cross-spec with specs 9 and 10).
- `gap-signal` — analyst writes gap file; next knowledge turn consumes it; gap file deleted on resolution.
- `gap-triage-match` — open gap exists; user re-asks matching question → triage routes to knowledge (not analyst).
- `sub-run-capture` — during analyst turn, user says "column X is in USD"; analyst calls `call_knowledge` → metadata updated; analyst's final answer uses unit; single turn in UI.

**End-to-end real-model:** same fixture set, `@pytest.mark.integration`, `HRAGENT_TEST_MODEL_PATH`, latency budgets in `tests/integration/budgets.json`.

## 10. Files

**New:**

- `src/core/agents/knowledge.py` — agent builder (renamed from earlier draft `file_onboarding.py`).
- `src/core/prompts/knowledge.md` — prompt (renamed from `onboarding.md`).
- `tests/core/agents/test_knowledge.py` — unit tests.
- `tests/integration/test_knowledge_e2e.py` — §9 integration fixtures.

**Modified:**

- `src/core/agents/triage.py` — fourth handoff target (tracked in spec 5).
- `src/core/pipeline.py` — provides tiny triage signals at turn start (tracked in spec 6).
- `hragent.spec` — bundles `knowledge.md` prompt (tracked in spec 8).

## 11. Acceptance

- Agent constructs with correct prompt + tool set (§3).
- All four entry points exercise correctly in integration fixtures.
- Skip + resume round-trip works.
- Gap-signal round-trip closes (analyst writes → knowledge resolves + deletes).
- Sub-run path persists writes under parent turn's `run_config`; single-turn UX preserved.
- Prompt loaded from disk; no hardcoded domain terms (grep check).
- Telemetry spans emitted with correct attributes (§8).
