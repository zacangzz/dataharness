from __future__ import annotations

from rich.text import Text
from textual._context import NoActiveAppError
from textual.widgets import Static


class PlanPanel(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._steps: list[dict] = []
        self._active_step_id: str | None = None
        self._active_step_title: str | None = None
        self._completed_steps: dict[str, str] = {}
        self.renderable = Text("(no plan)")

    def _refresh(self) -> None:
        lines: list[str] = []
        for step in self._steps:
            step_id = str(step.get("id", "step"))
            title = str(step.get("title", ""))
            lines.append(f"- {step_id}: {title}")
        if self._active_step_id is not None:
            title = self._active_step_title or ""
            suffix = f": {title}" if title else ""
            lines.append(f"[active] {self._active_step_id}{suffix}")
        for step_id, status in self._completed_steps.items():
            lines.append(f"[completed] {step_id} ({status})")
        self.renderable = Text("\n".join(lines) or "(no plan)")
        try:
            self.update(self.renderable)
        except NoActiveAppError:
            pass

    def set_plan(self, plan: dict) -> None:
        self._steps = list(plan.get("steps", []))
        self._active_step_id = None
        self._active_step_title = None
        self._completed_steps.clear()
        self._refresh()

    def reset(self) -> None:
        self._steps = []
        self._active_step_id = None
        self._active_step_title = None
        self._completed_steps.clear()
        self._refresh()

    def mark_active_step(self, step_id: str, title: str | None = None) -> None:
        self._active_step_id = step_id
        self._active_step_title = title
        self._refresh()

    def mark_completed_step(self, step_id: str, status: str) -> None:
        self._completed_steps[step_id] = status
        if self._active_step_id == step_id:
            self._active_step_id = None
            self._active_step_title = None
        self._refresh()
