# Spec 5 — Triage agent + handoff routing

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3, 4
**Blocks:** specs 6, 7, 8

## 1. Purpose

Replace the current `Pipeline._select_route` + heuristics (`fast_direct`, `no_data_fast_direct`, `single_agent`, `grounded_fallback`, `fallback_direct`, `overflow_fallback`) with a single triage agent that uses Agents SDK handoffs.

**Primary success criterion: user-perceived latency.** Triage exists to cut wait time. A correctly-routed turn that streams its first token within ~1 s beats a silent specialist that takes 10 s to show the same answer. Two levers:

1. **Effective + efficient routing.** Pick the right specialist on the first try (no second triage pass, no "fallback" re-routing). Wrong picks compound latency.
2. **Hold the line verbally.** Triage is encouraged to emit a short status line *before* the handoff tool_call (e.g., "Looking at your files…"), so the user sees something happening while the specialist spins up. Verbosity is a feature here, not a bug.

## 2. Scope

### In scope

- `triage_agent` construction: prompt, model, handoff targets.
- Handoff definitions pointing at `conversational_agent`, `data_analyst_agent`, `clarification_agent`, `knowledge_agent`, `doctor_agent`.
- Pre-triage data-availability check: a small helper (non-LLM) that signals to the triage prompt whether any analysis-ready files exist in the active workspace.
- Pre-triage new-files signal (spec 9 §6): a helper that detects whether any data files are not yet captured into the knowledge store (no matching `memory/files/<name>.json`).
- Pre-triage definitional-content heuristic (spec 9 §6): lightweight prompt-side heuristic — triage detects whether the current user turn teaches a definition (formula / column meaning / mapping / policy) versus asks a question. No Python classifier; the signal is surfaced as a flag in the triage prompt so the LLM decides.
- Pre-triage gaps-open signal (spec 9 §6): a helper that detects whether any open gap topics exist (one per `memory/notes/gaps/*.md`). Triage gets only the boolean presence signal; the detailed topic list stays behind `list_knowledge` and knowledge-store helpers.
- Pre-triage drift-detected signal (spec 12 §4, spec 9 §6): a helper that reads the `drift` block from `list_knowledge(verbosity="manifest")` and summarizes what's drifted (stale / minimal / orphan / missing index). Triage receives only a boolean `drift_present`; counts and paths stay out of the hot path. Triage routes to doctor only on user acknowledgment or explicit "clean up" intent — never silently.
- Grounding heuristic: folded into the triage prompt. No Python classifier.
- Pre-handoff status ack: triage emits a brief text message (streamed live) before its handoff tool_call, so the UI shows activity during specialist spin-up.
- Deletion of `Pipeline._select_route` logic and its supporting heuristic functions.

### Out of scope

- Fallback agents (not included per user decision A).
- Follow-up tracking (`is that all?` routing). See §6.

## 3. Triage agent

```python
triage_agent = Agent(
    name="triage",
    instructions=_load_prompt("triage.md"),
    model=custom_model_direct,
    handoffs=[
        handoff(conversational_agent),
        handoff(data_analyst_agent),
        handoff(clarification_agent),
        handoff(knowledge_agent),   # spec 11
        handoff(doctor_agent),      # spec 12
    ],
    tools=[],
)
```

## 4. Data-availability + new-files signal

Before each `Runner.run`, Pipeline computes internal helper outputs:

```python
has_data         = workspace_manager.has_usable_data()
new_files        = knowledge_store.list_new_files(active_workspace)   # spec 9 §6
gaps_open        = knowledge_store.list_gaps(active_workspace)        # spec 9 §6
drift_detected   = knowledge_store.summarize_drift(active_workspace)  # spec 12 §4, spec 9 §5.11 drift block
```

`summarize_drift` returns a compact dict: `{stale: int, minimal: int, orphan_metadata: int, orphan_notes: int, orphan_functions: int, index_missing: list[str]}`. These helper outputs are for Pipeline/knowledge-store logic only. The triage prefix reduces them to booleans:

```python
new_files_present = bool(new_files)
gaps_open_present = bool(gaps_open)
drift_present     = bool(
    drift_detected["stale"]
    or drift_detected["minimal"]
    or drift_detected["orphan_metadata"]
    or drift_detected["orphan_notes"]
    or drift_detected["orphan_functions"]
    or drift_detected["index_missing"]
)
```

No counts, file paths, topic lists, manifest excerpts, saved-function listings, or preferences are injected into triage. Counts may be emitted to telemetry or used by background-sweep messaging, but **never** passed through the triage prompt.

These are injected into the triage input as a system-prefix note:

```
[context] workspace "<name>" has_data=<true|false> new_files_present=<true|false> gaps_open_present=<true|false> drift_present=<true|false>
```

This is deliberately tiny. Triage does **not** receive the knowledge manifest, saved-function lists, note summaries, gap topic lists, drift counts, or user preferences. Its job is routing speed, not retrieval.

Triage prompt uses the signals:

- `has_data=false` + data question → hand off to conversational with instructions to explain that a dataset is needed (preserves the current `no_data_fast_direct` UX).
- `new_files_present=true` + user turn is a pure onboarding / pure teaching / pure "I added a file" turn → hand off to `knowledge` (spec 11).
- `new_files_present=true` + user turn contains a concrete analytical ask about the newly added file → hand off to `data_analyst`. Intake is not a prerequisite for the first answer.
- User turn teaches a definition (formula / column meaning / mapping / policy) rather than asking a question → hand off to `knowledge` (spec 9 §6 `definitional_content` signal; behavior in spec 11 §4.2).
- `gaps_open_present=true` AND user turn looks like a follow-up that can resolve deferred missing knowledge → hand off to `knowledge` for gap resolution (spec 11 §4.3).
- `drift_present=true` AND user turn is explicit maintenance intent ("clean up", "tidy up", "dedupe", "rebuild the index", "fix memory", "yes doctor") → hand off to `doctor` (spec 12). Drift alone **never** triggers handoff — doctor runs only on explicit or confirming user intent. If drift is present but the user asked a normal analytical question, ignore drift for routing purposes (normal handoff rules win; doctor backlog surfaces via background-sweep `StatusUpdate` per spec 12 §4.3).
- Otherwise → conversational / data_analyst / clarification per the usual rules.

## 5. Prompt shape

`triage.md` (authored in spec 4) tells the triage agent:

- Never answer the substantive question directly.
- **Before** emitting the handoff tool_call, emit one short status line (≤ 12 words) that names the action in progress. Examples:
  - "Reading your files…"
  - "Computing that for you…"
  - "One quick clarification first…"
  - "Just chatting for this one…"
  - "Capturing that…"
- Classify into one of: conversational, data_analyst, clarification, knowledge, doctor.
- Use `has_data` context to avoid handing off to the analyst when no data exists.
- Treat triage context as routing signals only. Do not expect a knowledge manifest, note summaries, saved-function listings, or preferences to be present here.
- If the user's intent is ambiguous or depends on an earlier unclear reference, hand off to clarification.
- If the user is teaching a definition (formula / column meaning / mapping / business rule) rather than asking a question, hand off to knowledge.
- If the user has just added a file **and** is already asking an analytical question about it, hand off to analyst rather than forcing intake first.
- If `gaps_open` lists an open gap topic that matches the user's current turn (they're re-asking something the analyst previously flagged as blocked), hand off to knowledge for gap resolution.
- If the user explicitly asks to maintain memory ("clean up", "tidy up", "dedupe functions", "rebuild the index", "fix memory", or an affirmative reply to a prior drift `StatusUpdate` like "yes doctor" / "ok clean it up"), hand off to doctor. Never route to doctor on drift alone — the user must ask or confirm.
- Be decisive: commit to one handoff target per turn. Do not reclassify mid-turn.

The ack message streams via the spec 1 §8 contract (`TokenDelta` with `output_type="message"`). The specialist's final answer replaces or extends it — the ack is not a "loading spinner" the UI hides later; it becomes part of the transcript.

## 6. Follow-up handling

Current pipeline tracks small follow-up markers ("is that all?", "show all", "are you sure?") to keep grounded turns in analyst mode. Under Agents SDK, the `SQLiteSession` retains the previous turn's assistant message and tool outputs, so the triage model can recognize the follow-up from context. Accepted simplification: no separate follow-up flag in Python.

## 7. Telemetry

- Triage agent span: `agent.name="triage"`, `agent.handoff_to=<chosen_target>`, `agent.has_data_signal=<bool>`, `agent.drift_present=<bool>`, `agent.user_maintenance_intent=<bool>` (prompt-reported flag to attribute doctor routes correctly).
- Triage latency fields: `agent.triage_first_token_ms` (request receipt → first streamed token of ack), `agent.triage_handoff_ms` (request receipt → handoff tool_call emitted). Both feed the speed-of-routing success criterion in §1.
- Turn-level span includes the chosen specialist (derived from the first handoff).

## 8. Testing

**Integration (recorded LLM responses or stub Model for determinism):**
- "hello" with `has_data=true` → handoff to conversational.
- "hello" with `has_data=false` → handoff to conversational.
- "show my files" with `has_data=true` → handoff to data_analyst.
- "show my files" with `has_data=false` → handoff to conversational with explanation.
- "what do you mean by that" mid-chat → handoff to clarification.
- Follow-up after an analyst turn (e.g., "is that all?") routes back to analyst via session context.
- Open gap exists in `memory/notes/gaps/<topic>.md`; user re-asks a question matching that topic → handoff to knowledge (not analyst). Without this rule, analyst would re-flag the same gap, producing an infinite loop.
- New file exists and user asks an immediate concrete analytical question about it → handoff to analyst, not knowledge.
- `drift=stale=2, minimal=1` in context AND user says "clean up" → handoff to doctor.
- `drift=stale=2` in context AND user asks an analytical question ("what's the average salary") → handoff to data_analyst, NOT doctor. Drift alone must not hijack routing.
- No drift, user says "clean up" → triage may still route to doctor (doctor handles no-op: reports nothing to clean).
- **Ack-before-handoff:** stream contains ≥ 1 `TokenDelta` with `output_type="message"` *before* the handoff tool_call event. No silent triage.
- **Single handoff per turn:** stream contains exactly one handoff event; no back-and-forth between triage and specialists.

Stub Model approach: in tests, `LlamaCppAgentsModel` is swapped for a recorded-transcript model that returns deterministic handoff tool_calls.

**Real-model (pytest marker `@pytest.mark.integration`, real GGUF via `HRAGENT_TEST_MODEL_PATH`):**
- `agent.triage_first_token_ms` budget: warn > 1000 ms, hard-fail > 2000 ms on the reference dev machine (tier baseline in `tests/integration/budgets.json`).
- `agent.triage_handoff_ms` budget: warn > 2500 ms, hard-fail > 5000 ms. Covers model warm-up + ack + handoff decoding.
- Routing accuracy on the canonical fixture set (spec 6 §10): ≥ 4/5 correct routes per run across `greet`, `list-files`, `column-stats`, `clarification`, `no-data`.

## 9. Files

**New:**
- `src/core/agents/triage.py` — constructs `triage_agent`, exposes a builder function that accepts the three specialist agents and returns the triage agent.
- `tests/core/agents/test_triage.py`

**Retired:**
- `Pipeline._select_route` and every helper it calls (inside the current `pipeline.py` which is deleted by spec 6).

**Tests retired:** none in this spec. Route-selection tests live in `tests/core/agents/test_pipeline.py`, which spec 6 deletes; the replacement `tests/core/test_pipeline.py` verifies triage handoffs end-to-end.

## 10. Acceptance

- Triage agent constructs with exactly five handoffs (conversational, data_analyst, clarification, knowledge, doctor).
- Prompt injection carries `has_data` correctly.
- Integration routing tests green.
- No Python-side route heuristic remains.
