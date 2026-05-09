from __future__ import annotations

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
