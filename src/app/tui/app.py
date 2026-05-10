from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

from textual.app import App
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Footer, Header, Input

from textual import on

from app.session import AppSession
from app.tui.commands import DataHarnessCommandProvider, build_command_prefill
from app.tui.event_consumer import EventConsumer
from app.tui.file_picker import FilePicker, WorkspaceFileIndex, format_file_mention
from app.tui.help import HelpScreen
from app.tui.jump import Jumper, JumpOverlay
from app.tui.prompt_bar import PromptBar
from app.tui.prompt_editor import PromptEditor
from app.tui.run_trace import RunTrace
from app.tui.screens import ApprovalScreen, ClarificationScreen
from app.tui.screens.file_ingest import FileIngestScreen
from app.tui.screens.workspace_manager import WorkspaceManagerScreen
from app.tui.sidebar_sections import InsertMentionRequested, ResumeChatRequested
from app.tui.widgets import (
    ConversationPane,
    SidebarPane,
    WorkspaceBar,
)
from harness.command_registry import HarnessCommandDescriptor, parse_slash
from harness.control import RunStateRecord
from observability import Telemetry, bind_session, resolve_telemetry_dir
from observability.events import EventKind, Layer

# Migration alias for cli.py and external callers
DataAnalysisAppSession = AppSession


class DataHarnessApp(App[None]):
    TITLE = "DataHarness"
    CSS_PATH = Path(__file__).with_name("dataharness.tcss")
    # Keep the palette scoped to DataHarness commands; Textual system providers are intentionally omitted.
    COMMANDS = {DataHarnessCommandProvider}
    BINDINGS = [
        Binding("ctrl+p", "command_palette", "Commands"),
        Binding("ctrl+o", "toggle_jump_mode", "Jump", id="jump"),
        Binding("ctrl+f", "open_files", "Files"),
        Binding("f2", "open_workspaces", "Workspaces"),
        Binding("f3", "upload_files", "Upload"),
        Binding("f1,ctrl+question_mark", "help", "Help", id="help"),
    ]

    def __init__(
        self,
        *,
        session: AppSession | None = None,
        workspace_dir: Path | None = None,
        state: RunStateRecord | None = None,
        telemetry: Telemetry | None = None,
        session_id: UUID | None = None,
    ) -> None:
        super().__init__()
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())
        self.session_id = session_id or uuid4()
        self._workspace_dir = workspace_dir or Path.cwd() / "workspaces" / "w_0001"
        self._session = session or AppSession(
            telemetry=self.telemetry,
            app_root=self._workspace_dir.parent.parent,
        )
        self._state = state or RunStateRecord(
            workspace_id=self._workspace_dir.name, active_agent_mode="interaction"
        )
        self._active_chat_id: str | None = None
        self._trace = RunTrace()
        self._run_state_text = str(self._state.state)
        self._active_mode_text = self._state.active_agent_mode
        self._runtime_status = "checking"
        self._emit(EventKind.APP_LIFECYCLE_CONSTRUCTED, {"title": self.TITLE})

    @property
    def session(self) -> AppSession:
        return self._session

    @property
    def state(self) -> RunStateRecord:
        return self._state

    @property
    def active_chat_id(self) -> str | None:
        return self._active_chat_id

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    def _emit(self, kind: EventKind, payload: dict | None = None):
        with bind_session(self.session_id):
            return self.telemetry.emit(Layer.APP, kind, payload=payload or {})

    def _emit_error(self, *, phase: str, exc: BaseException):
        with bind_session(self.session_id):
            return self.telemetry.emit_error(Layer.APP, EventKind.APP_ERROR, phase=phase, exc=exc)

    def compose_ids(self) -> list[str]:
        return [
            "workspace_bar",
            "conversation",
            "sidebar",
            "prompt_bar",
            "user_input",
        ]

    def compose(self) -> Iterator[Widget]:
        self._emit(EventKind.APP_COMPOSE_START, {"compose_ids": self.compose_ids()})
        widgets: list[Widget] = [
            Header(),
            Vertical(
                WorkspaceBar(id="workspace_bar", classes="surface"),
                Horizontal(
                    Vertical(
                        ConversationPane(id="conversation"),
                        PromptBar(session=self._session, state=self._state, id="prompt_bar"),
                        id="chat_column",
                    ),
                    SidebarPane(id="sidebar"),
                    id="main",
                ),
            ),
            Footer(),
        ]
        count = 0
        try:
            for widget in widgets:
                count += 1
                self._emit(
                    EventKind.APP_COMPOSE_WIDGET,
                    {"widget_class": type(widget).__name__, "widget_id": getattr(widget, "id", None)},
                )
                yield widget
        except Exception as exc:
            self._emit_error(phase="compose", exc=exc)
            raise
        finally:
            self._emit(EventKind.APP_COMPOSE_END, {"widget_count": count})

    def on_mount(self) -> None:
        self._emit(EventKind.APP_MOUNT_START)
        expected = self.compose_ids()
        found: list[str] = []
        missing: list[str] = []
        for widget_id in expected:
            try:
                self.query_one(f"#{widget_id}")
                found.append(widget_id)
            except Exception:
                missing.append(widget_id)
        self._emit(
            EventKind.APP_SCREEN_SNAPSHOT,
            {
                "screen": type(self.screen).__name__ if self.screen else None,
                "expected_ids": expected,
                "found_ids": found,
                "missing_ids": missing,
            },
        )
        for widget_id in expected:
            self._emit(
                EventKind.APP_WIDGET_HEALTH, {"widget_id": widget_id, "present": widget_id in found}
            )
        self.query_one("#workspace_bar", WorkspaceBar).update_from(
            workspace_id=self._state.workspace_id,
            run_state=str(self._state.state),
            active_mode=self._state.active_agent_mode,
            runtime_status="checking",
            chat_id=self._active_chat_id,
            phase=self._trace.current_phase,
        )
        self.query_one("#sidebar", SidebarPane).update_status(
            workspace_id=self._state.workspace_id,
            run_state=str(self._state.state),
            active_mode=self._state.active_agent_mode,
            runtime_status="checking",
        )
        self.query_one("#sidebar", SidebarPane).update_trace(self._trace.lines)
        self.set_focus(self.query_one("#prompt_bar", PromptBar).input)
        self._emit(EventKind.APP_MOUNT_END, {"missing_ids": missing})
        self._emit(EventKind.APP_READY)
        self.run_worker(self._subscribe_status())
        self.run_worker(self._refresh_sidebar_resources())

    async def _refresh_sidebar_resources(self) -> None:
        workspace_dir = self._workspace_dir
        workspace_id = self._state.workspace_id
        try:
            sidebar = self.query_one("#sidebar", SidebarPane)
        except Exception:
            return
        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(
            None, lambda: WorkspaceFileIndex(workspace_dir).scan()
        )
        sidebar.update_files([entry.path for entry in entries])
        try:
            chats = await self._session.list_chats(workspace_id)
        except Exception:
            sidebar.update_chats([])
        else:
            sidebar.update_chats(list(chats))
        try:
            self.query_one("#prompt_bar", PromptBar).update_state(self._state)
        except Exception:
            pass

    async def _subscribe_status(self) -> None:
        try:
            async for snap in self._session.watch_status():
                try:
                    workspace_id = snap.workspace_id or self._state.workspace_id
                    self._run_state_text = snap.run_state
                    self._active_mode_text = snap.active_mode
                    self._runtime_status = snap.runtime_status
                    self.query_one("#workspace_bar", WorkspaceBar).update_from(
                        workspace_id=workspace_id,
                        run_state=snap.run_state,
                        active_mode=snap.active_mode,
                        runtime_status=snap.runtime_status,
                        chat_id=self._active_chat_id,
                        phase=self._trace.current_phase,
                    )
                    self.query_one("#sidebar", SidebarPane).update_status(
                        workspace_id=workspace_id,
                        run_state=snap.run_state,
                        active_mode=snap.active_mode,
                        runtime_status=snap.runtime_status,
                    )
                    self.query_one("#prompt_bar", PromptBar).update_status(
                        active_mode=snap.active_mode,
                        run_state=snap.run_state,
                    )
                except Exception:
                    return
        except Exception:
            pass

    async def _ensure_chat(self) -> str:
        if self._active_chat_id is None:
            # Create workspace if needed, then chat
            try:
                summary = await self._session.create_chat(self._state.workspace_id)
                self._active_chat_id = summary.chat_id
            except Exception:
                self._active_chat_id = f"chat_{uuid4().hex[:8]}"
        return self._active_chat_id

    async def submit_user_text(self, text: str) -> None:
        if text.startswith("/"):
            try:
                command, args = parse_slash(text)
            except ValueError as exc:
                self.notify(str(exc), severity="error")
                return
            if command == "workspaces":
                await self.action_open_workspaces()
                return
            if command == "files":
                await self.action_open_files()
                return
            if command == "upload":
                await self.action_upload_files()
                return
            if command in {"exit", "quit"}:
                self.exit()
                return
            descriptors = await self._session.list_commands()
            spec = next((d for d in descriptors if d.name == command), None)
            if spec is None:
                self.notify(f"unknown command: {command}", severity="error")
                return
            argument_dict = self._args_to_dict(spec, args)
            self.run_worker(self._stream_command(command, argument_dict))
            return

        self.query_one("#conversation", ConversationPane).append_user(text)
        await self._ensure_chat()
        self.run_worker(self._stream_turn(text))

    async def _stream_turn(self, text: str) -> None:
        consumer = self._build_consumer()
        try:
            async for ev in self._session.run_user_turn(
                state=self._state, workspace_dir=self._workspace_dir,
                chat_id=self._active_chat_id or "default",
                user_text=text,
            ):
                consumer.dispatch(ev)
        except Exception as exc:
            self._emit_error(phase="run_turn", exc=exc)
            self.notify(str(exc), severity="error")

    async def _stream_command(self, command: str, arguments: dict) -> None:
        consumer = self._build_consumer()
        try:
            async for ev in self._session.handle_direct_command(
                self._state, command=command, arguments=arguments,
            ):
                consumer.dispatch(ev)
            if command == "resume_chat" and "chat_id" in arguments:
                await self.action_resume_chat(arguments["chat_id"])
        except Exception as exc:
            self._emit_error(phase="direct_command", exc=exc)
            self.query_one("#sidebar", SidebarPane).failure(str(exc), "direct_command")
            self.notify(str(exc), severity="error")

    def _build_consumer(self) -> EventConsumer:
        return EventConsumer({
            "AppTurnStarted": self._handle_turn_started,
            "AppRuntimeDelta": self._handle_runtime_delta,
            "AppFinalMessage": self._handle_final_message,
            "AppTurnFailed": self._handle_turn_failed,
            "AppTurnCancelled": self._handle_turn_cancelled,
            "AppApprovalRequired": lambda e: self.push_screen(
                ApprovalScreen(plan={"id": e.plan_id, "steps": [e.step]}, step_contract=e.step)
            ),
            "AppCommandStarted": self._handle_command_started,
            "AppCommandProgress": self._handle_command_progress,
            "AppCommandCompleted": self._handle_command_completed,
            "AppDoctorFinding": self._handle_doctor_finding,
            "AppDoctorReportReady": self._handle_doctor_report_ready,
            "AppStatusChanged": self._handle_status_changed,
            "AppChatHistoryLoaded": lambda e: None,
        })

    def _handle_status_changed(self, event) -> None:
        snapshot = event.snapshot
        workspace_id = snapshot["workspace_id"] or self._state.workspace_id
        self._run_state_text = snapshot["run_state"]
        self._active_mode_text = snapshot["active_mode"]
        self._runtime_status = snapshot["runtime_status"]
        self.query_one("#workspace_bar", WorkspaceBar).update_from(
            workspace_id=workspace_id,
            run_state=snapshot["run_state"],
            active_mode=snapshot["active_mode"],
            runtime_status=snapshot["runtime_status"],
            chat_id=self._active_chat_id,
            phase=self._trace.current_phase,
        )
        self.query_one("#sidebar", SidebarPane).update_status(
            workspace_id=workspace_id,
            run_state=snapshot["run_state"],
            active_mode=snapshot["active_mode"],
            runtime_status=snapshot["runtime_status"],
        )
        self.query_one("#prompt_bar", PromptBar).update_status(
            active_mode=snapshot["active_mode"],
            run_state=snapshot["run_state"],
        )

    def _refresh_trace_widgets(self) -> None:
        self.query_one("#sidebar", SidebarPane).update_trace(self._trace.lines)
        self.query_one("#workspace_bar", WorkspaceBar).update_from(
            workspace_id=self._state.workspace_id,
            run_state=self._run_state_text,
            active_mode=self._active_mode_text,
            runtime_status=self._runtime_status,
            chat_id=self._active_chat_id,
            phase=self._trace.current_phase,
        )

    def _handle_turn_started(self, event) -> None:
        if event.chat_id:
            self._active_chat_id = event.chat_id
        self._trace.turn_started(event.active_mode)
        self._refresh_trace_widgets()

    def _handle_runtime_delta(self, event) -> None:
        self.query_one("#conversation", ConversationPane).append_assistant_delta(event)
        self._trace.runtime_delta(event.delta_type)
        self._refresh_trace_widgets()

    def _handle_final_message(self, event) -> None:
        self.query_one("#conversation", ConversationPane).finalize_assistant(event.text)
        self._trace.final_message()
        self._refresh_trace_widgets()

    def _handle_turn_failed(self, event) -> None:
        self._trace.failed(event.failure_summary, event.error_code)
        self.query_one("#conversation", ConversationPane).append_failure(
            event.failure_summary, event.error_code
        )
        self.query_one("#sidebar", SidebarPane).failure(event.failure_summary, event.error_code)
        self._refresh_trace_widgets()

    def _handle_turn_cancelled(self, event) -> None:
        self.query_one("#conversation", ConversationPane).finalize_assistant(
            f"[cancelled: {event.reason}]"
        )
        self._trace.cancelled(event.reason)
        self._refresh_trace_widgets()

    def _handle_command_started(self, event) -> None:
        self._trace.command_started(event.command)
        self.query_one("#sidebar", SidebarPane).command_started(event.command)
        self._refresh_trace_widgets()

    def _handle_command_progress(self, event) -> None:
        self._trace.command_progress(event.command, event.phase, event.phase_index, event.phase_total)
        self.query_one("#sidebar", SidebarPane).command_progress(
            event.command, event.phase, event.phase_index, event.phase_total
        )
        self._refresh_trace_widgets()

    def _handle_command_completed(self, event) -> None:
        self._trace.command_completed(event.command, event.result)
        self.query_one("#sidebar", SidebarPane).command_completed(event.command, event.result)
        snapshot = event.result.get("snapshot") if isinstance(event.result, dict) else None
        if snapshot:
            self.apply_workspace_snapshot(snapshot)
        else:
            self._refresh_trace_widgets()

    def _handle_doctor_finding(self, event) -> None:
        self.query_one("#sidebar", SidebarPane).append_doctor_finding(event.summary, event.severity)

    def _handle_doctor_report_ready(self, event) -> None:
        self.query_one("#sidebar", SidebarPane).doctor_report(
            event.summary_counts, event.recommendations
        )

    def apply_workspace_snapshot(self, snapshot) -> None:
        if not isinstance(snapshot, dict):
            snapshot = snapshot.model_dump(mode="json")
        if not snapshot.get("workspace_id"):
            return
        workspace_id = snapshot["workspace_id"]
        self._state = self._state.model_copy(update={"workspace_id": workspace_id})
        self._workspace_dir = self._session.app_root / "workspaces" / workspace_id
        self._active_chat_id = None
        self.query_one("#prompt_bar", PromptBar).update_state(self._state)
        self._handle_status_changed(type("_StatusEvent", (), {"snapshot": snapshot})())
        self.run_worker(self._refresh_sidebar_resources())

    def _args_to_dict(self, spec, positional: list[str]) -> dict:
        out = {}
        for i, p in enumerate(positional):
            if i >= len(spec.arguments):
                break
            out[spec.arguments[i].name] = p
        return out

    def handle_command_palette_selection(self, descriptor: HarnessCommandDescriptor) -> None:
        if descriptor.name in {"exit", "quit"}:
            self.exit()
            return
        if not descriptor.available:
            self.notify(
                descriptor.disabled_reason or f"{descriptor.name} is unavailable",
                severity="warning",
            )
            return
        if any(arg.required for arg in descriptor.arguments):
            prompt = self.query_one("#prompt_bar", PromptBar)
            prompt.prefill(build_command_prefill(descriptor))
            self.set_focus(prompt.input)
            return
        self.run_worker(self._stream_command(descriptor.name, {}))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        # Retained for non-prompt Input widgets (e.g. workspace manager screen).
        if event.input.id == "user_input":
            return

    async def on_prompt_editor_submitted(self, event: PromptEditor.Submitted) -> None:
        text = event.text.strip()
        if not text:
            return
        await self.submit_user_text(text)

    async def action_resume_chat(self, chat_id: str) -> None:
        record = await self._session.view_chat(chat_id)
        self._active_chat_id = chat_id
        self.query_one("#conversation", ConversationPane).rehydrate_from_record(record)
        async for _ in self._session.resume_chat(chat_id):
            pass

    async def action_open_workspaces(self) -> None:
        def _after(result) -> None:
            if isinstance(result, dict) and "insert_mention" in result:
                self._insert_mention_into_editor(result["insert_mention"])

        await self.push_screen(
            WorkspaceManagerScreen(
                session=self._session,
                active_workspace_id=self._state.workspace_id,
            ),
            _after,
        )

    async def action_open_files(self) -> None:
        prompt = self.query_one("#prompt_bar", PromptBar)
        try:
            picker = prompt.query_one("#prompt_file_picker", FilePicker)
        except Exception:
            return
        picker.index.workspace_dir = self._workspace_dir
        picker.index.invalidate()
        picker.refresh_query("")
        picker.focus_picker()

    async def action_upload_files(self) -> None:
        def _after(_result) -> None:
            self.run_worker(self._refresh_sidebar_resources())

        await self.push_screen(
            FileIngestScreen(
                session=self._session, workspace_id=self._state.workspace_id
            ),
            _after,
        )

    def _insert_mention_into_editor(self, path: str) -> None:
        try:
            editor = self.query_one("#prompt_bar", PromptBar).editor
        except Exception:
            return
        editor.insert_text(format_file_mention(path) + " ")
        try:
            self.set_focus(editor)
        except Exception:
            pass

    @on(ResumeChatRequested)
    async def on_resume_chat_requested(self, event: ResumeChatRequested) -> None:
        await self.action_resume_chat(event.chat_id)

    @on(InsertMentionRequested)
    def on_insert_mention_requested(self, event: InsertMentionRequested) -> None:
        self._insert_mention_into_editor(event.path)

    async def action_toggle_jump_mode(self) -> None:
        focused = self.focused
        jumper = Jumper(
            {
                "user_input": "1",
                "conversation": "2",
                "sidebar": "3",
                "workspace_bar": "w",
            },
            screen=self.screen,
        )

        def handle_jump(target: str | Widget | None) -> None:
            if target is None:
                if focused is not None:
                    self.set_focus(focused)
                return
            if isinstance(target, Widget):
                self.set_focus(target)
                return
            self.set_focus(self.query_one(f"#{target}", Widget))

        await self.push_screen(JumpOverlay(jumper), handle_jump)

    async def action_help(self) -> None:
        focused = self.focused

        def restore_focus(_: None) -> None:
            if focused is not None:
                self.set_focus(focused)

        await self.push_screen(HelpScreen(focused), restore_focus)

    def handle_approval_decision(
        self, plan: dict, step_contract: dict | None, decision: str
    ) -> None:
        approval = {"decision": decision, "decided_by": "user", "approval_kind": "code_execution"}
        self.pop_screen()
        if decision == "revise_requested":
            self.run_worker(self._stream_command("revise_goal", {"plan_id": plan.get("id")}))
            return
        self.run_worker(self._stream_resume_approved(plan, step_contract or {}, approval))

    async def _stream_resume_approved(self, plan, step_contract, approval) -> None:
        consumer = self._build_consumer()
        try:
            async for ev in self._session.resume_approved_step(
                workspace_dir=self._workspace_dir,
                state=self._state,
                plan_payload=plan,
                contract_payload=step_contract,
                approval=approval,
            ):
                consumer.dispatch(ev)
        except Exception as exc:
            self._emit_error(phase="resume_approved", exc=exc)
            self.notify(str(exc), severity="error")

    def handle_clarification_response(self, text: str) -> None:
        self.pop_screen()
        self.run_worker(self._stream_clarification(text))

    async def _stream_clarification(self, text: str) -> None:
        consumer = self._build_consumer()
        try:
            async for ev in self._session.resume_with_clarification(
                workspace_dir=self._workspace_dir,
                state=self._state,
                clarification_text=text,
            ):
                consumer.dispatch(ev)
        except Exception as exc:
            self._emit_error(phase="clarification", exc=exc)
            self.notify(str(exc), severity="error")
