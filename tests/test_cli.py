from __future__ import annotations

from types import SimpleNamespace

import pytest

import cli


def test_main_help_exits_before_building_tui(monkeypatch, capsys):
    def fail_build(*args, **kwargs):
        raise AssertionError("help should not construct the TUI")

    monkeypatch.setattr(cli, "build_app", fail_build)
    monkeypatch.setattr(cli.sys, "argv", ["dataharness", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert "usage: dataharness" in capsys.readouterr().out


def test_main_passes_default_runtime_factory(monkeypatch):
    captured = {}

    class FakeApp:
        def run(self) -> None:
            captured["ran"] = True

    def fake_build(telemetry, **kwargs):
        captured.update(kwargs)
        return FakeApp()

    monkeypatch.setattr(cli, "build_app", fake_build)
    monkeypatch.setattr(cli.sys, "argv", ["dataharness"])

    cli.main()

    assert captured["ran"] is True
    assert callable(captured["runtime_factory"])


def test_main_dispatches_packaged_worker_bootstrap_before_building_tui(monkeypatch):
    captured = {}

    def fail_build(*args, **kwargs):
        raise AssertionError("worker bootstrap should not construct the TUI")

    def fake_bootstrap_main() -> int:
        captured["argv"] = list(cli.sys.argv)
        return 17

    def fake_import_module(name: str):
        if name == "worker.sandbox_bootstrap":
            return SimpleNamespace(main=fake_bootstrap_main)
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(cli, "build_app", fail_build)
    monkeypatch.setattr(cli.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(cli.sys, "argv", ["dataharness", "-m", "worker.sandbox_bootstrap", "sandbox_config.json"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 17
    assert captured["argv"] == ["worker.sandbox_bootstrap", "sandbox_config.json"]


def test_main_rejects_unknown_private_module_without_building_tui(monkeypatch, capsys):
    def fail_build(*args, **kwargs):
        raise AssertionError("unknown -m target should not construct the TUI")

    monkeypatch.setattr(cli, "build_app", fail_build)
    monkeypatch.setattr(cli.sys, "argv", ["dataharness", "-m", "not.allowed", "config.json"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "unsupported private module target: not.allowed" in capsys.readouterr().err
