from __future__ import annotations

from collections import deque
import json

from app.tui.help import HelpData
from app.tui.conversation import (
    AssistantMessageBlock, CompactionSummaryBlock, DoctorMessageBlock,
    SystemMessageBlock, UserMessageBlock,
)
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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Checkbox, Input, Static


class WorkspaceBar(Static):
    can_focus = True
    help = HelpData(
        title="Workspace Bar",
        description="Shows the active workspace, run state, mode, runtime status, chat, and phase.",
    )

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)

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
        if getattr(event, "delta_type", "text") != "text":
            return
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

    def append_doctor_line(self, text: str) -> None:
        block = DoctorMessageBlock(text)
        self._blocks.append(block)
        self._safe_mount(block)
        self._safe_scroll_end()

    def append_doctor_block(self, text: str) -> None:
        block = DoctorMessageBlock(text)
        self._blocks.append(block)
        self._safe_mount(block)
        self._safe_scroll_end()

    def append_compaction(self, summary_text: str, *, replaced_turn_count: int | None = None) -> None:
        block = CompactionSummaryBlock(summary_text, replaced_turn_count=replaced_turn_count)
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
        from app.tui.conversation import _clean as _clean_text
        for message in record.messages:
            cleaned = _clean_text(message.text)
            if not cleaned:
                continue  # skip synthetic tool-followup / draft echoes from older chats
            if message.role == "user":
                self.append_user(cleaned)
            elif message.role == "assistant":
                self.append_assistant(cleaned)
            elif message.role == "compacted_summary":
                self.append_compaction(cleaned)
            else:
                block = SystemMessageBlock(cleaned)
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
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)

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
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)

    def render_contract(self, contract: dict | None, requires_approval: bool) -> None:
        if contract is None:
            self.update("(no active step)")
            return
        suffix = "  [APPROVAL REQUIRED]" if requires_approval else ""
        self.update(
            f"step {contract.get('step_id')} -- inputs: {contract.get('declared_inputs', [])}{suffix}"
        )


class ArtifactsPane(Static):
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)

    def render_refs(self, refs: list[str]) -> None:
        self.update("\n".join(refs) if refs else "(no artifacts)")


class ContextMemoryPane(Static):
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)

    def render_summary(self, *, preferences: dict, notes_count: int, doctor_warning_count: int) -> None:
        self.update(
            f"prefs: {len(preferences)} keys | notes: {notes_count} | doctor warnings: {doctor_warning_count}"
        )


class DoctorPane(Static):
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
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
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)

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
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)

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
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)
        self._events: deque[str] = deque(maxlen=20)

    def append_events(self, events: list[str]) -> None:
        for event in events:
            self._events.append(event)
        self.update(" | ".join(self._events))


class ApprovalBanner(Vertical):
    """Inline approval banner; replaces full-screen ApprovalScreen.

    Shows plan goal, step contract summary, and code preview. Posts
    ApprovalDecisionMade on button or keybinding.
    """

    can_focus = True
    BINDINGS = [
        ("a", "decide('approved')", "approve"),
        ("r", "decide('rejected')", "reject"),
        ("v", "decide('revise_requested')", "revise"),
    ]

    class ApprovalDecisionMade(Message):
        def __init__(self, plan: dict, step_contract: dict, decision: str) -> None:
            super().__init__()
            self.plan = plan
            self.step_contract = step_contract
            self.decision = decision

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", "approval_banner")
        super().__init__(**kwargs)
        self._plan: dict = {}
        self._step_contract: dict = {}
        self._doctor_mode = False
        self._doctor_report_id: str = ""
        self._doctor_actions: list[dict] = []
        self.display = False

    def compose(self) -> ComposeResult:
        yield Static("(awaiting approval)", id="approval_goal", markup=False)
        yield Static("", id="approval_step", markup=False)
        yield Static("", id="approval_code", markup=False)
        yield Horizontal(
            Button("Approve (a)", id="approve", variant="success"),
            Button("Reject (r)", id="reject", variant="error"),
            Button("Revise (v)", id="revise"),
            id="approval_buttons",
        )
        yield Vertical(id="doctor_review")

    def show(self, *, plan: dict, step_contract: dict) -> None:
        self._clear_doctor_review()
        self._set_normal_approval_visible(True)
        self._doctor_mode = False
        self._doctor_report_id = ""
        self._doctor_actions = []
        self._plan = plan or {}
        self._step_contract = step_contract or {}
        goal = self._plan.get("goal") or self._step_contract.get("purpose") or "(unknown goal)"
        step_id = self._step_contract.get("step_id", "?")
        inputs = self._step_contract.get("declared_inputs", [])
        outputs = self._step_contract.get("expected_outputs", [])
        code = self._step_contract.get("code", "") or ""
        preview_lines = code.splitlines()[:6]
        if len(code.splitlines()) > 6:
            preview_lines.append(f"... ({len(code.splitlines()) - 6} more lines)")
        try:
            self.query_one("#approval_goal", Static).update(f"APPROVE PLAN: {goal}")
            self.query_one("#approval_step", Static).update(
                f"step {step_id}  inputs={inputs}  outputs={outputs}"
            )
            self.query_one("#approval_code", Static).update(
                "\n".join(preview_lines) or "(no code)"
            )
        except Exception:
            pass
        self.add_class("visible")
        self.display = True
        try:
            self.focus()
        except Exception:
            pass

    def hide(self) -> None:
        self.remove_class("visible")
        self.display = False
        self._doctor_mode = False
        self._clear_doctor_review()
        self._set_normal_approval_visible(True)

    def show_doctor_review(self, report_id, actions, findings):
        """Render doctor batch approval with checkboxes per action."""
        self._clear_doctor_review()
        self._set_normal_approval_visible(False)
        self.display = True
        self._doctor_mode = True
        self._doctor_report_id = report_id
        self._doctor_actions = actions

        container = self.query_one("#doctor_review", Vertical)
        container.display = True

        container.mount(Static(
            f"Doctor Review ({len(findings)} findings, {len(actions)} actions)",
            id="doctor_header",
        ))

        for i, action in enumerate(actions):
            icon = {"cleanup": " ", "promote": " ", "keep": " ", "review": " "}.get(action.get("action", ""), " ")
            label = f"{icon} {action.get('action')}: {action.get('rationale', action.get('target', ''))[:80]}"
            cb = Checkbox(label, id=f"doctor_action_{i}", value=True)
            container.mount(cb)

        container.mount(Horizontal(
            Button("Accept All", id="doctor_accept_all", variant="success"),
            Button("Reject All", id="doctor_reject_all", variant="error"),
            Button("Apply Selected", id="doctor_apply_selected", variant="primary"),
        ))
        self.add_class("visible")

    def get_doctor_decisions(self) -> list[dict]:
        """Collect accept/reject per action from checkboxes."""
        decisions: list[dict] = []
        for i in range(len(self._doctor_actions)):
            cb = self.query_one(f"#doctor_action_{i}", Checkbox)
            decisions.append({
                "index": i,
                "accepted": cb.value,
                "action": self._doctor_actions[i],
            })
        return decisions

    def action_decide(self, decision: str) -> None:
        if self._doctor_mode:
            return
        self._emit(decision)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {"approve": "approved", "reject": "rejected", "revise": "revise_requested"}
        decision = mapping.get(event.button.id)
        if decision is None:
            return
        event.stop()
        self._emit(decision)

    def _emit(self, decision: str) -> None:
        if self._doctor_mode:
            return
        self.post_message(self.ApprovalDecisionMade(self._plan, self._step_contract, decision))

    def _clear_doctor_review(self) -> None:
        try:
            container = self.query_one("#doctor_review", Vertical)
        except Exception:
            return
        for child in list(container.children):
            child.remove()
        container.display = False

    def _set_normal_approval_visible(self, visible: bool) -> None:
        for selector in ("#approval_goal", "#approval_step", "#approval_code", "#approval_buttons"):
            try:
                self.query_one(selector).display = visible
            except Exception:
                pass


class ClarificationBar(Vertical):
    """Inline clarification bar; replaces full-screen ClarificationScreen.

    Pins a clarification question above the prompt bar and provides an
    input + submit button. Posts ClarificationSubmitted with the user's
    response; the app routes it through `handle_clarification_response`.
    """

    can_focus = True
    BINDINGS = [
        ("escape", "dismiss", "dismiss"),
    ]

    class ClarificationSubmitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class ClarificationDismissed(Message):
        pass

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", "clarification_bar")
        super().__init__(**kwargs)
        self._question: str = ""
        self.display = False

    def compose(self) -> ComposeResult:
        yield Static("(no clarification)", id="clarification_question", markup=False)
        yield Input(placeholder="Your clarification...", id="clarification_input")
        yield Horizontal(
            Button("Submit", id="clarification_submit", variant="primary"),
            Button("Dismiss", id="clarification_dismiss"),
            id="clarification_buttons",
        )

    def show(self, *, question: str) -> None:
        self._question = question or "Clarification required"
        try:
            self.query_one("#clarification_question", Static).update(self._question)
            self.query_one("#clarification_input", Input).value = ""
        except Exception:
            pass
        self.add_class("visible")
        self.display = True
        try:
            self.query_one("#clarification_input", Input).focus()
        except Exception:
            pass

    def hide(self) -> None:
        self.remove_class("visible")
        self.display = False

    def action_dismiss(self) -> None:
        self.post_message(self.ClarificationDismissed())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "clarification_input":
            return
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "clarification_submit":
            event.stop()
            self._submit()
        elif event.button.id == "clarification_dismiss":
            event.stop()
            self.post_message(self.ClarificationDismissed())

    def _submit(self) -> None:
        try:
            text = self.query_one("#clarification_input", Input).value.strip()
        except Exception:
            return
        if not text:
            return
        self.post_message(self.ClarificationSubmitted(text))
