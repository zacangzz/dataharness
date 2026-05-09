# M1 M2 M3 M5 Compatibility-Bridge Fix Design

**Date:** 2026-04-20

**Status:** Draft for user review

**Scope:** Resolve `M1`, `M2`, `M3`, and `M5` from [Issues.md](/Users/zacang/Documents/datascience/hragent/Issues.md) with a low-regression-risk design that prioritizes stable interfaces, explicit tests, and staged tightening over broad refactors.

## Goal

Bring the process log, tool contract surface, model streaming contract, and clarification boundary back into alignment with specs 1, 3, and 7 without introducing a wide rewrite. The fix should be strong enough to close the known contract gaps and detailed enough to prevent the same drift from reappearing in adjacent code paths.

## Non-goals

- No unrelated UI redesign.
- No broad cleanup of other medium or low issues.
- No migration of unrelated agents or packaging behavior.
- No git workflow assumptions; this design does not require commits.

## Problem Summary

The four target issues are coupled by one shared weakness: activity contracts are not normalized early enough and are not rendered or consumed through a single stable boundary.

- `M1`: the UI process log reuses one block per agent across the whole chat, expands too early, duplicates tool-call rows, and appends tool output without structural linkage.
- `M2`: workspace file tools drift from the spec-defined argument and response shapes, do not consistently enforce truncation or scope envelopes, and omit tool telemetry. `KnowledgeStore.search(...)` also ignores `path_glob` and `regex`.
- `M3`: the model wrapper does not fully satisfy the streaming and telemetry contract, and the pipeline maps tool lifecycle events later than intended.
- `M5`: clarification flow still relies on UI polling of private bus internals and the cancellation behavior is not deterministic enough for the current tests.

## Recommended Approach

### Option A: Spec-first hard cut

Rewrite the process log, tool surfaces, model wrapper, pipeline event mapping, and clarification flow in one coordinated pass with minimal compatibility behavior.

**Pros:** fastest direct spec alignment.

**Cons:** highest regression risk, largest review surface, harder to isolate failures.

### Option B: Compatibility bridge

Repair the missing contracts behind shared helpers and normalized event boundaries first, then tighten behavior after targeted tests prove the path is safe.

**Pros:** lowest regression risk, easier verification, cleaner rollback points, best fit for a strong and detailed fix.

**Cons:** slightly more code during transition because compatibility seams remain until the final tightening step.

### Option C: Test-harness first

Build broad integration coverage before fixing implementation.

**Pros:** strongest long-term confidence.

**Cons:** too much delay before closing the known defects; not justified for the current scope.

### Recommendation

Use **Option B: compatibility bridge**.

This path gives one normalized event spine for `M1`, `M3`, and `M5`, while isolating `M2` behind tool helpers and targeted tests. It minimizes behavioral churn and keeps each slice verifiable on its own.

## Architecture

The design is organized as four workstreams that share one compatibility seam.

### Workstream A: Event contract spine

The model wrapper and pipeline become the authoritative source for agent activity timing and identity. The UI must only consume normalized `PipelineEvent` objects, never infer lifecycle state from transcript heuristics or private queues.

Key design points:

- Preserve the existing `PipelineEvent` vocabulary where practical, but enrich payloads so events carry enough identity to support per-turn rendering and tool lifecycle updates.
- Normalize correlation fields at the pipeline layer:
  - `turn_id`
  - `agent`
  - `tool_call_id`
  - tool name and completed args where applicable
- Prefer early tool lifecycle mapping:
  - emit `ToolCallStart` as soon as the model wrapper has a valid tool name
  - emit `ToolCallComplete` when the full validated arguments payload is available
  - keep `ToolOutput` separate and correlated by `tool_call_id`
- Keep status bar text pipeline-driven rather than UI-derived so telemetry and UI stay aligned.

This spine is the prerequisite for the UI fixes because the current `M1` problems are partly caused by weak event timing and correlation from `M3`.

### Workstream B: Process log and clarification UI

`ProcessLog` should render one collapsible block per `(turn_id, agent)` for the active turn and treat tool rows as stateful entries rather than append-only strings.

Key design points:

- Replace block storage keyed only by `agent` with storage keyed by `(turn_id, agent)`.
- Default block state remains collapsed.
- `AgentStarted` creates a block but does not auto-expand it.
- `ToolCallStart` creates a pending row such as `-> tool_name(...)`.
- `ToolCallComplete` updates the matching pending row in place to include arguments.
- `ToolOutput` appends beneath the matching tool row using the shared `tool_call_id`.
- `AgentFinished` appends a final status row and leaves collapse behavior explicit rather than implicit.

Clarification flow boundary:

- UI must stop reading `clarification_bus._questions` directly.
- `ClarificationBus` needs a public consumer boundary, either:
  - a `drain_question()` / `get_nowait()` style method, or
  - a dedicated async queue accessor that hides storage details.
- Workspace switch and shutdown continue to call `cancel_all()`, but cancellation semantics must be observable and deterministic by the time tests assert on futures.

### Workstream C: Tool contract repair

`src/core/tools/workspace_files.py` should use one shared response-path helper so the spec contract is enforced centrally rather than reimplemented per tool.

Key design points:

- Introduce one envelope builder for:
  - `status="ok"`
  - `status="error"`
  - `reason="path_out_of_scope"` when applicable
  - truncation metadata when output is capped
- Apply `_cap_output(...)` or its replacement at a single exit point so truncation cannot be forgotten.
- Align `inspect_file_schema(path)` with the spec:
  - return `columns_schema`
  - keep shape/path fields explicit
- Align `column_stats(path, column)` with the spec:
  - primary contract takes both `path` and `column`
  - if low-risk compatibility requires transition handling, keep it internal and temporary rather than exposing two public shapes forever
- Emit tool telemetry from shared helpers so every tool invocation records:
  - tool name
  - status
  - output chars
  - truncation flag / metadata
  - turn and run context when available

Knowledge-store repair in scope for `M2`:

- `search(query, path_glob="**/*", regex=False, max_matches=50)` must honor both `path_glob` and `regex`
- keep search scoping rooted to the workspace memory tree
- return the same stable envelope style used elsewhere

### Workstream D: Model streaming and telemetry

`LlamaCppAgentsModel` should remain the single LLM entry point but fill the missing streaming and telemetry contract from spec 1.

Key design points:

- Malformed tool-call JSON gets one constrained retry.
- Second failure becomes a model-behavior error rather than silent fallback.
- Assistant text and reasoning text become distinct stream surfaces.
- Track per-call telemetry fields required by spec:
  - input message count
  - input chars
  - input token estimate
  - output chars
  - output chunk count
  - effective max token budget
  - compaction flags
- Pipeline should prefer earlier raw function-call add/done signals over the later `RunItemStreamEvent("tool_called")` path for start/complete mapping.

This keeps tool lifecycle render timing compliant without forcing the UI to infer state from partial model text.

## Data Flow

The intended runtime flow after the fix is:

1. Model wrapper builds messages and starts a streamed run.
2. As soon as a tool name is decoded, the wrapper exposes an early tool-start signal.
3. Pipeline converts raw model/runner signals into normalized `PipelineEvent`s with correlation fields.
4. UI updates the process log and status bar only from those normalized events.
5. Tool execution returns output, pipeline emits `ToolOutput`, and the process log attaches it to the matching row.
6. If a tool requests user clarification, the tool awaits a `ClarificationBus` future while the UI consumes a public question payload and later resolves it.
7. Workspace switch or shutdown cancels the pending clarification future through the public bus contract.

## Error Handling

### Model wrapper

- Retry malformed tool-call JSON once with a constrained correction instruction.
- On second malformed output, raise an explicit behavior error and record telemetry.
- Do not leak raw tool-call markup into visible assistant text when parsing fails.

### Pipeline and UI

- If a `ToolCallComplete` or `ToolOutput` arrives with an unknown `tool_call_id`, append a bounded fallback row and emit a telemetry warning instead of crashing.
- If clarification is cancelled during workspace switch, propagate cancellation cleanly so the awaiting tool exits without stale UI state.
- Status updates remain best-effort and must never be allowed to block final message delivery.

### Tools

- All scope violations return a spec-shaped error envelope rather than ad hoc strings.
- Truncation must be explicit in payload metadata, not silently implied by shortened strings.
- Search regex errors must return structured error envelopes rather than uncaught exceptions.

## Testing Strategy

Testing leads implementation. Each defect gets a narrow regression test before behavior is tightened.

### `M1` process log tests

- one block per agent per turn
- default collapsed block state
- no auto-expand on `AgentStarted`
- `ToolCallStart` creates one pending row
- `ToolCallComplete` updates the same row instead of appending a second row
- `ToolOutput` is attached beneath the matching tool row
- handoff and finish rows render in the correct block

### `M2` tool contract tests

- `inspect_file_schema` returns `columns_schema`
- `column_stats(path, column)` accepts the spec surface and returns the expected numeric/non-numeric fields
- scope violation returns structured `path_out_of_scope`
- truncation contract is enforced on real oversized payloads
- tool telemetry is emitted
- `search(...)` respects `path_glob`
- `search(...)` respects `regex=True`
- invalid regex returns structured error

### `M3` model wrapper and pipeline tests

- malformed tool-call output retries once, then fails deterministically
- reasoning deltas are surfaced separately from assistant message text
- early raw function-call add/done events become `ToolCallStart` / `ToolCallComplete`
- telemetry includes the missing required fields
- visible assistant text never includes raw tool-call protocol markup

### `M5` clarification tests

- UI no longer accesses `clarification_bus._questions`
- question consumption happens through a public bus boundary
- `cancel_all()` leaves test futures cancelled by the time assertions run
- workspace switch clears pending clarification state and prevents stale answers from re-entering a new turn

### Cross-cutting verification

- run focused `pytest` targets first for touched modules
- then run the broader suite that currently covers pipeline, tools, engine, and Textual UI
- add focused regression tests instead of waiting for missing full end-to-end harnesses

## Implementation Sequencing

The fix sequence is intentionally ordered to reduce blast radius.

### Phase 1: Add failing regression tests

- lock down current defects in unit and contract tests
- avoid changing implementation until each target behavior is pinned

### Phase 2: Repair the event contract spine

- enrich model wrapper and pipeline event mapping first
- establish reliable `tool_call_id`, event timing, and telemetry fields

### Phase 3: Update process log and clarification UI

- move `ProcessLog` to per-turn/per-agent storage
- replace private clarification queue access with a public bus contract
- harden workspace-switch cancellation behavior

### Phase 4: Repair tool contracts

- centralize response envelopes
- align `workspace_files` and `KnowledgeStore.search(...)`
- apply truncation and telemetry consistently

### Phase 5: Tighten and remove temporary compatibility branches

- remove any temporary fallback paths only if all tests and direct callers are already moved
- retain harmless shims if removing them would increase regression risk without clear gain

## Files Expected To Change

Primary files:

- `src/cli/process_log.py`
- `src/cli/app.py`
- `src/core/clarification_bus.py`
- `src/core/tools/workspace_files.py`
- `src/core/knowledge_store.py`
- `src/core/engine/agents_model.py`
- `src/core/pipeline.py`

Primary tests:

- `tests/cli/test_app.py`
- `tests/cli/test_process_log.py`
- `tests/core/tools/test_workspace_files.py`
- `tests/core/test_clarification_bus.py`
- `tests/core/engine/test_agents_model.py`
- `tests/core/test_pipeline.py`

## Acceptance Criteria

The design is considered complete when all of the following are true:

- Process log behavior matches spec 7 section 4.1 for block identity, default collapse state, tool row lifecycle, and tool output association.
- Workspace-file tools match spec 3 argument and payload contracts, including truncation and telemetry.
- `KnowledgeStore.search(...)` honors `path_glob` and `regex`.
- Model wrapper matches the missing spec 1 streaming and telemetry requirements within the scoped issue set.
- Clarification flow no longer depends on private UI polling of bus internals and cancellation is deterministic.
- Focused regression tests cover each repaired defect.

## Risks and Mitigations

### Risk: event timing changes break current UI expectations

Mitigation:

- land event tests before UI edits
- keep pipeline as the compatibility seam
- prefer additive event enrichment over wholesale event renaming

### Risk: tool contract fixes break current prompt assumptions or tests

Mitigation:

- update prompt-facing tool signatures deliberately
- use shared envelope helpers
- add compatibility handling only where tests prove a current caller still depends on old behavior

### Risk: clarification cancellation remains flaky under Textual scheduling

Mitigation:

- move assertions to public bus behavior
- ensure cancellation is observable before state is cleared
- test workspace-switch and shutdown paths explicitly

### Risk: telemetry additions become inconsistent across wrapper and pipeline

Mitigation:

- define required telemetry fields once
- assert them in unit tests for the touched paths

## Open Decision

This design assumes one combined implementation plan for all four issues and a low-risk execution style. It does not assume any git workflow.
