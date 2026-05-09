# Spec 12 — Doctor agent

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3, 4, 5, 6, 7, 8, 9, 11
**Blocks:** none

> **Examples are illustrative.** Orphan scenarios, dedup clusters, rebuild prompts use generic placeholders. Doctor is domain-agnostic.

## 1. Purpose

Define the **doctor agent** — the fifth specialist triage hands off to. Maintains `memory/` integrity: drift resolution, orphan cleanup, function dedup, notes consolidation, index rebuilds. Never answers analytical questions. Never touches `data/`. Never silently deletes. Never sits on the first-answer hot path for a normal analysis turn. Collaborates with the knowledge agent via `call_knowledge` (spec 9 §5.12, spec 11 §4.4) for every semantic write — doctor owns *structural* operations only.

## 2. Scope

### In scope

- Agent construction (referenced from spec 4 §2.5).
- Three entry points (drift-triggered handoff, explicit user ask, passive background sweep).
- Behavior per maintenance class (stale / minimal / orphan / dedup / schema drift / notes consolidation / index rebuild).
- Collaboration matrix with knowledge agent.
- Guardrails (caller-auth, scan-first rule, never-assume rule, batched confirmation).
- `src/core/prompts/doctor.md` content.
- Agent-specific telemetry.
- Integration fixtures for doctor paths.

### Out of scope

- Knowledge-store layout + tool contracts — spec 9.
- Destructive tool implementations — spec 3 §5.3 (caller-auth enforcement lives in tool code).
- Knowledge agent behavior — spec 11.
- Triage signal computation — spec 5.
- Analyst behavior — spec 10.

## 3. Agent construction

```python
doctor_agent = Agent(
    name="doctor",
    instructions=_load_prompt("doctor.md"),
    model=custom_model_agent,     # shared compaction — sweeps can span many files
    tools=[
        # read
        list_files, inspect_file_schema, preview_file,
        read_text, search, file_digest,
        get_file_metadata, list_saved_functions,
        list_knowledge,
        # write (structural only)
        set_file_metadata, write_knowledge_note,
        save_python_function,                    # overwrite=True for merges
        # doctor-exclusive destructive (spec 3 §5.3 caller-auth)
        delete_saved_function, delete_knowledge_note,
        delete_file_metadata, rebuild_index,
        # collaboration (Option D sub-run, spec 9 §5.12, spec 11 §4.4)
        call_knowledge,
        # batched deletion confirmations
        user_input,
    ],
)
```

- `max_turns=12` per Pipeline `RunConfig` (spec 6 §8) — longer sweeps may touch many files.
- No `run_saved_function` — not analysis; not maintenance.
- No direct writes to `memory/files/*.json` semantic fields, `memory/notes/*.md` bodies — those route through `call_knowledge`.

## 4. Entry points

### 4.1 Triage signal `drift_detected` (spec 5 §4)

Pipeline pre-triage helper detects *any* of: `intake_status="stale"`, `intake_status="minimal"`, orphan metadata (path missing from `data/`), orphan note (`source_files` missing from `data/`), orphan function (references file no longer in `data/` or a column missing from current schema — validated on demand), corrupted or missing `functions/index.json` / `notes/index.json`. Any drift triggers the signal; no threshold.

Triage hands off to doctor **only** on user acknowledgment of a drift `StatusUpdate` or on explicit maintenance intent (§4.2). Drift alone never triggers silently.

Normal analytical questions continue to route to analyst even when drift exists. Doctor backlog is surfaced, not auto-invoked.

### 4.2 Explicit user ask

Phrases that route to doctor: "clean up memory", "tidy up", "fix the knowledge store", "dedupe functions", "rebuild the index", "yes doctor", "ok clean it up". Triage heuristic recognizes these (spec 5 §5).

### 4.3 Background sweep (passive)

On workspace open and after N turns (configurable; spec 6 §5 default 20), Pipeline emits `StatusUpdate(text="memory/ has <N> drift items — say \`clean up\` to address", level="warn")`. No auto-invoke. User remains in control. This is the only way drift becomes visible without an explicit ask.

## 5. Behavior

### 5.1 Scan-first rule

Every doctor turn **begins** with `list_knowledge(verbosity="detail")`. Enumerate drift by class (stale / minimal / orphan / index missing). Summarize the backlog to the user *before* doing anything. Plan first, act second.

### 5.2 Never-assume rule

If `functions/index.json` or `notes/index.json` is missing or corrupted, do **not** assume the user hasn't started intake. Missing index could mean: intake not yet begun / paused / complete but index deleted externally / crash mid-write. Call:

```
call_knowledge(task="status", context="checking whether intake has begun / is paused / is complete for workspace <name>")
```

Knowledge agent reports its state by reading `files/*.json` itself. Doctor rebuilds the index only after knowledge confirms the store is in a stable terminal state. Prevents doctor from clobbering a knowledge turn in flight or wiping a user's paused session.

Same rule for any ambiguous intake/drift state: consult knowledge first.

### 5.3 Resolution per drift class

| Class | Condition | Doctor action | Knowledge delegation |
|---|---|---|---|
| Stale, schema unchanged | `source_digest` mismatch; `inspect_file_schema` identical to captured | restamp `source_digest` + `intake_status="complete"` + `last_checked_at` atomically | — |
| Stale, schema changed | `source_digest` mismatch; columns added / removed / dtype flipped | — | `call_knowledge("re-intake <file>", "<schema diff + existing claims>")` — knowledge decides what carries over |
| Minimal intake | `intake_status="minimal"` | — | `call_knowledge("resume intake for <file>", "<structural schema>")` — knowledge runs its normal intake flow |
| Orphan metadata | `memory/files/<path>.json` exists; `data/<path>` missing | batch into `user_input` prompt listing all orphans + reasons → on y → `delete_file_metadata(<path>)`; clean backlinks from `notes_refs` | — |
| Orphan note | `notes/index.json` entry points to non-existent `.md` OR `source_files` all missing from `data/` | batched `user_input` → on y → `delete_knowledge_note(<path>)` | — |
| Orphan function | `.py` references column missing from current schema (validated on demand via `inspect_file_schema`) | batched `user_input` with broken list; on "rewrite" → delegate; on "delete" → `delete_saved_function` | `call_knowledge("rewrite <fn> against current schema", "<current schema + old body>")` |
| Saved function marked stale / schema_mismatch | `functions/index.json` preflight status is not `valid` | batch stale functions into a maintenance summary; on "rewrite" → delegate; on "delete" → `delete_saved_function`; on "keep" → leave quarantined | `call_knowledge("refresh <fn> for current file/schema", "<current schema + old body>")` |
| Duplicate functions | two `.py` files with near-identical `run(...)` body + signature | keep higher `last_used_at`; `delete_saved_function(<loser>)`; for overlap-but-not-identical, batched `user_input` asks which to keep — never merge silently | — |
| Notes consolidation | two notes same `source_files`, overlapping `keywords`, each short | batched `user_input` proposes merge; on y → knowledge writes merged note; delete originals | `call_knowledge("write merged note consolidating <a>+<b>", "<both bodies>")` |
| Index rebuild | `functions/index.json` / `notes/index.json` missing or fails schema | only after §5.2 never-assume check passes → `rebuild_index(kind)` | — |

### 5.4 End-of-turn summary

Final message lists every action taken: what merged, what deleted, what rebuilt, what deferred, what user deferred on. User-readable one-paragraph summary.

## 6. Collaboration with knowledge agent

Doctor owns structural ops (delete, restamp, rebuild). Knowledge owns semantic writes (column meanings, metric definitions, note bodies, merged-note curation). All semantic writes route through `call_knowledge`:

- Same sub-run pattern as analyst (spec 9 §5.12).
- Caller = `doctor` (allow-listed).
- `sub_run_depth` context var blocks recursion (max depth = 1).
- Child session ephemeral. Child streams proxy to doctor's stream — user sees inline narration.

Doctor never calls `call_knowledge` recursively. A single doctor turn produces at most depth-1 sub-runs, but may produce many of them sequentially (one per drift item requiring semantic write).

## 7. Guardrails

- **Caller-auth.** `delete_saved_function`, `delete_knowledge_note`, `delete_file_metadata`, `rebuild_index` check the `agent_name` context var and return `status="error"`, `reason="not_authorized"` if caller is not `doctor`. Enforcement in tool code (spec 3 §5.3); prompt-side protection is defense in depth, not primary.
- **Batched confirmation.** Every destructive op preceded by `user_input`. Bulk deletes use one prompt with numbered list + reasons; user answers subset or blanket y/n.
- **No writes to `data/`.** Enforced at sandbox mount (spec 8 §5). Doctor prompt must not attempt.
- **No `run_saved_function`.** Not in tool set.
- **Not in the answer path.** Doctor never interrupts a normal analysis turn. Its work happens only on explicit maintenance turns.
- **No mid-turn handoff back to triage.** Doctor either completes the sweep or reports what it deferred; never abandons mid-turn.
- **No assumptions about state.** Covered by §5.2. All ambiguity → `call_knowledge("status", …)` first.

## 8. Prompt (`src/core/prompts/doctor.md`)

Short, behavior-focused. Constraints:

- State the agent's job in one sentence: "You maintain the knowledge store's integrity — dedup, orphan cleanup, index rebuilds, drift resolution. You never answer analytical questions."
- **Scan-first rule** as first operating instruction.
- **Never-assume rule** with the missing-index example explicit.
- Resolution table (§5.3) compressed to one-line-per-class guidance.
- Batched confirmation rule with a sample `user_input` format for bulk delete.
- End-of-turn summary rule.
- Boundary rule: no writes to `data/`; no semantic writes (delegate via `call_knowledge`); no running saved functions.

No hardcoded domain terms. No framework internals. No example data values.

## 9. Telemetry

- `agent.doctor` span attributes: `trigger=<drift|explicit|background>`, `drift_detected` (object: `stale`, `minimal`, `orphan_metadata`, `orphan_notes`, `orphan_functions`, `index_missing` — int counts), `functions_merged`, `functions_deleted`, `notes_consolidated`, `notes_deleted`, `metadata_deleted`, `indexes_rebuilt` (list of kinds), `call_knowledge_invocations`, `user_input_confirmations`, `wall_time_ms`.
- `tool.delete_saved_function` / `tool.delete_knowledge_note` / `tool.delete_file_metadata` / `tool.rebuild_index` span attributes: `caller`, `authorized` (bool), `target_path`, `atomic_success`. Span status = error + `reason="not_authorized"` on caller mismatch.
- `tool.call_knowledge` span carries `caller="doctor"` (vs `data_analyst` for analyst-initiated). Depth guard: `sub_run_depth_at_entry`.

## 10. Testing

**Unit:**

- Agent constructs with declared tool set.
- Prompt loads.
- Scan-first invariant: mocked turn always calls `list_knowledge(verbosity="detail")` as first tool call.
- Caller-auth matrix: simulate conversational / analyst / clarification / knowledge calling a destructive tool → all get `reason="not_authorized"`.
- Recursion guard: doctor→`call_knowledge`→ (child tries `call_knowledge`) → error.

**Integration (stub LLM, temp workspace):**

- `doctor-stale-rescan` — file on disk edited → next read-path tool stamps `intake_status="stale"` → "clean up" → doctor restamps on unchanged schema path.
- `doctor-stale-function` — saved function preflight marks `validation_status="stale"` → normal analysis turn still routes to analyst fallback → later "clean up" routes to doctor, which proposes refresh/delete without blocking the earlier answer.
- `doctor-stale-schema-change` — add new column to file → "clean up" → doctor detects delta → `call_knowledge("re-intake …")` → knowledge asks user about new column.
- `doctor-minimal-resume` — workspace has `intake_status="minimal"` → "finish onboarding" → triage drift signal → doctor `call_knowledge("resume intake …")`.
- `doctor-orphan-metadata` — external delete of `data/<f>.csv`; `memory/files/<f>.csv.json` remains → "clean up" → batched `user_input` → on y → `delete_file_metadata`.
- `doctor-dedup-functions` — two near-identical `.py` → "tidy up functions" → batched `user_input` asks which to keep → loser removed.
- `doctor-function-schema-drift` — saved fn references removed column → batched `user_input` → on "rewrite" → `call_knowledge` rewrites; on "delete" → `delete_saved_function`.
- `doctor-notes-consolidate` — two short notes, same `source_files`, overlapping `keywords` → "clean up" → merge proposal → knowledge writes merged → originals deleted.
- `doctor-rebuild-index-missing` — external delete of `notes/index.json` → "rebuild the notes index" → doctor `call_knowledge("status", …)` → knowledge reports stable → `rebuild_index("notes")`.
- `doctor-no-assumption-missing-index` — delete `functions/index.json` during an intake turn → "rebuild" → `call_knowledge` reports intake in flight → doctor defers; no destructive action.
- `doctor-auth-guard` — conversational agent attempts `delete_knowledge_note` → `status="error"`, `reason="not_authorized"`; no file mutated.
- `doctor-background-sweep` — 20 turns elapse with drift outstanding → Pipeline emits `StatusUpdate` warn line; no auto-handoff.

**End-to-end real-model:** `@pytest.mark.integration`, `HRAGENT_TEST_MODEL_PATH`, budgets in `tests/integration/budgets.json`.

## 11. Files

**New:**

- `src/core/agents/doctor.py` — agent builder.
- `src/core/prompts/doctor.md` — prompt.
- `tests/core/agents/test_doctor.py` — unit tests (scan-first invariant, caller-auth matrix, recursion guard).
- `tests/integration/test_doctor_e2e.py` — §10 integration fixtures.

**Modified:**

- `src/core/agents/triage.py` — fifth handoff target (tracked in spec 5).
- `src/core/tools/knowledge.py` — four destructive tools + caller-auth (tracked in spec 3 + spec 9 §5.13–§5.16).
- `src/core/pipeline.py` — `drift_detected` signal + background sweep `StatusUpdate` (tracked in spec 6).
- `hragent.spec` — bundles `doctor.md` prompt (tracked in spec 8).
- `tests/core/tools/test_knowledge.py` — caller-auth matrix on destructive tools (tracked in spec 9).

## 12. Acceptance

- Agent constructs with correct prompt + tool set (§3).
- Scan-first invariant holds in all integration fixtures (`list_knowledge(verbosity="detail")` is the first tool call on every turn).
- Never-assume invariant holds: every missing-index scenario consults knowledge via `call_knowledge("status", …)` before rebuilding.
- Every destructive op preceded by `user_input` confirmation; batch format verified in dedup + orphan fixtures.
- Caller-auth rejects non-doctor callers on all four destructive tools (unit + `doctor-auth-guard` integration).
- Drift alone never triggers handoff — `doctor-background-sweep` fixture confirms.
- All collaboration paths (stale-schema-change, minimal-resume, function-schema-drift, notes-consolidate) route through `call_knowledge`, not direct semantic writes.
- Telemetry spans emitted with correct attributes (§9).
- Prompt loaded from disk; no hardcoded domain terms.
