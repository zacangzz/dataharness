from __future__ import annotations

import logging
import threading
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator
from uuid import UUID

from observability.events import EventKind, Layer, Outcome, TelemetryEvent

_boot_id: ContextVar[UUID | None] = ContextVar("telemetry_boot_id", default=None)
_session_id: ContextVar[UUID | None] = ContextVar("telemetry_session_id", default=None)
_turn_id: ContextVar[UUID | None] = ContextVar("telemetry_turn_id", default=None)
_step_id: ContextVar[str | None] = ContextVar("telemetry_step_id", default=None)


def current_boot_id() -> UUID | None:
    return _boot_id.get()


def current_session_id() -> UUID | None:
    return _session_id.get()


def current_turn_id() -> UUID | None:
    return _turn_id.get()


def current_step_id() -> str | None:
    return _step_id.get()


@contextmanager
def bind_boot(boot_id: UUID | None) -> Iterator[None]:
    token = _boot_id.set(boot_id)
    try:
        yield
    finally:
        _boot_id.reset(token)


@contextmanager
def bind_session(session_id: UUID | None) -> Iterator[None]:
    token = _session_id.set(session_id)
    try:
        yield
    finally:
        _session_id.reset(token)


@contextmanager
def bind_turn(turn_id: UUID | None) -> Iterator[None]:
    token = _turn_id.set(turn_id)
    try:
        yield
    finally:
        _turn_id.reset(token)


@contextmanager
def bind_step(step_id: str | None) -> Iterator[None]:
    token = _step_id.set(step_id)
    try:
        yield
    finally:
        _step_id.reset(token)


class Telemetry:
    def __init__(self, log_dir: Path | str) -> None:
        self.log_dir = Path(log_dir)
        self._lock = threading.Lock()

    def emit(
        self,
        layer: Layer,
        kind: EventKind,
        *,
        payload: dict[str, object] | None = None,
        outcome: Outcome = Outcome.OK,
        duration_ms: float | None = None,
    ) -> TelemetryEvent:
        event = TelemetryEvent(
            layer=layer,
            kind=kind,
            outcome=outcome,
            boot_id=current_boot_id(),
            session_id=current_session_id(),
            turn_id=current_turn_id(),
            step_id=current_step_id(),
            duration_ms=duration_ms,
            payload=dict(payload or {}),
        )
        self.log_dir.mkdir(parents=True, exist_ok=True)
        event_path = self.log_dir / f"{layer.value}.events.jsonl"
        with self._lock:
            with event_path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json() + "\n")
        logging.getLogger(layer.value).info(
            "%s %s",
            event.kind.value,
            event.payload,
            extra={"telemetry_event": event},
        )
        return event

    def emit_error(self, layer: Layer, kind: EventKind, *, phase: str, exc: BaseException) -> TelemetryEvent:
        return self.emit(
            layer,
            kind,
            outcome=Outcome.ERROR,
            payload={
                "phase": phase,
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            },
        )
