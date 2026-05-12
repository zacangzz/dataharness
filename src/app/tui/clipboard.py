from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Protocol


class ClipboardProvider(Protocol):
    def copy(self, text: str) -> bool:
        """Copy text to the system clipboard if available."""

    def paste(self) -> str | None:
        """Return text from the system clipboard, or None if unavailable."""


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
WhichCommand = Callable[[str], str | None]


class NativeClipboard:
    """Best-effort OS clipboard provider for terminal TUI builds."""

    def __init__(
        self,
        *,
        platform: str | None = None,
        which: WhichCommand = shutil.which,
        run: RunCommand = subprocess.run,
        timeout_seconds: float = 1.0,
    ) -> None:
        self._platform = platform or sys.platform
        self._which = which
        self._run = run
        self._timeout_seconds = timeout_seconds

    def copy(self, text: str) -> bool:
        argv = self._copy_command()
        if argv is None:
            return False
        try:
            self._run(
                argv,
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            return False
        return True

    def paste(self) -> str | None:
        argv = self._paste_command()
        if argv is None:
            return None
        try:
            completed = self._run(
                argv,
                text=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            return None
        return completed.stdout

    def _copy_command(self) -> list[str] | None:
        if self._platform == "darwin":
            return self._command_if_found("pbcopy")
        if self._platform == "win32":
            shell = self._which("pwsh") or self._which("powershell")
            if shell:
                return [shell, "-NoProfile", "-Command", "$input | Set-Clipboard"]
            return self._command_if_found("clip")
        return self._first_found(
            ("wl-copy",),
            ("xclip", "-selection", "clipboard"),
            ("xsel", "--clipboard", "--input"),
        )

    def _paste_command(self) -> list[str] | None:
        if self._platform == "darwin":
            return self._command_if_found("pbpaste")
        if self._platform == "win32":
            shell = self._which("pwsh") or self._which("powershell")
            if shell:
                return [shell, "-NoProfile", "-Command", "Get-Clipboard -Raw"]
            return None
        return self._first_found(
            ("wl-paste", "--no-newline"),
            ("xclip", "-selection", "clipboard", "-out"),
            ("xsel", "--clipboard", "--output"),
        )

    def _command_if_found(self, name: str, *args: str) -> list[str] | None:
        path = self._which(name)
        if path is None:
            return None
        return [path, *args]

    def _first_found(self, *commands: Sequence[str]) -> list[str] | None:
        for command in commands:
            name, *args = command
            if found := self._command_if_found(name, *args):
                return found
        return None
