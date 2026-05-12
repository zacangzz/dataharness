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
    bridge_queue_size: int = 64
