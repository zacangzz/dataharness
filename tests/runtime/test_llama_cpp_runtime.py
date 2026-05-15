import asyncio

from runtime.config import RuntimeConfig
from runtime.llama_cpp_runtime import LlamaCppRuntime, build_llama_kwargs
from runtime.types import RuntimeMessage, RuntimeRequest


async def collect_text(runtime, request):
    pieces = []
    finish = None
    async for ev in runtime.stream(request):
        if ev.type == "text_delta":
            pieces.append(ev.text or "")
        if ev.type == "finish":
            finish = ev
    return "".join(pieces), finish


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


def test_completion_kwargs_include_sampling_defaults() -> None:
    runtime = LlamaCppRuntime.__new__(LlamaCppRuntime)
    runtime._config = RuntimeConfig(model_path="dummy")
    request = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content="hi")],
        max_completion_tokens=128,
        request_id="r1",
    )
    kwargs = runtime._completion_kwargs(request)
    assert kwargs["temperature"] == 0.2
    assert kwargs["top_k"] == 64
    assert kwargs["top_p"] == 0.95


def test_completion_kwargs_pass_request_temperature_unchanged() -> None:
    runtime = LlamaCppRuntime.__new__(LlamaCppRuntime)
    runtime._config = RuntimeConfig(model_path="dummy")
    request = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content="hi")],
        max_completion_tokens=128,
        temperature=0.73,
        request_id="r1",
    )
    kwargs = runtime._completion_kwargs(request)
    assert kwargs["temperature"] == 0.73


async def test_runtime_exposes_token_pressure_report() -> None:
    cfg = RuntimeConfig(model_path="model.gguf", n_ctx=4096)

    class FakeLlama:
        def n_ctx(self):
            return 4096

        def tokenize(self, b, add_bos=False):
            return [0] * (len(b) // 4 + 1)

    runtime = LlamaCppRuntime.__new__(LlamaCppRuntime)
    runtime._config = cfg
    runtime._llama = FakeLlama()
    runtime._llama_lock = asyncio.Lock()
    request = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content="one two three four")],
        max_completion_tokens=512,
        request_id="r1",
    )
    pressure = await runtime.token_pressure(request)
    assert pressure.prompt_tokens > 0
    assert pressure.context_window == 4096
    assert pressure.reserved_completion_tokens == 512
