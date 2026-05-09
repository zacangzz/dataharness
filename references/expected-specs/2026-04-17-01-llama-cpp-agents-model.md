# Spec 1 — Custom Agents SDK `Model` wrapping llama_cpp

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** none (first in build order)
**Blocks:** specs 2, 3, 4, 5, 6, 7, 8

## 1. Purpose

Provide a custom subclass of the OpenAI Agents SDK `Model` interface that dispatches generation to the local llama_cpp engine. This is the single LLM entry point used by every agent (triage, conversational, data analyst SandboxAgent, clarification). It also hosts the `Compaction` hook, which summarizes the oldest conversation/step history when context usage approaches the engine limit, freeing tokens so long-running turns can continue on the summarized prefix.

## 2. Scope

### In scope

- Class `LlamaCppAgentsModel` implementing the Agents SDK `Model` contract (methods required by `Runner` and `SandboxAgent` — at minimum: a non-streaming response call, a streaming response call).
- OpenAI Responses-format output (messages, tool_calls, finish_reason, usage).
- Tool-call JSON parsing from the llama_cpp chat-completion output.
- Streaming delta chunks.
- `Compaction.maybe_compact()` invocation before every dispatch.
- Telemetry emission: per-call input message count, input char count, estimated tokens, output chunk count, finish_reason, effective max_new_tokens.
- Config surface: `ModelConfig` (temperature, top_p, max_new_tokens cap, min_output_tokens floor, output_safety_margin, thinking mode flag).

### Out of scope

- The underlying llama_cpp engine (spec 2).
- Per-agent prompt wiring (spec 4).
- Session memory / `SQLiteSession` (spec 6).

## 3. Public surface

```python
class LlamaCppAgentsModel(Model):
    def __init__(
        self,
        engine: LlmModel,                 # spec 2
        compaction: Compaction | None,
        config: ModelConfig,
    ): ...

    async def get_response(
        self,
        system_instructions: str | None,
        input: list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        previous_response_id: str | None,
        **kwargs,
    ) -> ModelResponse: ...

    async def stream_response(self, ...) -> AsyncIterator[TResponseStreamEvent]: ...
```

Exact signatures track the upstream `openai-agents` release pinned at migration time. The probe task confirms signatures before implementation.

## 4. Internal responsibilities

1. Accept Agents SDK message list + tool definitions.
2. Translate to llama_cpp `chat_completion` arguments, including tool JSON schema bound into the chat template.
3. Call `compaction.maybe_compact(messages)` before dispatch if attached; replace messages list with the compacted one. `Compaction` detects when cumulative input tokens cross its trigger threshold (default ~70% of `n_ctx`), summarizes the oldest messages/steps via a dedicated prompt, and returns a shorter message list that preserves the summary plus recent tail.
4. Invoke `engine.chat_with_tools(...)` (non-streaming) or `engine.stream(...)` (streaming).
5. Parse response:
   - If the model emitted a tool_call JSON block, decode into `ResponseFunctionToolCall` items.
   - Otherwise, emit a plain assistant text message.
   - Populate `finish_reason`: `stop`, `tool_calls`, `length`.
6. Emit telemetry: input/output sizes, finish_reason, which agent called (context var), turn_id/run_id.
7. Compute effective `max_new_tokens` per call from actual input size using `ModelConfig.min_output_tokens` and `output_safety_margin`, matching current behavior.

## 5. `Compaction` integration

- A single `Compaction` instance is shared across all analyst-route model calls (matches current `agent` adapter behavior): analyst turns accumulate long tool-call history and benefit from summarization.
- For the conversational and triage paths, `compaction=None` is used (direct route, no compaction — matches current `assistant` adapter).
- Pipeline decides which variant to hand to each agent at construction.
- `Compaction` is implementation-detail of this layer: the SDK `Runner` and `SQLiteSession` are unaware of it. The compacted list is passed into llama_cpp; the SDK-level session still stores the original turn items.

### 5.1 Summary cache

- `Compaction` caches each produced summary keyed by `(prefix_hash, tail_len)`, where `prefix_hash` hashes the exact message-id sequence of the summarized prefix and `tail_len` is the count of uncompacted tail messages.
- On each dispatch, `maybe_compact` first computes the current prefix/tail split; if the key hits cache, it reuses the summary without calling `engine.completion`. Tail grows past threshold → cache miss → resummarize.
- Cache is per-`Compaction`-instance (per-Pipeline, per-workspace). Dropped on workspace switch.
- Avoids per-dispatch re-summarization when `Runner` replays a long `SQLiteSession` across many turns.

### 5.2 Atomic tool-call / tool-output pairs

- `Compaction` must never split a `tool_call` message from its matching `tool_output`. Splitting breaks llama_cpp chat-template tool-loop rendering and confuses the model.
- Implementation: when selecting the prefix cut-off, walk backwards from the target boundary until the next message is a clean `user`/`assistant` message (not a tool turn). Include full tool-call pairs in whichever side (summarized prefix or retained tail) they land on.
- Multi-tool-call turns (one assistant message emitting N tool_calls, followed by N tool_output messages) are treated as one atomic group.

## 6. Why not SDK-level compaction

SDK ships `agents.sandbox.capabilities.compaction` (see `https://openai.github.io/openai-agents-python/ref/sandbox/capabilities/compaction/`). Rejected for this migration:

- Scope: applies to `SandboxAgent` only. Triage, conversational, clarification agents get no compaction.
- `CompactionModelInfo` defaults hardcode OpenAI model context windows (GPT-5.x, O-series, GPT-4o). Custom `CompactionModelInfo` is possible but still tied to the sandbox scope.
- Documentation does not specify which model runs the summarization pass or whether that call is guaranteed to flow through the agent's configured `Model`. Unverified offline safety.
- No documented hook to inject a custom-Model summarizer distinct from the agent's Model.

Revisit if upstream ships a `CompactionProvider` that accepts our `LlamaCppAgentsModel` and applies at `Runner` level across all agents. Tracked in umbrella §12 risks.

## 7. Tool-call JSON parsing

- Reuse the existing `LlmModel.chat_with_tools` output shape. Extract `tool_calls` field. Map to `ResponseFunctionToolCall` (id, name, arguments JSON string).
- If the model emits malformed JSON in a tool-call block, retry once with a constrained instruction (`"Emit valid JSON tool_call only."`). On second failure, raise `ModelBehaviorError` — caller decides what to do.

## 8. Streaming

End-to-end streaming is a hard requirement. All four agents (triage, conversational, analyst, clarification) run via `Runner.run_streamed`. Model wrapper emits the following events as soon as the underlying llama_cpp stream reveals them — no batching, no wait-for-turn-end:

- **Assistant text tokens:** `ResponseOutputItemAddedEvent` + `ResponseTextDeltaEvent` per token. UI renders live.
- **Reasoning / thought tokens** (Gemma thinking-mode output, when enabled in `ModelConfig`): same delta path as assistant text, but tagged `output_type="reasoning"` so spec 6/spec 7 can convert them into summarized reasoning rows inside the active agent's process block rather than the conversation pane.
- **Tool-call start:** as soon as the stream reveals the tool name (before args are complete), emit `ResponseFunctionToolCallAddedEvent(name, id)`. Gives UI an immediate "→ tool_name(…)" render.
- **Tool-call args:** buffer arg deltas until closing brace; emit `ResponseFunctionToolCallCompletedEvent(name, args)` when the JSON validates. Args are emitted as one atomic completion event (Agents SDK does not stream partial tool args reliably for all models).
- **Handoff:** emit as soon as the triage decision token sequence completes (handled by SDK Runner layer; model wrapper exposes the underlying delta to it).
- **Finish event:** terminal event with `usage` and `finish_reason`.

Tool-output streaming is handled by the Runner/Pipeline layer (spec 6): as soon as a `@function_tool` returns, Runner emits a `RunItemStreamEvent` carrying the output. No buffering in the model wrapper.

Spec 7 `PipelineEvent` mapping must distinguish `ToolCallStart` from `ToolCallComplete` to render activity ASAP. Spec 4 agent defs inherit streaming by default — no opt-out.

## 9. Telemetry

- `span.kind = "generation"`, `span.attributes`:
  - `model.name = "gemma-4-E4B-it-Q4_K_M"` (from engine metadata)
  - `model.input_messages`, `model.input_chars`, `model.input_tokens_est`
  - `model.output_chars`, `model.output_tokens_est`
  - `model.finish_reason`
  - `model.effective_max_new_tokens`
  - `model.compaction_triggered` (bool)
  - `model.compaction_cache_hit` (bool — true if §5.1 cache reused a summary without re-running engine)
  - `turn_id`, `run_id` from context vars

## 10. Testing

**Unit (mocked `LlmModel`):**
- Plain-text response produces a single assistant message, `finish_reason="stop"`.
- Tool-call response produces one or more `ResponseFunctionToolCall` items, `finish_reason="tool_calls"`.
- Length-capped response produces `finish_reason="length"`.
- Streaming path yields delta events in order, closed by a final usage event.
- `Compaction.maybe_compact` is called exactly once per dispatch when attached, zero times when not.
- Over-budget input list triggers compaction before engine call; returned list is shorter and preserves the summary-plus-tail invariant.
- Second dispatch with identical prefix + unchanged tail reuses cached summary (no additional `engine.completion` call); `model.compaction_cache_hit=true` recorded.
- Compaction never splits a `tool_call` + `tool_output` pair across the summarized/retained boundary (fixture: assistant emits 2 tool_calls, 2 tool_outputs follow; boundary walks back to the preceding user turn).
- Malformed tool_call JSON triggers one constrained retry; second failure raises `ModelBehaviorError`.

**Integration (real llama_cpp, real model GGUF, pytest marker `@pytest.mark.integration`):**

These tests actually load the production model (`gemma-4-E4B-it-Q4_K_M.gguf` or a fixture-pinned smaller variant when the full model is unavailable via env var `HRAGENT_TEST_MODEL_PATH`). Not run in pre-commit; gated on CI `integration` job and on release tags.

- **Probe:** `SandboxAgent` + `LlamaCppAgentsModel` + trivial tool (`echo`) returns expected tool_call + final message on `"call echo with 'hi'"`.
- **Nested sub-run probe (blocks spec 3 `call_knowledge`):** A parent agent has a `@function_tool` whose body invokes `Runner.run_streamed(child_agent, ...)` synchronously (awaits completion). Assert:
  - Child's streaming events reach a supplied event consumer (directly or via a proxy channel) while the parent turn is still in flight.
  - Child's telemetry span nests under the parent turn's span via `turn_id` / `run_id` context vars.
  - Child's final assistant message returns to the parent tool as the tool's string output.
  - Child's `SQLiteSession` is either scoped to the parent turn (ephemeral, recommended) or uses the parent's session with a clear boundary marker; choice pinned here and enforced in spec 11 §4.4 `call_knowledge` entry point.
  - No deadlock: parent does not block the event loop while child runs.
  - Outcome recorded in the spec 1 implementation PR description; if the SDK forbids or makes this unreliable, fall back to Option A (strict handoff) — spec 10 decision tree drops branches 3b/3c and spec 3 drops `call_knowledge`.
- **Plain text turn:** prompt `"hello"` → streamed assistant message, `finish_reason="stop"`, first-token latency < 5000ms, total wall < 15000ms (budgets captured per-machine tier in `tests/integration/budgets.json`; failing a budget logs a warning but does not fail the test unless budget is exceeded by >50%).
- **Tool-call turn:** prompt that requires one `echo` call; stream contains exactly one `ToolCallStart` → one `ToolCallComplete` → one tool_output → one `FinalMessage`, in order.
- **Streaming contract:** tokens arrive in > 1 delta event (i.e., not batched into one final event). First text delta lands before the last.
- **Compaction end-to-end:** fixture session with 40 prior assistant+tool turns; dispatch crosses threshold; compaction fires; second identical dispatch hits cache (no second `engine.completion` for summarization).
- **Offline:** all of the above run with `socket.socket` monkey-patched to refuse `api.openai.com`. No test fails from connection attempts.

## 11. Files

**New:**
- `src/core/engine/__init__.py`
- `src/core/engine/agents_model.py` (`LlamaCppAgentsModel`, `ModelConfig`)
- `tests/core/engine/__init__.py`
- `tests/core/engine/conftest.py` — `LlamaCppAgentsModel` stub fixtures for downstream test suites.
- `tests/core/engine/test_agents_model.py`

**Modified:**
- `src/core/engine/compaction.py` (moved + renamed from `src/core/agents/memory_manager.py`; class `MemoryManager` → `Compaction`) — no behavior change, but the integration point moves from `model_adapter.py` (retired) to the new model wrapper.
- `tests/core/engine/test_compaction.py` (moved + renamed from `tests/core/agents/test_memory_manager.py`) — integration test updated so `Compaction` attaches to `LlamaCppAgentsModel` instead of the retired adapter.
- `tests/core/agents/conftest.py` — strip smolagents fixtures (agents/ tests now cover specialist/triage agents only).
- `src/core/prompts/compaction_summarize.md` — renamed from `memory_summarize.md`; contents unchanged. Loaded by `Compaction` for the summarization pass.

**Tests retired:**
- `tests/core/agents/test_model_adapter.py` — the smolagents adapter it covered is deleted.

## 12. Acceptance

- Unit tests green.
- Probe integration test passes against a small local GGUF.
- `finish_reason` values map correctly.
- Telemetry span emitted once per call with all documented fields.
- No egress (verified under socket patch).
