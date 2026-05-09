from __future__ import annotations

from collections import deque
import json

from app.tui.help import HelpData
from textual.widgets import RichLog, Static


class WorkspaceBar(Static):
    can_focus = True
    help = HelpData(
        title="Workspace Bar",
        description="Shows the active workspace, run state, mode, runtime status, chat, and phase.",
    )

    def update_from(
        self,
        *,
        workspace_id: str,
        chat_id: str | None = None,
        run_state: str,
        active_mode: str,
        runtime_status: str = "checking",
        phase: str = "idle",
    ) -> None:
        chat = chat_id or "none"
        self.update(
            f"workspace: {workspace_id} | state: {run_state} | "
            f"mode: {active_mode} | runtime: {runtime_status} | "
            f"chat: {chat} | phase: {phase}"
        )


class ConversationPane(RichLog):
    can_focus = True
    help = HelpData(
        title="Conversation",
        description="Shows the current chat transcript and streamed assistant responses.",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(min_width=1, wrap=True, highlight=False, markup=False, **kwargs)
        self._lines: list[str] = []
        self._streaming_buffer: list[str] = []

    def append_user(self, text: str) -> None:
        self._lines.append(f"> {text}")
        self._refresh_text()

    def append_assistant(self, text: str) -> None:
        if not text:
            return
        self._lines.append(text)
        self._refresh_text()

    def append_assistant_delta(self, event) -> None:
        if event.text:
            self._streaming_buffer.append(event.text)
        self._refresh_text()

    def finalize_assistant(self, text: str) -> None:
        self._streaming_buffer = []
        self._lines.append(text)
        self._refresh_text()

    def discard_streaming(self) -> None:
        self._streaming_buffer = []
        self._refresh_text()

    def text_buffer(self) -> str:
        if self._streaming_buffer:
            return "\n".join(self._lines + ["".join(self._streaming_buffer)])
        return "\n".join(self._lines)

    def rehydrate_from_record(self, record) -> None:
        self._lines = []
        for m in record.messages:
            prefix = "> " if m.role == "user" else ""
            self._lines.append(f"{prefix}{m.text}")
        self._streaming_buffer = []
        self._refresh_text()

    def _refresh_text(self) -> None:
        self.clear()
        text = self.text_buffer()
        if text:
            self.write(text, scroll_end=True)


class SidebarPane(RichLog):
    can_focus = True
    help = HelpData(
        title="Sidebar",
        description="Shows workspace status, run trace, command progress, doctor findings, and failures.",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(min_width=1, wrap=True, highlight=False, markup=False, **kwargs)
        self._status = "status: starting"
        self._trace_lines: deque[str] = deque(maxlen=20)
        self._command_lines: deque[str] = deque(maxlen=12)
        self._doctor_lines: deque[str] = deque(maxlen=8)
        self._failure: str | None = None
        self._help = "F2 workspaces | slash: /workspaces  /list_workspaces  /switch_workspace <id>"
        self._refresh_text()

    def update_status(
        self,
        *,
        workspace_id: str,
        run_state: str,
        active_mode: str,
        runtime_status: str = "checking",
    ) -> None:
        self._status = (
            f"workspace: {workspace_id}\nstate: {run_state}\n"
            f"mode: {active_mode}\nruntime: {runtime_status}"
        )
        self._refresh_text()

    def command_started(self, command: str) -> None:
        self._command_lines.append(f"/{command}: running")
        self._refresh_text()

    def command_progress(self, command: str, phase: str, phase_index: int, phase_total: int) -> None:
        self._command_lines.append(f"/{command}: {phase} {phase_index}/{phase_total}")
        self._refresh_text()

    def command_completed(self, command: str, result: dict) -> None:
        if "error" in result:
            self._command_lines.append(f"/{command}: {result['error']}")
        else:
            self._command_lines.append(f"/{command}: {self._brief_result(result)}")
        self._refresh_text()

    def append_doctor_finding(self, summary: str, severity: str) -> None:
        self._doctor_lines.append(f"[{severity}] {summary}")
        self._refresh_text()

    def doctor_report(self, summary_counts: dict, recommendations: list[str]) -> None:
        counts = ", ".join(f"{k}: {v}" for k, v in summary_counts.items()) or "no findings"
        recs = "; ".join(recommendations[:3]) or "no recommendations"
        self._doctor_lines.append(f"report: {counts}")
        self._doctor_lines.append(recs)
        self._refresh_text()

    def failure(self, summary: str, error_code: str) -> None:
        self._failure = f"{error_code}: {summary}"
        self._refresh_text()

    def update_trace(self, lines: list[str]) -> None:
        self._trace_lines.clear()
        self._trace_lines.extend(lines)
        self._refresh_text()

    def text_buffer(self) -> str:
        return self._render_text()

    def _brief_result(self, result: dict) -> str:
        if "snapshot" in result:
            snap = result["snapshot"]
            return f"workspace {snap.get('workspace_id')} {snap.get('run_state')}"
        if "workspaces" in result:
            return ", ".join(w.get("workspace_id", "?") for w in result["workspaces"]) or "no workspaces"
        if "workspace" in result:
            return f"workspace {result['workspace'].get('workspace_id')}"
        if "chats" in result:
            return f"{len(result['chats'])} chats"
        if "chat" in result:
            return f"chat {result['chat'].get('chat_id')}"
        return json.dumps(result, sort_keys=True)[:160]

    def _refresh_text(self) -> None:
        self.clear()
        self.write(self._render_text(), scroll_end=True)

    def _render_text(self) -> str:
        trace = "\n".join(self._trace_lines) or "no trace yet"
        commands = "\n".join(self._command_lines) or "no commands yet"
        doctor = "\n".join(self._doctor_lines) or "no doctor findings"
        failure = self._failure or "no failures"
        return (
            f"STATUS\n{self._status}\n\n"
            f"TRACE\n{trace}\n\n"
            f"COMMANDS\n{commands}\n\n"
            f"DOCTOR\n{doctor}\n\n"
            f"FAILURES\n{failure}\n\n"
            f"{self._help}"
        )


class PlanPane(Static):
    def render_plan(self, plan: dict | None) -> None:
        if plan is None:
            self.update("(no plan)")
            return
        steps = plan.get("steps", [])
        body = "\n".join(
            f"{step.get('step_order', '?')}. {step.get('purpose', '')} status={step.get('status', 'pending')}"
            for step in steps
        )
        self.update(f"goal: {plan.get('goal', '')}\n{body}")


class StepStatusPane(Static):
    def render_contract(self, contract: dict | None, requires_approval: bool) -> None:
        if contract is None:
            self.update("(no active step)")
            return
        suffix = "  [APPROVAL REQUIRED]" if requires_approval else ""
        self.update(
            f"step {contract.get('step_id')} -- inputs: {contract.get('declared_inputs', [])}{suffix}"
        )


class ArtifactsPane(Static):
    def render_refs(self, refs: list[str]) -> None:
        self.update("\n".join(refs) if refs else "(no artifacts)")


class ContextMemoryPane(Static):
    def render_summary(self, *, preferences: dict, notes_count: int, doctor_warning_count: int) -> None:
        self.update(
            f"prefs: {len(preferences)} keys | notes: {notes_count} | doctor warnings: {doctor_warning_count}"
        )


class DoctorPane(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._findings: list[str] = []

    def render_doctor(self, *, validity_warnings: list[dict], recommendations: list[str]) -> None:
        warning_text = (
            "\n".join(f"  {w.get('path')} -> {w.get('state')}" for w in validity_warnings)
            or "(no validity warnings)"
        )
        rec_text = "\n".join(f"- {r}" for r in recommendations) or "(no recommendations)"
        self.update(f"VALIDITY:\n{warning_text}\n\nRECOMMENDATIONS:\n{rec_text}")

    def append_finding(self, summary: str, severity: str) -> None:
        self._findings.append(f"[{severity}] {summary}")
        self.update("\n".join(self._findings))

    def render_report(self, summary_counts: dict, recommendations: list[str]) -> None:
        counts = ", ".join(f"{k}: {v}" for k, v in summary_counts.items())
        recs = "\n".join(f"- {r}" for r in recommendations) or "(none)"
        self.update(f"DOCTOR REPORT\n{counts}\n\nRECOMMENDATIONS:\n{recs}")


class FailurePane(Static):
    def render_failure(self, failure: dict | None) -> None:
        if failure is None:
            self.update("(no failure)")
            return
        actions = ", ".join(failure.get("offered_actions", []))
        self.update(
            f"FAILURE: {failure.get('failure_kind')}\n"
            f"summary: {failure.get('failure_summary')}\n"
            f"offered: {actions}"
        )


class ProvenancePane(Static):
    def render_lineage(self, lineage_refs: list[dict]) -> None:
        if not lineage_refs:
            self.update("(no lineage)")
            return
        body = "\n".join(
            f"{ref.get('artifact')} | fingerprint: {ref.get('fingerprint')} | validity: {ref.get('validity')}"
            for ref in lineage_refs
        )
        self.update(body)


class StatusPane(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._events: deque[str] = deque(maxlen=20)

    def append_events(self, events: list[str]) -> None:
        for event in events:
            self._events.append(event)
        self.update(" | ".join(self._events))
