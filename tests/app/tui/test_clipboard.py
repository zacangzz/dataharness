import subprocess

from app.tui.clipboard import NativeClipboard


class _Completed:
    def __init__(self, stdout: str = "") -> None:
        self.stdout = stdout


def test_native_clipboard_uses_macos_pbcopy_and_pbpaste():
    calls: list[tuple[list[str], str | None]] = []

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"pbcopy", "pbpaste"} else None

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs.get("input")))
        return _Completed(stdout="from pasteboard")

    clipboard = NativeClipboard(platform="darwin", which=which, run=run)

    assert clipboard.copy("hello") is True
    assert clipboard.paste() == "from pasteboard"
    assert calls[0] == (["/usr/bin/pbcopy"], "hello")
    assert calls[1] == (["/usr/bin/pbpaste"], None)


def test_native_clipboard_returns_fallback_signals_when_no_provider_exists():
    clipboard = NativeClipboard(platform="linux", which=lambda _name: None)

    assert clipboard.copy("hello") is False
    assert clipboard.paste() is None


def test_native_clipboard_ignores_provider_failures():
    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"wl-copy", "wl-paste"} else None

    def run(_argv, **_kwargs):
        raise subprocess.SubprocessError("clipboard unavailable")

    clipboard = NativeClipboard(platform="linux", which=which, run=run)

    assert clipboard.copy("hello") is False
    assert clipboard.paste() is None
