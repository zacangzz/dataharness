import pytest

from harness.approval import TimedDecisionGate


def test_non_execution_decision_auto_proceeds_after_timeout() -> None:
    gate = TimedDecisionGate()
    decision = gate.wait(eligible_for_auto_proceed=True, timeout_seconds=0.01)
    assert decision == "auto_proceed"


def test_code_execution_decision_never_auto_proceeds() -> None:
    gate = TimedDecisionGate()
    with pytest.raises(TimeoutError):
        gate.wait(eligible_for_auto_proceed=False, timeout_seconds=0.01)


def test_user_decision_overrides_auto_proceed() -> None:
    gate = TimedDecisionGate()
    gate.submit_user_decision("approved")
    decision = gate.wait(eligible_for_auto_proceed=True, timeout_seconds=0.5)
    assert decision == "approved"


def test_user_cancel_blocks_auto_proceed() -> None:
    gate = TimedDecisionGate()
    gate.cancel()
    with pytest.raises(InterruptedError):
        gate.wait(eligible_for_auto_proceed=True, timeout_seconds=0.5)
