# App Run Issues Fix Design

Status: design, ready for review
Purpose: fix 15 issues discovered in the 2026-05-12 app run (dist/harness/ logs, telemetry, chat history)

## Issue Inventory

Issues discovered from `dist/harness/logs/`, `dist/harness/telemetry/`, `dist/workspaces/w_0001/chats/chat_1c12bd35d929/messages.jsonl`, and `dist/workspaces/w_0001/artifacts/tmp/`:

| # | Issue | Evidence | Layer |
|---|-------|----------|-------|
| 1 | Runtime `finish_reason='unknown'` opaque, 4 occurrences | runtime.log lines 20-21, 26-27, 42-43 | L1 |
| 2 | `sales_customers.csv` created but not promoted from tmp | Worker rc=0, file at artifacts/tmp/run_.../step_1/sales_customers.csv, never visible to user | L3 |
| 3 | `/doctor` returned wrong output, no structured events | Runtime doctor stream 676ms/320tokens, harness.log empty, no DoctorFinding/DoctorReportReady events | L3 |
| 4 | `/compact` produced no observable output | No compaction events in any log, compaction_count=0, no compactions.jsonl | L3 |
| 5 | New column creation threw `ModuleNotFoundError: tabulate` | Worker rc=1, stderr.txt shows pandas.to_markdown() importing tabulate | L2 |
| 6 | `harness.log` empty (0 bytes) | No harness orchestration events logged | L3 |
| 7 | Missing `harness.events.jsonl` | Only app/runtime/worker/bootstrap telemetry exist | L3 |
| 8 | Plans lost across turns (in-memory cache cleared) | Plan created in turn e4b78002, gone by turn 0b346d5e | L3 |
| 9 | Second worker dispatch overwrote first run's artifact directory | Both used run_d1ef36.../step_1/, same sandbox_config.json | L3 |
| 10 | `tabulate` not in worker sandbox allowlist | allowed_packages misses pandas optional dependency | L2 |
| 11 | No workspace-level telemetry mirror | state/ directory has no telemetry/ subdir | L3 |
| 12 | No `compactions.jsonl` in chat dir | Chat dir only has metadata.json + messages.jsonl | L3 |
| 13 | No `memory/functions/` or `memory/notes/` | workspace memory/ only has empty preferences.json | L3 |
| 14 | Approval banner never appeared, user typed "approved" in chat | No ApprovalBanner shown, plan was already lost from cache | L3/L4 |
| 15 | Sandbox config not regenerated for second dispatch | Same config reused, stale allowed_reads | L3 |

## Root Cause Groups

### Group A: Harness Observability (#6, #7, #11)

Harness logger and telemetry writer never wired to file sinks. Workspace telemetry mirror never implemented.

**Fix:**
- Add `logging.getLogger("harness")` file handler → `dist/harness/logs/harness.log`
- Add `logging.getLogger("persistence")` file handler → `dist/harness/logs/persistence.log`
- Create `HarnessTelemetry` class, append to `dist/harness/telemetry/harness.events.jsonl`
- On workspace activation, create `workspace_dir/state/telemetry/`, tee harness events there

### Group B: Doctor (#3, #13)

Doctor currently only counts tmp files. Missing: drift detection, validity updates, knowledge extraction, script relevance, action proposals, report persistence, deletion/cleanup instructions, and `memory/` directory scaffolding.

**Fix — 8-phase pipeline with 3 run modes:**

Doctor exposes three modes via a `mode` parameter:

| Mode | Phases | Purpose |
|------|--------|---------|
| `light` | 1-3 + 7-8 (deterministic only) | File accounting, cleanup |
| `semantic` | 4-6 + 7-8 (LLM only) | Knowledge mining, script assessment, consistency |
| `full` | 1-8 (all) | Complete scan on demand |

Phase breakdown:

Deterministic phases:
1. Source rescan — fingerprint comparison against stored state, detect drift/missing/new
2. Artifact inventory — classify tmp artifacts: active-run, stale, orphaned, failed. Emit `DoctorActionProposed(action="delete", ...)` for eligible stale tmp items. Emit `DoctorActionProposed(action="keep_temporarily", ...)` for items with active references.
3. Pending plan pruning — read `state/pending_plans.jsonl`, tombstone resolved >7 days old, flag stuck plans >24h as warnings

LLM phases:
4. Chat knowledge mining — scan conversation history, extract user-taught facts/preferences/definitions, emit `DoctorFinding(type="knowledge_candidate")` per item. Also detect: references to source files that no longer exist → flag notes for deletion; gaps that are now resolved → flag for removal.
5. Script relevance assessment — read all `memory/functions/*.py`, flag obsolete (stale against current data), identify combinable pairs, extract reusable functions. Emit `DoctorActionProposed(action="archive_or_delete", ...)` for obsolete scripts.
6. Knowledge consistency check — cross-reference notes + preferences + functions, find contradictions/stale references/conflicting definitions. Emit `DoctorActionProposed(action="delete", ...)` for notes with dead references; emit `DoctorActionProposed(action="remove_preference", ...)` for preferences conflicting with stored knowledge.

Final deterministic phases:
7. Action compilation — aggregate all proposed actions (promote, delete, archive, keep, review, set_preference) per artifact/memory item. Classify each action by guard level (safe, requires_review, blocked). Apply save policy (auto-save or propose) based on trigger mode. Collect into `DoctorReport`.
8. Summary + report persistence — write to `state/doctor_reports/<timestamp>.json` AND append to `state/doctor_reports.jsonl`, emit `DoctorReportReady`

Doctor LLM budget: each LLM phase runs its own independent runtime stream, separate from conversation turns. Prompts are focused and small. Budget caps: Phase 4 (30% of prompt budget), Phase 5 (25%), Phase 6 (15%).

**Doctor automation triggers:**

| When | Mode | Save policy | Rationale |
|------|------|-------------|-----------|
| Startup / workspace activation | `light` (phases 1-3+7-8) | auto-save `safe` items, propose `requires_review` | Files accounted for, stale tmp cleaned, stuck plans flagged |
| After every worker execution | `semantic` (phases 4-6+7-8) | auto-save knowledge/preferences/notes; propose deletions and preference changes | New scripts, artifacts, conversation context. Chat grows each turn. |
| Explicit `/doctor` command | `full` (phases 1-8) | propose ALL items (nothing auto-saved) | User reviews, approves, or rejects every finding and action |

**Execution model:** All doctor runs execute as an async background task — never block the TUI. Findings stream to the doctor sidebar section as they arrive. Doctor runs concurrently with user interaction; the hard-serial constraint only applies to runtime usage (deterministic phases don't need the runtime). When a doctor LLM phase needs the runtime and a user turn is streaming, the doctor LLM call queues until the runtime is idle.

**Save behavior by item type:**

| Item type | Guard level | Post-worker (auto) | `/doctor` (propose) |
|-----------|-------------|---------------------|----------------------|
| Knowledge note (formula, metric, definition) | safe | Auto-save via KnowledgeManager | Propose |
| Behavioral preference (e.g. "show 2 rows") | requires_review | Propose (prefs change app behavior) | Propose |
| Tmp artifact deletion (stale, no refs) | safe | Auto-delete | Propose |
| Memory item deletion (note, function, gap) | requires_review | Propose | Propose |
| Function promotion (step.py → functions/) | safe | Auto-save | Propose |
| Obsolete function archival | requires_review | Propose | Propose |

**Knowledge echo dedup:** Each note saved by doctor records `source_turn_ids` in its metadata. On subsequent runs, Phase 4 skips chat segments whose turn IDs already have corresponding notes in `memory/`. No duplicate extraction.

**Proposal UI mechanism (for `/doctor` and `requires_review` items):**

When doctor runs in mode where items are proposed (not auto-saved), the TUI renders findings in the doctor sidebar section and, on `DoctorReportReady`, shows a batch approval banner:

```
┌─ Doctor Review (12 findings, 8 actions) ────────────────┐
│                                                          │
│  Findings:                                               │
│  ⚠ data/sales.csv fingerprint changed (drift)           │
│  ⚠ 3 tmp artifacts from stale run abc123                │
│                                                          │
│  Actions:                     [accept] [reject] [skip]   │
│  📝 Save note: avg_headcount = total / 6                │
│  ⚙ Set preference: preview_rows = 2                     │
│  🗑 Delete: tmp/run_old/step_1/* (3 files)              │
│  📦 Promote: step.py → memory/functions/                │
│  🗑 Delete: memory/notes/obsolete_ref.md                │
│                                                          │
│  [Accept All]  [Reject All]                              │
└──────────────────────────────────────────────────────────┘
```

Each action row has a checkbox. Keyboard shortcuts: `a` accept highlighted, `r` reject, `s` skip, `A` accept all. `enter` toggles checkbox. `escape` dismisses (unreviewed items stay pending). Applied actions update `doctor_reports.jsonl` with resolution status per item.

**Knowledge destinations** (via `KnowledgeManager` only, spec §7.17):
- User-taught formulas/metrics/definitions → `memory/notes/<name>.md`
- Unresolved/incomplete knowledge → `memory/notes/gaps/<name>.md`
- Behavioral preferences → `memory/preferences.json`
- Extracted/combined reusable functions → `memory/functions/<name>.py`
- Charts/tables/reports from successful runs → `artifacts/<name>.<ext>`

Doctor creates `memory/notes/`, `gaps/`, `functions/` directories on first run.

**Deletion and cleanup rules:**

Deletion guard levels applied to every `DoctorActionProposed`:
| Guard level | Condition | Behavior |
|---|---|---|
| `safe` | Tmp item with no active references (no active run, no pending review, no provenance link, no artifact registry entry) | Deletion proceeds automatically (no user approval needed) |
| `requires_review` | Memory item (note, function, preference, gap), or tmp item referenced by a stale/failed run that is >7 days old | Doctor proposes deletion, user must explicitly approve each item via TUI (same approval pattern as code execution) |
| `blocked` | Tmp item referenced by active run, pending review, failure envelope under investigation, provenance record, or artifact registry | Item cannot be deleted. Doctor emits `DoctorFinding(type="deletion_blocked", reason="...")` |

Deletion targets:
| What | When | Action type |
|---|---|---|
| Tmp artifacts from stale/failed runs (>7 days) | Phase 2 | `DoctorActionProposed(action="delete")` |
| Tmp scaffolding (symlinks, dirs) from completed runs | Phase 2 | `DoctorActionProposed(action="delete")` |
| Old doctor reports (>30 days) | Phase 2 | `DoctorActionProposed(action="delete")` |
| Notes referencing deleted/missing source files | Phase 4 (LLM detects) | `DoctorActionProposed(action="delete")` |
| Gaps that are now resolved (knowledge now exists) | Phase 4 (LLM detects) | `DoctorActionProposed(action="delete")` |
| Obsolete functions (stale against current data) | Phase 5 (LLM detects) | `DoctorActionProposed(action="archive_or_delete")` |
| Conflicting preferences (newer knowledge supersedes) | Phase 6 (LLM detects) | `DoctorActionProposed(action="remove_preference")` |
| Notes with dead/broken references | Phase 6 (LLM detects) | `DoctorActionProposed(action="delete")` |

All deletions are always via `KnowledgeManager`, never direct filesystem writes. Items pending deletion are flagged in the report with their guard level. User review of `requires_review` items uses the same approval flow as code execution — doctor emits `ApprovalRequired(reason="doctor_deletion", items=[...])` and the TUI renders an approval banner for each batch.

### Group C: Worker Sandbox (#5, #10)

Pandas `to_markdown()` imports `tabulate` but it's not in allowed packages.

**Fix:**
- Add `tabulate` to `ALLOWED_PACKAGES` in `src/worker/policy.py`
- Add `tabulate` to mirror in `src/worker/sandbox_bootstrap.py`
- Also add `openpyxl`, `xlrd` (common pandas optional deps for Excel I/O)
- Do NOT add visualization libs (matplotlib, seaborn) unless explicitly requested

### Group D: Plan Lifecycle + Artifact Promotion (#2, #8, #9, #14, #15)

Plans stored in `_pending_plans` dict are lost between turns. Approval banner wiring is broken. Artifacts stay in tmp. Same run_id reused across dispatches.

**Fix:**

**Plan persistence — append-only JSONL:**
- On plan creation, append line to `workspace_dir/state/pending_plans.jsonl`
- On orchestrator init, replay JSONL to rebuild `_pending_plans` dict
- On plan resolution (approved/rejected/cancelled/timed-out), append resolution line with status marker
- Doctor prunes old resolved entries (>7 days) by appending tombstone lines
- No upfront compaction needed — JSONL entries are ~1KB each, 1000 plans = 1MB

**Artifact promotion on success:**
After `resume_approved_step` succeeds, run `_promote_step_artifacts()`:
- `step.py` → `memory/functions/<run_id>_step.py`
- CSV/Excel/Parquet outputs → `artifacts/<name>.<ext>`
- Markdown/text reports → `artifacts/<name>.md`
- Update workspace.db artifact registry

**New run_id per dispatch:**
Generate fresh `run_id = uuid4()` per execution attempt, not per plan.

**Approval wiring fix:**
Trace `ApprovalRequired` event path from harness to TUI. Verify `ApprovalBanner` widget receives the event and calls `show(plan=..., step_contract=...)`. Fix any broken links in the handler chain in `app/tui/app.py`.

### Group E: Compact (#4, #12)

`/compact` produces zero events and zero output.

**Fix:**
1. Emit `ChatHistoryCompacted(status="queued")` immediately
2. Call `runtime.token_pressure()` — if <80%, skip: emit `ChatHistoryCompacted(status="skipped", reason="below_threshold")`
3. If run active: queue behind run, wait for idle state
4. Call LLM to summarize messages beyond the recent-8-turns window
5. Write compaction summary to `compactions.jsonl` in chat directory
6. Append `{"role": "compacted_summary", "text": "..."}` to `messages.jsonl`
7. Update `metadata.json`: `last_compacted_at`, `compaction_count++`
8. Update in-memory prompt history: replace old turns with compaction summary
9. Emit `ChatHistoryCompacted(status="completed", turns_compacted=N, token_savings=M)`

### Group F: Runtime Finish Reason (#1)

`finish_reason='unknown'` is opaque. Three distinct causes exist.

**Fix** in `LlamaCppRuntime._sync_event_iterator`:
- Split `unknown` into `empty_stream` (0 text, 0 tool calls), `parse_error` (tool-call JSON failed), `truncated` (hit max_completion_tokens)
- Include diagnostics payload per sub-reason (correlation_id, partial_content_snippet for parse_error)
- Layer 3 maps to harness warning with specific `warning_code`
- TUI can render "Model produced no output — retrying" instead of silence

### Knowledge Retrieval (new)

How agents access doctor-saved knowledge during conversations.

**Hybrid approach (Option C):**
- On each turn, Layer 3 context builder auto-injects top-N most relevant notes into the durable workspace context block (relevance by recency + keyword match against current user query)
- Register `recall_knowledge` as a harness tool-call the model can invoke: `<tool_call>{"name":"recall_knowledge","arguments":{"query":"average headcount formula"}}>` — harness searches `memory/` and returns matching note
- `recall_knowledge` searches: notes/*.md content, preferences.json keys, function docstrings
- Injected context respects the 30% durable context budget cap (spec §7.8)

## Layer Change Summary

| Layer | Tasks |
|-------|-------|
| L1 Runtime | `finish_reason` sub-reasons (`empty_stream`, `parse_error`, `truncated`) |
| L2 Worker | Add `tabulate`, `openpyxl`, `xlrd` to allowed packages |
| L3 Harness | Harness logging+telemetry, workspace telemetry mirror, doctor 8-phase pipeline, plan JSONL persistence, compact event flow, artifact promotion, new run_id per dispatch, `recall_knowledge` tool, KnowledgeManager-based doctor writes, hybrid context injection |
| L4 TUI | Fix ApprovalRequired→ApprovalBanner wiring, render compact/doctor events in conversation pane and sidebar |

## Implementation Order

1. Group A (Observability) — foundational, enables debugging of all other groups
2. Group F (Runtime finish reason) — enables L1 forensics for L3 work
3. Group C (Sandbox allowlist) — simplest, independent
4. Group D (Plan lifecycle) — core fix for broken approval/workflow
5. Group E (Compact) — depends on D (needs idle detection), depends on A (needs logging)
6. KnowledgeManager write support — add `write_note`, `write_function`, `set_preference`, `remove_preference`, `delete_note` methods needed by doctor
7. Group B (Doctor) — depends on A (logging), D (plan JSONL), and KnowledgeManager writes; uses mode parameter (light/semantic/full); runs async background
8. Knowledge retrieval (hybrid context injection + recall_knowledge tool) — depends on B (doctor must populate memory/ first)
9. Packaging verification — rebuild dist, re-run all acceptance paths

## Acceptance Criteria

- Harness events logged to `harness.log` and `harness.events.jsonl`
- Workspace telemetry mirrored to `workspace/state/telemetry/`
- `finish_reason` never shows `unknown` — always specific sub-reason
- `tabulate` available in worker sandbox, `df.to_markdown()` works
- Pending plans survive across chat turns and app restart
- Approval banner appears when `ApprovalRequired` is emitted
- Successful worker output promoted from tmp to `artifacts/`
- Each dispatch uses a new run_id, no directory overwrite
- `/doctor` runs full 8-phase pipeline, emits all structured events, persists report
- `/compact` compacts chat, writes `compactions.jsonl`, updates metadata
- `memory/notes/`, `memory/functions/`, and `memory/notes/gaps/` exist after doctor
- `recall_knowledge` tool callable by LLM, returns matching knowledge
- Top-N relevant knowledge auto-injected into durable context each turn
