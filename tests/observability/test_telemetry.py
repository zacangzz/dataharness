from __future__ import annotations

import json
import threading
from uuid import uuid4

from observability import Telemetry, bind_boot, bind_session, bind_step, bind_turn
from observability.events import EventKind, Layer, Outcome, TelemetryEvent


def _events(path):
    return [TelemetryEvent.model_validate_json(line) for line in path.read_text().splitlines()]


def test_emit_writes_jsonl_with_context_ids(tmp_path) -> None:
    telemetry = Telemetry(tmp_path)
    boot_id = uuid4()
    session_id = uuid4()
    turn_id = uuid4()

    with bind_boot(boot_id), bind_session(session_id), bind_turn(turn_id), bind_step("step_1"):
        event = telemetry.emit(Layer.APP, EventKind.APP_INPUT, payload={"chars": 2})

    events = _events(tmp_path / "app.events.jsonl")
    assert events == [event]
    assert events[0].boot_id == boot_id
    assert events[0].session_id == session_id
    assert events[0].turn_id == turn_id
    assert events[0].step_id == "step_1"
    assert events[0].payload == {"chars": 2}


def test_emit_error_includes_traceback(tmp_path) -> None:
    telemetry = Telemetry(tmp_path)

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        event = telemetry.emit_error(Layer.APP, EventKind.APP_ERROR, phase="compose", exc=exc)

    assert event.outcome is Outcome.ERROR
    assert event.payload["phase"] == "compose"
    assert event.payload["exception_type"] == "RuntimeError"
    assert event.payload["message"] == "boom"
    assert "Traceback" in event.payload["traceback"]


def test_concurrent_emits_write_complete_json_lines(tmp_path) -> None:
    telemetry = Telemetry(tmp_path)

    def emit_many() -> None:
        for index in range(25):
            telemetry.emit(Layer.WORKER, EventKind.WORKER_DISPATCH_START, payload={"index": index})

    threads = [threading.Thread(target=emit_many) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = (tmp_path / "worker.events.jsonl").read_text().splitlines()
    assert len(lines) == 50
    assert all(json.loads(line)["kind"] == "worker.dispatch.start" for line in lines)
