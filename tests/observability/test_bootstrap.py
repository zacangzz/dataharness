from __future__ import annotations

import importlib
import sys

import pytest


def test_importing_cli_does_not_import_textual_app() -> None:
    sys.modules.pop("cli", None)
    sys.modules.pop("app.tui.app", None)

    importlib.import_module("cli")

    assert "app.tui.app" not in sys.modules


def test_main_logs_import_error(monkeypatch, tmp_path) -> None:
    import cli

    monkeypatch.setattr(cli, "resolve_log_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "resolve_telemetry_dir", lambda: tmp_path)

    def boom(module_name: str):
        raise RuntimeError(f"import boom: {module_name}")

    monkeypatch.setattr(cli.importlib, "import_module", boom)

    with pytest.raises(RuntimeError, match="import boom"):
        cli.main()

    assert "bootstrap.import.error" in (tmp_path / "bootstrap.log").read_text()
    assert "import boom" in (tmp_path / "bootstrap.log").read_text()
    assert "bootstrap.import.error" in (tmp_path / "bootstrap.events.jsonl").read_text()


def test_main_logs_run_error(monkeypatch, tmp_path) -> None:
    import cli

    monkeypatch.setattr(cli, "resolve_log_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "resolve_telemetry_dir", lambda: tmp_path)

    class FakeApp:
        def run(self) -> None:
            raise RuntimeError("run boom")

    monkeypatch.setattr(cli, "build_app", lambda telemetry, **_kwargs: FakeApp())

    with pytest.raises(RuntimeError, match="run boom"):
        cli.main()

    text = (tmp_path / "bootstrap.log").read_text()
    assert "bootstrap.run.start" in text
    assert "bootstrap.error" in text
    assert "run boom" in text
