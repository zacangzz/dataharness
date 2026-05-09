from __future__ import annotations

import asyncio

from app.tui.app import DataHarnessApp
from observability import Telemetry
from observability.events import TelemetryEvent


def _event_kinds(path):
    return [TelemetryEvent.model_validate_json(line).kind.value for line in path.read_text().splitlines()]


def test_app_construction_and_compose_emit_blank_screen_diagnostics(tmp_path) -> None:
    telemetry = Telemetry(tmp_path)
    app = DataHarnessApp(telemetry=telemetry)

    widgets = list(app.compose())

    kinds = _event_kinds(tmp_path / "app.events.jsonl")
    assert "app.lifecycle.constructed" in kinds
    assert "app.compose.start" in kinds
    assert kinds.count("app.compose.widget") == len(widgets)
    assert "app.compose.end" in kinds


def test_app_mount_emits_screen_snapshot(tmp_path) -> None:
    app = DataHarnessApp(telemetry=Telemetry(tmp_path))

    async def run_app() -> None:
        async with app.run_test():
            pass

    asyncio.run(run_app())

    kinds = _event_kinds(tmp_path / "app.events.jsonl")
    assert "app.mount.start" in kinds
    assert "app.mount.end" in kinds
    assert "app.screen.snapshot" in kinds
