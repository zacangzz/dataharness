from __future__ import annotations

from rich.text import Text
from textual._context import NoActiveAppError
from textual.widgets import Static


class ArtifactPanel(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.renderable = Text("(no artifacts)")

    def set_artifacts(self, artifacts: list[dict]) -> None:
        text = "\n".join(f"- {item['path']} ({item['type']})" for item in artifacts)
        self.renderable = Text(text or "(no artifacts)")
        try:
            self.update(self.renderable)
        except NoActiveAppError:
            pass
