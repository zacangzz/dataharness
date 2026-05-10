from __future__ import annotations

from collections import deque
import json

from app.tui.help import HelpData
from app.tui.conversation import AssistantMessageBlock, SystemMessageBlock, UserMessageBlock
from app.tui.sidebar import SidebarState
from app.tui.sidebar_sections import (
    ChatsSection,
    CommandsSection,
    DoctorSection,
    FailuresSection,
    FilesSection,
    TraceSection,
    WorkspaceSection,
)
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


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


class ConversationPane(VerticalScroll):
    can_focus = True
    help = HelpData(
        title="Conversation",
        description="Shows the current chat transcript and streamed assistant responses.",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._blocks: list[object] = []
        self._streaming_block: AssistantMessageBlock | None = None

    def _safe_mount(self, widget) -> None:
        try:
            self.mount(widget)
        except Exception:
            # When the pane is not yet mounted (e.g. used in unit tests
            # outside an App context), fall back to a no-op mount and
            # rely on text_buffer() for assertions.
            pass

    def _safe_scroll_end(self) -> None:
        try:
            self.scroll_end(animate=False)
        except Exception:
            pass

    def append_user(self, text: str) -> None:
        block = UserMessageBlock(text)
        self._blocks.append(block)
        self._safe_mount(block)
        self._safe_scroll_end()

    def append_assistant(self, text: str) -> None:
        block = AssistantMessageBlock(text)
        self._blocks.append(block)
        self._safe_mount(block)
        self._safe_scroll_end()

    def append_assistant_delta(self, event) -> None:
        if self._streaming_block is None:
            self._streaming_block = AssistantMessageBlock("")
            self._blocks.append(self._streaming_block)
            self._safe_mount(self._streaming_block)
        self._streaming_block.append_delta(event.text)
        self._safe_scroll_end()

    def finalize_assistant(self, text: str) -> None:
        if self._streaming_block is None:
            self.append_assistant(text)
            return
        self._streaming_block.update_text(text)
        self._streaming_block = None
        self._safe_scroll_end()

    def append_failure(self, summary: str, error_code: str) -> None:
        self.discard_streaming()
        block = SystemMessageBlock(f"{error_code}: {summary}")
        self._blocks.append(block)
        self._safe_mount(block)
        self._safe_scroll_end()

    def discard_streaming(self) -> None:
        if self._streaming_block is not None:
            try:
                self._blocks.remove(self._streaming_block)
            except ValueError:
                pass
            try:
                self._streaming_block.remove()
            except Exception:
                pass
            self._streaming_block = None

    def text_buffer(self) -> str:
        parts: list[str] = []
        for block in self._blocks:
            text_buffer = getattr(block, "text_buffer", None)
            if callable(text_buffer):
                parts.append(text_buffer())
        return "\n".join(parts)

    def rehydrate_from_record(self, record) -> None:
        try:
            self.remove_children()
        except Exception:
            pass
        self._blocks = []
        self._streaming_block = None
        for message in record.messages:
            if message.role == "user":
                self.append_user(message.text)
            elif message.role == "assistant":
                self.append_assistant(message.text)
            else:
                block = SystemMessageBlock(message.text)
                self._blocks.append(block)
                self._safe_mount(block)


class SidebarPane(VerticalScroll):
    can_focus = True
    help = HelpData(
        title="Sidebar",
        description="Shows workspace, chat, files, run trace, command progress, doctor findings, and failures.",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state = SidebarState()

    def compose(self) -> ComposeResult:
        yield WorkspaceSection(id="sidebar_workspace")
        yield ChatsSection(id="sidebar_chats")
        yield FilesSection(id="sidebar_files")
        yield TraceSection(id="sidebar_trace")
        yield CommandsSection(id="sidebar_commands")
        yield DoctorSection(id="sidebar_doctor")
        yield FailuresSection(id="sidebar_failures")

    def _section(self, widget_id: str, cls):
        try:
            return self.query_one(f"#{widget_id}", cls)
        except Exception:
            return None

    def update_status(
        self,
        *,
        workspace_id: str,
        run_state: str,
        active_mode: str,
        runtime_status: str = "checking",
        chat_id: str | None = None,
    ) -> None:
        self._state.update_status(
            workspace_id=workspace_id,
            run_state=run_state,
            active_mode=active_mode,
            runtime_status=runtime_status,
            chat_id=chat_id,
        )
        section = self._section("sidebar_workspace", WorkspaceSection)
        if section is not None:
            section.update_status(
                workspace_id=workspace_id,
                run_state=run_state,
                active_mode=active_mode,
                runtime_status=runtime_status,
            )
        chats_section = self._section("sidebar_chats", ChatsSection)
        if chats_section is not None:
            chats_section.set_active_chat(chat_id)

    def update_files(self, files: list[str]) -> None:
        self._state.set_files(files)
        section = self._section("sidebar_files", FilesSection)
        if section is not None:
            section.update_files(self._state.files)

    def update_chats(self, chats) -> None:
        if chats and not isinstance(chats[0], str):
            self._state.set_chat_summaries(list(chats))
        else:
            self._state.set_chats(list(chats))
        section = self._section("sidebar_chats", ChatsSection)
        if section is not None:
            section.update_chats(
                self._state.chat_summaries if self._state.chat_summaries else self._state.chats
            )

    def command_started(self, command: str) -> None:
        self._state.command_started(command)
        section = self._section("sidebar_commands", CommandsSection)
        if section is not None:
            section.replace(list(self._state.commands))

    def command_progress(self, command: str, phase: str, phase_index: int, phase_total: int) -> None:
        self._state.command_progress(command, phase, phase_index, phase_total)
        section = self._section("sidebar_commands", CommandsSection)
        if section is not None:
            section.replace(list(self._state.commands))

    def command_completed(self, command: str, result: dict) -> None:
        if isinstance(result, dict) and "error" in result:
            text = f"/{command}: {result['error']}"
        else:
            text = f"/{command}: {self._brief_result(result)}"
        self._state.command_completed(text)
        section = self._section("sidebar_commands", CommandsSection)
        if section is not None:
            section.replace(list(self._state.commands))

    def append_doctor_finding(self, summary: str, severity: str) -> None:
        self._state.append_doctor(f"[{severity}] {summary}")
        section = self._section("sidebar_doctor", DoctorSection)
        if section is not None:
            section.replace(list(self._state.doctor))

    def doctor_report(self, summary_counts: dict, recommendations: list[str]) -> None:
        counts = ", ".join(f"{k}: {v}" for k, v in summary_counts.items()) or "no findings"
        recs = "; ".join(recommendations[:3]) or "no recommendations"
        self._state.append_doctor(f"report: {counts}")
        self._state.append_doctor(recs)
        section = self._section("sidebar_doctor", DoctorSection)
        if section is not None:
            section.replace(list(self._state.doctor))

    def failure(self, summary: str, error_code: str) -> None:
        self._state.set_failure(summary, error_code)
        section = self._section("sidebar_failures", FailuresSection)
        if section is not None:
            section.set_failure(summary, error_code)

    def update_trace(self, lines: list[str]) -> None:
        self._state.update_trace(lines)
        section = self._section("sidebar_trace", TraceSection)
        if section is not None:
            section.replace(list(self._state.trace))

    def text_buffer(self) -> str:
        return self._state.text_buffer()

    def _brief_result(self, result) -> str:
        if not isinstance(result, dict):
            return str(result)
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
