# Spec 2 — `LlmModel` refactor

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** spec 1 (Custom Agents SDK Model surface is known)
**Blocks:** specs 3, 4, 5, 6, 7, 8

## 1. Purpose

Move and shrink `src/core/model.py` `LlmModel` into `src/core/engine/llm.py` as a thin llama_cpp engine holder. Responsibilities unique to the Agents SDK (tool-call JSON shaping, OpenAI-Responses format, streaming delta translation) move out into the Custom Model wrapper defined in spec 1.

## 2. Scope

### In scope

- Keep: `EngineConfig`, `load()`, auto-ctx sizing by RAM tier, GPU offload, flash_attn, KV cache quant.
- Keep: raw `completion(messages, **kwargs) -> str` producing a non-streamed full text body.
- Keep: low-level `stream(messages, **kwargs) -> iterator[str]` producing raw token strings.
- Keep: engine metadata (model name, context size, BOS/EOS tokens, tokenizer).
- Keep: existing telemetry fields that describe the engine itself (startup, load time, n_ctx, kv_cache sizes).
- Remove: `chat_with_tools()` public method — moved into spec 1 (since the tool-call framing is tied to Agents SDK output). The internal helper that formats tools into the chat template may stay but is private.
- Remove: any smolagents-specific compatibility layer or import.

### Out of scope

- Agents SDK `Model` interface (spec 1).
- Tool definitions (spec 3).

## 3. Rationale

Today `LlmModel` straddles two concerns: running llama_cpp, and producing an agent-framework-shaped response. After migration, only the Custom Model wrapper knows about Agents SDK. Keeping `LlmModel` framework-agnostic means a future swap (or a side-by-side benchmark) is easier, and the raw engine is testable without pulling in Agents SDK.

## 4. Public surface after refactor

```python
class EngineConfig:
    # unchanged
    n_ctx: int | None            # auto-scaled if None
    n_batch: int
    n_threads: int | None
    type_k: str
    type_v: str
    n_gpu_layers: int
    offload_kqv: bool
    flash_attn: bool

class LlmModel:
    def __init__(self, model_path: Path, config: EngineConfig): ...
    def load(self) -> None: ...

    def completion(
        self,
        messages: list[dict],
        *,
        temperature: float,
        top_p: float,
        max_new_tokens: int,
        stop: list[str] | None = None,
    ) -> CompletionResult: ...

    def stream(
        self,
        messages: list[dict],
        *,
        temperature: float,
        top_p: float,
        max_new_tokens: int,
        stop: list[str] | None = None,
    ) -> Iterator[StreamChunk]: ...

    @property
    def metadata(self) -> EngineMetadata: ...
```

`CompletionResult` and `StreamChunk` are plain dataclasses. No OpenAI / Agents SDK types leak in.

## 5. Telemetry

- Startup: `startup/engine_loaded` with n_ctx, ram_tier, gpu_layers.
- Per completion: `engine/completion` with input token estimate, output token estimate, wall time.
- Per stream: `engine/stream` with first-token latency, total tokens, wall time.

These are engine-level spans; Agents SDK spans wrap them at the next layer (spec 1).

## 6. Testing

This spec covers the **fast unit tier** only. Real-model quality/latency tests against the production GGUF live in spec 1 §10 (model-wrapper end-to-end), spec 6 §10 (pipeline conversation fixtures), and spec 8 §6 (packaged-binary smoke). All real-model tests are gated on `HRAGENT_TEST_MODEL_PATH` and the `integration` pytest marker. A tiny 1-MB test GGUF is suitable here because we're validating shape, types, telemetry, and auto-sizing arithmetic — not generation quality.

**Unit (llama_cpp mocked or with a 1-MB test GGUF):**
- `EngineConfig` auto-ctx sizing at all RAM tiers unchanged from current behavior (unit test by monkey-patching `psutil.virtual_memory`).
- `completion()` returns a `CompletionResult` with text + usage counters; no Agents SDK types.
- `stream()` yields chunks in order; terminates with a final chunk marker.
- Compile-time assertion: `assert not hasattr(LlmModel, "chat_with_tools")` (guard against reintroduction).

## 7. Files

**New:**
- `src/core/engine/llm.py` — shrunk `LlmModel` at new path.
- `tests/core/engine/test_llm.py` — RAM-tier auto-ctx, `CompletionResult` / `StreamChunk` shape, absence of tool-call API.

**Retired (deleted):**
- `src/core/model.py` — content moved to `src/core/engine/llm.py`, old file deleted.
- `tests/core/test_model.py` — replaced by `tests/core/engine/test_llm.py`.

**Retired code paths (callers removed in later specs):**
- `LlmModel.chat_with_tools` callers in `model_adapter.py` → gone when spec 1 ships.

**Tests retired:**
- `tests/core/test_model.py` — replaced by `tests/core/engine/test_llm.py` at the new location.

## 8. Acceptance

- `LlmModel` has no Agents SDK or smolagents imports.
- `EngineConfig` defaults and auto-sizing unchanged.
- All existing engine-level telemetry events still emitted.
- Tests green.
