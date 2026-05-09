from __future__ import annotations

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static


class ApprovalScreen(Screen[None]):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, *, plan: dict | None = None, step_contract: dict | None = None) -> None:
        super().__init__(name="approval")
        self.id = "approval"
        self._plan = plan or {}
        self._step_contract = step_contract or {}

    def compose(self):
        yield Vertical(
            Static(f"Approve plan: {self._plan.get('goal', '(unknown goal)')}", id="approval_prompt"),
            Static(f"Step: {self._step_contract.get('step_id', '?')}", id="approval_step"),
            Button("Approve", id="approve"),
            Button("Reject", id="reject"),
            Button("Revise", id="revise"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        decision = {"approve": "approved", "reject": "rejected", "revise": "revise_requested"}[event.button.id]
        handler = getattr(self.app, "handle_approval_decision", None)
        if handler is not None:
            handler(self._plan, self._step_contract, decision)


class ClarificationScreen(Screen[None]):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, *, question: str = "Clarification required") -> None:
        super().__init__(name="clarification")
        self.id = "clarification"
        self._question = question

    def compose(self):
        yield Vertical(
            Static(self._question, id="clarification_prompt"),
            Input(placeholder="Your clarification...", id="clarification_input"),
            Button("Submit", id="submit_clarification"),
        )

    async def submit_clarification(self, text: str) -> None:
        handler = getattr(self.app, "handle_clarification_response", None)
        if handler is not None:
            handler(text)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit_clarification":
            text = self.query_one("#clarification_input", Input).value
            await self.submit_clarification(text)
