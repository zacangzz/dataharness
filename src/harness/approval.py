from __future__ import annotations

import threading


class TimedDecisionGate:
    """10-second auto-proceed window per spec §6.4 for non-execution decisions only.

    Code-execution decisions never auto-proceed; they raise TimeoutError on expiry.
    A user-supplied decision overrides the timeout. cancel() raises InterruptedError.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._decision: str | None = None
        self._cancelled = False

    def submit_user_decision(self, decision: str) -> None:
        self._decision = decision
        self._event.set()

    def cancel(self) -> None:
        self._cancelled = True
        self._event.set()

    def wait(self, *, eligible_for_auto_proceed: bool, timeout_seconds: float) -> str:
        signaled = self._event.wait(timeout=timeout_seconds)
        if self._cancelled:
            raise InterruptedError("decision cancelled by user")
        if signaled and self._decision is not None:
            return self._decision
        if not eligible_for_auto_proceed:
            raise TimeoutError("code-execution decision requires explicit approval; no auto-proceed")
        return "auto_proceed"
