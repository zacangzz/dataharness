from __future__ import annotations

import json
import logging
import asyncio
import inspect
import queue
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Footer, Input, Markdown, Static
from textual.containers import ScrollableContainer
from textual.worker import Worker

from src.core import telemetry
from src.core.clarification_bus import clarification_bus
from src.core.harness_factory import build_harness
from src.core.harness.schemas import DoctorCommand, ReviewCommand
from src.core.tools.formatting import normalize_markdown_blocks
from src.cli.artifact_panel import ArtifactPanel
from src.cli.context_bar import ContextBar
from src.cli.plan_panel import PlanPanel
from src.cli.status_bar import StatusBar
from src.cli.workspace_screen import WorkspaceScreen
from src.cli.process_log import ProcessLog
from src.core.workspace import WorkspaceManager

if TYPE_CHECKING:
    from src.core.harness.orchestrator import Harness

_log = logging.getLogger(__name__)

_MSG_MODEL_READY = (
    "Local model is loaded and ready.\nType a question below and press Enter to start."
)
_MSG_MODEL_LOADING = "Model is still loading — input will be enabled when ready."


def _format_step(step) -> str:
    parts = []
    tool_calls = getattr(step, "tool_calls", None)
    if tool_calls:
        for tc in tool_calls:
            args = getattr(tc, "arguments", {}) or {}
            formatted_args = (
                json.dumps(args, indent=2) if isinstance(args, dict) else str(args)
            )
            parts.append(
                f"Tool: {getattr(tc, 'name', 'unknown')}\nArguments: {formatted_args}"
            )
    observations = getattr(step, "observations", None)
    if observations:
        parts.append(f"Observation:\n{observations}")
    error = getattr(step, "error", None)
    if error:
        parts.append(f"Error:\n{error}")
    return "\n\n".join(parts) if parts else str(step)


class AgentStepView(ScrollableContainer):
    """Collapsed panel showing agent action steps."""

    def __init__(self, steps: list) -> None:
        from textual.widgets import Collapsible

        content = (
            "\n\n".join(_format_step(s) for s in steps)
            if steps
            else "(no step details)"
        )
        super().__init__()
        self._collapsible = Collapsible(
            Static(content, markup=False),
            title="Agent Steps (click to expand)",
            collapsed=True,
        )

    def compose(self) -> ComposeResult:
        yield self._collapsible


class ChatApp(App):
    BINDINGS = [
        Binding("ctrl+w", "open_workspace", "Workspaces"),
    ]

    CSS = """
    #message-log {
        height: 1fr;
        border: solid $primary;
        padding: 1 2;
        border-title-align: left;
    }

    #chat-input {
        dock: bottom;
        height: 3;
        width: 100%;
        border: tall $accent;
    }

    Footer {
        dock: bottom;
        height: 1;
    }

    .user-message {
        color: $text;
        margin-bottom: 1;
    }

    .assistant-message {
        color: $accent;
        margin-bottom: 1;
    }

    .system-message {
        color: $success;
        margin-bottom: 1;
    }

    .clarification-prompt {
        color: $warning;
        margin-bottom: 1;
    }

    Input {
        dock: bottom;
    }

    StatusBar {
        dock: top;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
    }

    #error-container {
        margin: 1 2;
    }

    #error-container Button {
        margin-right: 1;
    }
    """

    def __init__(self, model_path: str, manager: WorkspaceManager) -> None:
        super().__init__()
        self._model_path = model_path
        self._manager = manager
        self._harness: Harness | None = None
        self._history: list[dict] = []
        self._welcome_mounted = False
        self._awaiting_clarification: bool = False
        self._pending_clarification_token: str | None = None
        self._active_turn_id: str | None = None
        self._turn_started_at: dict[str, float] = {}
        self._turn_workspace_snapshots: dict[str, tuple[str, Path]] = {}
        self._turn_in_flight: bool = False
        self._pipeline_worker: Worker[None] | None = None
        self._loading: bool = False
        self._input_ready: bool = False
        self._error_message: str | None = None
        self._init_loading_msg_id: str | None = None
        self._streaming_tokens: list[str] = []
        self._streaming_widget: Static | None = None
        self._final_rendered: bool = False
        self._last_submitted_input: object | None = None
        _log.debug("ChatApp.__init__: model_path=%s", model_path)

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        message_log = ScrollableContainer(id="message-log")
        message_log.border_title = "Conversation"
        yield message_log
        yield PlanPanel(id="plan-panel")
        yield ProcessLog(id="process-log")
        yield ArtifactPanel(id="artifact-panel")
        yield ContextBar(id="context-bar")
        yield Input(
            placeholder="Ask about HR data, policy, or headcount…",
            id="chat-input",
            disabled=True,
        )
        yield Footer()

    def on_mount(self) -> None:
        _log.debug("on_mount: starting model load")
        clarification_bus.cancel_all()
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.workspace_name = self._manager.active_name()
        self._init_loading_msg_id = self._mount_temp_message("Initializing HR Agent…")
        self._loading = True
        self._load_model_and_pipeline()
        self.query_one("#chat-input", Input).focus()
        self.query_one("#chat-input", Input).border_title = "Prompt"
        self.set_interval(0.1, self._poll_clarification_queue)

    def action_open_workspace(self) -> None:
        self.push_screen(WorkspaceScreen(self._manager))

    async def on_workspace_screen_workspace_switched(
        self, event: WorkspaceScreen.WorkspaceSwitched
    ) -> None:
        """Clear history and update UI when the active workspace changes."""
        old_workspace_name = self.query_one("#status-bar", StatusBar).workspace_name
        self._awaiting_clarification = False
        self._pending_clarification_token = None
        self._turn_in_flight = False
        self._active_turn_id = None
        self._turn_started_at.clear()
        self._turn_workspace_snapshots.clear()
        clarification_bus.cancel_all()
        self._cancel_pipeline_worker()
        if self._harness is not None and hasattr(self._harness, "invalidate_workspace"):
            maybe_awaitable = self._harness.invalidate_workspace(old_workspace_name)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        self._history.clear()
        message_log = self.query_one("#message-log")
        message_log.remove_children()
        self.query_one("#process-log", ProcessLog).reset()
        self.query_one("#plan-panel", PlanPanel).reset()
        self.query_one("#context-bar", ContextBar).reset()
        self.query_one("#artifact-panel", ArtifactPanel).set_artifacts([])
        model_ready = self._input_ready
        self._mount_system_message(
            f"[bold]HR Agent[/] — Workspace: [bold]{event.name}[/]\n"
            f"Workspace switched. {_MSG_MODEL_READY if model_ready else _MSG_MODEL_LOADING}",
        )
        self._welcome_mounted = True
        self.query_one("#status-bar", StatusBar).workspace_name = event.name
        if model_ready:
            self._enable_input(force=True)
        telemetry.emit_event(
            "ui",
            "workspace_switched",
            actor="app",
            status="ok",
            workspace=event.name,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        if not self._input_ready:
            return
        if self._turn_in_flight and not self._awaiting_clarification:
            return
        event.input.clear()

        if text.lower() == "/workspace":
            self.push_screen(WorkspaceScreen(self._manager))
            return

        if self._awaiting_clarification:
            self._awaiting_clarification = False
            event.input.disabled = True
            user_widget = Static(f"[bold]You:[/] {text}", classes="user-message")
            self.query_one("#message-log").mount(user_widget)
            self.query_one("#message-log").scroll_end(animate=False)
            self._history.append({"role": "user", "content": text})
            telemetry.emit_event(
                "ui",
                "clarification_answer_submitted",
                actor="app",
                status="ok",
                turn_id=self._active_turn_id,
                message_len=len(text),
            )
            if self._pending_clarification_token is not None:
                clarification_bus.answer(self._pending_clarification_token, text)
                self._pending_clarification_token = None
            return

        turn_id = uuid.uuid4().hex[:12]
        self._active_turn_id = turn_id
        self._turn_started_at[turn_id] = time.perf_counter()
        self._turn_workspace_snapshots[turn_id] = (
            self._manager.active_name(),
            self._manager.active_dir(),
        )
        self._turn_in_flight = True
        self.query_one("#process-log", ProcessLog).reset()
        self.query_one("#context-bar", ContextBar).reset()
        event.input.disabled = True
        user_widget = Static(f"[bold]You:[/] {text}", classes="user-message")
        self.query_one("#message-log").mount(user_widget)
        self.query_one("#message-log").scroll_end(animate=False)

        self._history.append({"role": "user", "content": text})
        telemetry.emit_event(
            "ui",
            "user_submit",
            actor="app",
            status="ok",
            turn_id=turn_id,
            message_len=len(text),
            history_turns=len(self._history) - 1,
        )
        self._submit_harness_input(text, turn_id=turn_id)

    def action_submit_doctor_report(self) -> None:
        if not self._input_ready or self._turn_in_flight:
            return
        self._submit_harness_input(DoctorCommand())

    def action_submit_review_request(self) -> None:
        if not self._input_ready or self._turn_in_flight:
            return
        self._submit_harness_input(ReviewCommand())

    def _submit_harness_input(self, payload: object, *, turn_id: str | None = None) -> str:
        if turn_id is None:
            turn_id = uuid.uuid4().hex[:12]
        self._last_submitted_input = payload
        self._active_turn_id = turn_id
        self._turn_started_at[turn_id] = time.perf_counter()
        self._turn_workspace_snapshots[turn_id] = (
            self._manager.active_name(),
            self._manager.active_dir(),
        )
        self._turn_in_flight = True
        self.query_one("#chat-input", Input).disabled = True
        self.query_one("#process-log", ProcessLog).reset()
        self.query_one("#context-bar", ContextBar).reset()
        workspace_name = self._manager.active_name()
        workspace_dir = self._manager.active_dir()
        self._pipeline_worker = self._run_pipeline(
            turn_id,
            payload,
            workspace_name=workspace_name,
            workspace_dir=workspace_dir,
        )
        return turn_id

    def _cancel_pipeline_worker(self) -> None:
        worker = self._pipeline_worker
        if worker is None:
            return
        worker.cancel()
        self._pipeline_worker = None

    def _workspace_snapshot_for_turn(self, turn_id: str | None) -> tuple[str, Path] | None:
        if turn_id is None:
            return None
        return self._turn_workspace_snapshots.get(turn_id)

    def _is_current_turn(self, turn_id: str | None) -> bool:
        return bool(turn_id) and turn_id == self._active_turn_id

    def _clarification_matches_current_turn(self, payload: dict) -> bool:
        turn_id = payload.get("turn_id")
        if not self._is_current_turn(turn_id):
            return False
        workspace_snapshot = self._workspace_snapshot_for_turn(turn_id)
        if workspace_snapshot is None:
            return False
        payload_workspace_name = payload.get("workspace_name")
        payload_workspace_dir = payload.get("workspace_dir")
        if payload_workspace_name is not None and payload_workspace_name != workspace_snapshot[0]:
            return False
        if payload_workspace_dir is not None and Path(payload_workspace_dir) != workspace_snapshot[1]:
            return False
        return True

    def _poll_clarification_queue(self) -> None:
        if self._awaiting_clarification or self._pending_clarification_token is not None:
            return
        try:
            payload = clarification_bus.get_question_nowait()
        except queue.Empty:
            return
        question = payload["question"]
        if not self._turn_in_flight and self._active_turn_id is None:
            clarification_bus.cancel_token(payload["token"])
            return
        if not self._clarification_matches_current_turn(payload):
            clarification_bus.cancel_token(payload["token"])
            return
        self._pending_clarification_token = payload["token"]
        self._awaiting_clarification = True
        prompt_widget = Static(
            f"[bold]Agent needs clarification:[/] {question}",
            classes="clarification-prompt",
        )
        self.query_one("#message-log").mount(prompt_widget)
        self.query_one("#message-log").scroll_end(animate=False)
        self._enable_input(force=True)
        telemetry.emit_event(
            "ui",
            "clarification_prompt_shown",
            actor="app",
            status="waiting",
            turn_id=self._active_turn_id,
            question_len=len(question),
        )

    def _enable_input(self, *, force: bool = False) -> None:
        if self._turn_in_flight and not force and not self._awaiting_clarification:
            return
        inp = self.query_one("#chat-input", Input)
        inp.disabled = False
        inp.focus()

    def _mount_system_message(self, content: str) -> None:
        message_log = self.query_one("#message-log")
        message_log.mount(Static(content, classes="system-message"))
        message_log.scroll_end(animate=False)

    def _mount_temp_message(self, content: str) -> str:
        """Mount a temporary message and return its widget ID for later removal."""
        message_log = self.query_one("#message-log")
        widget = Static(
            content, classes="system-message", id=f"temp-msg-{uuid.uuid4().hex[:8]}"
        )
        message_log.mount(widget)
        message_log.scroll_end(animate=False)
        return widget.id

    def _remove_temp_message(self, widget_id: str | None) -> None:
        """Remove a temporary message by its widget ID."""
        if widget_id is None:
            return
        try:
            widget = self.query_one(f"#{widget_id}")
            widget.remove()
        except Exception:
            pass

    @work(thread=True)
    def _load_model_and_pipeline(self) -> None:
        """Background worker that loads the model and builds the harness."""
        from src.core.engine.llm import LlmModel
        from src.core.terminal import repair_standard_streams

        _log.debug("_load_model_and_pipeline: start")
        try:
            repair_standard_streams(_log)
            from src.core.engine.llm import EngineConfig
            from pathlib import Path

            model_dir = Path(self._model_path).parent
            draft_path = model_dir / "gemma-4-E2B-it-Q4_K_M.gguf"
            engine_config = EngineConfig(
                draft_model_path=str(draft_path) if draft_path.exists() else None
            )
            model = LlmModel(self._model_path, engine_config)
            repair_standard_streams(_log)
            harness = build_harness(model, workspace_manager=self._manager)
            self._harness = harness
            self.call_from_thread(self._on_model_loaded)
        except Exception as exc:
            _log.exception("_load_model_and_pipeline: FAILED")
            self.call_from_thread(self._on_model_error, exc)

    def _on_model_loaded(self) -> None:
        """Called on main thread when model and pipeline are ready."""
        self._loading = False
        self._input_ready = True
        self._remove_temp_message(self._init_loading_msg_id)
        self._init_loading_msg_id = None

        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.set_loaded()

        if not self._welcome_mounted:
            active = self._manager.active_name()
            self._mount_system_message(
                f"[bold]HR Agent[/] — Workspace: [bold]{active}[/]\n{_MSG_MODEL_READY}"
            )
            self._welcome_mounted = True

        self._enable_input(force=True)
        telemetry.emit_event("ui", "model_loaded", actor="app", status="ok")

    def _on_model_error(self, exc: Exception) -> None:
        """Called on main thread when model loading fails."""
        self._loading = False
        self._error_message = str(exc)
        self._remove_temp_message(self._init_loading_msg_id)
        self._init_loading_msg_id = None

        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.set_error()

        message_log = self.query_one("#message-log")
        message_log.mount(
            Static(
                f"[bold red]Failed to load model:[/] {exc}", classes="system-message"
            )
        )
        message_log.scroll_end(animate=False)

        # Mount error action buttons
        error_container = Static(id="error-container")
        message_log.mount(error_container)
        error_container.mount(Button("Retry", id="retry-button", variant="primary"))
        error_container.mount(Button("Switch Workspace", id="switch-workspace-button"))
        message_log.scroll_end(animate=False)

        _log.error("Model load failed: %s", exc)
        telemetry.emit_event(
            "startup", "model_load_error", actor="app", status="error", error=str(exc)
        )

    def _on_retry(self) -> None:
        """Retry model loading after an error."""
        if self._loading:
            return

        self._loading = True
        self._error_message = None

        # Remove error UI
        try:
            self.query_one("#error-container").remove()
        except Exception:
            pass

        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.start_loading()

        self._init_loading_msg_id = self._mount_temp_message("Retrying model load…")
        self._load_model_and_pipeline()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses in the conversation pane."""
        if event.button.id == "retry-button":
            self._on_retry()
        elif event.button.id == "switch-workspace-button":
            self.action_open_workspace()

    @work
    async def _run_pipeline(
        self,
        turn_id: str,
        message: object,
        *,
        workspace_name: str,
        workspace_dir,
    ) -> None:
        """Async worker that runs the harness with live event forwarding."""
        from src.core.runtime_context import pipeline_runtime_context, workspace_context

        _log.debug("_run_pipeline: start")
        command_only = isinstance(message, (DoctorCommand, ReviewCommand))
        telemetry.emit_event(
            "ui",
            "harness_worker_start",
            actor="app",
            status="start",
            turn_id=turn_id,
            submission_kind=type(message).__name__,
            message_len=len(message) if isinstance(message, str) else None,
        )
        try:
            answer = ""
            with telemetry.turn_context(turn_id):
                with workspace_context(workspace_name, workspace_dir):
                    with pipeline_runtime_context(self._harness):
                        async for event in self._harness.run_turn(message, turn_id):
                            await self._handle_pipeline_event(event)
                            if event.kind == "FinalMessage":
                                answer = event.payload.get("text", "")
            self._on_pipeline_complete(turn_id, answer, command_only=command_only)
            _log.debug("_run_pipeline: complete")
        except asyncio.CancelledError:
            _log.debug("_run_pipeline: cancelled")
            if self._is_current_turn(turn_id):
                self._turn_in_flight = False
                self._active_turn_id = None
                self._pipeline_worker = None
                self._enable_input(force=True)
            self._turn_started_at.pop(turn_id, None)
            self._turn_workspace_snapshots.pop(turn_id, None)
            telemetry.emit_event(
                "ui",
                "harness_worker_cancelled",
                actor="app",
                status="cancelled",
                turn_id=turn_id,
            )
        except Exception:
            _log.exception("_run_pipeline: FAILED")
            if self._is_current_turn(turn_id):
                self._on_pipeline_complete(
                    turn_id, "(error — see logs)", command_only=command_only
                )
            else:
                self._turn_started_at.pop(turn_id, None)
                self._turn_workspace_snapshots.pop(turn_id, None)
            telemetry.emit_event(
                "ui",
                "harness_worker_error",
                actor="app",
                status="error",
                turn_id=turn_id,
            )

    async def _handle_pipeline_event(self, event) -> None:
        """Handle a single HarnessEvent on the main thread."""

        process_log = self.query_one("#process-log", ProcessLog)
        status_bar = self.query_one("#status-bar", StatusBar)
        plan_panel = self.query_one("#plan-panel", PlanPanel)
        artifact_panel = self.query_one("#artifact-panel", ArtifactPanel)
        context_bar = self.query_one("#context-bar", ContextBar)
        kind = getattr(event, "kind", "")
        payload = getattr(event, "payload", {}) or {}
        turn_id = payload.get("turn_id")
        if not self._is_current_turn(turn_id):
            return
        workspace_snapshot = self._workspace_snapshot_for_turn(turn_id)

        if kind == "PlanReady":
            plan_panel.set_plan(payload)
            process_log.handle_event(event)
            status_bar.update_text("Plan ready", "ok")
            context_bar.set_state(
                dataset=workspace_snapshot[0] if workspace_snapshot else "",
                validity="trusted",
                compacted=False,
            )
            artifact_panel.set_artifacts(payload.get("artifacts", []))
        elif kind == "StepStarted":
            process_log.handle_event(event)
            plan_panel.mark_active_step(
                payload.get("step_id", ""),
                payload.get("title"),
            )
            status_bar.update_text(f"Step started: {payload.get('step_id', '')}", "ok")
        elif kind == "StepCompleted":
            process_log.handle_event(event)
            result = payload.get("result", {}) or {}
            plan_panel.mark_completed_step(
                payload.get("step_id", ""),
                str(result.get("status", "done")),
            )
            status_bar.update_text(f"Step completed: {payload.get('step_id', '')}", "ok")
            artifact_panel.set_artifacts(result.get("artifacts", []))
        elif kind == "DoctorReportReady":
            process_log.handle_event(event)
            context_bar.set_doctor_report(payload.get("report", {}))
            status_bar.update_text("Doctor report ready", "ok")
        elif kind == "ReviewReady":
            process_log.handle_event(event)
            context_bar.set_review_proposal(payload.get("proposal", {}))
            status_bar.update_text("Review ready", "ok")
        elif kind == "FinalMessage":
            full_text = payload.get("text", "") or "".join(self._streaming_tokens)
            if full_text:
                message_log = self.query_one("#message-log")
                if self._streaming_widget is not None:
                    try:
                        self._streaming_widget.remove()
                    except Exception:
                        pass
                    self._streaming_widget = None
                else:
                    message_log.mount(
                        Static("[bold cyan]Assistant:[/]", classes="assistant-message")
                    )
                normalized = normalize_markdown_blocks(full_text)
                message_log.mount(Markdown(normalized, classes="assistant-message"))
                message_log.scroll_end(animate=False)
                self._final_rendered = True
                self._streaming_tokens.clear()
        else:
            process_log.handle_event(event)

    def _on_pipeline_complete(self, turn_id: str, answer: str, *, command_only: bool) -> None:
        if not self._is_current_turn(turn_id):
            self._turn_started_at.pop(turn_id, None)
            self._turn_workspace_snapshots.pop(turn_id, None)
            return

        message_log = self.query_one("#message-log")

        if not self._final_rendered and not command_only:
            # FinalMessage event didn't render — render now (fallback / non-streaming path)
            message_log.mount(
                Static("[bold cyan]Assistant:[/]", classes="assistant-message")
            )
            normalized_answer = normalize_markdown_blocks(answer)
            message_log.mount(Markdown(normalized_answer, classes="assistant-message"))
            message_log.scroll_end(animate=False)

        # Reset streaming state for next turn
        self._final_rendered = False
        self._streaming_tokens.clear()
        if self._streaming_widget is not None:
            try:
                self._streaming_widget.remove()
            except Exception:
                pass
            self._streaming_widget = None

        if not command_only:
            self._history.append({"role": "assistant", "content": answer})
        self._turn_in_flight = False
        self._enable_input(force=True)
        turn_started_at = self._turn_started_at.pop(turn_id, None)
        total_ui_ms = None
        if turn_started_at is not None:
            total_ui_ms = round((time.perf_counter() - turn_started_at) * 1000, 3)
        if not command_only:
            telemetry.emit_event(
                "ui",
                "assistant_rendered",
                actor="app",
                status="ok",
                turn_id=turn_id,
                elapsed_ms=total_ui_ms,
                answer_len=len(answer),
            )
        self._turn_in_flight = False
        self._active_turn_id = None
        self._pipeline_worker = None
        self._turn_workspace_snapshots.pop(turn_id, None)
