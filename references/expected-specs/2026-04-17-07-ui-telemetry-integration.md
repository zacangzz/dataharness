# Spec 7 — UI async refactor + telemetry integration

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3, 4, 5, 6
**Blocks:** spec 8

## 1. Purpose

Refit the Textual UI to drive the new async `Pipeline`, and wire Agents SDK tracing into the existing `hragent-telemetry.log`. This is the final integration touch before packaging.

The UI contract also upgrades the old single collapsed `Agent Steps` dump into a streamed per-turn process surface: one collapsible process block per agent involved in the turn, updated live as events arrive.

## 2. Scope

### In scope

- `src/cli/app.py` refactor: `@work(thread=True)` → async `@work` coroutine.
- `PipelineEvent` → UI rendering mapping: tokens into the conversation pane, and all streamed agent activity into per-agent process blocks.
- Clarification flow: the UI pushes the user's answer to the async `user_input` future (spec 3), not a blocking queue.
- Custom `TracingProcessor` registered with Agents SDK; emits SDK spans (as JSON) into `local/hragent-telemetry.log`.
- `turn_id` / `run_id` context propagation across the new async flow.
- Disable Agents SDK default OpenAI tracing export; register only the custom processor.
- Per-turn process log contract: one collapsible process block per agent per turn, with `+` collapsed and `-` expanded affordance.
- Summarized reasoning surface: raw chain-of-thought is not rendered; concise reasoning summaries stream into each agent block instead.

### Out of scope

- Changing the workspace modal, file browser, or filedrop.
- Startup model-loading UI flow (unchanged).

## 3. Async UI refactor

- `ChatApp.on_input_submitted` (or equivalent) launches `await self._run_turn(message)` via `@work`.
- `_run_turn` builds the `on_event` callback and calls `await pipeline.run(message, on_event, active_workspace)`.
- `on_event` dispatches to widget updaters scheduled on the Textual event loop (`self.call_from_thread` no longer needed — everything runs on the main loop).
- Worker cancellation on workspace switch: `self.workers.cancel_group("turn")` → `CancelledError` → Pipeline cleanup.

## 4. `PipelineEvent` → UI mapping

Events arrive live over the `on_event` coroutine as the SDK `Runner.run_streamed` produces them. No batching. Contract defined in spec 1 §8 (model-wrapper side) and spec 6 §4 (pipeline side).

### 4.1 Process-log structure

- Each turn has one process-log area separate from the transcript.
- Each agent involved in the turn gets exactly one collapsible process block.
- Blocks are created from `AgentStarted(agent)` events, not from transcript heuristics.
- Collapsed title prefix is `+`; expanded title prefix is `-`.
- Default state: collapsed.
- Block title is the agent name only (`+ triage`, `+ data_analyst`, `+ knowledge`, `+ doctor`, `+ clarification`, `+ conversational`).
- Entries inside a block stream in append order and are never reordered after render, except that a pending tool-call row may be updated in place when args complete.
- The old single-agent post-hoc `Agent Steps` dump is retired.

| Event | UI action |
|---|---|
| `AgentStarted(agent)` | Create that agent's collapsible process block for the current turn if absent. |
| `ReasoningSummary(text, agent)` | Append a concise `thinking:` line inside that agent's process block. This is the only user-visible reasoning surface. |
| `TokenDelta(text, output_type)` | `output_type="message"` → append to current assistant-message widget (streaming render in conversation pane). `output_type="reasoning"` is not rendered directly; Pipeline already converted visible reasoning into `ReasoningSummary`. |
| `ToolCallStart(id, name)` | Append inside the current agent block: `→ tool_name(…)` with a pending marker. Emitted the moment the tool name is decoded, before args complete. |
| `ToolCallComplete(id, name, args)` | Update the pending entry in-place inside the same agent block: `→ tool_name(args)`. |
| `ToolOutput(id, output)` | Append below the matching tool-call entry inside the same agent block: `← <truncated output>`. Emitted the moment the tool returns. |
| `Handoff(from, to)` | Append inside the source agent block: `↦ handoff to=<to>`. The destination block is created by `AgentStarted(to)`. |
| `AgentFinished(agent, outcome)` | Append a final status row inside that agent block (`completed`, `handoff`, `cancelled`, `error`). |
| `FinalMessage(text)` | Finalize assistant-message widget; re-enable input. |
| `StatusUpdate(text, level, agent)` | Update the status bar widget: set text; color-code by `level` (idle=dim, working=default, tool=accent, handoff=accent, warn=yellow, error=red). Previous status replaced — status bar is single-line, not a log. Also append the status text to the current agent block when `agent` is present, so the process surface reflects the same lifecycle. |
| `Error(kind, message)` | Render in conversation pane with error styling; re-enable input. |

Every agent thought/action that reaches Pipeline's shared activity vocabulary should appear in the process surface unless a spec explicitly marks it telemetry-only. There is no silent drop path for user-visible activity.

**Status bar is Pipeline-driven.** The UI does not compute status text from `ToolCallStart` / `Handoff` / `TokenDelta` on its own — Pipeline (spec 6 §3.1, §4) emits explicit `StatusUpdate` events at each lifecycle transition and the UI mirrors them. This keeps status text authoritative and consistent with telemetry. On a fresh app boot (no turn active), the status bar shows `Ready` from the UI's startup handler; thereafter every transition is Pipeline-originated.

### 4.2 Telemetry alignment

- UI and telemetry share the same activity vocabulary from spec 6 §3.2.
- UI renders live events; telemetry records the same lifecycle for debugging and correlation.
- UI does not tail `hragent-telemetry.log` and telemetry does not drive UI state.
- Every process-log row should be correlatable by `turn_id`, `run_id`, `agent`, and `tool_call_id` where applicable.
- Reasoning is summarized in both surfaces for this feature. Raw chain-of-thought is not required by either path.

## 5. Clarification flow

- Futures live in `src/core/clarification_bus.py` (spec 3). Both the `user_input` tool and this UI layer import from the bus, so neither side owns the state.
- `user_input` tool calls `clarification_bus.ask(question)` → returns (token, future). Bus posts `{question, token}` onto the UI queue.
- UI consumer drains the queue, renders the question, re-enables input, captures the next submitted text, and calls `clarification_bus.answer(token, text)` which sets the future result. Tool resumes.
- On workspace switch or app shutdown, UI calls `clarification_bus.cancel_all()`. All pending futures are cancelled; awaiting tools re-raise `CancelledError`.

## 6. Telemetry processor

```python
class HrAgentTracingProcessor(TracingProcessor):
    def on_span_start(self, span): self._emit("span_start", span)
    def on_span_end(self, span): self._emit("span_end", span)
    def _emit(self, phase, span):
        record = {
            "phase": phase,
            "span_id": span.span_id,
            "trace_id": span.trace_id,
            "name": span.name,
            "kind": span.kind,
            "attributes": span.attributes,
            "turn_id": current_turn_id(),
            "run_id": current_run_id(),
            "ts": time.time(),
        }
        telemetry_logger.info(json.dumps(record))
```

Registered once at pipeline init:
```python
set_tracing_disabled(False)
add_trace_processor(HrAgentTracingProcessor(telemetry_logger))
# Do NOT call any export processor that uploads to OpenAI.
```

`src/core/telemetry.py` keeps its JSON-lines file handler; only the emission side is swapped. `turn_id` and `run_id` remain context vars.

## 7. Offline enforcement (UI-side assertions)

- On startup, the UI calls a `verify_offline()` helper that:
  - Asserts no trace processor of type `BackendSpanProcessor` (or equivalent OpenAI uploader) is registered.
  - Asserts `OPENAI_API_KEY` is either unset or a known sentinel.
- Smoke test harness: monkey-patches `socket.socket` to fail any connection to `api.openai.com` and runs a trivial turn.

## 8. Testing

**Unit:**
- `_on_event` maps each `PipelineEvent` variant to the correct widget call.
- `StatusUpdate` updates the status bar and, when `agent` is present, appends the same lifecycle row to that agent's process block. It never writes into the assistant transcript.
- Each `StatusUpdate.level` resolves to the expected style class.
- `AgentStarted` creates one collapsible block per agent per turn; duplicate start events do not create duplicate blocks.
- Block chrome shows `+` while collapsed and `-` while expanded.
- `ReasoningSummary` appends summarized thought lines; raw reasoning deltas are never rendered directly.
- `HrAgentTracingProcessor` emits correct JSON lines for `span_start` and `span_end`.
- `verify_offline()` asserts pass on a correctly configured app and fail when an export processor is present.

**Integration (Textual test harness, stub Pipeline emitting scripted events):**
- Full turn: type message → stream tokens → render final → input re-enabled.
- Multi-agent turn: triage block appears first, then analyst block after handoff; each agent keeps its own streamed rows within the same turn.
- Streaming order: `ToolCallStart` renders pending marker before `ToolCallComplete` fills args; `ToolOutput` appears below the tool-call entry inside the same agent block.
- Reasoning summaries route to the agent process block, not the conversation pane.
- Clarification turn: tool question displayed → input captured → tool resolves → final answer rendered.
- Workspace switch cancels an in-flight turn without leaving the input disabled.
- Status bar transitions through expected states over a scripted turn: `Thinking…` → `Handed off to <specialist>` → `Calling <tool>…` → `Streaming answer` → `Ready`.
- Every canonical activity row emitted by Pipeline (`agent_started`, `reasoning_summary`, `tool_call_start`, `tool_call_complete`, `tool_output`, `handoff`, `status_update`, `agent_finished`) appears in the process surface unless marked telemetry-only by the spec.
- Telemetry file contains both `span_start` and `span_end` records for a turn.
- Socket-patched test: turn completes, no `api.openai.com` connection.

**End-to-end real-model + real-UI (pytest marker `@pytest.mark.integration`):**
- Launch Textual app under harness, point at real GGUF via `HRAGENT_TEST_MODEL_PATH`, run the fixtures from spec 6 §10, assert the UI receives streaming updates (multiple text deltas visible before final) rather than one atomic drop.

## 9. Files

**Modified:**
- `src/cli/app.py` — async refactor, event mapping, clarification resolution, and per-turn/per-agent process blocks (imports `clarification_bus` from `src/core/clarification_bus.py`).
- `src/core/telemetry.py` — expose `HrAgentTracingProcessor`, retain logger config.

**New:**
- `tests/cli/test_app_async.py` — replaces retired `tests/cli/test_app.py`; covers async `@work`, event mapping, clarification, workspace-switch cancellation.
- `tests/core/test_telemetry_processor.py` — span-start/end JSON record shape; asserts no OpenAI uploader processor is registered.

**Retired:**
- Any `thread=True` worker paths that called the old smolagents pipeline.

**Tests retired:**
- `tests/cli/test_app.py` — covered the synchronous `@work(thread=True)` UI path and old pipeline bindings. Replaced by `tests/cli/test_app_async.py`.

## 10. Acceptance

- UI runs turns on the Textual event loop; no background thread blocks on `queue.get`.
- Each turn renders one collapsible process block per involved agent, streamed live.
- Process blocks use `+` collapsed and `-` expanded affordance.
- All user-visible agent thoughts/actions in the shared activity vocabulary appear in the process surface.
- `hragent-telemetry.log` has SDK-native span records with `turn_id` / `run_id`.
- Offline assertions green.
- Integration tests pass under Textual harness.
