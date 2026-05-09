from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness.chat import (
    ChatCompactor, ChatDeleteResult, ChatMessage, ChatRecord, ChatStore, ChatSummary,
    RuntimeRequestBuilder,
)
from harness.command_registry import (
    ArgSpec, CommandContext, HarnessCommandDescriptor, HarnessCommandRegistry, HelpResult,
)
from harness.context import ContextManager
from harness.control import (
    ApprovalRecord, DoctorReport, ModeSwitchEvent, Plan, PlanStep, PromptPackage,
    RunState, RunStateRecord, SessionConfig, StepContract, TmpAction,
)
from harness.doctor import Doctor
from harness.doctor_runner import DoctorRunner
from harness.events import (
    ApprovalRequired, ApprovalResolved, ArtifactsReady, ChatHistoryCompacted,
    ChatHistoryLoaded,
    CommandCompleted, CommandStarted, FinalMessage, HarnessEvent, ModeActivated,
    PlanReady, PromptBuilt, RuntimeDelta, RuntimeStatusChanged, StatusChanged,
    StepCompleted, StepTaskStatusChanged, StepTaskSubmitted, TurnCancelled,
    TurnFailed, TurnStarted,
)
from harness.exceptions import ChatNotFound, RunAlreadyActive, WorkspaceSwitchBlocked
from harness.persistence import HarnessPersistence
from harness.state_machine import HarnessStateMachine
from harness.status import HarnessStatusSnapshot, StatusBroker
from harness.workspace_async import AsyncWorkspaceManager, WorkspaceIngestResult, WorkspaceSummary
from observability import Telemetry, resolve_telemetry_dir
from runtime.protocol import Runtime
from runtime.types import RuntimeMessage, RuntimeRequest
from worker.executor import PythonStepExecutor
from worker.models import PermissionEnvelope, ResourceLimits, StepExecutionRequest


class Orchestrator:
    def __init__(
        self,
        *,
        runtime: Runtime | None = None,
        context_manager: ContextManager | None = None,
        worker: PythonStepExecutor | None = None,
        persistence: HarnessPersistence | None = None,
        doctor: Doctor | None = None,
        telemetry: Telemetry | None = None,
        config: SessionConfig | None = None,
        app_root: Path | None = None,
    ) -> None:
        self.telemetry = telemetry or getattr(persistence, "telemetry", None) or Telemetry(resolve_telemetry_dir())
        self.state_machine = HarnessStateMachine()
        self.runtime = runtime
        self.context_manager = context_manager or ContextManager()
        self.worker = worker or PythonStepExecutor()
        self.doctor = doctor or Doctor()
        if hasattr(self.worker, "telemetry"):
            self.worker.telemetry = self.telemetry
        self.persistence = persistence
        if self.persistence is not None:
            self.persistence.telemetry = self.telemetry
        self.config = config or SessionConfig()
        self.app_root = app_root or Path.cwd()
        self._active_run_id: str | None = None
        self._stop_after_step_run_ids: set[str] = set()
        self._step_action_requests: dict[str, str] = {}
        self._cancel_flags: dict[str, asyncio.Event] = {}
        self._run_lock = asyncio.Lock()
        self._status_broker: StatusBroker | None = None
        self._pending_contracts: dict[tuple[str, str], StepContract] = {}
        self.chat_store = ChatStore(self.app_root)
        self.request_builder: RuntimeRequestBuilder | None = None
        self._runtime_lock = asyncio.Lock()
        self.compactor: ChatCompactor | None = None
        self.workspace_manager = AsyncWorkspaceManager(app_root=self.app_root, chat_store=self.chat_store)
        self.doctor_runner = DoctorRunner(self.doctor)
        self.registry = HarnessCommandRegistry()
        self._register_commands()

    # ---- command registry ----
    def _register_commands(self) -> None:
        R = self.registry
        R.register(
            HarnessCommandDescriptor(
                name="doctor", slash_alias="/doctor",
                short_description="Run the harness doctor diagnostic",
                arguments=[ArgSpec(name="trigger", type="str", required=False, description="trigger label", example="manual")],
                available=True, disabled_reason=None, affected_resource="doctor",
                expected_event_types=["DoctorStarted", "CommandProgress", "DoctorFinding", "DoctorReportReady", "CommandCompleted"],
                example_usage="/doctor",
            ),
            self._handle_doctor,
        )
        R.register(
            HarnessCommandDescriptor(
                name="compact", slash_alias="/compact",
                short_description="Compact active chat history",
                arguments=[],
                available=True, affected_resource="chat",
                expected_event_types=["ChatHistoryCompacted", "CommandCompleted"],
                example_usage="/compact",
            ),
            self._handle_compact,
        )
        R.register(
            HarnessCommandDescriptor(
                name="help", slash_alias="/help", short_description="Show command help",
                arguments=[ArgSpec(name="command", type="str", required=False, description="command name", example="doctor")],
                available=True, affected_resource="run",
                expected_event_types=["CommandCompleted"], example_usage="/help inspect_artifact",
            ),
            self._handle_help,
        )
        for n, args_spec, resource in [
            ("create_chat", [ArgSpec(name="title", type="str", required=False, description="title", example=None)], "chat"),
            ("list_chats", [], "chat"),
            ("view_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
            ("resume_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
            ("delete_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
        ]:
            R.register(
                HarnessCommandDescriptor(
                    name=n, slash_alias=f"/{n}", short_description=n.replace("_", " "),
                    arguments=args_spec, available=True, affected_resource=resource,
                    expected_event_types=["CommandStarted", "CommandCompleted"], example_usage=f"/{n}",
                ),
                self._make_chat_handler(n),
            )
        for n, args_spec in [
            ("list_workspaces", []),
            ("create_workspace", [ArgSpec(name="workspace_id", type="workspace_id", required=True, description="workspace id", example="w_0002")]),
            ("rename_workspace", [
                ArgSpec(name="old_id", type="workspace_id", required=True, description="current workspace id", example="w_old"),
                ArgSpec(name="new_id", type="workspace_id", required=True, description="new workspace id", example="w_new"),
            ]),
            ("delete_workspace", [ArgSpec(name="workspace_id", type="workspace_id", required=True, description="workspace id", example="w_0002")]),
            ("switch_workspace", [
                ArgSpec(name="workspace_id", type="workspace_id", required=True, description="workspace id", example="w_0002"),
                ArgSpec(name="force", type="bool", required=False, description="cancel active run before switching", example="false"),
            ]),
            ("workspace_status", []),
            ("workspace_inventory", []),
        ]:
            R.register(
                HarnessCommandDescriptor(
                    name=n, slash_alias=f"/{n}", short_description=n.replace("_", " "),
                    arguments=args_spec, available=True, affected_resource="workspace",
                    expected_event_types=["CommandStarted", "StatusChanged", "CommandCompleted"],
                    example_usage=f"/{n}",
                ),
                self._make_workspace_handler(n),
            )
        R.register(
            HarnessCommandDescriptor(
                name="cancel_run", slash_alias="/cancel_run",
                short_description="Cancel the active run",
                arguments=[ArgSpec(
                    name="reason", type="str", required=False,
                    description="cancellation reason", example="user_request",
                )],
                available=True, affected_resource="run",
                expected_event_types=["CommandStarted", "TurnCancelled", "CommandCompleted"],
                example_usage='/cancel_run "stuck"',
            ),
            self._handle_cancel_run,
        )
        R.register(
            HarnessCommandDescriptor(
                name="memory_review", slash_alias="/memory_review",
                short_description="List memory update proposals",
                arguments=[ArgSpec(
                    name="status", type="str", required=False,
                    description="filter by status (pending|approved|applied|rejected)",
                    example="pending",
                )],
                available=True, affected_resource="memory",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/memory_review pending",
            ),
            self._handle_memory_review,
        )
        R.register(
            HarnessCommandDescriptor(
                name="inspect_artifact", slash_alias="/inspect_artifact",
                short_description="Inspect an artifact file in the active workspace",
                arguments=[ArgSpec(
                    name="path", type="artifact_path", required=True,
                    description="workspace-relative path",
                    example="artifacts/tmp/run_1/step_1/output.txt",
                )],
                available=True, affected_resource="artifact",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/inspect_artifact artifacts/out.txt",
            ),
            self._handle_inspect_artifact,
        )
        R.register(
            HarnessCommandDescriptor(
                name="provenance_inspect", slash_alias="/provenance_inspect",
                short_description="Inspect lineage for an artifact",
                arguments=[ArgSpec(
                    name="path", type="artifact_path", required=True,
                    description="workspace-relative artifact path",
                    example="artifacts/out.csv",
                )],
                available=True, affected_resource="provenance",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/provenance_inspect artifacts/out.csv",
            ),
            self._handle_provenance_inspect,
        )
        R.register(
            HarnessCommandDescriptor(
                name="validity_inspect", slash_alias="/validity_inspect",
                short_description="Inspect validity_state records",
                arguments=[ArgSpec(
                    name="subject_id", type="str", required=False,
                    description="filter records by subject_id (artifact path or step id)",
                    example="artifacts/out.csv",
                )],
                available=True, affected_resource="provenance",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/validity_inspect artifacts/out.csv",
            ),
            self._handle_validity_inspect,
        )
        R.register(
            HarnessCommandDescriptor(
                name="mark_result_trusted", slash_alias="/mark_result_trusted",
                short_description="Mark a step result as user-trusted (revalidated)",
                arguments=[
                    ArgSpec(name="step_id", type="step_id", required=True,
                            description="step whose result is trusted",
                            example="step_42"),
                    ArgSpec(name="reason", type="str", required=False,
                            description="why trust was granted",
                            example="spot-checked output"),
                ],
                available=True, affected_resource="step",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/mark_result_trusted step_42 \"spot-checked output\"",
            ),
            self._handle_mark_result_trusted,
        )
        R.register(
            HarnessCommandDescriptor(
                name="mark_result_invalidated", slash_alias="/mark_result_invalidated",
                short_description="Mark a step result as needing review",
                arguments=[
                    ArgSpec(name="step_id", type="step_id", required=True,
                            description="step whose result is invalidated",
                            example="step_42"),
                    ArgSpec(name="reason", type="str", required=False,
                            description="why the result is invalidated",
                            example="input data changed upstream"),
                ],
                available=True, affected_resource="step",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/mark_result_invalidated step_42 \"input changed\"",
            ),
            self._handle_mark_result_invalidated,
        )
        R.register(
            HarnessCommandDescriptor(
                name="challenge_conclusion", slash_alias="/challenge_conclusion",
                short_description="Open a review proposal challenging a prior conclusion",
                arguments=[
                    ArgSpec(name="target", type="str", required=True,
                            description="run_id, artifact path, or conclusion id under challenge",
                            example="run_42"),
                    ArgSpec(name="reason", type="str", required=True,
                            description="why the conclusion is being challenged",
                            example="sample size too small"),
                ],
                available=True, affected_resource="run",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/challenge_conclusion run_42 \"sample size too small\"",
            ),
            self._handle_challenge_conclusion,
        )
        R.register(
            HarnessCommandDescriptor(
                name="stop_after_current_step", slash_alias="/stop_after_current_step",
                short_description="Request graceful run stop after current step finishes",
                arguments=[
                    ArgSpec(name="run_id", type="run_id", required=False,
                            description="run to stop (defaults to active run)",
                            example="run_abc"),
                    ArgSpec(name="reason", type="str", required=False,
                            description="why a graceful stop was requested",
                            example="user requested graceful stop"),
                ],
                available=True, affected_resource="run",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/stop_after_current_step",
            ),
            self._handle_stop_after_current_step,
        )
        R.register(
            HarnessCommandDescriptor(
                name="revise_goal", slash_alias="/revise_goal",
                short_description="Revise the goal text on a plan record",
                arguments=[
                    ArgSpec(name="plan_id", type="str", required=True,
                            description="plan whose goal is being revised",
                            example="plan_1"),
                    ArgSpec(name="new_goal", type="str", required=True,
                            description="replacement goal text",
                            example="refined goal text"),
                ],
                available=True, affected_resource="plan",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/revise_goal plan_1 \"refined goal text\"",
            ),
            self._handle_revise_goal,
        )
        R.register(
            HarnessCommandDescriptor(
                name="retry_step", slash_alias="/retry_step",
                short_description="Request retry of a failed step within retry budget",
                arguments=[
                    ArgSpec(name="step_id", type="step_id", required=True,
                            description="step to retry", example="step_5"),
                    ArgSpec(name="reason", type="str", required=False,
                            description="why retry was requested",
                            example="transient timeout"),
                ],
                available=True, affected_resource="step",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/retry_step step_5 \"transient timeout\"",
            ),
            self._handle_retry_step,
        )
        R.register(
            HarnessCommandDescriptor(
                name="rerun_step", slash_alias="/rerun_step",
                short_description="Force re-execution of a step ignoring fingerprint cache",
                arguments=[
                    ArgSpec(name="step_id", type="step_id", required=True,
                            description="step to rerun", example="step_7"),
                    ArgSpec(name="reason", type="str", required=False,
                            description="why rerun was requested",
                            example="force fresh fingerprint"),
                ],
                available=True, affected_resource="step",
                expected_event_types=["CommandStarted", "CommandCompleted"],
                example_usage="/rerun_step step_7 \"force fresh fingerprint\"",
            ),
            self._handle_rerun_step,
        )

    # ---- command handlers ----
    async def _handle_doctor(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        workspace_dir = self.workspace_manager.workspaces_dir / (ctx.workspace_id or "")
        async for ev in self.doctor_runner.run(
            workspace_id=ctx.workspace_id or "", workspace_dir=workspace_dir,
            trigger=str(args.get("trigger", "manual")),
            chat_id=ctx.chat_id, run_id=ctx.run_id,
        ):
            yield ev

    async def _handle_compact(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="compact", arguments={},
        )
        if ctx.chat_id:
            async for ev in self.compact_chat_history(ctx.chat_id, reason="user_requested"):
                yield ev
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="compact", result={},
        )

    async def _handle_help(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="help", arguments=args,
        )
        res = self.registry.help(args.get("command"))
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="help", result=res.model_dump(),
        )

    async def _handle_cancel_run(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        reason = str(args.get("reason") or "user_request")
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="cancel_run", arguments={"reason": reason},
        )
        target_run_id = str(args.get("run_id")) if args.get("run_id") else self._active_run_id
        if target_run_id is None:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=None,
                command="cancel_run", result={"error": "no active run"},
            )
            return
        cancelled = await self.cancel_run(target_run_id, reason=reason)
        yield cancelled
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=target_run_id,
            command="cancel_run", result={"run_id": target_run_id, "reason": reason},
        )

    async def _handle_memory_review(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        status_filter = args.get("status")
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="memory_review", arguments={"status": status_filter} if status_filter else {},
        )
        proposals: list[dict[str, Any]] = []
        if self.persistence is not None:
            try:
                proposals = self.persistence.db.list_records("memory_update_proposals")
            except Exception as exc:
                yield CommandCompleted(
                    ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                    command="memory_review", result={"error": f"{type(exc).__name__}: {exc}"},
                )
                return
        if status_filter:
            proposals = [p for p in proposals if p.get("status") == status_filter]
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="memory_review",
            result={"proposals": proposals, "count": len(proposals), "status_filter": status_filter},
        )

    async def _handle_inspect_artifact(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        rel_path = str(args.get("path", ""))
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="inspect_artifact", arguments={"path": rel_path},
        )
        if not ctx.workspace_id:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="inspect_artifact", result={"error": "no active workspace"},
            )
            return
        workspace_dir = (self.workspace_manager.workspaces_dir / ctx.workspace_id).resolve()
        candidate = (workspace_dir / rel_path).resolve()
        try:
            candidate.relative_to(workspace_dir)
        except ValueError:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="inspect_artifact",
                result={"error": f"path {rel_path!r} resolves outside workspace"},
            )
            return
        if not candidate.exists():
            registry_entry: dict[str, Any] | None = None
            if self.persistence is not None:
                try:
                    registry_entry = self.persistence.db.load_record("artifact_registry", "path", rel_path)
                except KeyError:
                    registry_entry = None
                except Exception:
                    registry_entry = None
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="inspect_artifact",
                result={"path": rel_path, "exists": False, "registry": registry_entry},
            )
            return
        stat = candidate.stat()
        head_bytes = 4096
        try:
            head = candidate.read_bytes()[:head_bytes].decode("utf-8", errors="replace")
        except Exception as exc:
            head = f"<read error: {type(exc).__name__}: {exc}>"
        registry_entry = None
        if self.persistence is not None:
            try:
                registry_entry = self.persistence.db.load_record("artifact_registry", "path", rel_path)
            except KeyError:
                registry_entry = None
            except Exception:
                registry_entry = None
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="inspect_artifact",
            result={
                "path": rel_path,
                "exists": True,
                "size_bytes": stat.st_size,
                "modified_ts": stat.st_mtime,
                "content_head": head,
                "truncated": stat.st_size > head_bytes,
                "registry": registry_entry,
            },
        )

    async def _handle_provenance_inspect(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        rel_path = str(args.get("path", ""))
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="provenance_inspect", arguments={"path": rel_path},
        )
        if self.persistence is None:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="provenance_inspect",
                result={"path": rel_path, "found": False, "error": "persistence unavailable"},
            )
            return
        try:
            lineage = self.persistence.db.load_record("lineage_records", "artifact_path", rel_path)
        except KeyError:
            lineage = None
        registry: dict[str, Any] | None = None
        try:
            registry = self.persistence.db.load_record("artifact_registry", "path", rel_path)
        except KeyError:
            registry = None
        validity: dict[str, Any] | None = None
        if lineage is not None and lineage.get("validity_id"):
            try:
                validity = self.persistence.db.load_record("validity_state", "id", str(lineage["validity_id"]))
            except KeyError:
                validity = None
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="provenance_inspect",
            result={
                "path": rel_path,
                "found": lineage is not None,
                "lineage": lineage,
                "registry": registry,
                "validity": validity,
            },
        )

    async def _handle_validity_inspect(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        subject_filter = args.get("subject_id")
        subject_filter_str = str(subject_filter) if subject_filter else None
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="validity_inspect",
            arguments={"subject_id": subject_filter_str} if subject_filter_str else {},
        )
        if self.persistence is None:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="validity_inspect",
                result={"records": [], "count": 0, "subject_id_filter": subject_filter_str,
                        "error": "persistence unavailable"},
            )
            return
        try:
            records = self.persistence.db.list_records("validity_state")
        except Exception as exc:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="validity_inspect",
                result={"error": f"{type(exc).__name__}: {exc}"},
            )
            return
        if subject_filter_str:
            records = [r for r in records if r.get("subject_id") == subject_filter_str]
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="validity_inspect",
            result={"records": records, "count": len(records), "subject_id_filter": subject_filter_str},
        )

    async def _mark_step_validity(
        self, ctx: CommandContext, args: dict[str, Any], *, command: str, status: str,
    ) -> AsyncIterator[HarnessEvent]:
        step_id = args.get("step_id")
        reason = args.get("reason")
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command=command,
            arguments={"step_id": step_id, "reason": reason} if reason else {"step_id": step_id},
        )
        if not step_id:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command, result={"error": "step_id required"},
            )
            return
        if self.persistence is None:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command, result={"error": "persistence unavailable"},
            )
            return
        step_id_str = str(step_id)
        try:
            self.persistence.db.load_record("step_records", "id", step_id_str)
        except KeyError:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command,
                result={"error": f"step_id {step_id_str!r} not found in step_records"},
            )
            return
        record_id = f"validity:step:{step_id_str}"
        record: dict[str, Any] = {
            "id": record_id,
            "subject_id": step_id_str,
            "subject_kind": "step",
            "status": status,
            "set_by": "user",
            "set_at": datetime.now(UTC).isoformat(),
        }
        if reason:
            record["reason"] = str(reason)
        try:
            self.persistence.db.save_record("validity_state", "id", record_id, record)
        except Exception as exc:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command, result={"error": f"{type(exc).__name__}: {exc}"},
            )
            return
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command=command,
            result={"step_id": step_id_str, "status": status, "record_id": record_id},
        )

    async def _handle_mark_result_trusted(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        async for ev in self._mark_step_validity(
            ctx, args, command="mark_result_trusted", status="revalidated",
        ):
            yield ev

    async def _handle_mark_result_invalidated(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        async for ev in self._mark_step_validity(
            ctx, args, command="mark_result_invalidated", status="needs_review",
        ):
            yield ev

    async def _handle_challenge_conclusion(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        target = str(args.get("target") or "")
        reason = str(args.get("reason") or "")
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="challenge_conclusion",
            arguments={"target": target, "reason": reason},
        )
        if self.persistence is None:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="challenge_conclusion", result={"error": "persistence unavailable"},
            )
            return
        proposal_id = f"challenge:{uuid4().hex}"
        record = {
            "id": proposal_id,
            "kind": "challenge_conclusion",
            "target": target,
            "reason": reason,
            "status": "open",
            "raised_by": "user",
            "raised_at": datetime.now(UTC).isoformat(),
            "workspace_id": ctx.workspace_id,
            "chat_id": ctx.chat_id,
            "run_id": ctx.run_id,
        }
        try:
            self.persistence.db.append_record("review_proposals", proposal_id, record)
        except Exception as exc:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="challenge_conclusion",
                result={"error": f"{type(exc).__name__}: {exc}"},
            )
            return
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="challenge_conclusion",
            result={"proposal_id": proposal_id, "target": target, "reason": reason, "status": "open"},
        )

    async def _handle_stop_after_current_step(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        reason = str(args.get("reason") or "user_request")
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="stop_after_current_step", arguments={"reason": reason},
        )
        target_run_id = str(args.get("run_id")) if args.get("run_id") else self._active_run_id
        if target_run_id is None:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=None,
                command="stop_after_current_step", result={"error": "no active run"},
            )
            return
        self._stop_after_step_run_ids.add(target_run_id)
        if self.persistence is not None:
            try:
                self.persistence.db.append_record(
                    "run_state_history", f"stop_after:{target_run_id}:{uuid4().hex}",
                    {
                        "run_id": target_run_id,
                        "event": "stop_after_current_step_requested",
                        "reason": reason,
                        "requested_by": "user",
                        "ts": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception:
                pass
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=target_run_id,
            command="stop_after_current_step",
            result={"run_id": target_run_id, "reason": reason, "status": "stop_requested"},
        )

    async def _handle_revise_goal(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        plan_id = str(args.get("plan_id") or "")
        new_goal = str(args.get("new_goal") or "")
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="revise_goal", arguments={"plan_id": plan_id, "new_goal": new_goal},
        )
        if self.persistence is None:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="revise_goal", result={"error": "persistence unavailable"},
            )
            return
        try:
            plan = self.persistence.db.load_record("plan_records", "id", plan_id)
        except KeyError:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="revise_goal", result={"error": f"plan_id {plan_id!r} not found"},
            )
            return
        previous_goal = str(plan.get("goal") or "")
        plan["goal"] = new_goal
        plan["updated_at"] = datetime.now(UTC).isoformat()
        try:
            self.persistence.db.save_record("plan_records", "id", plan_id, plan)
        except Exception as exc:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command="revise_goal", result={"error": f"{type(exc).__name__}: {exc}"},
            )
            return
        try:
            self.persistence.db.append_record(
                "run_state_history", f"goal_revised:{plan_id}:{uuid4().hex}",
                {
                    "event": "goal_revised",
                    "plan_id": plan_id,
                    "previous_goal": previous_goal,
                    "new_goal": new_goal,
                    "requested_by": "user",
                    "ts": datetime.now(UTC).isoformat(),
                    "run_id": ctx.run_id,
                    "workspace_id": ctx.workspace_id,
                },
            )
        except Exception:
            pass
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="revise_goal",
            result={"plan_id": plan_id, "previous_goal": previous_goal, "new_goal": new_goal},
        )

    async def _request_step_action(
        self, ctx: CommandContext, args: dict[str, Any], *, command: str, action: str,
    ) -> AsyncIterator[HarnessEvent]:
        step_id = str(args.get("step_id") or "")
        reason = args.get("reason")
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command=command,
            arguments={"step_id": step_id, "reason": reason} if reason else {"step_id": step_id},
        )
        if not step_id:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command, result={"error": "step_id required"},
            )
            return
        self._step_action_requests[step_id] = action
        if self.persistence is not None:
            try:
                self.persistence.db.append_record(
                    "step_action_history", f"{action}:{step_id}:{uuid4().hex}",
                    {
                        "step_id": step_id,
                        "action": action,
                        "reason": str(reason) if reason else None,
                        "requested_by": "user",
                        "ts": datetime.now(UTC).isoformat(),
                        "run_id": ctx.run_id,
                        "workspace_id": ctx.workspace_id,
                    },
                )
            except Exception as exc:
                yield CommandCompleted(
                    ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                    command=command, result={"error": f"{type(exc).__name__}: {exc}"},
                )
                return
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command=command,
            result={"step_id": step_id, "action": action, "status": "requested"},
        )

    async def _handle_retry_step(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        async for ev in self._request_step_action(ctx, args, command="retry_step", action="retry"):
            yield ev

    async def _handle_rerun_step(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        async for ev in self._request_step_action(ctx, args, command="rerun_step", action="rerun"):
            yield ev

    async def _handle_unavailable(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="(unavailable)", result={"error": "not implemented"},
        )

    def _make_chat_handler(self, command_name: str):
        async def handler(ctx, args):
            yield CommandStarted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command_name, arguments=args,
            )
            result: dict = {}
            try:
                if command_name == "create_chat":
                    if ctx.workspace_id is None:
                        raise ValueError("create_chat requires active workspace_id in CommandContext")
                    summary = await self.create_chat(workspace_id=ctx.workspace_id, title=args.get("title"))
                    result = {"chat": summary.model_dump(mode="json")}
                elif command_name == "list_chats":
                    if ctx.workspace_id is None:
                        raise ValueError("list_chats requires active workspace_id")
                    chats = await self.list_chats(ctx.workspace_id)
                    result = {"chats": [c.model_dump(mode="json") for c in chats]}
                elif command_name == "view_chat":
                    rec = await self.view_chat(args["chat_id"])
                    result = {"chat": rec.model_dump(mode="json")}
                elif command_name == "resume_chat":
                    events = [e async for e in self.resume_chat(args["chat_id"])]
                    result = {"events": [e.model_dump(mode="json") for e in events]}
                elif command_name == "delete_chat":
                    res = await self.delete_chat(args["chat_id"])
                    result = {"deleted": res.model_dump(mode="json")}
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command_name, result=result,
            )
        return handler

    def _make_workspace_handler(self, command_name: str):
        async def handler(ctx, args):
            yield CommandStarted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command_name, arguments=args,
            )
            result: dict[str, Any] = {}
            try:
                workspace_id = str(args.get("workspace_id") or ctx.workspace_id or "")
                if command_name == "list_workspaces":
                    workspaces = await self.list_workspaces()
                    result = {"workspaces": [w.model_dump(mode="json") for w in workspaces]}
                elif command_name == "create_workspace":
                    summary = await self.create_workspace(workspace_id)
                    result = {"workspace": summary.model_dump(mode="json")}
                elif command_name == "rename_workspace":
                    summary = await self.rename_workspace(str(args["old_id"]), str(args["new_id"]))
                    result = {"workspace": summary.model_dump(mode="json")}
                elif command_name == "delete_workspace":
                    summary = await self.delete_workspace(workspace_id)
                    result = {"workspace": summary.model_dump(mode="json")}
                elif command_name == "switch_workspace":
                    snapshot = await self.activate_workspace(workspace_id, force=bool(args.get("force", False)))
                    yield StatusChanged(
                        ts=datetime.now(UTC), workspace_id=snapshot.workspace_id,
                        chat_id=snapshot.chat_id, run_id=snapshot.run_id, snapshot=snapshot,
                    )
                    result = {"snapshot": snapshot.model_dump(mode="json")}
                elif command_name == "workspace_status":
                    snapshot = await self.status_snapshot(workspace_id=workspace_id)
                    yield StatusChanged(
                        ts=datetime.now(UTC), workspace_id=snapshot.workspace_id,
                        chat_id=snapshot.chat_id, run_id=snapshot.run_id, snapshot=snapshot,
                    )
                    result = {"snapshot": snapshot.model_dump(mode="json")}
                elif command_name == "workspace_inventory":
                    workspaces = await self.list_workspaces()
                    result = {"workspaces": [w.model_dump(mode="json") for w in workspaces]}
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
                command=command_name, result=result,
            )
        return handler

    # ---- public command API ----
    async def list_commands(self, context: CommandContext | None = None) -> list[HarnessCommandDescriptor]:
        return self.registry.list_descriptors(context or CommandContext(
            workspace_id=None, chat_id=None, run_id=None,
            has_pending_approval=False, has_pending_clarification=False,
        ))

    async def help(self, command: str | None = None) -> HelpResult:
        return self.registry.help(command)

    async def handle_direct_command(
        self,
        state: RunStateRecord,
        *,
        command: str,
        arguments: dict[str, Any],
    ) -> AsyncIterator[HarnessEvent]:
        arguments = self.registry.validate(command, arguments)
        ctx = CommandContext(
            workspace_id=state.workspace_id,
            chat_id=arguments.get("chat_id"),  # type: ignore[arg-type]
            run_id=getattr(state, "run_id", None),
            has_pending_approval=getattr(state, "state", None) == RunState.AWAITING_APPROVAL,
            has_pending_clarification=bool(getattr(state, "pending_clarification_id", None)),
        )
        handler = self.registry.get_handler(command)
        async for ev in handler(ctx, arguments):
            yield ev

    # ---- workspace API ----
    async def list_workspaces(self) -> list[WorkspaceSummary]:
        return await self.workspace_manager.list_workspaces()

    async def create_workspace(self, workspace_id: str) -> WorkspaceSummary:
        return await self.workspace_manager.create_workspace(workspace_id)

    async def rename_workspace(self, old_id: str, new_id: str) -> WorkspaceSummary:
        return await self.workspace_manager.rename_workspace(old_id, new_id)

    async def delete_workspace(self, workspace_id: str) -> WorkspaceSummary:
        return await self.workspace_manager.delete_workspace(workspace_id)

    async def activate_workspace(
        self, workspace_id: str, force: bool = False,
    ) -> HarnessStatusSnapshot:
        if self._active_run_id is not None:
            if not force:
                raise WorkspaceSwitchBlocked(active_run_id=self._active_run_id)
            await self.cancel_run(self._active_run_id, reason="workspace_switch")
        await self.workspace_manager.activate_workspace(workspace_id, force=force)
        return await self.status_snapshot(workspace_id=workspace_id)

    async def ingest_files(self, workspace_id: str, paths: list[Path]) -> WorkspaceIngestResult:
        return await self.workspace_manager.ingest_files(workspace_id, paths)

    # ---- single-active-run guard ----
    async def _acquire_run(self, run_id: str) -> asyncio.Event:
        async with self._run_lock:
            if self._active_run_id is not None:
                raise RunAlreadyActive(run_id=self._active_run_id)
            self._active_run_id = run_id
            cancel = asyncio.Event()
            self._cancel_flags[run_id] = cancel
            return cancel

    async def _release_run(self, run_id: str) -> None:
        async with self._run_lock:
            if self._active_run_id == run_id:
                self._active_run_id = None
            self._cancel_flags.pop(run_id, None)

    # ---- chat management ----
    async def create_chat(self, *, workspace_id: str, title: str | None = None) -> ChatSummary:
        return await self.chat_store.create_chat(workspace_id=workspace_id, title=title)

    async def list_chats(self, workspace_id: str) -> list[ChatSummary]:
        return await self.chat_store.list_chats(workspace_id)

    async def view_chat(self, chat_id: str) -> ChatRecord:
        return await self.chat_store.view_chat(chat_id)

    async def delete_chat(self, chat_id: str) -> ChatDeleteResult:
        return await self.chat_store.delete_chat(chat_id)

    async def resume_chat(self, chat_id: str) -> AsyncIterator[HarnessEvent]:
        rec = await self.chat_store.view_chat(chat_id)
        yield ChatHistoryLoaded(
            ts=datetime.now(UTC), workspace_id=rec.workspace_id, chat_id=chat_id,
            message_count=rec.message_count, token_estimate=rec.token_estimate,
            source="resumed",
        )

    async def compact_chat_history(
        self, chat_id: str, reason: str = "user_requested",
    ) -> AsyncIterator[HarnessEvent]:
        rec = await self.chat_store.view_chat(chat_id)
        if self.compactor is None:
            self.compactor = ChatCompactor(
                store=self.chat_store, runtime=self.runtime, runtime_lock=self._runtime_lock,
            )
        async for status in self.compactor.compact(chat_id, reason=reason):
            snapshot = await self.chat_store.view_chat(chat_id)
            yield ChatHistoryCompacted(
                ts=datetime.now(UTC), workspace_id=rec.workspace_id, chat_id=chat_id,
                status=status,
                summary_token_estimate=None,
                replaced_turn_count=None,
                compaction_count=snapshot.compaction_count,
            )

    # ---- public async API ----
    async def run_turn(
        self,
        state: RunStateRecord,
        *,
        workspace_dir: Path,
        chat_id: str,
        user_input: str,
        requested_mode: str | None = None,
        prompt_text: str | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        run_id = state.run_id
        cancel = await self._acquire_run(run_id)
        active_mode = requested_mode or state.active_agent_mode
        turn_id = f"turn_{uuid4().hex[:12]}"
        user_msg_id = f"msg_{uuid4().hex[:12]}"
        ts = datetime.now(UTC)
        try:
            yield TurnStarted(
                ts=ts, workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                turn_id=turn_id, user_message_id=user_msg_id, active_mode=active_mode,
            )
            yield ModeActivated(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                mode=active_mode, prior_mode=state.active_agent_mode, decided_at=datetime.now(UTC),
            )
            # Load chat history and emit event (auto-register unknown chat_ids for backwards compat)
            try:
                await self.chat_store.view_chat(chat_id)
            except ChatNotFound:
                await self.chat_store.register_chat(chat_id=chat_id, workspace_id=state.workspace_id)
            chat_record = await self.chat_store.view_chat(chat_id)
            yield ChatHistoryLoaded(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                message_count=chat_record.message_count, token_estimate=chat_record.token_estimate,
                source="new" if chat_record.message_count == 0 else "resumed",
            )
            # Append user message (lazy flush to disk)
            await self.chat_store.append_message(chat_id, ChatMessage(
                message_id=user_msg_id, role="user", text=user_input,
                ts=datetime.now(UTC), turn_id=turn_id, active_mode=active_mode,
                token_estimate=max(len(user_input) // 4, 1),
            ))
            if cancel.is_set():
                yield TurnCancelled(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id,
                    run_id=run_id, reason="cancel_before_runtime", cancelled_at=datetime.now(UTC),
                )
                return

            # Plan/approval branch for analyst mode
            if active_mode == "analyst" and "compare" in user_input.lower():
                plan, contract = self._build_v1_analysis_plan(state, user_input)
                yield PlanReady(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                    plan_id=plan.id, plan=plan.model_dump(mode="json"),
                )
                yield ApprovalRequired(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                    plan_id=plan.id, step_id="step_1",
                    step=plan.steps[0].model_dump(mode="json"),
                    prompt="Approval required before running code.",
                )
                self._pending_contracts[(state.run_id, "step_1")] = contract
                return

            # Runtime stream
            if self.runtime is None:
                yield TurnFailed(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id,
                    run_id=run_id,
                    failure_summary="LLM runtime is not loaded. Configure DATAHARNESS_MODEL_PATH or use the packaged model.",
                    error_code="runtime_not_loaded",
                    details={"runtime_status": "not_loaded"},
                )
                return

            # Build request using RuntimeRequestBuilder
            ctx_window = await self.runtime.context_window()
            runtime_chat_format = getattr(self.runtime, "chat_format", None)
            if (
                self.request_builder is None
                or self.request_builder.context_window != ctx_window
                or self.request_builder.chat_format != runtime_chat_format
            ):
                self.request_builder = RuntimeRequestBuilder(
                    context_window=ctx_window, chat_format=runtime_chat_format,
                )
            durable_context = ""  # plan 3c plumbs ContextManager output here
            chat_record_after_user = await self.chat_store.view_chat(chat_id)
            messages = self.request_builder.build_messages(
                active_mode_prompt=prompt_text or "You are the harness.",
                durable_context=durable_context,
                chat_record=chat_record_after_user,
                current_user_text=user_input,
            )
            request = RuntimeRequest(
                messages=messages,
                max_completion_tokens=self.request_builder.completion_reservation,
                request_id=f"req_{uuid4().hex[:12]}",
                correlation_id=run_id,
            )
            pressure = await self.runtime.token_pressure(request)
            if pressure.over_threshold:
                async for _ in self.compact_chat_history(chat_id, reason="token_pressure"):
                    pass
                chat_record_after_compact = await self.chat_store.view_chat(chat_id)
                messages = self.request_builder.build_messages(
                    active_mode_prompt=prompt_text or "You are the harness.",
                    durable_context=durable_context,
                    chat_record=chat_record_after_compact,
                    current_user_text=user_input,
                )
                request = RuntimeRequest(
                    messages=messages,
                    max_completion_tokens=self.request_builder.completion_reservation,
                    request_id=f"req_{uuid4().hex[:12]}",
                    correlation_id=run_id,
                )
            yield PromptBuilt(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                request_id=request.request_id, prompt_token_estimate=pressure.prompt_tokens,
                breakdown={"prompt": pressure.prompt_tokens, "reserved": pressure.reserved_completion_tokens},
            )

            buffer: list[str] = []
            usage: dict[str, int] = {}
            async with self._runtime_lock:
                async for ev in self.runtime.stream(request):
                    if cancel.is_set():
                        yield TurnCancelled(
                            ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id,
                            run_id=run_id, reason="user", cancelled_at=datetime.now(UTC),
                        )
                        return
                    if ev.type == "text_delta":
                        buffer.append(ev.text or "")
                        yield RuntimeDelta(
                            ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                            request_id=ev.request_id, seq=ev.seq, delta_type="text", text=ev.text, tool_call=None,
                        )
                    elif ev.type == "reasoning_delta":
                        yield RuntimeDelta(
                            ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                            request_id=ev.request_id, seq=ev.seq, delta_type="reasoning", text=ev.text, tool_call=None,
                        )
                    elif ev.type == "tool_call":
                        yield RuntimeDelta(
                            ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                            request_id=ev.request_id, seq=ev.seq, delta_type="tool_call",
                            text=None, tool_call=ev.tool_call,
                        )
                    elif ev.type == "finish":
                        usage = ev.usage or {}
                    elif ev.type == "error":
                        yield TurnFailed(
                            ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                            failure_summary=ev.error_message or "runtime error",
                            error_code=ev.error_code or "runtime_error",
                            details={"finish_reason": ev.finish_reason},
                        )
                        return

            # Persist assistant message
            assistant_text = "".join(buffer)
            assistant_msg_id = f"asg_{uuid4().hex[:12]}"
            await self.chat_store.append_message(chat_id, ChatMessage(
                message_id=assistant_msg_id,
                role="assistant", text=assistant_text, ts=datetime.now(UTC),
                turn_id=turn_id, active_mode=active_mode,
                token_estimate=max(len(assistant_text) // 4, 1),
            ))
            yield FinalMessage(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                assistant_message_id=assistant_msg_id,
                text=assistant_text, usage=usage,
            )
        finally:
            await self._release_run(run_id)

    async def close(self) -> None:
        if self._status_broker is not None:
            await self._status_broker.close()

    async def cancel_run(self, run_id: str, reason: str) -> TurnCancelled:
        async with self._run_lock:
            cancel = self._cancel_flags.get(run_id)
            if cancel is not None:
                cancel.set()
        # Also cancel any outstanding worker tasks tagged with this run.
        try:
            tasks = await self.worker.list_tasks()
            for t in tasks:
                if t.run_id == run_id and t.status in ("queued", "running"):
                    await self.worker.cancel(t.task_id, reason=reason)
        except Exception:
            pass
        return TurnCancelled(
            ts=datetime.now(UTC), run_id=run_id, reason=reason, cancelled_at=datetime.now(UTC),
        )

    async def status_snapshot(self, workspace_id: str | None = None) -> HarnessStatusSnapshot:
        runtime_status = await self.runtime.status() if self.runtime else "not_loaded"
        tasks = await self.worker.list_tasks()
        counts: dict[str, int] = {}
        for t in tasks:
            counts[t.status] = counts.get(t.status, 0) + 1
        return HarnessStatusSnapshot(
            workspace_id=workspace_id or "",
            chat_id=None, chat_title=None,
            workspace_health="ready",
            active_mode="interaction",
            run_id=self._active_run_id,
            run_state="running" if self._active_run_id else "idle",
            runtime_status=runtime_status,
            execution_tasks=counts,
            approval_state="idle", clarification_state="idle",
            chat_turn_count=0, chat_token_estimate=0,
            last_compacted_at=None, compaction_count=0,
            doctor_warning_count=0, last_event=None,
        )

    async def watch_status(self) -> AsyncIterator[HarnessStatusSnapshot]:
        if self._status_broker is None:
            self._status_broker = StatusBroker(
                await self.status_snapshot(),
                heartbeat_seconds=self.config.status_heartbeat_seconds,
                coalesce_seconds=self.config.status_coalesce_seconds,
            )
        async for snap in self._status_broker.watch():
            yield snap

    async def resume_approved_step(
        self,
        *,
        workspace_dir: Path,
        state: RunStateRecord,
        plan_payload: dict,
        contract_payload: dict,
        approval: ApprovalRecord,
    ) -> AsyncIterator[HarnessEvent]:
        plan = Plan.model_validate(plan_payload)
        step_id = str(contract_payload.get("_step_id") or contract_payload.get("step_id") or "step_1")
        contract = self._pending_contracts.pop((state.run_id, step_id), None)
        if contract is None:
            contract = StepContract.model_validate(contract_payload)
        yield ApprovalResolved(
            ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
            plan_id=plan.id, step_id=step_id, decision="approved",
        )
        cancel = await self._acquire_run(state.run_id)
        try:
            request = StepExecutionRequest(
                id=contract.id,
                workspace_id=contract.workspace_id, run_id=contract.run_id,
                plan_id=contract.plan_id, step_id=contract.step_id,
                workspace_dir=workspace_dir,
                code=contract.code,
                declared_inputs={p: p for p in contract.declared_inputs},
                workspace_paths=contract.workspace_paths,
                permission_envelope=PermissionEnvelope(**contract.permission_envelope),
                expected_output_contract=list(contract.expected_output_contract.get("files", [])),
                run_metadata=contract.run_metadata,
                resource_limits=ResourceLimits(),
            )
            handle = await self.worker.submit(request)
            yield StepTaskSubmitted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
                task_id=handle.task_id, step_id=contract.step_id, plan_id=plan.id,
            )
            # Initial running status
            running_status = await self.worker.get_task(handle.task_id)
            if running_status is not None:
                yield StepTaskStatusChanged(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
                    task_id=handle.task_id, status=running_status,
                )
            envelope = await self.worker.wait(handle.task_id)
            yield StepTaskStatusChanged(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
                task_id=handle.task_id, status=envelope.status,
            )
            yield StepCompleted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
                task_id=handle.task_id, envelope=envelope,
            )
            yield ArtifactsReady(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
                step_id=contract.step_id, artifacts=envelope.artifacts,
            )
            yield FinalMessage(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
                assistant_message_id=f"asg_{uuid4().hex[:12]}",
                text=f"Analysis complete. See {envelope.artifacts[0] if envelope.artifacts else 'artifacts'}.",
                usage={},
            )
        finally:
            await self._release_run(state.run_id)

    async def resume_with_clarification(
        self,
        *,
        workspace_dir: Path,
        state: RunStateRecord,
        clarification_text: str,
    ) -> AsyncIterator[HarnessEvent]:
        cleared = state.model_copy(update={"state": RunState.CLARIFYING, "pending_clarification_id": None})
        async for ev in self.run_turn(
            cleared, workspace_dir=workspace_dir, chat_id=state.run_id,
            user_input=clarification_text, requested_mode=state.active_agent_mode,
        ):
            yield ev

    # ---- legacy sync helpers (kept for plan 3c / backwards compat) ----
    def prepare_worker_dispatch(
        self,
        plan: Plan,
        *,
        approval: ApprovalRecord | None,
    ) -> dict[str, object]:
        if not self.state_machine.can_dispatch_execution(plan, approval):
            return {
                "dispatch": False,
                "reason": "explicit code execution approval required",
            }
        return {"dispatch": True, "plan_id": plan.id}

    def _build_v1_analysis_plan(self, state: RunStateRecord, user_input: str) -> tuple[Plan, StepContract]:
        step = PlanStep(
            id="step_1",
            workspace_id=state.workspace_id,
            plan_id=f"plan_{state.run_id}",
            step_order=1,
            purpose="Create a small evidence artifact for the requested analysis.",
            kind="code",
            declared_inputs=["data/input.csv"],
            expected_outputs=["output.txt"],
        )
        plan = Plan(
            id=f"plan_{state.run_id}",
            workspace_id=state.workspace_id,
            run_id=state.run_id,
            goal=user_input,
            steps=[step],
            requires_code_execution=True,
        )
        contract = StepContract(
            id=f"contract_{state.run_id}_step_1",
            workspace_id=state.workspace_id,
            run_id=state.run_id,
            plan_id=plan.id,
            step_id=step.id,
            code="from pathlib import Path\nPath('output.txt').write_text('department,leavers\\nSales,1\\n')\n",
            declared_inputs=["data/input.csv"],
            workspace_paths={"workspace": "."},
            permission_envelope={
                "allowed_read_paths": ["data/input.csv"],
                "registered_artifact_paths": [],
                "allowed_write_roots": ["artifacts/tmp"],
                "allowed_packages": ["pathlib"],
                "allow_network": False,
                "allow_shell": False,
            },
            expected_output_contract={"files": ["output.txt"]},
            run_metadata={"source": "deterministic_v1_analysis_plan"},
        )
        return plan, contract

    def switch_workspace(self, state: RunStateRecord, *, new_workspace_id: str) -> RunStateRecord:
        new_state = RunStateRecord(
            workspace_id=new_workspace_id,
            active_agent_mode=state.active_agent_mode,
            state=RunState.IDLE,
        )
        if self.persistence is not None:
            record_id = f"{state.run_id}:switch:{new_state.run_id}"
            self.persistence.save_dict(
                "mode_switch_history",
                "id",
                record_id,
                {
                    "id": record_id,
                    "run_id": new_state.run_id,
                    "from_run_id": state.run_id,
                    "from_workspace_id": state.workspace_id,
                    "to_workspace_id": new_workspace_id,
                    "from_mode": state.active_agent_mode,
                    "to_mode": new_state.active_agent_mode,
                    "reason": "switch_workspace_command",
                    "requested_by": "user",
                    "accepted": True,
                },
            )
            self.persistence.save_model("run_records", "run_id", new_state.run_id, new_state)
            self.persistence.save_model("run_state_history", "id", new_state.id, new_state)
        return new_state
