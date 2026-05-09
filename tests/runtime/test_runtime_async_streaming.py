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


def test_no_sync_complete():
    assert not hasattr(LlamaCppRuntime, "complete")


async def test_stream_end_emitted_on_cancel(monkeypatch, tmp_path):
    """RUNTIME_STREAM_END must fire even when stream is cancelled early."""
    from runtime import config as cfg_mod, llama_cpp_runtime as rt_mod
    from observability.events import EventKind

    class InfiniteChunkLlama:
        def n_ctx(self):
            return 4096

        def tokenize(self, b, add_bos=False):
            return [0] * (len(b) // 4 + 1)

        def create_chat_completion(self, *, messages, stream, **kwargs):
            i = 0
            while True:
                yield fake_chunk(content=f"tok{i}")
                i += 1

    cfg = cfg_mod.RuntimeConfig(model_path=str(tmp_path / "m.gguf"), chat_format="gemma")
    monkeypatch.setattr(rt_mod, "Llama", lambda **kw: InfiniteChunkLlama())

    emitted = []

    class CaptureTelemetry:
        def emit(self, layer, kind, *, duration_ms=None, payload=None):
            emitted.append((kind, payload))

    rt = rt_mod.LlamaCppRuntime(cfg, telemetry=CaptureTelemetry())

    count = 0
    agen = rt.stream(make_request("cancel-test"))
    try:
        async for ev in agen:
            count += 1
            if count >= 3:
                break  # exit early — cancel path
    finally:
        await agen.aclose()

    stream_end_events = [(k, p) for k, p in emitted if k == EventKind.RUNTIME_STREAM_END]
    assert len(stream_end_events) == 1, f"expected 1 RUNTIME_STREAM_END, got {stream_end_events}"
    assert stream_end_events[0][1].get("finish_reason") is not None
