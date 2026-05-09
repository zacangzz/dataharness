from __future__ import annotations

import logging

from observability import Telemetry, configure_logging
from observability.events import EventKind, Layer


def test_configure_logging_routes_layer_logs_and_mirrors_events(tmp_path) -> None:
    configure_logging(tmp_path)

    logging.getLogger("app.session").info("hello app")
    logging.getLogger("runtime.llama_cpp").info("hello runtime")
    logging.getLogger("unknown").warning("hello bootstrap")
    Telemetry(tmp_path).emit(Layer.APP, EventKind.APP_READY, payload={"screen": "main"})

    assert "hello app" in (tmp_path / "app.log").read_text()
    assert "hello runtime" in (tmp_path / "runtime.log").read_text()
    assert "hello bootstrap" in (tmp_path / "bootstrap.log").read_text()
    app_log = (tmp_path / "app.log").read_text()
    assert "kind=app.ready" in app_log
    assert "event=" in app_log


def test_configure_logging_is_idempotent(tmp_path) -> None:
    configure_logging(tmp_path)
    configure_logging(tmp_path)

    logging.getLogger("harness.orchestrator").info("once")

    assert (tmp_path / "harness.log").read_text().count("once") == 1
