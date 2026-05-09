from __future__ import annotations

from typing import Any

from rich.text import Text
from textual._context import NoActiveAppError
from textual.widgets import Static


class ContextBar(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._dataset = ""
        self._validity = ""
        self._compacted = False
        self._doctor_report: dict[str, Any] | None = None
        self._review_proposal: dict[str, Any] | None = None
        self.renderable = Text("")

    def _refresh(self) -> None:
        lines: list[str] = []
        if self._dataset or self._validity:
            base = " | ".join(filter(None, [self._dataset, self._validity]))
            if self._compacted:
                base = f"{base} | reduced history active"
            lines.append(base)
        if self._doctor_report is not None:
            report = self._doctor_report
            lines.append(
                "Doctor report: "
                f"valid={len(report.get('still_valid', []))} "
                f"review={len(report.get('recommend_review', []))}"
            )
        if self._review_proposal is not None:
            proposal = self._review_proposal
            lines.append(
                "Review proposal: "
                f"observations={len(proposal.get('quality_observations', []))}"
            )
        self.renderable = Text("\n".join(lines))
        try:
            self.update(self.renderable)
        except NoActiveAppError:
            pass

    def set_state(self, *, dataset: str, validity: str, compacted: bool) -> None:
        self._dataset = dataset
        self._validity = validity
        self._compacted = compacted
        self._refresh()

    def set_doctor_report(self, report: dict[str, Any]) -> None:
        self._doctor_report = report
        self._refresh()

    def set_review_proposal(self, proposal: dict[str, Any]) -> None:
        self._review_proposal = proposal
        self._refresh()

    def reset(self) -> None:
        self._dataset = ""
        self._validity = ""
        self._compacted = False
        self._doctor_report = None
        self._review_proposal = None
        self._refresh()
