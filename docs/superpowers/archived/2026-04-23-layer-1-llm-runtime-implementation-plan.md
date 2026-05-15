# Layer 1 LLM Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the single managed local LLM runtime layer that the rest of the application will depend on.

**Architecture:** Create a new `src/runtime/` package and migrate the existing llama.cpp wrapper into it behind a small protocol-driven runtime interface. The runtime must expose predictable request/response types, streamed text and reasoning events, finish metadata, token-pressure reporting, and structured tool-call parsing with a narrow malformed-output correction path, while remaining free of harness policy and app-specific prompt ownership. The target model is Gemma 4 E4B IT Q4_K_M GGUF; default llama.cpp settings should use Gemma chat formatting, GPU offload, and a practical 32k local context while still exposing context sizing to callers. The legacy `dataharness/llm.py` file and `references/harness-docs/gemma4guide.md` are reference inputs during migration; preserve local-runtime configuration knobs that affect llama.cpp initialization, but leave telemetry, speculative decoding, harness policy, and app prompt ownership out of Layer 1.

**Tech Stack:** Python 3.12, `llama-cpp-python`, `pydantic`, `pytest`, `uv`, `typing`

## Caller Obligations

Layer 1 exposes `token_pressure(request) -> TokenPressure` and `validate_request(request)`. Any caller — and Layer 3 in particular — MUST:

1. Call `token_pressure(request)` BEFORE building the final `RuntimeRequest`.
2. If `pressure.remaining_tokens < request.max_new_tokens`, the caller is responsible for compaction or trimming before invoking `complete()` / `stream()`.
3. Treat `RuntimeInputError` as a hard precondition failure, not a recoverable runtime error.

Layer 1 enforces context-window safety at dispatch time. It does not own compaction policy.

---

## File Structure

**Create:**
- `pyproject.toml`
- `src/runtime/__init__.py`
- `src/runtime/config.py`
- `src/runtime/types.py`
- `src/runtime/protocol.py`
- `src/runtime/tool_calls.py`
- `src/runtime/llama_cpp_runtime.py`
- `scripts/build_dist.sh`
- `tests/conftest.py`
- `tests/runtime/test_config.py`
- `tests/runtime/test_tool_calls.py`
- `tests/runtime/test_llama_cpp_runtime.py`
- `tests/runtime/test_runtime_streaming.py`
- `tests/runtime/test_runtime_tool_call_integration.py`

### Task 1: Bootstrap The Runtime Package And Test Harness

**Files:**
- Create: `pyproject.toml`
- Create: `src/runtime/__init__.py`
- Create: `src/runtime/config.py`
- Create: `scripts/build_dist.sh`
- Test: `tests/conftest.py`
- Test: `tests/runtime/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
from runtime.config import RuntimeConfig, auto_ctx_from_ram_gb


def test_auto_ctx_from_ram_gb_uses_small_machine_defaults() -> None:
    assert auto_ctx_from_ram_gb(8) == 4096
    assert auto_ctx_from_ram_gb(16) == 8192
    assert auto_ctx_from_ram_gb(32) == 16384


def test_runtime_config_exposes_single_runtime_defaults() -> None:
    cfg = RuntimeConfig(model_path="model.gguf", n_threads=6)
    assert cfg.model_path == "model.gguf"
    assert cfg.chat_format == "gemma"
    assert cfg.n_ctx == 32768
    assert cfg.n_threads == 6
    assert cfg.n_gpu_layers == -1
    assert cfg.flash_attn is True
    assert cfg.enable_reasoning_stream is True


def test_runtime_config_does_not_own_session_policy() -> None:
    # session/concurrency policy belongs to the application session, not the runtime.
    assert "max_parallel_runs" not in RuntimeConfig.model_fields
    assert "session_id" not in RuntimeConfig.model_fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/runtime/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtime'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project]
name = "dataharness"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "llama-cpp-python",
  "numpy",
  "pydantic>=2.0",
  "psutil",
]

[dependency-groups]
dev = [
  "pytest",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/runtime"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# src/runtime/__init__.py
from runtime.config import RuntimeConfig, auto_ctx_from_ram_gb

__all__ = ["RuntimeConfig", "auto_ctx_from_ram_gb"]
```

```python
# src/runtime/config.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


def auto_ctx_from_ram_gb(total_gb: float) -> int:
    if total_gb <= 8:
        return 4096
    if total_gb <= 16:
        return 8192
    if total_gb <= 32:
        return 16384
    return 32768


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    model_path: str
    chat_format: str = "gemma"
    n_ctx: int = 32768
    n_batch: int = 512
    n_threads: int | None = None
    type_k: int | None = 2
    type_v: int | None = 2
    n_gpu_layers: int = -1
    offload_kqv: bool = True
    flash_attn: bool = True
    verbose: bool = False
    enable_reasoning_stream: bool = True
```

> Layer-boundary note: `RuntimeConfig` MUST NOT carry session-level policy. Concurrency limits, run identifiers, and execution policy live in the application session config (`src/app/session.py`). Adding such fields here breaks spec §4.6.

```bash
# scripts/build_dist.sh
#!/usr/bin/env bash
set -euo pipefail

uv build --out-dir dist
```

```python
# tests/conftest.py
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv sync --dev`
Expected: environment installs successfully from `pyproject.toml`

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/runtime/test_config.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/runtime/__init__.py src/runtime/config.py scripts/build_dist.sh tests/conftest.py tests/runtime/test_config.py
git commit -m "feat: bootstrap runtime package"
```

### Task 2: Define Runtime Request, Event, Result, And Token-Pressure Types

**Files:**
- Create: `src/runtime/types.py`
- Create: `src/runtime/protocol.py`
- Test: `tests/runtime/test_runtime_streaming.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from runtime.types import Message, ModelBehaviorError, RuntimeEvent, RuntimeInputError, RuntimeRequest


def test_runtime_request_keeps_message_order() -> None:
    request = RuntimeRequest(
        messages=[
            Message(role="system", content="sys"),
            Message(role="user", content="hello"),
        ],
        max_new_tokens=128,
        temperature=0.1,
        top_p=0.9,
    )
    assert [message.role for message in request.messages] == ["system", "user"]
    assert request.max_new_tokens == 128


def test_runtime_event_supports_reasoning_finish_and_tool_calls() -> None:
    text_event = RuntimeEvent(kind="text_delta", text="hel")
    reasoning_event = RuntimeEvent(kind="reasoning_delta", text="thinking")
    tool_event = RuntimeEvent(
        kind="tool_call",
        tool_name="doctor",
        tool_arguments={"mode": "manual"},
    )
    finish_event = RuntimeEvent(kind="finish", finish_reason="stop", usage={"prompt_tokens": 12, "completion_tokens": 8})
    assert text_event.kind == "text_delta"
    assert reasoning_event.kind == "reasoning_delta"
    assert tool_event.tool_name == "doctor"
    assert finish_event.usage["prompt_tokens"] == 12


def test_runtime_errors_are_specific_exception_types() -> None:
    with pytest.raises(RuntimeInputError):
        raise RuntimeInputError("over budget")
    with pytest.raises(ModelBehaviorError):
        raise ModelBehaviorError("malformed tool call")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/runtime/test_runtime_streaming.py -q`
Expected: FAIL with `ImportError` for missing runtime types

- [ ] **Step 3: Write minimal implementation**

```python
# src/runtime/types.py
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class RuntimeRequest(BaseModel):
    messages: list[Message]
    max_new_tokens: int
    temperature: float
    top_p: float
    stop: list[str] = Field(default_factory=list)


class RuntimeEvent(BaseModel):
    kind: Literal["text_delta", "reasoning_delta", "tool_call", "finish", "error"]
    text: str = ""
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class RuntimeResponse(BaseModel):
    text: str
    finish_reason: str | None
    usage: dict[str, int]


class TokenPressure(BaseModel):
    used_tokens: int
    max_context_tokens: int
    remaining_tokens: int


class RuntimeInputError(ValueError):
    pass


class ModelBehaviorError(ValueError):
    pass
```

```python
# src/runtime/protocol.py
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from runtime.types import RuntimeEvent, RuntimeRequest, RuntimeResponse, TokenPressure


class Runtime(Protocol):
    def complete(self, request: RuntimeRequest) -> RuntimeResponse: ...

    def stream(self, request: RuntimeRequest) -> Iterator[RuntimeEvent]: ...

    def context_window(self) -> int: ...

    def token_pressure(self, request: RuntimeRequest) -> TokenPressure: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/runtime/test_runtime_streaming.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/runtime/types.py src/runtime/protocol.py tests/runtime/test_runtime_streaming.py
git commit -m "feat: add runtime request and event types"
```

### Task 3: Migrate The Existing llama.cpp Wrapper Behind The Runtime Protocol

**Files:**
- Create: `src/runtime/llama_cpp_runtime.py`
- Test: `tests/runtime/test_llama_cpp_runtime.py`

- [ ] **Step 1: Write the failing test**

```python
from runtime.config import RuntimeConfig
from runtime.llama_cpp_runtime import LlamaCppRuntime, build_llama_kwargs


def test_build_llama_kwargs_uses_runtime_config_values() -> None:
    cfg = RuntimeConfig(model_path="model.gguf", n_ctx=4096, n_batch=256, n_threads=4)
    kwargs = build_llama_kwargs(cfg)
    assert kwargs["model_path"] == "model.gguf"
    assert kwargs["chat_format"] == "gemma"
    assert kwargs["n_ctx"] == 4096
    assert kwargs["n_batch"] == 256
    assert kwargs["n_threads"] == 4
    assert kwargs["n_gpu_layers"] == -1
    assert kwargs["flash_attn"] is True


def test_runtime_exposes_token_pressure_report() -> None:
    cfg = RuntimeConfig(model_path="model.gguf", n_ctx=4096)
    runtime = LlamaCppRuntime.__new__(LlamaCppRuntime)
    runtime._config = cfg
    pressure = runtime.token_pressure_tokens(prompt_tokens=1024, requested_output_tokens=512)
    assert pressure.used_tokens == 1024
    assert pressure.remaining_tokens == 2560
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/runtime/test_llama_cpp_runtime.py -q`
Expected: FAIL with `ModuleNotFoundError` for `runtime.llama_cpp_runtime`

- [ ] **Step 3: Write minimal implementation**

```python
# src/runtime/llama_cpp_runtime.py
from __future__ import annotations

from collections.abc import Iterator

from llama_cpp import Llama

from runtime.config import RuntimeConfig
from runtime.types import ModelBehaviorError, RuntimeEvent, RuntimeInputError, RuntimeRequest, RuntimeResponse, TokenPressure


def build_llama_kwargs(config: RuntimeConfig) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "model_path": config.model_path,
        "chat_format": config.chat_format,
        "n_ctx": config.n_ctx,
        "n_batch": config.n_batch,
        "n_gpu_layers": config.n_gpu_layers,
        "offload_kqv": config.offload_kqv,
        "flash_attn": config.flash_attn,
        "verbose": config.verbose,
    }
    if config.n_threads is not None:
        kwargs["n_threads"] = config.n_threads
    if config.type_k is not None:
        kwargs["type_k"] = config.type_k
    if config.type_v is not None:
        kwargs["type_v"] = config.type_v
    return kwargs


class LlamaCppRuntime:
    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        self._llama = Llama(**build_llama_kwargs(config))

    def context_window(self) -> int:
        return int(self._llama.n_ctx())

    def token_pressure(self, request: RuntimeRequest) -> TokenPressure:
        prompt_tokens = sum(max(len(message.content) // 4, 1) for message in request.messages)
        return self.token_pressure_tokens(
            prompt_tokens=prompt_tokens,
            requested_output_tokens=request.max_new_tokens,
        )

    def token_pressure_tokens(self, *, prompt_tokens: int, requested_output_tokens: int) -> TokenPressure:
        max_context_tokens = self._config.n_ctx
        remaining_tokens = max(max_context_tokens - prompt_tokens - requested_output_tokens, 0)
        return TokenPressure(
            used_tokens=prompt_tokens,
            max_context_tokens=max_context_tokens,
            remaining_tokens=remaining_tokens,
        )

    def validate_request(self, request: RuntimeRequest) -> None:
        if not request.messages:
            raise RuntimeInputError("runtime request must include at least one message")
        pressure = self.token_pressure(request)
        if pressure.used_tokens + request.max_new_tokens > pressure.max_context_tokens:
            raise RuntimeInputError(
                f"runtime request exceeds context window: "
                f"{pressure.used_tokens + request.max_new_tokens}>{pressure.max_context_tokens}"
            )

    def complete(self, request: RuntimeRequest) -> RuntimeResponse:
        self.validate_request(request)
        response = self._llama.create_chat_completion(
            messages=[message.model_dump() for message in request.messages],
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_new_tokens,
            stop=request.stop or None,
            stream=False,
        )
        choice = response["choices"][0]
        return RuntimeResponse(
            text=choice["message"].get("content", ""),
            finish_reason=choice.get("finish_reason"),
            usage=response.get("usage", {}),
        )

    def stream(self, request: RuntimeRequest) -> Iterator[RuntimeEvent]:
        self.validate_request(request)
        for chunk in self._llama.create_chat_completion(
            messages=[message.model_dump() for message in request.messages],
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_new_tokens,
            stop=request.stop or None,
            stream=True,
        ):
            delta = chunk["choices"][0].get("delta", {})
            if delta.get("reasoning_content"):
                yield RuntimeEvent(kind="reasoning_delta", text=delta["reasoning_content"])
            if delta.get("content"):
                yield RuntimeEvent(kind="text_delta", text=delta["content"])
            finish_reason = chunk["choices"][0].get("finish_reason")
            if finish_reason is not None:
                yield RuntimeEvent(kind="finish", finish_reason=finish_reason, usage=chunk.get("usage", {}))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/runtime/test_llama_cpp_runtime.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/runtime/llama_cpp_runtime.py tests/runtime/test_llama_cpp_runtime.py
git commit -m "feat: migrate llama runtime into src package"
```

### Task 4: Add Structured Tool-Call Parsing, Correction, And Malformed Output Detection

**Files:**
- Create: `src/runtime/tool_calls.py`
- Test: `tests/runtime/test_tool_calls.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from runtime.tool_calls import ToolCallParseError, parse_tool_call_block, repair_tool_call_block


def test_parse_tool_call_block_returns_name_and_arguments() -> None:
    payload = '<tool_call>{"name":"doctor","arguments":{"mode":"manual"}}</tool_call>'
    parsed = parse_tool_call_block(payload)
    assert parsed.name == "doctor"
    assert parsed.arguments == {"mode": "manual"}


def test_parse_tool_call_block_rejects_missing_arguments() -> None:
    with pytest.raises(ToolCallParseError):
        parse_tool_call_block('<tool_call>{"name":"doctor"}</tool_call>')


def test_parse_tool_call_block_rejects_invalid_json() -> None:
    with pytest.raises(ToolCallParseError):
        parse_tool_call_block('<tool_call>{"name":"doctor",</tool_call>')


def test_repair_tool_call_block_wraps_single_object_arguments() -> None:
    repaired = repair_tool_call_block('<tool_call>{"name":"doctor","arguments":"manual"}</tool_call>')
    assert repaired == '<tool_call>{"name":"doctor","arguments":{"value":"manual"}}</tool_call>'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/runtime/test_tool_calls.py -q`
Expected: FAIL with `ModuleNotFoundError` for `runtime.tool_calls`

- [ ] **Step 3: Write minimal implementation**

```python
# src/runtime/tool_calls.py
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel


TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)


class ToolCallParseError(ValueError):
    pass


class ParsedToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


def parse_tool_call_block(text: str) -> ParsedToolCall:
    match = TOOL_CALL_RE.search(text)
    if match is None:
        raise ToolCallParseError("missing tool_call block")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ToolCallParseError(f"invalid tool_call json: {exc}") from exc
    if set(payload) != {"name", "arguments"}:
        raise ToolCallParseError("tool_call payload must contain name and arguments")
    if not isinstance(payload["arguments"], dict):
        raise ToolCallParseError("tool_call arguments must be an object")
    return ParsedToolCall(name=payload["name"], arguments=payload["arguments"])


def repair_tool_call_block(text: str) -> str:
    match = TOOL_CALL_RE.search(text)
    if match is None:
        raise ToolCallParseError("missing tool_call block")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ToolCallParseError(f"invalid tool_call json: {exc}") from exc
    if isinstance(payload.get("arguments"), dict):
        return text
    payload["arguments"] = {"value": payload.get("arguments")}
    return f"<tool_call>{json.dumps(payload, separators=(',', ':'))}</tool_call>"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/runtime/test_tool_calls.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/runtime/tool_calls.py tests/runtime/test_tool_calls.py
git commit -m "feat: add runtime tool call parser"
```

### Task 5: Wire Tool Calls And Runtime Error Semantics Into The Runtime

**Files:**
- Modify: `src/runtime/llama_cpp_runtime.py`
- Test: `tests/runtime/test_runtime_tool_call_integration.py`

- [ ] **Step 1: Write the failing integration test**

```python
import pytest

from runtime.config import RuntimeConfig
from runtime.llama_cpp_runtime import LlamaCppRuntime
from runtime.types import Message, ModelBehaviorError, RuntimeInputError, RuntimeRequest


class FakeLlama:
    def __init__(self, response_text: str = "", chunks: list[dict] | None = None) -> None:
        self.response_text = response_text
        self.chunks = chunks or []
        self.tokenize_inputs: list[bytes] = []

    def n_ctx(self) -> int:
        return 128

    def tokenize(self, value: bytes, add_bos: bool = False) -> list[int]:
        self.tokenize_inputs.append(value)
        return list(range(len(value.decode("utf-8").split())))

    def create_chat_completion(self, **kwargs):
        if kwargs.get("stream"):
            return iter(self.chunks)
        return {
            "choices": [
                {
                    "message": {"content": self.response_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7},
        }


def make_runtime(fake: FakeLlama) -> LlamaCppRuntime:
    runtime = LlamaCppRuntime.__new__(LlamaCppRuntime)
    runtime._config = RuntimeConfig(model_path="model.gguf", n_ctx=128)
    runtime._llama = fake
    return runtime


def make_request(content: str = "call doctor") -> RuntimeRequest:
    return RuntimeRequest(
        messages=[Message(role="user", content=content)],
        max_new_tokens=16,
        temperature=0.1,
        top_p=0.9,
    )


def test_complete_returns_tool_call_event_when_model_emits_valid_block() -> None:
    runtime = make_runtime(FakeLlama('<tool_call>{"name":"doctor","arguments":{"mode":"manual"}}</tool_call>'))
    response = runtime.complete(make_request())
    assert response.text == ""
    assert len(response.events) == 1
    assert response.events[0].kind == "tool_call"
    assert response.events[0].tool_name == "doctor"
    assert response.events[0].tool_arguments == {"mode": "manual"}


def test_complete_splits_gemma_think_block_into_reasoning_event() -> None:
    content = "<|think|>inspect columns first</|think|>Ready."
    runtime = make_runtime(FakeLlama(content))
    response = runtime.complete(make_request())
    assert response.text == "Ready."
    assert response.events[0].kind == "reasoning_delta"
    assert response.events[0].text == "inspect columns first"


def test_complete_repairs_single_malformed_tool_call_once() -> None:
    runtime = make_runtime(FakeLlama('<tool_call>{"name":"doctor","arguments":"manual"}</tool_call>'))
    response = runtime.complete(make_request())
    assert response.events[0].tool_name == "doctor"
    assert response.events[0].tool_arguments == {"value": "manual"}


def test_complete_raises_model_behavior_error_when_tool_call_cannot_be_repaired() -> None:
    runtime = make_runtime(FakeLlama('<tool_call>{"name":"doctor"</tool_call>'))
    with pytest.raises(ModelBehaviorError, match="malformed tool call"):
        runtime.complete(make_request())


def test_stream_emits_tool_call_event_before_finish() -> None:
    chunks = [
        {"choices": [{"delta": {"content": '<tool_call>{"name":"doctor","arguments":{"mode":"manual"}}</tool_call>'}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = list(runtime.stream(make_request()))
    assert [event.kind for event in events] == ["tool_call", "finish"]
    assert events[0].tool_arguments == {"mode": "manual"}


def test_stream_buffers_tool_call_split_across_chunks() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<tool_call>{"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": '"name":"doctor",'}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": '"arguments":{"mode":"manual"}}</tool_call>'}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = list(runtime.stream(make_request()))
    assert [event.kind for event in events] == ["tool_call", "finish"]
    assert events[0].tool_name == "doctor"
    assert events[0].tool_arguments == {"mode": "manual"}


def test_stream_buffers_split_tool_call_opening_tag() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<tool"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": '_call>{"name":"doctor","arguments":{"mode":"manual"}}</tool_call>'}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = list(runtime.stream(make_request()))
    assert [event.kind for event in events] == ["tool_call", "finish"]
    assert events[0].tool_name == "doctor"


def test_stream_splits_gemma_think_block_across_chunks() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<|think|>inspect "}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "columns</|think|>Ready."}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = list(runtime.stream(make_request()))
    assert [event.kind for event in events] == ["reasoning_delta", "text_delta", "finish"]
    assert events[0].text == "inspect columns"
    assert events[1].text == "Ready."


def test_token_pressure_uses_llama_tokenizer_when_available() -> None:
    fake = FakeLlama("")
    runtime = make_runtime(fake)
    pressure = runtime.token_pressure(make_request("one two three four"))
    assert fake.tokenize_inputs
    assert pressure.used_tokens > 0
    assert pressure.max_context_tokens == 128


def test_runtime_rejects_over_budget_request_before_dispatch() -> None:
    runtime = make_runtime(FakeLlama(""))
    with pytest.raises(RuntimeInputError, match="exceeds context window"):
        runtime.validate_request(make_request("x" * 600))


def test_stream_emits_error_event_then_finish_when_buffer_incomplete_at_finish() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<tool_call>{\"name\":\"doctor\""}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = list(runtime.stream(make_request()))
    kinds = [event.kind for event in events]
    assert "error" in kinds
    assert kinds[-1] == "finish"
    error_event = next(event for event in events if event.kind == "error")
    assert "incomplete structured content at finish" in (error_event.error or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/runtime/test_runtime_tool_call_integration.py -q`
Expected: FAIL because `RuntimeResponse` does not have `events`, `LlamaCppRuntime` does not parse or buffer tool-call text, Gemma `<|think|>` content is not separated, and token pressure still uses only the heuristic path.

- [ ] **Step 3: Update runtime types**

```python
# src/runtime/types.py
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class RuntimeRequest(BaseModel):
    messages: list[Message]
    max_new_tokens: int
    temperature: float
    top_p: float
    stop: list[str] = Field(default_factory=list)


class RuntimeEvent(BaseModel):
    kind: Literal["text_delta", "reasoning_delta", "tool_call", "finish", "error"]
    text: str = ""
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class RuntimeResponse(BaseModel):
    text: str
    finish_reason: str | None
    usage: dict[str, int]
    events: list[RuntimeEvent] = Field(default_factory=list)


class TokenPressure(BaseModel):
    used_tokens: int
    max_context_tokens: int
    remaining_tokens: int


class RuntimeInputError(ValueError):
    pass


class ModelBehaviorError(ValueError):
    pass
```

- [ ] **Step 4: Update runtime implementation**

```python
# src/runtime/llama_cpp_runtime.py
from __future__ import annotations

from collections.abc import Iterator

from llama_cpp import Llama

from runtime.config import RuntimeConfig
from runtime.tool_calls import ToolCallParseError, parse_tool_call_block, repair_tool_call_block
from runtime.types import ModelBehaviorError, RuntimeEvent, RuntimeInputError, RuntimeRequest, RuntimeResponse, TokenPressure

TOOL_START = "<tool_call>"
TOOL_END = "</tool_call>"
THINK_START = "<|think|>"
THINK_END = "</|think|>"
STREAM_MARKERS = (TOOL_START, THINK_START)


def build_llama_kwargs(config: RuntimeConfig) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "model_path": config.model_path,
        "chat_format": config.chat_format,
        "n_ctx": config.n_ctx,
        "n_batch": config.n_batch,
        "n_gpu_layers": config.n_gpu_layers,
        "offload_kqv": config.offload_kqv,
        "flash_attn": config.flash_attn,
        "verbose": config.verbose,
    }
    if config.n_threads is not None:
        kwargs["n_threads"] = config.n_threads
    if config.type_k is not None:
        kwargs["type_k"] = config.type_k
    if config.type_v is not None:
        kwargs["type_v"] = config.type_v
    return kwargs


def event_from_tool_call_text(text: str) -> RuntimeEvent:
    try:
        parsed = parse_tool_call_block(text)
    except (ToolCallParseError, ValueError):
        try:
            parsed = parse_tool_call_block(repair_tool_call_block(text))
        except (ToolCallParseError, ValueError) as exc:
            raise ModelBehaviorError(f"malformed tool call: {exc}") from exc
    return RuntimeEvent(kind="tool_call", tool_name=parsed.name, tool_arguments=parsed.arguments)


def marker_prefix_suffix(text: str) -> str:
    for marker in STREAM_MARKERS:
        max_len = min(len(marker) - 1, len(text))
        for size in range(max_len, 0, -1):
            suffix = text[-size:]
            if marker.startswith(suffix):
                return suffix
    return ""


def split_gemma_think_text(text: str) -> tuple[list[RuntimeEvent], str]:
    events: list[RuntimeEvent] = []
    remaining = text
    while THINK_START in remaining and THINK_END in remaining:
        before, _, after_start = remaining.partition(THINK_START)
        reasoning, _, after_end = after_start.partition(THINK_END)
        if before.strip():
            events.append(RuntimeEvent(kind="text_delta", text=before.strip()))
        if reasoning.strip():
            events.append(RuntimeEvent(kind="reasoning_delta", text=reasoning.strip()))
        remaining = after_end
    return events, remaining


def response_from_text(text: str, *, finish_reason: str | None, usage: dict[str, int]) -> RuntimeResponse:
    events, remaining = split_gemma_think_text(text)
    tool_events = [event_from_tool_call_text(remaining)] if TOOL_START in remaining else []
    visible_text = remaining.split(TOOL_START, 1)[0].strip() if TOOL_START in remaining else remaining.strip()
    return RuntimeResponse(
        text=visible_text,
        finish_reason=finish_reason,
        usage=usage,
        events=[*events, *tool_events],
    )


def emit_content_events(content: str, stream_buffer: str) -> tuple[list[RuntimeEvent], str]:
    events: list[RuntimeEvent] = []
    pending = stream_buffer + content if stream_buffer else content

    if THINK_START in pending and THINK_END not in pending:
        return events, pending

    think_events, pending = split_gemma_think_text(pending)
    events.extend(think_events)

    if TOOL_START not in pending:
        suffix = marker_prefix_suffix(pending)
        if suffix:
            visible = pending[: -len(suffix)]
            if visible:
                events.append(RuntimeEvent(kind="text_delta", text=visible))
            return events, suffix
        if pending:
            events.append(RuntimeEvent(kind="text_delta", text=pending))
        return events, ""

    prefix, _, rest = pending.partition(TOOL_START)
    if prefix and not stream_buffer:
        events.append(RuntimeEvent(kind="text_delta", text=prefix))

    tool_text = TOOL_START + rest
    if TOOL_END not in tool_text:
        return events, tool_text

    tool_block, _, tail = tool_text.partition(TOOL_END)
    events.append(event_from_tool_call_text(tool_block + TOOL_END))
    if tail:
        events.append(RuntimeEvent(kind="text_delta", text=tail))
    return events, ""


class LlamaCppRuntime:
    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        self._llama = Llama(**build_llama_kwargs(config))

    def context_window(self) -> int:
        return int(self._llama.n_ctx())

    def count_message_tokens(self, request: RuntimeRequest) -> int:
        try:
            return sum(
                len(self._llama.tokenize(f"{message.role}\n{message.content}".encode("utf-8"), add_bos=False))
                for message in request.messages
            )
        except Exception:
            return sum(max(len(message.content) // 4, 1) for message in request.messages)

    def token_pressure(self, request: RuntimeRequest) -> TokenPressure:
        prompt_tokens = self.count_message_tokens(request)
        return self.token_pressure_tokens(
            prompt_tokens=prompt_tokens,
            requested_output_tokens=request.max_new_tokens,
        )

    def token_pressure_tokens(self, *, prompt_tokens: int, requested_output_tokens: int) -> TokenPressure:
        max_context_tokens = self._config.n_ctx
        remaining_tokens = max(max_context_tokens - prompt_tokens - requested_output_tokens, 0)
        return TokenPressure(
            used_tokens=prompt_tokens,
            max_context_tokens=max_context_tokens,
            remaining_tokens=remaining_tokens,
        )

    def validate_request(self, request: RuntimeRequest) -> None:
        if not request.messages:
            raise RuntimeInputError("runtime request must include at least one message")
        pressure = self.token_pressure(request)
        if pressure.used_tokens + request.max_new_tokens > pressure.max_context_tokens:
            raise RuntimeInputError(
                f"runtime request exceeds context window: "
                f"{pressure.used_tokens + request.max_new_tokens}>{pressure.max_context_tokens}"
            )

    def complete(self, request: RuntimeRequest) -> RuntimeResponse:
        self.validate_request(request)
        response = self._llama.create_chat_completion(
            messages=[message.model_dump() for message in request.messages],
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_new_tokens,
            stop=request.stop or None,
            stream=False,
        )
        choice = response["choices"][0]
        text = choice["message"].get("content", "")
        return response_from_text(
            text,
            finish_reason=choice.get("finish_reason"),
            usage=response.get("usage", {}),
        )

    def stream(self, request: RuntimeRequest) -> Iterator[RuntimeEvent]:
        self.validate_request(request)
        stream_buffer = ""
        for chunk in self._llama.create_chat_completion(
            messages=[message.model_dump() for message in request.messages],
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_new_tokens,
            stop=request.stop or None,
            stream=True,
        ):
            delta = chunk["choices"][0].get("delta", {})
            if delta.get("reasoning_content"):
                yield RuntimeEvent(kind="reasoning_delta", text=delta["reasoning_content"])
            if delta.get("content"):
                content = delta["content"]
                content_events, stream_buffer = emit_content_events(content, stream_buffer)
                yield from content_events
            finish_reason = chunk["choices"][0].get("finish_reason")
            if finish_reason is not None:
                if stream_buffer:
                    content_events, stream_buffer = emit_content_events("", stream_buffer)
                    yield from content_events
                    if stream_buffer:
                        # Yield as structured error event so the caller still observes finish.
                        yield RuntimeEvent(
                            kind="error",
                            error=f"incomplete structured content at finish: {stream_buffer}",
                        )
                yield RuntimeEvent(kind="finish", finish_reason=finish_reason, usage=chunk.get("usage", {}))
```

- [ ] **Step 5: Run focused tests to verify they pass**

Run: `uv run pytest tests/runtime/test_runtime_tool_call_integration.py tests/runtime/test_llama_cpp_runtime.py tests/runtime/test_runtime_streaming.py tests/runtime/test_tool_calls.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/runtime/types.py src/runtime/llama_cpp_runtime.py tests/runtime/test_runtime_tool_call_integration.py tests/runtime/test_llama_cpp_runtime.py tests/runtime/test_runtime_streaming.py
git commit -m "feat: wire runtime tool call events"
```

## Self-Review

**Spec coverage:**
- Covers Layer 1 purpose, local backend integration, streamed text and reasoning events, Gemma `<|think|>` reasoning separation, finish metadata, tokenizer-backed context-window accounting, token-pressure reporting, tool-call decoding/correction, malformed-output failure, split structured-output streaming, and over-budget request failure.
- Leaves application prompt identity, context policy, and provenance ownership out of this layer, matching the spec boundaries.

**Placeholder scan:**
- No placeholder markers or empty code blocks remain.

**Type consistency:**
- `RuntimeConfig`, `RuntimeRequest`, `RuntimeEvent`, `RuntimeResponse`, `RuntimeInputError`, `ModelBehaviorError`, and `LlamaCppRuntime` names are used consistently across tasks.
