import pytest

from runtime.config import RuntimeConfig
from runtime.llama_cpp_runtime import LlamaCppRuntime
from runtime.types import RuntimeMessage, ModelBehaviorError, RuntimeInputError, RuntimeRequest


class FakeLlama:
    def __init__(self, chunks: list[dict] | None = None) -> None:
        self.chunks = chunks or []
        self.tokenize_inputs: list[bytes] = []

    def n_ctx(self) -> int:
        return 128

    def tokenize(self, value: bytes, add_bos: bool = False) -> list[int]:
        self.tokenize_inputs.append(value)
        return list(range(max(len(value) // 4, 1)))

    def create_chat_completion(self, **kwargs):
        if kwargs.get("stream"):
            return iter(self.chunks)
        raise AssertionError("sync complete path must not be called")


class _NullTelemetry:
    def emit(self, *args, **kwargs):
        pass
    def emit_error(self, *args, **kwargs):
        pass


def make_runtime(fake: FakeLlama) -> LlamaCppRuntime:
    runtime = LlamaCppRuntime.__new__(LlamaCppRuntime)
    import threading
    runtime._config = RuntimeConfig(model_path="model.gguf", n_ctx=128)
    runtime._llama = fake
    runtime._status = "ready"
    runtime._status_lock = threading.Lock()
    runtime.telemetry = _NullTelemetry()
    return runtime


def make_request(content: str = "call doctor") -> RuntimeRequest:
    return RuntimeRequest(
        messages=[RuntimeMessage(role="user", content=content)],
        max_completion_tokens=16,
        request_id="req-1",
    )


async def collect_events(runtime, request):
    events = []
    async for ev in runtime.stream(request):
        events.append(ev)
    return events


async def collect_text(runtime, request):
    pieces = []
    finish = None
    async for ev in runtime.stream(request):
        if ev.type == "text_delta":
            pieces.append(ev.text or "")
        if ev.type == "finish":
            finish = ev
    return "".join(pieces), finish


async def test_stream_emits_tool_call_event_before_finish() -> None:
    chunks = [
        {"choices": [{"delta": {"content": '<tool_call>{"name":"doctor","arguments":{"mode":"manual"}}</tool_call>'}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = await collect_events(runtime, make_request())
    assert [event.type for event in events] == ["tool_call", "finish"]
    assert events[0].tool_call["arguments"] == {"mode": "manual"}


async def test_stream_buffers_tool_call_split_across_chunks() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<tool_call>{"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": '"name":"doctor",'}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": '"arguments":{"mode":"manual"}}</tool_call>'}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = await collect_events(runtime, make_request())
    assert [event.type for event in events] == ["tool_call", "finish"]
    assert events[0].tool_call["name"] == "doctor"
    assert events[0].tool_call["arguments"] == {"mode": "manual"}


async def test_stream_buffers_split_tool_call_opening_tag() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<tool"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": '_call>{"name":"doctor","arguments":{"mode":"manual"}}</tool_call>'}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = await collect_events(runtime, make_request())
    assert [event.type for event in events] == ["tool_call", "finish"]
    assert events[0].tool_call["name"] == "doctor"


async def test_stream_splits_gemma_think_block_across_chunks() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<|think|>inspect "}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "columns</|think|>Ready."}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = await collect_events(runtime, make_request())
    assert [event.type for event in events] == ["reasoning_delta", "text_delta", "finish"]
    assert events[0].text == "inspect columns"
    assert events[1].text == "Ready."


async def test_token_pressure_uses_llama_tokenizer_when_available() -> None:
    fake = FakeLlama()
    runtime = make_runtime(fake)
    pressure = await runtime.token_pressure(make_request("one two three four"))
    assert fake.tokenize_inputs
    assert pressure.prompt_tokens > 0
    assert pressure.context_window == 128


async def test_runtime_rejects_over_budget_request_before_dispatch() -> None:
    runtime = make_runtime(FakeLlama())
    with pytest.raises(RuntimeInputError, match="exceeds context window"):
        await runtime.validate_request(make_request("x" * 600))


async def test_stream_emits_error_event_then_finish_when_buffer_incomplete_at_finish() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<tool_call>{\"name\":\"doctor\""}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = await collect_events(runtime, make_request())
    types = [event.type for event in events]
    assert "error" in types
    assert types[-1] == "finish"
    error_event = next(event for event in events if event.type == "error")
    assert "incomplete structured content at finish" in (error_event.error_message or "")


async def test_stream_repairs_malformed_tool_call() -> None:
    chunks = [
        {"choices": [{"delta": {"content": '<tool_call>{"name":"doctor","arguments":"manual"}</tool_call>'}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    runtime = make_runtime(FakeLlama(chunks=chunks))
    events = await collect_events(runtime, make_request())
    tool_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_call["name"] == "doctor"
    assert tool_events[0].tool_call["arguments"] == {"value": "manual"}
