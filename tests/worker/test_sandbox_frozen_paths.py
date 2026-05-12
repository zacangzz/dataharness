import sys
import sysconfig
from pathlib import Path

from worker import executor


def test_allowed_code_roots_includes_sys_path():
    roots = executor.allowed_code_roots()
    for entry in sys.path:
        if entry:
            assert str(Path(entry).resolve()) in roots


def test_allowed_code_roots_includes_sysconfig_paths():
    roots = executor.allowed_code_roots()
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        p = sysconfig.get_path(key)
        if p:
            assert str(Path(p).resolve()) in roots


def test_allowed_code_roots_includes_meipass_when_set(monkeypatch, tmp_path):
    fake_meipass = tmp_path / "meipass"
    fake_meipass.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    roots = executor.allowed_code_roots()
    assert str(fake_meipass.resolve()) in roots


def test_allowed_code_roots_includes_frozen_exe_parent(monkeypatch, tmp_path):
    fake_exe = tmp_path / "bin" / "dataharness"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    roots = executor.allowed_code_roots()
    assert str(fake_exe.resolve().parent) in roots


def test_allowed_code_roots_deduplicates():
    roots = executor.allowed_code_roots()
    assert len(roots) == len(set(roots))


def test_allowed_code_roots_no_meipass_without_frozen(monkeypatch):
    # In source-mode (non-frozen) tests, sys._MEIPASS is absent; the function
    # must return a sane list without raising.
    if hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS")
    roots = executor.allowed_code_roots()
    assert isinstance(roots, list)
    assert all(isinstance(r, str) for r in roots)
