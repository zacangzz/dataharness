from __future__ import annotations

from collections import deque


class RunTrace:
    def __init__(self, *, max_lines: int = 20) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        self.current_phase = "idle"

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    def command_started(self, command: str) -> None:
        self.current_phase = f"{command} started"
        self._lines.append(f"{command}: started")

    def command_progress(
        self, command: str, phase: str, phase_index: int, phase_total: int
    ) -> None:
        self.current_phase = phase
        self._lines.append(f"{command}: {phase} {phase_index}/{phase_total}")

    def command_completed(self, command: str, result: dict) -> None:
        self.current_phase = f"{command} complete"
        if "error" in result:
            self._lines.append(f"{command}: {result['error']}")
        else:
            self._lines.append(f"{command}: complete")

    def turn_started(self, active_mode: str) -> None:
        self.current_phase = f"{active_mode} turn started"
        self._lines.append(self.current_phase)

    def runtime_delta(self, delta_type: str) -> None:
        self.current_phase = f"runtime {delta_type}"

    def final_message(self) -> None:
        self.current_phase = "final response"
        self._lines.append("final response")

    def cancelled(self, reason: str) -> None:
        self.current_phase = "cancelled"
        self._lines.append(f"cancelled: {reason}")

    def failed(self, summary: str, error_code: str) -> None:
        self.current_phase = "failed"
        self._lines.append(f"{error_code}: {summary}")
