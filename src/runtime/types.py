from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


KNOWN_FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "empty_stream", "parse_error", "truncated"})


class RuntimeMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class RuntimeRequest(BaseModel):
    messages: list[RuntimeMessage]
    max_completion_tokens: int
    temperature: float = 1.0
    top_k: int = 64
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
    finish_reason: Literal["stop", "length", "tool_call", "cancelled", "error", "empty_stream", "parse_error", "truncated"] | None = None
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
