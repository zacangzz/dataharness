from __future__ import annotations

from uuid import UUID

from observability import resolve_log_dir, resolve_telemetry_dir
from observability.events import EventKind, Layer, Outcome, TelemetryEvent


def test_event_contract_contains_required_layers_outcomes_and_kinds() -> None:
    assert {layer.value for layer in Layer} == {
        "bootstrap",
        "app",
        "harness",
        "runtime",
        "worker",
        "persistence",
    }
    assert {outcome.value for outcome in Outcome} == {"ok", "error"}
    required_kinds = {
        "bootstrap.start",
        "bootstrap.import.error",
        "app.lifecycle.constructed",
        "app.lifecycle.initial_view",
        "app.compose.start",
        "app.compose.widget",
        "app.compose.end",
        "app.mount.start",
        "app.mount.end",
        "app.ready",
        "app.screen.snapshot",
        "app.widget.health",
        "app.error",
        "turn.start",
        "turn.end",
        "turn.error",
        "agent.mode.proposed",
        "harness.turn.received",
        "harness.context.rebuild.start",
        "harness.context.rebuild.end",
        "harness.mode.activated",
        "harness.prompt.built",
        "harness.plan.built",
        "harness.approval.gate",
        "harness.step.resume",
        "harness.step.dispatch",
        "harness.turn.completed",
        "harness.error",
        "runtime.init.start",
        "runtime.init.end",
        "runtime.model.load.start",
        "runtime.model.load.end",
        "runtime.prompt.built",
        "runtime.model.call.start",
        "runtime.model.call.end",
        "runtime.stream.start",
        "runtime.stream.end",
        "runtime.tool_call.parsed",
        "runtime.token_pressure",
        "runtime.error",
        "worker.dispatch.start",
        "worker.sandbox.config",
        "worker.subprocess.start",
        "worker.subprocess.end",
        "worker.dispatch.end",
        "worker.timeout",
        "worker.sandbox.violation",
        "worker.error",
        "persistence.write.start",
        "persistence.write.end",
        "persistence.error",
    }
    assert required_kinds <= {kind.value for kind in EventKind}


def test_telemetry_event_round_trips_json() -> None:
    event = TelemetryEvent(layer=Layer.APP, kind=EventKind.APP_READY, payload={"screen": "main"})

    decoded = TelemetryEvent.model_validate_json(event.model_dump_json())

    assert isinstance(decoded.event_id, UUID)
    assert decoded.layer is Layer.APP
    assert decoded.kind is EventKind.APP_READY
    assert decoded.outcome is Outcome.OK
    assert decoded.payload == {"screen": "main"}


def test_default_observability_paths_use_plan_sink_layout() -> None:
    assert resolve_log_dir().parts[-2:] == ("harness", "logs")
    assert resolve_telemetry_dir().parts[-2:] == ("harness", "telemetry")
