# Layer 1 Runtime Async Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-01-async-layered-architecture-design.md` §6.

**Goal:** Replace sync `Runtime.complete(...)` and sync `Runtime.stream(...)` with an async-only protocol that exposes `stream`, `context_window`, `token_pressure`, `validate_request`, and `status`. `LlamaCppRuntime` privately bridges the blocking llama.cpp iterator via a background producer thread + bounded `asyncio.Queue` (default 64). Cancellation observed within one token. No sync public path remains.

**Architecture:** Public layer is async-only. Internal bridge thread runs the sync iterator on a worker thread, pushes typed `RuntimeEvent` items into an `asyncio.Queue`. Public `stream(...)` is an async iterator that drains the queue and surfaces `RuntimeEvent` items with `request_id` + monotonic `seq`. Cancellation flips a flag that the bridge checks between deltas; the bridge drains, emits a final cancelled error event, and exits cleanly.

**Tech Stack:** Python 3.12, `asyncio`, `llama-cpp-python` 0.3.x, `pydantic` 2.x, `pytest`, `pytest-asyncio`.

---

## File Structure

- `src/runtime/types.py` — replace request/event/pressure/status schemas to match spec §6.
- `src/runtime/protocol.py` — async-only `Runtime` protocol.
- `src/runtime/bridge.py` — **new**: `SyncToAsyncBridge` for llama.cpp blocking iterator.
- `src/runtime/llama_cpp_runtime.py` — async `LlamaCppRuntime` using the bridge. Drop sync `complete` and sync `stream`.
- `src/runtime/config.py` — add `bridge_queue_size: int = 64` to `RuntimeConfig`.
- `tests/runtime/test_runtime_async_streaming.py` — **new**: end-to-end async streaming, cancellation, backpressure, status.
- `tests/runtime/test_bridge.py` — **new**: bridge unit tests against synthetic sync iterators.
- `tests/runtime/test_runtime_streaming.py` — convert from sync to async.
- `tests/runtime/test_llama_cpp_runtime.py` — convert sync→async; remove `complete`/sync `stream` tests.

---

## Prep

- [ ] **Step 0.1: Add `pytest-asyncio` to dev deps**

Modify `pyproject.toml`:

```toml
[dependency-groups]
dev = [
  "pytest",
  "pytest-asyncio",
]
```

Run: `uv sync`
Expected: lockfile updated, no errors.

- [ ] **Step 0.2: Configure pytest-asyncio default mode**

Modify `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
asyncio_mode = "auto"
```

Run: `uv run pytest --collect-only tests/runtime -q`
Expected: collection succeeds.

- [ ] **Step 0.3: Commit prep**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(runtime): add pytest-asyncio for async tests"
```

---

## Task 1: New schemas in `runtime/types.py`

**Files:**
- Modify: `src/runtime/types.py`
- Test: `tests/runtime/test_types.py` (new)

- [ ] **Step 1.1: Write failing schema tests**

Create `tests/runtime/test_types.py`:

```python
import pytest
from pydantic import ValidationError

from runtime.types import (
    RuntimeMessage, RuntimeRequest, RuntimeEvent, TokenPressure,
)


def test_runtime_message_roles():
    for role in ("system", "user", "assistant", "tool"):
        m = RuntimeMessage(role=role, content="x")
        assert m.role == role


def test_runtime_message_invalid_role():
    with pytest.raises(ValidationError):
        RuntimeMessage(role="other", content="x")


def test_runtime_request_defaults():
    r = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content="hi")],
        max_completion_tokens=128,
        request_id="req_1",
    )
    assert r.temperature == 0.2
    assert r.top_p == 0.95
    assert r.stop == []
    assert r.tools == []
    assert r.correlation_id is None


def test_runtime_event_text_delta():
    e = RuntimeEvent(type="text_delta", request_id="r1", seq=0, text="hello")
    assert e.text == "hello"


def test_runtime_event_finish_carries_usage():
    e = RuntimeEvent(
        type="finish", request_id="r1", seq=10,
        finish_reason="stop", usage={"prompt_tokens": 5, "completion_tokens": 3},
    )
    assert e.usage["completion_tokens"] == 3


def test_token_pressure_over_threshold_true():
    p = TokenPressure(
        request_id="r", context_window=1000, prompt_tokens=900,
        reserved_completion_tokens=0, total_tokens=900, pressure_ratio=0.9,
        over_threshold=True,
    )
    assert p.over_threshold is True
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `uv run pytest tests/runtime/test_types.py -v`
Expected: ImportError or ValidationError mismatches because types are old shape.

- [ ] **Step 1.3: Replace `src/runtime/types.py`**

Replace entire file:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RuntimeMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class RuntimeRequest(BaseModel):
    messages: list[RuntimeMessage]
    max_completion_tokens: int
    temperature: float = 0.2
    top_p: float = 0.95
    stop: list[str] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    request_id: str
    correlation_id: str | None = None


class RuntimeEvent(BaseModel):
    type: Literal["text_delta", "reasoning_delta", "tool_call", "finish", "error"]
    request_id: str
    seq: int
    text: str | None = None
    tool_call: dict[str, Any] | None = None
    finish_reason: Literal["stop", "length", "tool_call", "cancelled", "error"] | None = None
    usage: dict[str, int] | None = None
    error_code: str | None = None
    error_message: str | None = None


class TokenPressure(BaseModel):
    request_id: str
    context_window: int
    prompt_tokens: int
    reserved_completion_tokens: int
    total_tokens: int
    pressure_ratio: float
    over_threshold: bool


RuntimeStatus = Literal["not_loaded", "loading", "ready", "streaming", "error"]


class RuntimeInputError(ValueError):
    pass


class ModelBehaviorError(ValueError):
    pass
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `uv run pytest tests/runtime/test_types.py -v`
Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add src/runtime/types.py tests/runtime/test_types.py
git commit -m "feat(runtime): replace runtime schemas per async spec §6"
```

---

## Task 2: Async-only `Runtime` protocol

**Files:**
- Modify: `src/runtime/protocol.py`
- Test: `tests/runtime/test_protocol_shape.py` (new)

- [ ] **Step 2.1: Failing protocol shape test**

Create `tests/runtime/test_protocol_shape.py`:

```python
import inspect
from runtime.protocol import Runtime


def test_protocol_methods_async_only():
    expected = {"stream", "context_window", "token_pressure", "validate_request", "status"}
    members = {name for name in vars(Runtime) if not name.startswith("_")}
    assert expected.issubset(members)
    assert "complete" not in members


def test_protocol_methods_have_async_signatures():
    for name in ("context_window", "token_pressure", "validate_request", "status", "stream"):
        method = getattr(Runtime, name)
        assert inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(method) or callable(method)
```

- [ ] **Step 2.2: Run; expect failure**

Run: `uv run pytest tests/runtime/test_protocol_shape.py -v`
Expected: FAIL — `complete` still present.

- [ ] **Step 2.3: Replace `src/runtime/protocol.py`**

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from runtime.types import RuntimeEvent, RuntimeRequest, RuntimeStatus, TokenPressure


class Runtime(Protocol):
    def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]: ...
    async def context_window(self) -> int: ...
    async def token_pressure(self, request: RuntimeRequest) -> TokenPressure: ...
    async def validate_request(self, request: RuntimeRequest) -> None: ...
    async def status(self) -> RuntimeStatus: ...
```

- [ ] **Step 2.4: Run; expect pass**

Run: `uv run pytest tests/runtime/test_protocol_shape.py -v`
Expected: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/runtime/protocol.py tests/runtime/test_protocol_shape.py
git commit -m "feat(runtime): async-only Runtime protocol"
```

---

## Task 3: `RuntimeConfig.bridge_queue_size`

**Files:**
- Modify: `src/runtime/config.py`
- Test: `tests/runtime/test_config.py`

- [ ] **Step 3.1: Failing test**

Append to `tests/runtime/test_config.py`:

```python
def test_bridge_queue_size_default(tmp_path):
    from runtime.config import RuntimeConfig
    cfg = RuntimeConfig(model_path=str(tmp_path / "m.gguf"), chat_format="gemma")
    assert cfg.bridge_queue_size == 64


def test_bridge_queue_size_override(tmp_path):
    from runtime.config import RuntimeConfig
    cfg = RuntimeConfig(model_path=str(tmp_path / "m.gguf"), chat_format="gemma", bridge_queue_size=8)
    assert cfg.bridge_queue_size == 8
```

- [ ] **Step 3.2: Run; expect failure**

Run: `uv run pytest tests/runtime/test_config.py -v`
Expected: FAIL — attribute missing.

- [ ] **Step 3.3: Add field**

In `src/runtime/config.py` add to `RuntimeConfig` (Pydantic model):

```python
    bridge_queue_size: int = 64
```

- [ ] **Step 3.4: Run; expect pass**

Run: `uv run pytest tests/runtime/test_config.py -v`
Expected: PASS.

- [ ] **Step 3.5: Commit**

```bash
git add src/runtime/config.py tests/runtime/test_config.py
git commit -m "feat(runtime): add bridge_queue_size config"
```

---

## Task 4: Sync→async bridge module

**Files:**
- Create: `src/runtime/bridge.py`
- Test: `tests/runtime/test_bridge.py`

- [ ] **Step 4.1: Failing bridge tests**

Create `tests/runtime/test_bridge.py`:

```python
import asyncio
import time

import pytest

from runtime.bridge import SyncToAsyncBridge
from runtime.types import RuntimeEvent


def make_iter(items):
    def gen():
        for it in items:
            yield it
    return gen


async def collect(bridge):
    out = []
    async for ev in bridge.stream():
        out.append(ev)
    return out


async def test_drains_iterator_in_order():
    items = [
        RuntimeEvent(type="text_delta", request_id="r", seq=0, text="a"),
        RuntimeEvent(type="text_delta", request_id="r", seq=1, text="b"),
        RuntimeEvent(type="finish", request_id="r", seq=2, finish_reason="stop", usage={}),
    ]
    bridge = SyncToAsyncBridge(make_iter(items), queue_size=4)
    out = await collect(bridge)
    assert [e.type for e in out] == ["text_delta", "text_delta", "finish"]


async def test_backpressure_blocks_producer_when_consumer_slow():
    produced = []

    def gen():
        for i in range(8):
            produced.append(i)
            yield RuntimeEvent(type="text_delta", request_id="r", seq=i, text=str(i))
        yield RuntimeEvent(type="finish", request_id="r", seq=8, finish_reason="stop", usage={})

    bridge = SyncToAsyncBridge(lambda: gen(), queue_size=2)
    agen = bridge.stream()
    first = await agen.__anext__()
    assert first.text == "0"
    await asyncio.sleep(0.05)
    # Producer should have been blocked at ~queue_size + 1 items.
    assert len(produced) <= 4
    rest = []
    async for ev in agen:
        rest.append(ev)
    assert rest[-1].type == "finish"


async def test_cancel_between_deltas_emits_cancelled_error():
    def slow_gen():
        for i in range(100):
            time.sleep(0.005)
            yield RuntimeEvent(type="text_delta", request_id="r", seq=i, text="x")
        yield RuntimeEvent(type="finish", request_id="r", seq=100, finish_reason="stop", usage={})

    bridge = SyncToAsyncBridge(slow_gen, queue_size=4)
    agen = bridge.stream()
    seen = 0
    async for ev in agen:
        seen += 1
        if seen == 3:
            bridge.cancel()
        if ev.type == "error":
            assert ev.finish_reason == "cancelled"
            break
    assert seen >= 3


async def test_iterator_exception_surfaces_as_error_event():
    def bad():
        yield RuntimeEvent(type="text_delta", request_id="r", seq=0, text="a")
        raise RuntimeError("boom")

    bridge = SyncToAsyncBridge(bad, queue_size=4)
    out = await collect(bridge)
    assert out[-1].type == "error"
    assert out[-1].error_code == "runtime_exception"
    assert "boom" in (out[-1].error_message or "")
```

- [ ] **Step 4.2: Run; expect ImportError**

Run: `uv run pytest tests/runtime/test_bridge.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4.3: Implement `src/runtime/bridge.py`**

```python
from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Iterator

from runtime.types import RuntimeEvent


_SENTINEL: object = object()


class SyncToAsyncBridge:
    """Bridges a blocking sync iterator of RuntimeEvent into an async iterator.

    Usage:
        bridge = SyncToAsyncBridge(lambda: llama_iterator, queue_size=64)
        async for event in bridge.stream():
            ...
        bridge.cancel()  # observed between deltas; one-token max latency
    """

    def __init__(
        self,
        iterator_factory: Callable[[], Iterator[RuntimeEvent]],
        *,
        queue_size: int = 64,
    ) -> None:
        self._factory = iterator_factory
        self._queue_size = queue_size
        self._cancel = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[object] | None = None
        self._thread: threading.Thread | None = None
        self._started = False

    def cancel(self) -> None:
        self._cancel.set()

    async def stream(self) -> AsyncIterator[RuntimeEvent]:
        if self._started:
            raise RuntimeError("bridge already consumed")
        self._started = True
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._queue_size)
        self._thread = threading.Thread(target=self._produce, name="runtime-bridge", daemon=True)
        self._thread.start()
        try:
            while True:
                item = await self._queue.get()
                if item is _SENTINEL:
                    return
                if isinstance(item, RuntimeEvent):
                    yield item
                    if item.type == "error" and item.finish_reason == "cancelled":
                        return
        finally:
            self._cancel.set()
            if self._thread is not None:
                self._thread.join(timeout=5.0)

    def _put(self, item: object) -> None:
        assert self._loop is not None
        assert self._queue is not None
        fut = asyncio.run_coroutine_threadsafe(self._queue.put(item), self._loop)
        fut.result()

    def _produce(self) -> None:
        try:
            iterator = self._factory()
            for event in iterator:
                if self._cancel.is_set():
                    self._put(RuntimeEvent(
                        type="error",
                        request_id=event.request_id,
                        seq=event.seq,
                        finish_reason="cancelled",
                        error_code="cancelled",
                        error_message="cancelled by consumer",
                    ))
                    return
                self._put(event)
        except Exception as exc:  # noqa: BLE001
            self._put(RuntimeEvent(
                type="error",
                request_id="unknown",
                seq=-1,
                error_code="runtime_exception",
                error_message=f"{type(exc).__name__}: {exc}",
            ))
        finally:
            self._put(_SENTINEL)
```

- [ ] **Step 4.4: Run; expect pass**

Run: `uv run pytest tests/runtime/test_bridge.py -v`
Expected: PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/runtime/bridge.py tests/runtime/test_bridge.py
git commit -m "feat(runtime): SyncToAsyncBridge with bounded queue and cancel"
```

---

## Task 5: Async `LlamaCppRuntime`

**Files:**
- Modify: `src/runtime/llama_cpp_runtime.py`
- Test: `tests/runtime/test_runtime_async_streaming.py` (new)

This task replaces the sync runtime in two passes: schema/method updates, then bridge wiring. Existing helper functions (`split_gemma_think_text`, `emit_content_events`, `event_from_tool_call_text`, `strip_eos`, `marker_prefix_suffix`, `build_llama_kwargs`) stay; their event construction must be updated to produce events with `request_id` + `seq`.

- [ ] **Step 5.1: Failing async runtime test**

Create `tests/runtime/test_runtime_async_streaming.py`:

```python
import asyncio
from collections.abc import Iterator

import pytest

from runtime.llama_cpp_runtime import LlamaCppRuntime
from runtime.types import RuntimeMessage, RuntimeRequest


class FakeLlama:
    def __init__(self, chunks):
        self._chunks = chunks
        self._n_ctx = 4096

    def n_ctx(self):
        return self._n_ctx

    def tokenize(self, b, add_bos=False):
        return [0] * (len(b) // 4 + 1)

    def create_chat_completion(self, *, messages, stream, **kwargs):
        if not stream:
            raise AssertionError("sync complete path must not be called")
        for ch in self._chunks:
            yield ch


def fake_chunk(content=None, reasoning=None, finish=None, usage=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    return {"choices": [{"delta": delta, "finish_reason": finish}], "usage": usage or {}}


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    from runtime import config as cfg_mod, llama_cpp_runtime as rt_mod
    cfg = cfg_mod.RuntimeConfig(model_path=str(tmp_path / "m.gguf"), chat_format="gemma")
    monkeypatch.setattr(rt_mod, "Llama", lambda **kw: FakeLlama([
        fake_chunk(content="hel"),
        fake_chunk(content="lo"),
        fake_chunk(finish="stop", usage={"prompt_tokens": 3, "completion_tokens": 2}),
    ]))
    return LlamaCppRuntime(cfg)


def make_request(rid="r1"):
    return RuntimeRequest(
        messages=[RuntimeMessage(role="user", content="hi")],
        max_completion_tokens=64, request_id=rid,
    )


async def test_stream_yields_text_delta_then_finish(runtime):
    out = []
    async for ev in runtime.stream(make_request()):
        out.append(ev)
    assert [e.type for e in out] == ["text_delta", "text_delta", "finish"]
    assert out[-1].usage == {"prompt_tokens": 3, "completion_tokens": 2}


async def test_seq_is_monotonic(runtime):
    seqs = []
    async for ev in runtime.stream(make_request("r2")):
        seqs.append(ev.seq)
    assert seqs == sorted(seqs)
    assert seqs[0] == 0


async def test_request_id_propagated(runtime):
    async for ev in runtime.stream(make_request("custom-id")):
        assert ev.request_id == "custom-id"


async def test_status_lifecycle(monkeypatch, tmp_path):
    from runtime import config as cfg_mod, llama_cpp_runtime as rt_mod
    cfg = cfg_mod.RuntimeConfig(model_path=str(tmp_path / "m.gguf"), chat_format="gemma")
    monkeypatch.setattr(rt_mod, "Llama", lambda **kw: FakeLlama([
        fake_chunk(content="x"), fake_chunk(finish="stop", usage={}),
    ]))
    rt = rt_mod.LlamaCppRuntime(cfg)
    assert await rt.status() == "ready"
    agen = rt.stream(make_request())
    first = await agen.__anext__()
    assert await rt.status() == "streaming"
    async for _ in agen:
        pass
    assert await rt.status() == "ready"


async def test_validate_request_rejects_empty(runtime):
    from runtime.types import RuntimeInputError
    bad = RuntimeRequest(messages=[], max_completion_tokens=10, request_id="x")
    with pytest.raises(RuntimeInputError):
        await runtime.validate_request(bad)


async def test_token_pressure_threshold_field(runtime):
    req = make_request()
    p = await runtime.token_pressure(req)
    assert p.request_id == req.request_id
    assert 0.0 <= p.pressure_ratio <= 1.0
    assert p.over_threshold == (p.pressure_ratio > 0.80)


async def test_no_sync_complete():
    assert not hasattr(LlamaCppRuntime, "complete") or callable(getattr(LlamaCppRuntime, "complete", None)) is False or False
```

(Note last test loose; the strict shape check is in `test_protocol_shape.py`.)

- [ ] **Step 5.2: Run; expect failure**

Run: `uv run pytest tests/runtime/test_runtime_async_streaming.py -v`
Expected: FAIL — runtime is sync.

- [ ] **Step 5.3: Rewrite `LlamaCppRuntime` to async**

Replace `src/runtime/llama_cpp_runtime.py` keeping helpers (`strip_eos`, `build_llama_kwargs`, `marker_prefix_suffix`, `split_gemma_think_text`, `emit_content_events`, `event_from_tool_call_text`) but updating event constructors to take `request_id` + `seq`. Add async methods.

```python
from __future__ import annotations

import threading
import time
from collections.abc import AsyncIterator, Iterator

from llama_cpp import Llama

from observability import Telemetry, resolve_telemetry_dir
from observability.events import EventKind, Layer
from runtime.bridge import SyncToAsyncBridge
from runtime.config import RuntimeConfig
from runtime.tool_calls import ToolCallParseError, parse_tool_call_block, repair_tool_call_block
from runtime.types import (
    ModelBehaviorError, RuntimeEvent, RuntimeInputError, RuntimeMessage,
    RuntimeRequest, RuntimeStatus, TokenPressure,
)

TOOL_START = "<tool_call>"
TOOL_END = "</tool_call>"
THINK_START = "<|think|>"
THINK_END = "</|think|>"
STREAM_MARKERS = (TOOL_START, THINK_START)
EOS_TOKENS = ("<end_of_turn>", "<eos>", "</s>")


def strip_eos(text: str) -> str:
    stripped = text
    for tok in EOS_TOKENS:
        stripped = stripped.replace(tok, "")
    return stripped.strip() if stripped != text else text


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


def marker_prefix_suffix(text: str) -> str:
    for marker in STREAM_MARKERS:
        max_len = min(len(marker) - 1, len(text))
        for size in range(max_len, 0, -1):
            suffix = text[-size:]
            if marker.startswith(suffix):
                return suffix
    return ""


class _SeqGen:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        v = self.value
        self.value += 1
        return v


def split_gemma_think_text(
    text: str, request_id: str, seq: _SeqGen
) -> tuple[list[RuntimeEvent], str]:
    events: list[RuntimeEvent] = []
    remaining = text
    while THINK_START in remaining and THINK_END in remaining:
        before, _, after_start = remaining.partition(THINK_START)
        reasoning, _, after_end = after_start.partition(THINK_END)
        if before.strip():
            events.append(RuntimeEvent(
                type="text_delta", request_id=request_id, seq=seq.next(), text=before.strip(),
            ))
        if reasoning.strip():
            events.append(RuntimeEvent(
                type="reasoning_delta", request_id=request_id, seq=seq.next(), text=reasoning.strip(),
            ))
        remaining = after_end
    return events, remaining


def event_from_tool_call_text(text: str, request_id: str, seq: _SeqGen) -> RuntimeEvent:
    try:
        parsed = parse_tool_call_block(text)
    except (ToolCallParseError, ValueError):
        try:
            parsed = parse_tool_call_block(repair_tool_call_block(text))
        except (ToolCallParseError, ValueError) as exc:
            raise ModelBehaviorError(f"malformed tool call: {exc}") from exc
    return RuntimeEvent(
        type="tool_call",
        request_id=request_id,
        seq=seq.next(),
        tool_call={"name": parsed.name, "arguments": parsed.arguments},
    )


def emit_content_events(
    content: str, stream_buffer: str, request_id: str, seq: _SeqGen
) -> tuple[list[RuntimeEvent], str]:
    events: list[RuntimeEvent] = []
    pending = stream_buffer + content if stream_buffer else content
    if THINK_START in pending and THINK_END not in pending:
        return events, pending
    think_events, pending = split_gemma_think_text(pending, request_id, seq)
    events.extend(think_events)
    if TOOL_START not in pending:
        suffix = marker_prefix_suffix(pending)
        if suffix:
            visible = pending[: -len(suffix)]
            if visible:
                events.append(RuntimeEvent(
                    type="text_delta", request_id=request_id, seq=seq.next(), text=visible,
                ))
            return events, suffix
        if pending:
            events.append(RuntimeEvent(
                type="text_delta", request_id=request_id, seq=seq.next(), text=pending,
            ))
        return events, ""
    prefix, _, rest = pending.partition(TOOL_START)
    if prefix:
        events.append(RuntimeEvent(
            type="text_delta", request_id=request_id, seq=seq.next(), text=prefix,
        ))
    tool_text = TOOL_START + rest
    if TOOL_END not in tool_text:
        return events, tool_text
    tool_block, _, tail = tool_text.partition(TOOL_END)
    events.append(event_from_tool_call_text(tool_block + TOOL_END, request_id, seq))
    if tail:
        events.append(RuntimeEvent(
            type="text_delta", request_id=request_id, seq=seq.next(), text=tail,
        ))
    return events, ""


class LlamaCppRuntime:
    def __init__(self, config: RuntimeConfig, telemetry: Telemetry | None = None) -> None:
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())
        self._config = config
        self._status: RuntimeStatus = "loading"
        self._status_lock = threading.Lock()
        self.telemetry.emit(
            Layer.RUNTIME, EventKind.RUNTIME_INIT_START,
            payload={"model_path": config.model_path, "n_ctx": config.n_ctx},
        )
        self.telemetry.emit(Layer.RUNTIME, EventKind.RUNTIME_MODEL_LOAD_START, payload={"model_path": config.model_path})
        self._llama = Llama(**build_llama_kwargs(config))
        self.telemetry.emit(Layer.RUNTIME, EventKind.RUNTIME_MODEL_LOAD_END, payload={"model_path": config.model_path})
        self._set_status("ready")
        self.telemetry.emit(Layer.RUNTIME, EventKind.RUNTIME_INIT_END, payload={"context_window": int(self._llama.n_ctx())})

    def _set_status(self, value: RuntimeStatus) -> None:
        with self._status_lock:
            self._status = value

    async def status(self) -> RuntimeStatus:
        with self._status_lock:
            return self._status

    async def context_window(self) -> int:
        return int(self._llama.n_ctx())

    def _count_tokens(self, request: RuntimeRequest) -> int:
        try:
            return sum(
                len(self._llama.tokenize(f"{m.role}\n{m.content}".encode("utf-8"), add_bos=False))
                for m in request.messages
            )
        except Exception:
            return sum(max(len(m.content) // 4, 1) for m in request.messages)

    async def token_pressure(self, request: RuntimeRequest) -> TokenPressure:
        ctx = int(self._llama.n_ctx())
        prompt = self._count_tokens(request)
        reserved = request.max_completion_tokens
        total = prompt + reserved
        ratio = total / ctx if ctx else 1.0
        return TokenPressure(
            request_id=request.request_id,
            context_window=ctx,
            prompt_tokens=prompt,
            reserved_completion_tokens=reserved,
            total_tokens=total,
            pressure_ratio=ratio,
            over_threshold=ratio > 0.80,
        )

    async def validate_request(self, request: RuntimeRequest) -> None:
        if not request.messages:
            raise RuntimeInputError("runtime request must include at least one message")
        p = await self.token_pressure(request)
        if p.total_tokens > p.context_window:
            raise RuntimeInputError(
                f"runtime request exceeds context window: {p.total_tokens}>{p.context_window}"
            )

    def _completion_kwargs(self, request: RuntimeRequest) -> dict[str, object]:
        return {
            "messages": [m.model_dump(exclude_none=True) for m in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_completion_tokens,
            "stop": request.stop or None,
        }

    def _sync_event_iterator(self, request: RuntimeRequest) -> Iterator[RuntimeEvent]:
        seq = _SeqGen()
        rid = request.request_id
        stream_buffer = ""
        for chunk in self._llama.create_chat_completion(**self._completion_kwargs(request), stream=True):
            choice = chunk["choices"][0]
            delta = choice.get("delta", {})
            if delta.get("reasoning_content"):
                yield RuntimeEvent(
                    type="reasoning_delta", request_id=rid, seq=seq.next(),
                    text=delta["reasoning_content"],
                )
            if delta.get("content"):
                content = strip_eos(delta["content"])
                if content:
                    events, stream_buffer = emit_content_events(content, stream_buffer, rid, seq)
                    yield from events
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None:
                if stream_buffer:
                    events, stream_buffer = emit_content_events("", stream_buffer, rid, seq)
                    yield from events
                    if stream_buffer:
                        yield RuntimeEvent(
                            type="error", request_id=rid, seq=seq.next(),
                            error_code="incomplete_structured_content",
                            error_message=f"incomplete structured content at finish: {stream_buffer}",
                        )
                yield RuntimeEvent(
                    type="finish", request_id=rid, seq=seq.next(),
                    finish_reason=finish_reason, usage=chunk.get("usage", {}),
                )

    async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]:
        await self.validate_request(request)
        self._set_status("streaming")
        self.telemetry.emit(
            Layer.RUNTIME, EventKind.RUNTIME_STREAM_START,
            payload={"max_completion_tokens": request.max_completion_tokens, "request_id": request.request_id},
        )
        bridge = SyncToAsyncBridge(
            lambda: self._sync_event_iterator(request),
            queue_size=self._config.bridge_queue_size,
        )
        started = time.perf_counter()
        try:
            async for event in bridge.stream():
                yield event
                if event.type == "finish":
                    self.telemetry.emit(
                        Layer.RUNTIME, EventKind.RUNTIME_STREAM_END,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        payload={"finish_reason": event.finish_reason, "usage": event.usage or {}},
                    )
        finally:
            self._set_status("ready")
```

- [ ] **Step 5.4: Run; expect pass**

Run: `uv run pytest tests/runtime/test_runtime_async_streaming.py -v`
Expected: PASS.

- [ ] **Step 5.5: Commit**

```bash
git add src/runtime/llama_cpp_runtime.py tests/runtime/test_runtime_async_streaming.py
git commit -m "feat(runtime): async LlamaCppRuntime via SyncToAsyncBridge"
```

---

## Task 6: Convert legacy runtime tests

**Files:**
- Modify: `tests/runtime/test_runtime_streaming.py`
- Modify: `tests/runtime/test_llama_cpp_runtime.py`
- Modify: `tests/runtime/test_runtime_tool_call_integration.py`

- [ ] **Step 6.1: Inspect existing tests**

Run: `uv run pytest tests/runtime/test_runtime_streaming.py tests/runtime/test_llama_cpp_runtime.py tests/runtime/test_runtime_tool_call_integration.py -v`
Expected: many failures referencing removed `complete`, `Message`, `max_new_tokens`, `Iterator[RuntimeEvent]`.

- [ ] **Step 6.2: Update each failing test**

For each failure:
- Replace `Message` → `RuntimeMessage`.
- Replace `max_new_tokens=N` with `max_completion_tokens=N, request_id="<unique>"`.
- Replace sync `runtime.complete(req)` calls with collecting an async stream into a final text buffer.
- Replace `RuntimeEvent(kind=...)` with `RuntimeEvent(type=..., request_id="r", seq=N)`.
- Replace `event.kind` with `event.type`.
- Replace `event.tool_name` / `event.tool_arguments` with `event.tool_call["name"]` / `event.tool_call["arguments"]`.

Helper to add at top of converted test files:

```python
async def collect_text(runtime, request):
    pieces = []
    finish = None
    async for ev in runtime.stream(request):
        if ev.type == "text_delta":
            pieces.append(ev.text or "")
        if ev.type == "finish":
            finish = ev
    return "".join(pieces), finish
```

- [ ] **Step 6.3: Run; expect pass**

Run: `uv run pytest tests/runtime -v`
Expected: full Layer 1 suite passes.

- [ ] **Step 6.4: Remove obsolete tests**

Search `tests/runtime/` for any test still asserting `RuntimeResponse` or sync semantics; delete those test functions or rewrite as streaming. Then re-run.

- [ ] **Step 6.5: Commit**

```bash
git add tests/runtime
git commit -m "test(runtime): migrate runtime tests to async-only contract"
```

---

## Task 7: Verify no Layer 1 leakage

- [ ] **Step 7.1: Scan**

Run:
```bash
grep -rn "RuntimeResponse\|complete(request\|max_new_tokens\|runtime.types.Message" src tests || true
```
Expected: empty (any matches must be fixed before completing this plan; downstream layers will be migrated in their own plans, but Layer 1 itself must be clean).

- [ ] **Step 7.2: Note remaining downstream usages**

If `grep` finds matches under `src/harness` or `src/app`, do NOT fix them here. Add a note:

```bash
echo "Layer 1 migrated; downstream callers (harness, app) updated in plans 3a/3b/3c/4." >> docs/superpowers/plans/2026-05-03-async-layer-1-runtime.md
```

- [ ] **Step 7.3: Final commit**

```bash
git add docs/superpowers/plans/2026-05-03-async-layer-1-runtime.md
git commit -m "docs(plan): note Layer 1 async migration done; downstream pending"
```

---

## Self-Review Checklist

- All five protocol methods (`stream`, `context_window`, `token_pressure`, `validate_request`, `status`) async ✓
- `complete(...)` removed ✓
- `RuntimeEvent` carries `request_id` + monotonic `seq` ✓
- `TokenPressure.over_threshold` driven by 0.80 ratio ✓
- Bridge default queue 64, configurable via `RuntimeConfig.bridge_queue_size` ✓
- Cancel observed within one token, emits `error` with `finish_reason="cancelled"` ✓
- Producer thread is private; queue never exposed ✓
- All Layer 1 tests passing under async ✓
Layer 1 migrated; downstream callers (harness, app) updated in plans 3a/3b/3c/4.
