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
    assert cfg.type_k == 8
    assert cfg.type_v == 8
    assert cfg.n_gpu_layers == -1
    assert cfg.flash_attn is True
    assert cfg.enable_reasoning_stream is True


def test_runtime_config_does_not_own_session_concurrency_policy() -> None:
    assert "max_parallel_runs" not in RuntimeConfig.model_fields


def test_bridge_queue_size_default(tmp_path):
    from runtime.config import RuntimeConfig
    cfg = RuntimeConfig(model_path=str(tmp_path / "m.gguf"), chat_format="gemma")
    assert cfg.bridge_queue_size == 64


def test_bridge_queue_size_override(tmp_path):
    from runtime.config import RuntimeConfig
    cfg = RuntimeConfig(model_path=str(tmp_path / "m.gguf"), chat_format="gemma", bridge_queue_size=8)
    assert cfg.bridge_queue_size == 8
