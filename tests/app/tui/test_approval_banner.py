"""ApprovalBanner: inline replacement for the full-screen ApprovalScreen.

Verifies show/hide, that decision buttons emit ApprovalDecisionMade with the
right decision string, and that bound keys map to the same message.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from app.tui.widgets import ApprovalBanner


class _Host(App):
    """Minimal host app to mount the banner under a Textual run loop."""

    captured: list[ApprovalBanner.ApprovalDecisionMade]

    def __init__(self) -> None:
        super().__init__()
        self.captured = []

    def compose(self) -> ComposeResult:
        yield ApprovalBanner(id="approval_banner")

    def on_approval_banner_approval_decision_made(
        self, message: ApprovalBanner.ApprovalDecisionMade
    ) -> None:
        self.captured.append(message)


PLAN = {"id": "plan_1", "goal": "count rows"}
STEP = {
    "step_id": "s1",
    "purpose": "count",
    "code": "print(len([1,2,3]))",
    "declared_inputs": ["data/customers.csv"],
    "expected_outputs": ["result.txt"],
}


@pytest.mark.asyncio
async def test_show_hide_toggles_display():
    async with _Host().run_test() as pilot:
        banner = pilot.app.query_one("#approval_banner", ApprovalBanner)
        assert banner.display is False
        banner.show(plan=PLAN, step_contract=STEP)
        assert banner.display is True
        banner.hide()
        assert banner.display is False


@pytest.mark.asyncio
async def test_approve_key_emits_decision():
    async with _Host().run_test() as pilot:
        banner = pilot.app.query_one("#approval_banner", ApprovalBanner)
        banner.show(plan=PLAN, step_contract=STEP)
        await pilot.press("a")
        await pilot.pause()
        assert any(m.decision == "approved" for m in pilot.app.captured)


@pytest.mark.asyncio
async def test_reject_key_emits_decision():
    async with _Host().run_test() as pilot:
        banner = pilot.app.query_one("#approval_banner", ApprovalBanner)
        banner.show(plan=PLAN, step_contract=STEP)
        await pilot.press("r")
        await pilot.pause()
        assert any(m.decision == "rejected" for m in pilot.app.captured)


@pytest.mark.asyncio
async def test_revise_key_emits_decision():
    async with _Host().run_test() as pilot:
        banner = pilot.app.query_one("#approval_banner", ApprovalBanner)
        banner.show(plan=PLAN, step_contract=STEP)
        await pilot.press("v")
        await pilot.pause()
        assert any(m.decision == "revise_requested" for m in pilot.app.captured)


@pytest.mark.asyncio
async def test_show_with_hostile_brackets_does_not_raise():
    hostile_step = {
        **STEP,
        "code": "x = [1,2,3]  # [TOOL_RESULT] not markup",
        "declared_inputs": ["[bracketed].csv"],
    }
    async with _Host().run_test() as pilot:
        banner = pilot.app.query_one("#approval_banner", ApprovalBanner)
        banner.show(plan={"id": "p", "goal": "test [brackets]"}, step_contract=hostile_step)
        await pilot.pause()
        assert banner.display is True
