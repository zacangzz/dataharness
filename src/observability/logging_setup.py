from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from observability.events import Layer, Outcome
from observability.telemetry import current_boot_id, current_session_id, current_step_id, current_turn_id

LAYER_NAMES = tuple(layer.value for layer in Layer)
FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "boot=%(boot_id)s session=%(session_id)s turn=%(turn_id)s step=%(step_id)s "
    "event=%(event_id)s kind=%(kind)s outcome=%(outcome)s %(message)s"
)


class TelemetryContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        event = getattr(record, "telemetry_event", None)
        record.boot_id = str(getattr(event, "boot_id", None) or current_boot_id() or "-")
        record.session_id = str(getattr(event, "session_id", None) or current_session_id() or "-")
        record.turn_id = str(getattr(event, "turn_id", None) or current_turn_id() or "-")
        record.step_id = str(getattr(event, "step_id", None) or current_step_id() or "-")
        record.event_id = str(getattr(event, "event_id", "-"))
        record.kind = getattr(getattr(event, "kind", None), "value", "-")
        record.outcome = getattr(getattr(event, "outcome", None), "value", Outcome.OK.value)
        return True


def _handler(path: Path) -> RotatingFileHandler:
    handler = RotatingFileHandler(path, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FORMAT))
    handler.addFilter(TelemetryContextFilter())
    return handler


def _clear_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _install_exception_hooks() -> None:
    root = logging.getLogger()

    def excepthook(exc_type, exc, tb) -> None:
        root.error("uncaught exception", exc_info=(exc_type, exc, tb))

    def threading_excepthook(args: threading.ExceptHookArgs) -> None:
        root.error("uncaught thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = threading_excepthook


def configure_logging(log_dir: Path | str) -> Path:
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    _clear_handlers(root)
    root.addHandler(_handler(log_path / "bootstrap.log"))
    if os.getenv("DATAHARNESS_LOG_STDERR") == "1":
        stderr = logging.StreamHandler()
        stderr.setFormatter(logging.Formatter(FORMAT))
        stderr.addFilter(TelemetryContextFilter())
        root.addHandler(stderr)

    for layer in LAYER_NAMES:
        logger = logging.getLogger(layer)
        logger.setLevel(logging.INFO)
        logger.propagate = layer == Layer.BOOTSTRAP.value
        _clear_handlers(logger)
        if layer != Layer.BOOTSTRAP.value:
            logger.addHandler(_handler(log_path / f"{layer}.log"))

    _install_exception_hooks()
    return log_path
