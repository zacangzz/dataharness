from __future__ import annotations

import asyncio
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
TOOL_START_MARKERS = (TOOL_START, "tool_call>")
THINK_START = "<|channel>thought"
THINK_END = "<channel|>"
LEGACY_THINK_START = "<|think|>"
LEGACY_THINK_END = "</|think|>"
THINK_START_MARKERS = (THINK_START, LEGACY_THINK_START)
THINK_END_MARKERS = (THINK_END, LEGACY_THINK_END)
STREAM_MARKERS = (*TOOL_START_MARKERS, *THINK_START_MARKERS)
EOS_TOKENS = ("<end_of_turn>", "<eos>", "</s>")


def strip_eos(text: str) -> str:
    stripped = text
    for tok in EOS_TOKENS:
        stripped = stripped.replace(tok, "")
    return stripped.strip() if stripped != text else text


def strip_full_eos(text: str) -> str:
    """Remove any complete EOS literal occurrences without trimming surrounding whitespace."""
    out = text
    for tok in EOS_TOKENS:
        out = out.replace(tok, "")
    return out


def eos_prefix_suffix(text: str) -> str:
    """Return the longest trailing substring of `text` that is a strict prefix of any EOS token."""
    for marker in EOS_TOKENS:
        max_len = min(len(marker) - 1, len(text))
        for size in range(max_len, 0, -1):
            suffix = text[-size:]
            if marker.startswith(suffix):
                return suffix
    return ""


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


def _prefix_suffix_for(text: str, markers: tuple[str, ...]) -> str:
    for marker in markers:
        max_len = min(len(marker) - 1, len(text))
        for size in range(max_len, 0, -1):
            suffix = text[-size:]
            if marker.startswith(suffix):
                return suffix
    return ""


def _find_earliest_marker(text: str, markers: tuple[str, ...]) -> tuple[int, str] | None:
    found: tuple[int, str] | None = None
    for marker in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        if found is None or idx < found[0]:
            found = (idx, marker)
    return found


class _SeqGen:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        v = self.value
        self.value += 1
        return v


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
    content: str,
    stream_buffer: str,
    request_id: str,
    seq: _SeqGen,
    *,
    in_reasoning: bool = False,
    enable_reasoning_stream: bool = True,
) -> tuple[list[RuntimeEvent], str, bool]:
    """Statefully emit events from content. returns (events, new_buffer, in_reasoning)."""
    events: list[RuntimeEvent] = []
    pending = stream_buffer + content if stream_buffer else content
    pending = strip_full_eos(pending)

    current_in_reasoning = in_reasoning

    while pending:
        if current_in_reasoning:
            end = _find_earliest_marker(pending, THINK_END_MARKERS)
            if end is not None:
                end_idx, end_marker = end
                before = pending[:end_idx]
                if before and enable_reasoning_stream:
                    events.append(RuntimeEvent(
                        type="reasoning_delta", request_id=request_id, seq=seq.next(), text=before,
                    ))
                pending = pending[end_idx + len(end_marker):]
                current_in_reasoning = False
                continue
            suffix = _prefix_suffix_for(pending, THINK_END_MARKERS) or eos_prefix_suffix(pending)
            visible = pending[: -len(suffix)] if suffix else pending
            if visible and enable_reasoning_stream:
                events.append(RuntimeEvent(
                    type="reasoning_delta", request_id=request_id, seq=seq.next(), text=visible,
                ))
            return events, suffix, True

        marker = _find_earliest_marker(pending, (*TOOL_START_MARKERS, *THINK_START_MARKERS))
        if marker is None:
            suffix = marker_prefix_suffix(pending) or eos_prefix_suffix(pending)
            visible = pending[: -len(suffix)] if suffix else pending
            if visible:
                events.append(RuntimeEvent(
                    type="text_delta", request_id=request_id, seq=seq.next(), text=visible,
                ))
            return events, suffix, False

        marker_idx, marker_text = marker
        if marker_idx:
            prefix = pending[:marker_idx]
            events.append(RuntimeEvent(
                type="text_delta", request_id=request_id, seq=seq.next(), text=prefix,
            ))
            pending = pending[marker_idx:]
            continue

        if marker_text in THINK_START_MARKERS:
            pending = pending[len(marker_text):]
            current_in_reasoning = True
            continue

        if marker_text in TOOL_START_MARKERS:
            tool_text = pending
            if TOOL_END not in tool_text:
                return events, tool_text, False
            tool_block, _, pending = tool_text.partition(TOOL_END)
            events.append(event_from_tool_call_text(tool_block + TOOL_END, request_id, seq))
            continue

    return events, "", current_in_reasoning


class LlamaCppRuntime:
    def __init__(self, config: RuntimeConfig, telemetry: Telemetry | None = None) -> None:
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())
        self._config = config
        self._status: RuntimeStatus = "loading"
        self._status_lock = threading.Lock()
        self._llama_lock = asyncio.Lock()
        self._last_parse_error: str = ""
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

    @property
    def chat_format(self) -> str:
        return self._config.chat_format

    async def context_window(self) -> int:
        async with self._llama_lock:
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
        async with self._llama_lock:
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
        msgs = [m.model_dump(exclude_none=True) for m in request.messages]
        if self._config.chat_format == "gemma":
            system_msg = next((m for m in msgs if m["role"] == "system"), None)
            if system_msg:
                msgs = [m for m in msgs if m["role"] != "system"]
                user_msg = next((m for m in msgs if m["role"] == "user"), None)
                if user_msg:
                    user_msg["content"] = f"{system_msg['content']}\n\n{user_msg['content']}"
                else:
                    msgs.insert(0, {"role": "user", "content": system_msg["content"]})
        return {
            "messages": msgs,
            "temperature": request.temperature,
            "top_k": request.top_k,
            "top_p": request.top_p,
            "max_tokens": request.max_completion_tokens,
            "stop": request.stop or None,
        }

    def _sync_event_iterator(self, request: RuntimeRequest) -> Iterator[RuntimeEvent]:
        seq = _SeqGen()
        rid = request.request_id
        stream_buffer = ""
        parse_error = ""
        in_reasoning = False
        for chunk in self._llama.create_chat_completion(**self._completion_kwargs(request), stream=True):
            choice = chunk["choices"][0]
            delta = choice.get("delta", {})
            if delta.get("reasoning_content") and self._config.enable_reasoning_stream:
                yield RuntimeEvent(
                    type="reasoning_delta", request_id=rid, seq=seq.next(),
                    text=delta["reasoning_content"],
                )
            if delta.get("content"):
                content = delta["content"]
                if content:
                    try:
                        events, stream_buffer, in_reasoning = emit_content_events(
                            content,
                            stream_buffer,
                            rid,
                            seq,
                            in_reasoning=in_reasoning,
                            enable_reasoning_stream=self._config.enable_reasoning_stream,
                        )
                    except ModelBehaviorError as exc:
                        parse_error = str(exc)
                        yield RuntimeEvent(
                            type="error", request_id=rid, seq=seq.next(),
                            error_code="parse_error",
                            error_message=str(exc),
                        )
                        events = []
                        stream_buffer = ""
                        in_reasoning = False
                    yield from events
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None:
                if stream_buffer:
                    flush_buffer = strip_full_eos(stream_buffer)
                    eos_tail = eos_prefix_suffix(flush_buffer)
                    if eos_tail:
                        flush_buffer = flush_buffer[: -len(eos_tail)]
                    stream_buffer = ""
                    if flush_buffer:
                        try:
                            events, stream_buffer, in_reasoning = emit_content_events(
                                flush_buffer,
                                "",
                                rid,
                                seq,
                                in_reasoning=in_reasoning,
                                enable_reasoning_stream=self._config.enable_reasoning_stream,
                            )
                        except ModelBehaviorError as exc:
                            parse_error = str(exc)
                            yield RuntimeEvent(
                                type="error", request_id=rid, seq=seq.next(),
                                error_code="parse_error",
                                error_message=str(exc),
                            )
                            events = []
                            stream_buffer = ""
                            in_reasoning = False
                        yield from events
                    if stream_buffer:
                        yield RuntimeEvent(
                            type="error", request_id=rid, seq=seq.next(),
                            error_code="incomplete_structured_content",
                            error_message=f"incomplete structured content at finish: {stream_buffer}",
                        )
                if finish_reason == "unknown" or finish_reason is None:
                    if seq.value == 0:
                        finish_reason = "empty_stream"
                    elif parse_error:
                        finish_reason = "parse_error"
                    else:
                        finish_reason = "truncated"
                diagnostics: dict[str, Any] | None = None
                if finish_reason == "empty_stream":
                    diagnostics = {"empty_stream": True}
                elif finish_reason == "parse_error":
                    diagnostics = {"parse_error_snippet": parse_error[:200]}
                elif finish_reason == "truncated":
                    diagnostics = {"total_deltas": seq.value}
                yield RuntimeEvent(
                    type="finish", request_id=rid, seq=seq.next(),
                    finish_reason=finish_reason, usage=chunk.get("usage", {}),
                    diagnostics=diagnostics,
                )

    async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]:
        await self.validate_request(request)
        self._set_status("streaming")
        self.telemetry.emit(
            Layer.RUNTIME, EventKind.RUNTIME_STREAM_START,
            payload={"max_completion_tokens": request.max_completion_tokens, "request_id": request.request_id},
        )
        started = time.perf_counter()
        terminal_finish_reason: str | None = None
        async with self._llama_lock:
            bridge = SyncToAsyncBridge(
                lambda: self._sync_event_iterator(request),
                queue_size=self._config.bridge_queue_size,
            )
            try:
                async for event in bridge.stream():
                    yield event
                    if event.type == "finish":
                        terminal_finish_reason = event.finish_reason
                    elif event.type == "error":
                        terminal_finish_reason = event.finish_reason or event.error_code or "error"
            finally:
                self.telemetry.emit(
                    Layer.RUNTIME, EventKind.RUNTIME_STREAM_END,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    payload={"finish_reason": terminal_finish_reason or "unknown"},
                )
                self._set_status("ready")
