"""Docked status bar showing workspace name and model loading status."""

from textual.reactive import reactive
from textual.widgets import Static

_SPINNER_CHARS = ["◐", "◑", "◒", "◓"]


class StatusBar(Static):
    """Status bar docked at top of ChatApp showing workspace and model status."""

    workspace_name: reactive[str] = reactive("default")
    model_status: reactive[str] = reactive("Loading ◐")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._spinner_index = 0

    def render(self) -> str:
        return f" Workspace: {self.workspace_name}  │  Model: {self.model_status}"

    def on_mount(self) -> None:
        self.set_interval(0.5, self._tick_spinner)

    def _tick_spinner(self) -> None:
        if not self.model_status.startswith("Loading"):
            return
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_CHARS)
        self.model_status = f"Loading {_SPINNER_CHARS[self._spinner_index]}"

    def start_loading(self) -> None:
        """Reset to initial loading state."""
        self._spinner_index = 0
        self.model_status = "Loading ◐"

    def set_loaded(self) -> None:
        """Mark model as loaded."""
        self.model_status = "Loaded ✓"

    def set_error(self) -> None:
        """Mark model load as failed."""
        self.model_status = "Error"

    def update_text(self, text: str, level: str = "idle") -> None:
        """Update the status bar with arbitrary text."""
        self.model_status = text
