from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness.services.chat import (
    ChatCompactor, ChatDeleteResult, ChatMessage, ChatRecord, ChatStore, ChatSummary,
    RuntimeRequestBuilder,
)
from harness.core.analysis_flow import AnalysisFlow, AnalysisPhase
from harness.core.command_registry import (
    ArgSpec, CommandContext, HarnessCommandDescriptor, HarnessCommandRegistry, HelpResult,
)
from harness.services.context import ContextManager, list_workspace_files, read_file_schema
from harness.control import (
    ApprovalRecord, DoctorReport, ModeSwitchEvent, Plan, PromptPackage,
    RunState, RunStateRecord, SessionConfig, StepContract, TmpAction, utc_now,
)
from harness.events import (
    ApprovalRequired, ApprovalResolved, ArtifactsReady, ChatHistoryCompacted,
    ChatHistoryLoaded,
    CommandCompleted, CommandProgress, CommandStarted, DoctorActionProposed, DoctorActionsApplied,
    DoctorFinding, FinalMessage,
    HarnessEvent, ModeActivated,
    PlanReady, PromptBuilt, RuntimeDelta, RuntimeStatusChanged, StatusChanged,
    ModeHandoffAccepted, StepCompleted, StepTaskStatusChanged, StepTaskSubmitted,
    ToolCallExecuted, TurnCancelled, TurnFailed, TurnPaused, TurnStarted,
)
from harness.services.knowledge import KnowledgeManager
from harness.services.analysis import AnalysisService
from harness.services.doctor import Doctor, DoctorRunner
from harness.services.mode_router import ModeRouter
from harness.services.prompt_profiles import PromptProfileRegistry
from harness.services.workspace_files import WorkspaceFileService
from harness.tools.analysis import (
    make_analysis_plan_handler, make_analysis_request_execution_handler,
)
from harness.tools.control import CONTROL_TOOL_NAMES, make_control_handler
from harness.tools.file import make_file_read_handler
from harness.tools.knowledge import (
    make_knowledge_propose_update_handler, make_knowledge_recall_handler,
)
from harness.tools.registry import (
    HarnessToolRegistry, ToolArgSpec, ToolContext, ToolDescriptor,
)
from harness.exceptions import ChatNotFound, RunAlreadyActive, WorkspaceSwitchBlocked
from harness.core.persistence import HarnessPersistence
from harness.core.state_machine import HarnessStateMachine
from harness.status import HarnessStatusSnapshot, StatusBroker
from harness.services.workspace import AsyncWorkspaceManager, WorkspaceIngestResult, WorkspaceSummary
from observability import Telemetry, resolve_telemetry_dir
from runtime.protocol import Runtime
from runtime.tool_calls import (
    ToolCallParseError, extract_fenced_code, parse_tool_call_block,
)
from runtime.types import RuntimeMessage, RuntimeRequest
from worker.executor import PythonStepExecutor
from worker.models import PermissionEnvelope, ResourceLimits, StepExecutionRequest

_ASSISTANT_DRAFT_TAG_RE = re.compile(r"\[/?ASSISTANT_DRAFT\]\s*")
_TURN_MARKER_RE = re.compile(
    r"(?:\[/?(?:start|end)_of_turn\]|/?(?:start|end)_of_turn>|<\s*/?(?:start|end)_of_turn\s*>)",
    re.IGNORECASE,
)
_GEN2_MAX_TOKENS = 2048
_GEN2_SYSTEM_PROMPT = (
    "You write a single self-contained Python snippet for ONE analysis step. "
    "Output ONLY a fenced ```python code block, nothing before or after it.\n"
    "Rules:\n"
    "- Use only these imports: pandas, numpy, pathlib, csv, json, math, "
    "statistics, time. No os, sys, shell, filesystem traversal, or network.\n"
    "- Read inputs from the given workspace-relative paths "
    "(e.g. pd.read_csv(\"data/x.csv\")). The harness stages declared inputs.\n"
    "- Compute the answer (do not hardcode it, do not fabricate data).\n"
    "- Write a SHORT human-readable summary to every expected output named "
    "below using Path(\"<name>\").write_text(...); the literal filename of "
    "each expected output MUST appear in the code. Also print() the answer.\n"
    "- Do NOT wrap reads in try/except, do NOT call exit()/sys.exit(); let "
    "real exceptions propagate."
)

_FORCE_PLAN_MAX_TOKENS = 1024
_FORCE_PLAN_SYSTEM_PROMPT = (
    "Emit EXACTLY ONE tool call and nothing else. No prose, no explanation, "
    "no other tool. Format:\n"
    '<tool_call>{"name":"analysis_plan","arguments":{"goal":"<one line>",'
    '"steps":[{"purpose":"<what this step computes>",'
    '"declared_inputs":["data/<file>.csv"],"expected_outputs":["result.txt"]}]}}'
    "</tool_call>\n"
    "The arguments are CODE-FREE: never include a 'code' field; the harness "
    "writes the Python. Use real workspace-relative input paths from the "
    "schema below. Output must START with <tool_call> and contain only the "
    "single JSON tool call."
)

_PENDING_PLANS_FILE = "pending_plans.jsonl"
_ANALYSIS_FLOWS_FILE = "analysis_flows.jsonl"

_log = logging.getLogger("harness")


def _sanitize_assistant_text(text: str) -> str:
    """Remove model/control markers that should never become user-visible chat text."""
    cleaned = _ASSISTANT_DRAFT_TAG_RE.sub("", text)
    cleaned = _TURN_MARKER_RE.sub("", cleaned)
    return cleaned.strip()


def _read_workspace_file(
    workspace_dir: Path, rel_path: str, *,
    max_bytes: int = 65536, encoding: str = "utf-8",
) -> dict[str, Any]:
    return WorkspaceFileService().read_content(
        workspace_dir,
        rel_path,
        max_bytes=max_bytes,
        encoding=encoding,
    )


def _artifact_path(workspace_dir: Path, artifact: Path) -> Path:
    return artifact if artifact.is_absolute() else workspace_dir / artifact


def _read_short_text(path: Path, *, max_chars: int = 2000) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        data = path.read_bytes()[: max_chars * 4]
        return data.decode("utf-8", errors="replace")[:max_chars].strip()
    except OSError:
        return None


def _summarize_step_execution(workspace_dir: Path, envelope) -> str:
    status = getattr(envelope.status, "status", "")
    if status != "completed":
        detail = (envelope.stderr or "").strip() or str(envelope.diagnostics.get("failure_summary") or "").strip()
        if not detail:
            detail = (envelope.stdout or "").strip()
        return f"Analysis failed during execution: {detail or status or 'unknown worker failure'}"

    if envelope.artifacts:
        artifact_paths = [_artifact_path(workspace_dir, Path(artifact)) for artifact in envelope.artifacts]
        summary_artifact = next((p for p in artifact_paths if p.name == "result.txt"), artifact_paths[0])
        content = _read_short_text(summary_artifact)
        artifact_lines = "\n".join(f"Artifact: {path}" for path in artifact_paths)
        if content:
            return f"Analysis complete: {content}\n\n{artifact_lines}"
        return f"Analysis complete.\n\n{artifact_lines}"
    stdout = (envelope.stdout or "").strip()
    if stdout:
        return f"Analysis complete: {stdout}"
    return "Analysis complete."


def _is_repairable_plan_analysis_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in (
        "purpose", "'code'", "code missing", "steps", "expected object",
        "expected_outputs", "does not reference expected output", "declared_inputs",
        "code generation failed",
    ))


def _workspace_schema_snapshot(workspace_dir: Path) -> str:
    files = list_workspace_files(workspace_dir, max_entries=20)
    if not files:
        return "No workspace data files were discovered."
    lines: list[str] = []
    for item in files:
        rel = str(item.get("path") or "")
        suffix = Path(rel).suffix.lower()
        if suffix in {".csv", ".tsv", ".parquet", ".xlsx", ".xls"}:
            lines.append(json.dumps(read_file_schema(workspace_dir, rel), ensure_ascii=False, default=str))
        else:
            lines.append(json.dumps({"path": rel, "kind": "file"}, ensure_ascii=False))
    return "\n".join(lines)


def _build_plan_analysis_repair_prompt(
    *,
    original_request: str,
    validation_error: str,
    workspace_dir: Path,
) -> str:
    schemas = _workspace_schema_snapshot(workspace_dir)
    return (
        "STRICT ANALYSIS_PLAN REPAIR\n\n"
        "Your previous `analysis_plan` tool call failed validation. No code ran.\n"
        f"Original user request:\n{original_request}\n\n"
        f"Internal validation error:\n{validation_error}\n\n"
        f"Available file schemas:\n{schemas}\n\n"
        "Emit exactly one corrected `analysis_plan` tool call. Do NOT write code — "
        "the harness generates each step's Python after this. Do not ask the user "
        "for internal fields; infer them from the request and schemas.\n\n"
        "Required shape (code-free):\n"
        "<tool_call>{\"name\":\"analysis_plan\",\"arguments\":{\"goal\":\"...\",\"steps\":[{\"purpose\":\"<what this step computes>\",\"declared_inputs\":[\"data/source.csv\"],\"expected_outputs\":[\"result.txt\"]}]}}</tool_call>\n\n"
        "Each step: a clear `purpose`, the workspace-relative `declared_inputs` it "
        "reads, and the `expected_outputs` filenames it should produce "
        "(default `result.txt`). No `code`/`code_lines` fields."
    )


def _plan_analysis_no_code_message(validation_error: str) -> str:
    return (
        "No code ran. I could not build a valid execution plan after one internal "
        f"repair attempt. Internal validation error: {validation_error}"
    )


def _apply_safe_action(km, workspace_dir, action):
    """Auto-apply safe doctor actions without user approval."""
    action_type = action.get("action", "")
    target = action.get("target", "")
    if action_type == "cleanup" and target.startswith("artifacts/tmp/"):
        path = Path(workspace_dir) / target
        try:
            if path.exists() and not path.is_symlink():
                if path.is_file():
                    path.unlink()
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
        except Exception:
            pass
    elif action_type == "promote" and "memory/" in target:
        name = Path(target).stem
        if "notes" in target:
            km.write_note(workspace_dir, name, "")
        elif "functions" in target:
            km.write_function(workspace_dir, name, "")


class Orchestrator:
    def __init__(
        self,
        *,
        runtime: Runtime | None = None,
        context_manager: ContextManager | None = None,
        worker: PythonStepExecutor | None = None,
        persistence: HarnessPersistence | None = None,
        doctor: Doctor | None = None,
        knowledge_manager: KnowledgeManager | None = None,
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
        self.knowledge_manager = knowledge_manager
        if hasattr(self.worker, "telemetry"):
            self.worker.telemetry = self.telemetry
        self.persistence = persistence
        if self.persistence is not None:
            self.persistence.telemetry = self.telemetry
        self.config = config or SessionConfig()
        self.app_root = app_root or Path.cwd()
        _log.info("Orchestrator.__init__ workspace_id=%s app_root=%s",
                   getattr(self.config, "workspace_id", None), self.app_root)
        self._active_run_id: str | None = None
        self._stop_after_step_run_ids: set[str] = set()
        self._step_action_requests: dict[str, str] = {}
        self._cancel_flags: dict[str, asyncio.Event] = {}
        self._run_lock = asyncio.Lock()
        self._status_broker: StatusBroker | None = None
        self._pending_contracts: dict[tuple[str, str], StepContract] = {}
        self._pending_plans: dict[str, Plan] = {}
        self._analysis_flows: dict[str, AnalysisFlow] = {}
        self.chat_store = ChatStore(self.app_root)
        self._state_dir = self.app_root / "state"
        self._replay_pending_plans()
        self._replay_analysis_flows()
        self.request_builder: RuntimeRequestBuilder | None = None
        self._runtime_lock = asyncio.Lock()
        self.compactor: ChatCompactor | None = None
        self.workspace_manager = AsyncWorkspaceManager(app_root=self.app_root, chat_store=self.chat_store)
        self.workspace_file_service = WorkspaceFileService()
        self.doctor_runner = DoctorRunner(
            self.doctor, persistence=self.persistence,
            runtime=self.runtime, knowledge_manager=self.knowledge_manager,
            chat_store=self.chat_store,
        )
        self.analysis_service = AnalysisService(self)
        self.registry = HarnessCommandRegistry()
        self._register_commands()
        self.tool_registry = HarnessToolRegistry()
        self._register_tools()
        self.mode_router = ModeRouter(telemetry=self.telemetry)
        self.prompt_profiles = PromptProfileRegistry(
            Path(__file__).resolve().parent / "prompts",
            tool_registry=self.tool_registry,
        )

    # ---- command registry ----
    def _register_commands(self) -> None:
        from harness.commands.chat import register_chat_commands
        from harness.commands.compact import register_compact_commands
        from harness.commands.diagnostics import register_diagnostics_commands
        from harness.commands.doctor import register_doctor_commands
        from harness.commands.memory import register_memory_commands
        from harness.commands.provenance import register_provenance_commands
        from harness.commands.run import register_run_commands
        from harness.commands.workspace import register_workspace_commands

        register_doctor_commands(self, self.registry)
        register_compact_commands(self, self.registry)
        register_diagnostics_commands(self, self.registry)
        register_chat_commands(self, self.registry)
        register_workspace_commands(self, self.registry)
        register_run_commands(self, self.registry)
        register_memory_commands(self, self.registry)
        register_provenance_commands(self, self.registry)

    # ---- tool registry ----
    def _register_tools(self) -> None:
        self.tool_registry.register(
            ToolDescriptor(
                name="file_read",
                family="core",
                short_description="Read workspace file inventory, schema, or text content",
                arguments=[
                    ToolArgSpec(
                        name="operation",
                        type="str",
                        required=True,
                        description="list|inspect|content",
                        example="inspect",
                        allowed_values=["list", "inspect", "content"],
                    ),
                    ToolArgSpec(
                        name="path",
                        type="path",
                        required=False,
                        description="workspace-relative path",
                        example="data/sales.csv",
                        regex=r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$)).*",
                    ),
                    ToolArgSpec(
                        name="max_bytes",
                        type="int",
                        required=False,
                        description="content byte cap",
                        example="8192",
                    ),
                    ToolArgSpec(
                        name="encoding",
                        type="str",
                        required=False,
                        description="text encoding",
                        example="utf-8",
                    ),
                ],
            ),
            make_file_read_handler(self),
        )
        for _name in CONTROL_TOOL_NAMES:
            self.tool_registry.register(
                ToolDescriptor(
                    name=_name,
                    family="control",
                    short_description=f"Control intent: {_name}",
                ),
                make_control_handler(_name),
            )
        # Analysis tools — model-facing names only. Legacy command names stay
        # in the command registry for Layer 4 slash/palette access.
        _analysis_plan_args = [
            ToolArgSpec(
                name="goal", type="str", required=True,
                description="one-line user goal", example="count customers",
            ),
            ToolArgSpec(
                name="steps", type="json", required=True,
                description="list of {purpose,declared_inputs,expected_outputs} — do NOT write code",
                example='[{"purpose":"count rows","declared_inputs":["data/sales.csv"],"expected_outputs":["result.txt"]}]',
            ),
        ]
        _analysis_plan_handler = make_analysis_plan_handler(self)
        self.tool_registry.register(
            ToolDescriptor(
                name="analysis_plan",
                family="analysis",
                short_description="Build a Python analysis plan and request user approval",
                arguments=_analysis_plan_args,
            ),
            _analysis_plan_handler,
        )
        self.tool_registry.register(
            ToolDescriptor(
                name="analysis_request_execution",
                family="analysis",
                short_description="Re-emit ApprovalRequired for an existing pending step",
                arguments=[
                    ToolArgSpec(
                        name="plan_id", type="str", required=True,
                        description="plan id", example="plan_...",
                    ),
                    ToolArgSpec(
                        name="step_id", type="str", required=True,
                        description="step id", example="step_1",
                    ),
                ],
            ),
            make_analysis_request_execution_handler(self),
        )
        # Knowledge tools.
        self.tool_registry.register(
            ToolDescriptor(
                name="knowledge_recall",
                family="knowledge",
                short_description="Search saved workspace knowledge",
                arguments=[
                    ToolArgSpec(
                        name="query", type="str", required=True,
                        description="what to search for", example="pandas",
                    ),
                ],
            ),
            make_knowledge_recall_handler(self),
        )
        self.tool_registry.register(
            ToolDescriptor(
                name="knowledge_propose_update",
                family="knowledge",
                short_description="Propose notes, preferences, gaps, or function candidates",
                arguments=[
                    ToolArgSpec(
                        name="operation",
                        type="str",
                        required=True,
                        description="note|preference|gap|function_candidate",
                        allowed_values=["note", "preference", "gap", "function_candidate"],
                    ),
                    ToolArgSpec(
                        name="title", type="str", required=False,
                        description="note title (operation=note)",
                    ),
                    ToolArgSpec(
                        name="content", type="str", required=False,
                        description="note content (operation=note)",
                    ),
                    ToolArgSpec(
                        name="key", type="str", required=False,
                        description="preference key (operation=preference)",
                    ),
                    ToolArgSpec(
                        name="value", type="str", required=False,
                        description="preference value (operation=preference)",
                    ),
                    ToolArgSpec(
                        name="description", type="str", required=False,
                        description="gap description (operation=gap)",
                    ),
                    ToolArgSpec(
                        name="name", type="str", required=False,
                        description="function name (operation=function_candidate)",
                    ),
                    ToolArgSpec(
                        name="code", type="str", required=False,
                        description="function code (operation=function_candidate)",
                    ),
                    ToolArgSpec(
                        name="source_refs", type="json", required=False,
                        description="provenance source refs",
                    ),
                ],
            ),
            make_knowledge_propose_update_handler(self),
        )

    def _read_workspace_file_for_tool(
        self, workspace_dir: Path, path: str, *, max_bytes: int, encoding: str,
    ) -> dict[str, Any]:
        return self.workspace_file_service.read_content(
            workspace_dir,
            path,
            max_bytes=max_bytes,
            encoding=encoding,
        )

    def _append_pending_plan(self, plan_id: str, entry: dict) -> None:
        """Append a line to state/pending_plans.jsonl."""
        path = self._state_dir / _PENDING_PLANS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        entry["ts"] = time.time()
        entry["plan_id"] = plan_id
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _replay_pending_plans(self) -> None:
        """Replay pending_plans.jsonl on init to rebuild _pending_plans dict."""
        path = self._state_dir / _PENDING_PLANS_FILE
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                pid = entry["plan_id"]
                action = entry.get("action", "created")
                if action == "created":
                    self._pending_plans[pid] = entry.get("plan_data")
                elif action in ("resolved", "rejected", "cancelled", "timed_out"):
                    self._pending_plans.pop(pid, None)

    # ---- analysis flow registry (mirror pending_plans) ----
    def _append_analysis_flow(self, chat_id: str, entry: dict) -> None:
        """Append a line to state/analysis_flows.jsonl."""
        path = self._state_dir / _ANALYSIS_FLOWS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        entry["ts"] = time.time()
        entry["chat_id"] = chat_id
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _replay_analysis_flows(self) -> None:
        """Rebuild _analysis_flows from the log; prune terminal/dropped flows."""
        path = self._state_dir / _ANALYSIS_FLOWS_FILE
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            cid = entry["chat_id"]
            action = entry.get("action", "set")
            if action == "dropped":
                self._analysis_flows.pop(cid, None)
                continue
            flow_data = entry.get("flow_data")
            if not flow_data:
                continue
            flow = AnalysisFlow.model_validate(flow_data)
            if flow.is_terminal():
                self._analysis_flows.pop(cid, None)
            else:
                self._analysis_flows[cid] = flow

    def _get_flow(self, chat_id: str) -> AnalysisFlow | None:
        return self._analysis_flows.get(chat_id)

    def _set_phase(self, chat_id: str, phase: AnalysisPhase, **patch: Any) -> AnalysisFlow | None:
        flow = self._analysis_flows.get(chat_id)
        if flow is None:
            return None
        updated = flow.model_copy(update={**patch, "phase": phase, "updated_at": utc_now()})
        self._analysis_flows[chat_id] = updated
        self._append_analysis_flow(
            chat_id, {"action": "set", "flow_data": updated.model_dump(mode="json")}
        )
        return updated

    def _drop_flow(self, chat_id: str) -> None:
        self._analysis_flows.pop(chat_id, None)
        self._append_analysis_flow(chat_id, {"action": "dropped"})

    def _find_flow_by_plan(self, plan_id: str | None) -> AnalysisFlow | None:
        if not plan_id:
            return None
        for flow in self._analysis_flows.values():
            if flow.plan_id == plan_id:
                return flow
        return None

    def _ensure_inspecting_flow(
        self, state: RunStateRecord, chat_id: str, user_input: str
    ) -> AnalysisFlow:
        """Create an INSPECTING flow for this chat if none is in-flight."""
        existing = self._analysis_flows.get(chat_id)
        if existing is not None and not existing.is_terminal():
            return existing
        flow = AnalysisFlow(
            chat_id=chat_id, run_id=state.run_id, workspace_id=state.workspace_id,
            phase=AnalysisPhase.INSPECTING, original_request=user_input,
        )
        self._analysis_flows[chat_id] = flow
        self._append_analysis_flow(
            chat_id, {"action": "set", "flow_data": flow.model_dump(mode="json")}
        )
        _log.info("analysis_flow created chat_id=%s phase=inspecting", chat_id)
        return flow

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
        _log.info("_handle_compact chat_id=%s", ctx.chat_id)
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="compact", arguments={},
        )
        result = {}
        if ctx.chat_id:
            async for ev in self.compact_chat_history(ctx.chat_id, reason="user_requested"):
                yield ev
        else:
            _log.warning("_handle_compact: missing chat_id")
            result = {"error": "no active chat to compact"}

        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=ctx.workspace_id, chat_id=ctx.chat_id, run_id=ctx.run_id,
            command="compact", result=result,
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

    async def _recall_knowledge_events(
        self,
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        args: dict[str, Any],
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        query = args["query"].lower()
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command=event_command, arguments={"query": query},
        )
        workspace_dir = self.workspace_manager.workspaces_dir / (workspace_id or "")
        results: list[str] = []

        notes_dir = workspace_dir / "memory" / "notes"
        if notes_dir.exists():
            for note_file in sorted(notes_dir.glob("*.md")):
                content = note_file.read_text()
                if query in content.lower():
                    results.append(f"[NOTE {note_file.stem}]: {content[:500]}")

        prefs_path = workspace_dir / "memory" / "preferences.json"
        if prefs_path.exists():
            try:
                prefs = json.loads(prefs_path.read_text())
                matching = {k: v for k, v in prefs.items() if query in k.lower()}
                if matching:
                    results.append(f"[PREFERENCES]: {json.dumps(matching)}")
            except Exception:
                pass

        funcs_dir = workspace_dir / "memory" / "functions"
        if funcs_dir.exists():
            for func_file in sorted(funcs_dir.glob("*.py")):
                content = func_file.read_text()
                if query in content.lower():
                    results.append(f"[FUNCTION {func_file.stem}]: {content[:500]}")

        if not results:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command=event_command, result={"found": False, "text": "No matching knowledge found."},
            )
        else:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command=event_command,
                result={"found": True, "text": "\n---\n".join(results), "count": len(results)},
            )

    async def _handle_recall_knowledge(self, ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        async for ev in self._recall_knowledge_events(
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            args=args,
            event_command="recall_knowledge",
        ):
            yield ev

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
                elif command_name == "list_files":
                    workspace_dir = self.workspace_manager.workspaces_dir / (workspace_id or ctx.workspace_id or "")
                    files = self.workspace_file_service.list_files(workspace_dir)
                    result = {"workspace_id": workspace_id or ctx.workspace_id, "files": files}
                elif command_name == "inspect_file":
                    workspace_dir = self.workspace_manager.workspaces_dir / (workspace_id or ctx.workspace_id or "")
                    path_arg = str(args.get("path") or "")
                    result = self.workspace_file_service.inspect_file(workspace_dir, path_arg)
                elif command_name == "read_file":
                    workspace_dir = self.workspace_manager.workspaces_dir / (workspace_id or ctx.workspace_id or "")
                    path_arg = str(args.get("path") or "")
                    if not path_arg:
                        result = {"error": "missing required arg 'path'"}
                    else:
                        result = self.workspace_file_service.read_content(
                            workspace_dir, path_arg,
                            max_bytes=int(args.get("max_bytes") or 65536),
                            encoding=str(args.get("encoding") or "utf-8"),
                        )
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
        raw_arguments = dict(arguments)
        arguments = self.registry.validate(command, raw_arguments)
        ctx = CommandContext(
            workspace_id=state.workspace_id,
            chat_id=raw_arguments.get("chat_id"),  # type: ignore[arg-type]
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

        ws_dir = Path(self.workspace_manager.workspaces_dir) / workspace_id
        light_runner = DoctorRunner(
            self.doctor, self.persistence,
            runtime=None, knowledge_manager=self.knowledge_manager,
        )
        async for event in light_runner.run(
            workspace_id=workspace_id,
            workspace_dir=ws_dir,
            trigger="workspace_activation",
            chat_id=None,
            run_id=None,
            mode="light",
        ):
            if isinstance(event, DoctorFinding):
                _log.info("startup_doctor_finding category=%s severity=%s", event.category, event.severity)

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
        _log.info("compact_chat_history start chat_id=%s reason=%s", chat_id, reason)
        rec = await self.chat_store.view_chat(chat_id)
        prior_count = rec.compaction_count
        if self.compactor is None:
            self.compactor = ChatCompactor(
                store=self.chat_store, runtime=self.runtime, runtime_lock=self._runtime_lock,
            )
        recent_turns_kept = 0 if reason == "user_requested" else None
        async for status in self.compactor.compact(
            chat_id, reason=reason, recent_turns_kept=recent_turns_kept,
        ):
            snapshot = await self.chat_store.view_chat(chat_id)
            replaced = None
            summary_tokens = None
            if status == "completed" and snapshot.compaction_count > prior_count:
                latest_summary = next(
                    (m for m in reversed(snapshot.messages) if m.role == "compacted_summary"), None,
                )
                if latest_summary is not None:
                    summary_tokens = latest_summary.token_estimate
                replaced = max(0, rec.message_count - snapshot.message_count + 1)
            yield ChatHistoryCompacted(
                ts=datetime.now(UTC), workspace_id=rec.workspace_id, chat_id=chat_id,
                status=status,
                summary_token_estimate=summary_tokens,
                replaced_turn_count=replaced,
                compaction_count=snapshot.compaction_count,
            )
        _log.info("compact_chat_history end chat_id=%s status=%s", chat_id, status)

    async def apply_doctor_actions(
        self, *, report_id: str, decision: str, workspace_id: str, workspace_dir: Path,
        chat_id: str | None = None, action_ids: list[str] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        normalized = "yes" if str(decision).strip().lower() == "yes" else "no"
        selected_ids = None if action_ids is None else {str(action_id) for action_id in action_ids}
        rows: list[dict[str, Any]] = []
        if self.persistence is not None:
            try:
                all_actions = self.persistence.db.list_records("tmp_actions")
                rows = [r for r in all_actions if r.get("doctor_report_id") == report_id]
            except Exception:
                rows = []
        if normalized == "no":
            yield DoctorActionsApplied(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=None,
                report_id=report_id, applied_count=0, skipped_count=len(rows),
                details=[{"id": r.get("id"), "action": r.get("action"), "applied": False} for r in rows],
            )
            return
        applied_count = 0
        skipped_count = 0
        details: list[dict[str, Any]] = []
        for record in rows:
            record_id = str(record.get("id") or "")
            if selected_ids is not None and record_id not in selected_ids:
                skipped_count += 1
                details.append({
                    "id": record.get("id"),
                    "action": record.get("action"),
                    "applied": False,
                    "note": "not_selected",
                })
                continue
            if record.get("applied"):
                skipped_count += 1
                details.append({"id": record.get("id"), "action": record.get("action"), "applied": True, "note": "already_applied"})
                continue
            try:
                updated = self.doctor.apply_tmp_action(record, workspace_dir=workspace_dir)
                if self.persistence is not None:
                    self.persistence.db.save_record("tmp_actions", "id", str(updated["id"]), updated)
                applied_count += 1
                details.append({"id": updated.get("id"), "action": updated.get("action"), "applied": True})
            except Exception as exc:
                skipped_count += 1
                details.append({"id": record.get("id"), "action": record.get("action"), "applied": False, "error": str(exc)})
        yield DoctorActionsApplied(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=None,
            report_id=report_id, applied_count=applied_count, skipped_count=skipped_count,
            details=details,
        )

    # ---- agentic-turn intents ----
    _TERMINAL_INTENTS = frozenset({"answer_directly", "respond_to_user", "request_clarification"})
    _HANDOFF_INTENTS = {
        "handoff_to_analyst": "analyst",
        "handoff_to_knowledge": "knowledge",
        "handoff_to_clarification": "clarification",
    }

    def _select_profile(self, state: RunStateRecord, *, chat_id: str, user_input: str) -> str:
        """Pick the prompt profile for this turn and persist it on `state` in place.

        Routing is keyword-based on the user text. When the text is ambiguous
        the router returns 'interaction'; in that case we keep the prior
        non-interaction profile (continuity for clarification / follow-ups).
        The chosen profile is written back into the *same* RunStateRecord
        object (not a model_copy) so the long-lived TUI state stays correct.
        chat_id is accepted for telemetry; the body does not use it yet, but keeping a stable signature avoids churn when observability is wired in.
        """
        routed = self.mode_router.route(user_input).mode
        prior = state.active_agent_mode
        if routed == "interaction" and prior and prior != "interaction":
            chosen = prior
        else:
            chosen = routed
        state.active_agent_mode = chosen
        return chosen

    # ---- public async API ----
    async def run_agentic_turn(
        self,
        state: RunStateRecord,
        *,
        workspace_dir: Path,
        chat_id: str,
        user_input: str,
        max_iterations: int = 4,
    ) -> AsyncIterator[HarnessEvent]:
        """Bounded multi-iteration turn: stream → tool_call → dispatch → re-stream.

        Owns the full agentic control loop per spec §6.3 / §8.1. The harness
        routes the prompt profile internally via `_select_profile` (keyword
        router + continuity) and resolves prompt text via the orchestrator's
        own `PromptProfileRegistry`. It also handles tool dispatch, retry,
        mode handoff acceptance, approval-gate termination, and follow-up
        message construction.
        """
        active_mode = self._select_profile(state, chat_id=chat_id, user_input=user_input)
        sticky_flow = self._get_flow(chat_id)
        if (
            sticky_flow is not None
            and not sticky_flow.is_terminal()
            and active_mode != "analyst"
        ):
            yield ModeHandoffAccepted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id,
                chat_id=chat_id, run_id=state.run_id,
                from_mode=active_mode, to_mode="analyst",
                reason="analysis_flow_sticky",
            )
            _log.info(
                "run_agentic_turn sticky_override chat_id=%s routed=%s -> analyst phase=%s",
                chat_id, active_mode, sticky_flow.phase,
            )
            active_mode = "analyst"
            state.active_agent_mode = "analyst"
        if active_mode == "analyst":
            self._ensure_inspecting_flow(state, chat_id, user_input)
        prompt_text = self.prompt_profiles.load(active_mode).prompt_text
        durable = await self._build_durable_context_block(state.workspace_id, workspace_dir, user_query=user_input)

        # APPROVAL_PENDING — hybrid by intent. Deterministic handling for
        # approve / reject / show-plan (NO model turn → cannot hallucinate
        # "I already ran the plan"); free-form questions fall through to a
        # normal analyst turn with the stashed plan injected for grounding.
        appr_flow = self._get_flow(chat_id)
        if appr_flow is not None and appr_flow.phase is AnalysisPhase.APPROVAL_PENDING:
            intent = self._classify_approval_intent(user_input)
            plan = (
                self._pending_plans.get(appr_flow.plan_id)
                if appr_flow.plan_id else None
            )
            if intent == "approve" and plan is not None:
                first_step = plan.steps[0]
                yield PlanReady(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id,
                    chat_id=chat_id, run_id=state.run_id,
                    plan_id=plan.id, plan=plan.model_dump(mode="json"),
                )
                yield ApprovalRequired(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id,
                    chat_id=chat_id, run_id=state.run_id,
                    plan_id=plan.id, step_id=first_step.id,
                    step=first_step.model_dump(mode="json"),
                    prompt="Approval required before running code.",
                )
                _log.info(
                    "analysis_flow chat_id=%s approval re-surfaced plan_id=%s (deterministic)",
                    chat_id, plan.id,
                )
                return
            if intent == "reject":
                if appr_flow.plan_id:
                    self._pending_plans.pop(appr_flow.plan_id, None)
                    self._append_pending_plan(appr_flow.plan_id, {"action": "cancelled"})
                self._set_phase(chat_id, AnalysisPhase.FAILED)
                self._drop_flow(chat_id)
                yield FinalMessage(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id,
                    chat_id=chat_id, run_id=state.run_id,
                    assistant_message_id=f"asg_{uuid4().hex[:12]}",
                    text=(
                        "Plan cancelled. Nothing was run. Tell me if you'd "
                        "like a different analysis."
                    ),
                    usage={},
                )
                return
            if intent == "show" and plan is not None:
                yield PlanReady(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id,
                    chat_id=chat_id, run_id=state.run_id,
                    plan_id=plan.id, plan=plan.model_dump(mode="json"),
                )
                _log.info(
                    "analysis_flow chat_id=%s plan re-rendered plan_id=%s (deterministic)",
                    chat_id, plan.id,
                )
                return
            # Free-form question about the pending plan: ground the analyst
            # turn with the stashed plan + approval state.
            if plan is not None:
                durable = (
                    f"{durable}\n\n[A PLAN IS AWAITING YOUR APPROVAL — it has "
                    f"NOT run yet]\n{self._plan_brief(plan)}"
                )

        _log.info("run_agentic_turn chat_id=%s user_input_chars=%d routed=%s max_iterations=%d",
                   chat_id, len(user_input), active_mode, max_iterations)

        current_input = user_input
        retried_malformed = False
        retried_plan_repair = False
        handoff_used = False
        first_iter = True

        for iteration in range(max_iterations):
            _log.info("run_agentic_turn iteration=%d mode=%s", iteration, active_mode)
            buffer: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            paused_tool_calls: list[dict[str, Any]] = []
            empty_failed = False
            empty_failed_ec: str | None = None
            malformed_failed = False
            approval_pending = False
            plan_analysis_error: str | None = None

            async for ev in self.run_turn(
                state, workspace_dir=workspace_dir, chat_id=chat_id,
                user_input=current_input, requested_mode=active_mode,
                prompt_text=prompt_text, durable_context=durable,
                persist_user_message=first_iter,
            ):
                yield ev
                if isinstance(ev, RuntimeDelta):
                    if ev.delta_type == "text":
                        buffer.append(ev.text or "")
                    elif ev.delta_type == "tool_call" and ev.tool_call:
                        tool_calls.append(ev.tool_call)
                elif isinstance(ev, TurnPaused):
                    paused_tool_calls = list(ev.pending_tool_calls)
                elif isinstance(ev, ApprovalRequired):
                    approval_pending = True
                elif isinstance(ev, TurnFailed):
                    if ev.error_code in ("empty_output", "empty_stream"):
                        empty_failed = True
                        empty_failed_ec = ev.error_code
                    elif ev.error_code in (
                        "parse_error", "incomplete_structured_content", "malformed_tool_call"
                    ):
                        malformed_failed = True
                    else:
                        msg = (ev.failure_summary or "").lower()
                        if "malformed tool" in msg or "tool_call" in msg or "modelbehavior" in msg:
                            malformed_failed = True
                        else:
                            return

            if approval_pending:
                return

            effective = paused_tool_calls or tool_calls
            final_text = "".join(buffer).strip()

            # Mode handoff (App layer routed initial mode; this is mid-turn)
            handoff_target = self._detect_handoff(effective)
            if handoff_target and not handoff_used and handoff_target != active_mode:
                handoff_used = True
                yield ModeHandoffAccepted(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id,
                    chat_id=chat_id, run_id=state.run_id,
                    from_mode=active_mode, to_mode=handoff_target, reason="model_requested",
                )
                active_mode = handoff_target
                prompt_text = self.prompt_profiles.load(handoff_target).prompt_text
                state.active_agent_mode = handoff_target
                if handoff_target == "analyst":
                    self._ensure_inspecting_flow(state, chat_id, user_input)
                current_input = user_input  # re-run original under new mode
                first_iter = False
                continue

            if effective and self._has_dispatchable(effective):
                results: list[tuple[dict[str, Any], dict[str, Any]]] = []
                terminal = False
                dispatch_approval = False
                for tc in effective:
                    name = str(tc.get("name") or "")
                    args = dict(tc.get("arguments") or {})
                    if name in self._TERMINAL_INTENTS or name in self._HANDOFF_INTENTS:
                        terminal = True
                        continue
                    result = {}
                    async for sub_ev in self._dispatch_tool_call(state, name, args, chat_id=chat_id):
                        yield sub_ev
                        if isinstance(sub_ev, CommandCompleted):
                            result = sub_ev.result
                            if (
                                name == "analysis_plan"
                                and isinstance(result, dict)
                                and result.get("error")
                                and _is_repairable_plan_analysis_error(str(result.get("error")))
                            ):
                                plan_analysis_error = str(result.get("error"))
                        if isinstance(sub_ev, ApprovalRequired):
                            dispatch_approval = True
                    results.append((tc, result))
                    yield ToolCallExecuted(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id,
                        chat_id=chat_id, run_id=state.run_id,
                        tool_name=name, arguments=args, result=result, iteration=iteration,
                    )
                if active_mode == "analyst" and results:
                    insp_flow = self._get_flow(chat_id)
                    if insp_flow is not None and insp_flow.phase is AnalysisPhase.INSPECTING:
                        summary = self._summarize_inspection(results)
                        if summary:
                            self._set_phase(
                                chat_id, AnalysisPhase.INSPECTING,
                                inspection_summary=summary,
                            )
                if dispatch_approval:
                    return  # approval gate — wait for user via resume_approved_step
                if plan_analysis_error:
                    if not retried_plan_repair:
                        retried_plan_repair = True
                        current_input = _build_plan_analysis_repair_prompt(
                            original_request=user_input,
                            validation_error=plan_analysis_error,
                            workspace_dir=workspace_dir,
                        )
                        first_iter = False
                        continue
                    yield FinalMessage(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id,
                        chat_id=chat_id, run_id=state.run_id,
                        assistant_message_id=f"asg_{uuid4().hex[:12]}",
                        text=_plan_analysis_no_code_message(plan_analysis_error),
                        usage={},
                    )
                    return
                if terminal or not results:
                    return
                current_input = self._format_tool_followup(final_text, results)
                first_iter = False
                continue

            if empty_failed:
                _log.info("agentic_retry_empty error_code=%s iteration=%d", empty_failed_ec, iteration)
                if iteration < max_iterations:
                    yield TurnPaused(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id,
                        chat_id=chat_id, run_id=state.run_id,
                        reason="awaiting_tool_dispatch",
                    )
                    continue

            if malformed_failed and not retried_malformed:
                retried_malformed = True
                current_input = (
                    f"{user_input}\n\n"
                    "(Your previous response contained a malformed <tool_call> block. "
                    "Either answer directly without a tool_call, or emit exactly one valid "
                    'block: <tool_call>{"name":"<tool>","arguments":{...}}</tool_call> with '
                    "strict JSON — no literal newlines/tabs in string values, no extra keys.)"
                )
                first_iter = False
                continue

            if malformed_failed:
                # Repair nudge already spent; do not end the turn silently.
                yield FinalMessage(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id,
                    chat_id=chat_id, run_id=state.run_id,
                    assistant_message_id=f"asg_{uuid4().hex[:12]}",
                    text=(
                        "I couldn't complete that — the model produced an invalid "
                        "tool call twice in a row. Please rephrase or simplify the "
                        "request; for analysis, describe the goal in plain language."
                    ),
                    usage={},
                )
                return

            # Prose-only with no tool_call / failure / handoff. In analyst, an
            # in-flight INSPECTING flow means the model is "done inspecting /
            # about to plan" — advance to PLAN_PENDING instead of ending the
            # turn silently (Gap A). Forced plan emission is wired separately.
            if active_mode == "analyst":
                flow = self._get_flow(chat_id)
                should_plan = (
                    flow is not None
                    and flow.phase in (AnalysisPhase.INSPECTING, AnalysisPhase.PLAN_PENDING)
                    and (
                        flow.phase is AnalysisPhase.PLAN_PENDING
                        or flow.force_attempts > 0
                        or flow.inspection_summary is not None
                        or self._looks_like_plan_intent(final_text)
                    )
                )
                if (
                    flow is not None
                    and not should_plan
                    and flow.phase in (AnalysisPhase.INSPECTING, AnalysisPhase.PLAN_PENDING)
                ):
                    # Analyst answered in prose without inspecting data or
                    # signalling a plan — not a plan flow. Release it so the
                    # turn ends normally (prose answer) and mode un-sticks.
                    # APPROVAL_PENDING / EXECUTING flows are left intact (a
                    # free-form grounded answer must not cancel them).
                    self._drop_flow(chat_id)
                    _log.info(
                        "analysis_flow chat_id=%s released (prose answer, no inspection)",
                        chat_id,
                    )
                if should_plan:
                    if flow.phase is AnalysisPhase.INSPECTING:
                        flow = self._set_phase(chat_id, AnalysisPhase.PLAN_PENDING) or flow
                        _log.info(
                            "analysis_flow chat_id=%s inspecting->plan_pending (prose-only)",
                            chat_id,
                        )
                    args = await self._force_plan_tool_call(
                        state, flow=flow, workspace_dir=workspace_dir,
                        chat_id=chat_id, run_id=state.run_id,
                    )
                    if args is None and flow.force_attempts == 0:
                        flow = self._set_phase(
                            chat_id, AnalysisPhase.PLAN_PENDING, force_attempts=1,
                        ) or flow
                        args = await self._force_plan_tool_call(
                            state, flow=flow, workspace_dir=workspace_dir,
                            chat_id=chat_id, run_id=state.run_id,
                            correction=(
                                "You did not emit a valid code-free "
                                "analysis_plan <tool_call>. Emit exactly one "
                                "now — no prose, no 'code' field."
                            ),
                        )
                    if args is None:
                        yield FinalMessage(
                            ts=datetime.now(UTC), workspace_id=state.workspace_id,
                            chat_id=chat_id, run_id=state.run_id,
                            assistant_message_id=f"asg_{uuid4().hex[:12]}",
                            text=(
                                "I couldn't draft an analysis plan for that "
                                "request. Please restate the goal in plain "
                                "language (which files, what to compute)."
                            ),
                            usage={},
                        )
                        self._set_phase(chat_id, AnalysisPhase.FAILED)
                        self._drop_flow(chat_id)
                        return
                    plan_id_seen: str | None = None
                    async for ev in self.analysis_service.assemble_plan_events(
                        workspace_id=state.workspace_id, chat_id=chat_id,
                        run_id=state.run_id, args=args,
                        event_command="analysis_plan",
                    ):
                        yield ev
                        if isinstance(ev, PlanReady):
                            plan_id_seen = ev.plan_id
                    if plan_id_seen is not None:
                        self._set_phase(
                            chat_id, AnalysisPhase.APPROVAL_PENDING,
                            plan_id=plan_id_seen,
                            goal=str(args.get("goal") or "") or None,
                        )
                        _log.info(
                            "analysis_flow chat_id=%s plan_pending->approval_pending plan_id=%s",
                            chat_id, plan_id_seen,
                        )
                        return
                    yield FinalMessage(
                        ts=datetime.now(UTC), workspace_id=state.workspace_id,
                        chat_id=chat_id, run_id=state.run_id,
                        assistant_message_id=f"asg_{uuid4().hex[:12]}",
                        text=(
                            "I drafted a plan but it failed validation and "
                            "could not be repaired. Please simplify the "
                            "request and try again."
                        ),
                        usage={},
                    )
                    self._set_phase(chat_id, AnalysisPhase.FAILED)
                    self._drop_flow(chat_id)
                    return

            _log.info("run_agentic_turn end chat_id=%s iterations_done=%d", chat_id, iteration)
            return

    def _mirror_to_workspace(self, workspace_dir: Path, event: dict[str, Any]) -> None:
        telemetry_dir = workspace_dir / "state" / "telemetry"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        path = telemetry_dir / "workspace-harness-events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    async def _build_durable_context_block(self, workspace_id: str, workspace_dir: Path, user_query: str = "") -> str:
        status_text = f"WORKSPACE: {workspace_id}"
        try:
            snapshot = await self.status_snapshot(workspace_id=workspace_id)
            status_text = (
                f"WORKSPACE: {snapshot.workspace_id} "
                f"(chat: {snapshot.chat_id or '-'}, run_state: {snapshot.run_state}, "
                f"runtime: {snapshot.runtime_status}, mode: {snapshot.active_mode})"
            )
        except Exception:  # noqa: BLE001
            pass

        ctx_window = 4096
        if self.runtime is not None:
            try:
                ctx_window = await self.runtime.context_window()
            except Exception:  # noqa: BLE001
                pass
        durable_budget = max(int(ctx_window * 0.30), 256)
        if self.context_manager is None or not hasattr(self.context_manager, "build"):
            return status_text
        context = await self.context_manager.build(
            workspace_dir, token_budget=durable_budget, status_text=status_text,
        )

        if user_query:
            notes_dir = Path(workspace_dir) / "memory" / "notes"
            if notes_dir.exists():
                relevant: list[str] = []
                for note_file in sorted(notes_dir.glob("*.md")):
                    content = note_file.read_text()
                    words = [w for w in user_query.lower().split() if len(w) > 3]
                    if any(word in content.lower() for word in words):
                        relevant.append(f"[{note_file.stem}]: {content[:300]}")
                if relevant:
                    context += "\n\n## Relevant Knowledge\n" + "\n".join(relevant[:3])

        return context

    def _has_dispatchable(self, tool_calls: list[dict[str, Any]]) -> bool:
        for tc in tool_calls:
            name = str(tc.get("name") or "")
            if name and name not in self._TERMINAL_INTENTS and name not in self._HANDOFF_INTENTS:
                return True
        return any(str(tc.get("name") or "") == "request_clarification" for tc in tool_calls)

    _PLAN_INTENT_MARKERS = (
        "analysis_plan", "analysis plan", "outline the steps", "the steps",
        "i will use the", "request your approval", "for your approval",
        "i will plan", "plan to calculate", "plan to compute", "draft a plan",
        "generate a plan", "generate an analysis", "propose a plan",
    )

    def _looks_like_plan_intent(self, text: str) -> bool:
        """Conservative heuristic: did the analyst narrate plan/approval intent
        instead of emitting the tool call? Only used to decide whether a
        prose-only analyst turn should be forced into a plan."""
        low = (text or "").lower()
        return any(m in low for m in self._PLAN_INTENT_MARKERS)

    _APPROVE_PHRASES = frozenset({
        "approve", "approved", "ok proceed", "proceed", "yes run it",
        "run it", "ok", "okay", "go", "go ahead", "yes", "y", "run",
        "do it", "execute", "yes please", "sounds good", "lgtm",
    })
    _REJECT_PHRASES = frozenset({
        "reject", "cancel", "cancel it", "no", "n", "stop", "abort",
        "nevermind", "never mind", "don't", "do not",
    })
    _SHOW_MARKERS = (
        "show me the plan", "show plan", "show the plan", "what's the plan",
        "whats the plan", "what is the plan", "display the plan",
        "see the plan", "view the plan", "the plan again",
    )

    def _classify_approval_intent(self, text: str) -> str:
        """approve / reject / show / freeform for an APPROVAL_PENDING turn.
        Ambiguous input is treated as freeform (a grounded answer is safer
        than an accidental approve)."""
        low = (text or "").strip().lower().rstrip(".!")
        if any(m in low for m in self._SHOW_MARKERS):
            return "show"
        if low in self._APPROVE_PHRASES:
            return "approve"
        if low in self._REJECT_PHRASES:
            return "reject"
        return "freeform"

    def _plan_brief(self, plan) -> str:
        lines = [f"Goal: {getattr(plan, 'goal', '')}"]
        for idx, step in enumerate(getattr(plan, "steps", []), start=1):
            lines.append(f"  Step {idx}: {getattr(step, 'purpose', '')}")
        return "\n".join(lines)

    def _summarize_inspection(
        self, results: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> str | None:
        """Short, bounded note of what the analyst inspected this iteration —
        stored on the flow so the forced plan generation has grounding."""
        parts: list[str] = []
        for tc, result in results:
            name = str(tc.get("name") or "")
            args = tc.get("arguments") or {}
            target = args.get("path") or args.get("file") or args.get("name") or ""
            label = f"{name}({target})" if target else name
            if isinstance(result, dict) and result.get("error"):
                label += f" -> error: {str(result['error'])[:120]}"
            parts.append(label)
        if not parts:
            return None
        return "; ".join(parts)[:600]

    def _detect_handoff(self, tool_calls: list[dict[str, Any]]) -> str | None:
        for tc in tool_calls:
            target = self._HANDOFF_INTENTS.get(str(tc.get("name") or ""))
            if target is not None:
                return target
        return None

    async def _dispatch_tool_call(
        self, state: RunStateRecord, name: str, args: dict[str, Any], *, chat_id: str | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """Dispatch one tool_call. Yields all handler events; the loop body
        captures `CommandCompleted.result` and detects `ApprovalRequired`."""
        if not name:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=state.run_id,
                command="", result={"error": "missing tool name"},
            )
            return

        try:
            handler = self.tool_registry.get_handler(name)
        except KeyError:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=state.run_id,
                command=name, result={"error": f"unknown tool: {name}"},
            )
            return

        try:
            validated = self.tool_registry.validate(name, args)
        except Exception as exc:  # noqa: BLE001
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=state.run_id,
                command=name, result={"error": f"invalid arguments: {exc}"},
            )
            return

        ctx = ToolContext(
            workspace_id=state.workspace_id,
            chat_id=chat_id,
            run_id=state.run_id,
            has_pending_approval=False, has_pending_clarification=False,
        )
        try:
            async for ev in handler(ctx, validated):
                yield ev
        except Exception as exc:  # noqa: BLE001
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=state.run_id,
                command=name, result={"error": f"{type(exc).__name__}: {exc}"},
            )

    @staticmethod
    def _format_tool_followup(
        assistant_partial: str,
        results: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> str:
        import json as _json
        parts: list[str] = []
        cleaned = _sanitize_assistant_text(assistant_partial or "")
        if cleaned:
            parts.append(f"[ASSISTANT_DRAFT]\n{cleaned}\n[/ASSISTANT_DRAFT]")
        for tc, result in results:
            tool_name = tc.get("name") or "?"
            try:
                payload = _json.dumps(result, default=str, ensure_ascii=False)
            except Exception:  # noqa: BLE001
                payload = str(result)
            parts.append(f"[TOOL_RESULT name={tool_name}]\n{payload}\n[/TOOL_RESULT]")
        parts.append("Use the tool result(s) above to answer the user's original question concisely.")
        return "\n\n".join(parts)

    async def run_turn(
        self,
        state: RunStateRecord,
        *,
        workspace_dir: Path,
        chat_id: str,
        user_input: str,
        requested_mode: str | None = None,
        prompt_text: str | None = None,
        durable_context: str = "",
        persist_user_message: bool = True,
    ) -> AsyncIterator[HarnessEvent]:
        run_id = state.run_id
        cancel = await self._acquire_run(run_id)
        active_mode = requested_mode or state.active_agent_mode
        turn_id = f"turn_{uuid4().hex[:12]}"
        user_msg_id = f"msg_{uuid4().hex[:12]}"
        ts = datetime.now(UTC)
        _log.info("run_turn turn_id=%s mode=%s input_chars=%d", turn_id, active_mode, len(user_input))
        self._mirror_to_workspace(workspace_dir, {
            "event": "turn_start",
            "turn_id": turn_id,
            "mode": active_mode,
            "input_chars": len(user_input),
            "chat_id": chat_id,
            "run_id": run_id,
            "ts": ts.isoformat(),
        })
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
            # Append user message (lazy flush to disk).
            # Skipped for synthetic tool-followup inputs from run_agentic_turn
            # to avoid polluting durable chat history.
            if persist_user_message:
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

            # Plans are built via the model emitting the registered
            # `analysis_plan` tool. The harness dispatches that to the neutral
            # analysis service, which yields PlanReady + ApprovalRequired and
            # stashes the contract. No keyword triggers.

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
            collected_tool_calls: list[dict[str, Any]] = []
            usage: dict[str, int] = {}
            terminal_finish_reason: str | None = None
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
                        if ev.tool_call is not None:
                            collected_tool_calls.append(ev.tool_call)
                        yield RuntimeDelta(
                            ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                            request_id=ev.request_id, seq=ev.seq, delta_type="tool_call",
                            text=None, tool_call=ev.tool_call,
                        )
                    elif ev.type == "finish":
                        usage = ev.usage or {}
                        terminal_finish_reason = ev.finish_reason
                    elif ev.type == "error":
                        if collected_tool_calls and ev.error_code in (
                            "parse_error", "incomplete_structured_content"
                        ):
                            # A usable tool_call already streamed before a
                            # trailing truncated/garbled block. Don't fail the
                            # whole turn; let the awaiting_tool_dispatch path
                            # below dispatch the collected calls.
                            break
                        details = {"finish_reason": ev.finish_reason}
                        if ev.diagnostics:
                            details["diagnostics"] = ev.diagnostics
                        yield TurnFailed(
                            ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                            failure_summary=ev.error_message or "runtime error",
                            error_code=ev.error_code or "runtime_error",
                            details=details,
                        )
                        return

            assistant_text = "".join(buffer)

            # Empty buffer + pending tool_calls → pause for App-layer dispatch.
            if not assistant_text.strip() and collected_tool_calls:
                yield TurnPaused(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                    reason="awaiting_tool_dispatch",
                    pending_tool_calls=collected_tool_calls,
                    partial_text=assistant_text,
                )
                return

            # Empty buffer + no tool_calls → fail loudly; do NOT persist hollow row.
            if not assistant_text.strip():
                failure_error_code = "empty_stream" if terminal_finish_reason == "empty_stream" else "empty_output"
                yield TurnFailed(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                    failure_summary="Runtime produced no output.",
                    error_code=failure_error_code,
                    details={"usage": usage, "finish_reason": terminal_finish_reason},
                )
                return

            # Persist assistant message after removing leaked control markers.
            assistant_msg_id = f"asg_{uuid4().hex[:12]}"
            persisted_text = _sanitize_assistant_text(assistant_text) or assistant_text
            await self.chat_store.append_message(chat_id, ChatMessage(
                message_id=assistant_msg_id,
                role="assistant", text=persisted_text, ts=datetime.now(UTC),
                turn_id=turn_id, active_mode=active_mode,
                token_estimate=max(len(persisted_text) // 4, 1),
            ))
            yield FinalMessage(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, chat_id=chat_id, run_id=run_id,
                assistant_message_id=assistant_msg_id,
                text=persisted_text, usage=usage,
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

    async def _promote_step_artifacts(
        self,
        workspace_dir: str,
        step_result_path: str,
        run_id: str,
    ) -> list[Path]:
        ws = Path(workspace_dir)
        promoted: list[Path] = []

        result_path = ws / step_result_path if step_result_path else None
        if result_path is not None and result_path.exists() and result_path.is_file():
            result = json.loads(result_path.read_text())
        else:
            result = {}
            if step_result_path:
                _log.debug("_promote_step_artifacts step_result_path not found: %s", step_result_path)

        step_py = ws / "artifacts" / "tmp" / run_id / "step_1" / "step.py"
        if step_py.exists():
            funcs_dir = ws / "memory" / "functions"
            funcs_dir.mkdir(parents=True, exist_ok=True)
            dest = funcs_dir / f"{run_id}_step.py"
            shutil.copy2(step_py, dest)
            promoted.append(dest)

        for ref in result.get("artifact_refs", []):
            src = ws / ref
            if not src.exists() or src.is_symlink():
                continue
            suffix = src.suffix.lower()
            if suffix in (".csv", ".xlsx", ".parquet", ".md", ".txt", ".json"):
                dest_dir = ws / "artifacts"
                dest_dir.mkdir(parents=True, exist_ok=True)
                base = src.name
                dest = dest_dir / base
                counter = 1
                while dest.exists():
                    stem = src.stem
                    dest = dest_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
                shutil.copy2(src, dest)
                promoted.append(dest)

        return promoted

    async def resume_approved_step(
        self,
        *,
        workspace_dir: Path,
        state: RunStateRecord,
        contract_payload: dict,
        approval: ApprovalRecord,
        plan_id: str | None = None,
        plan_payload: dict | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        pid = plan_id or (plan_payload or {}).get("id")
        plan = self._pending_plans.get(pid) if pid else None
        if plan is None:
            if not plan_payload:
                raise ValueError(f"no cached plan for plan_id {pid!r} and no plan_payload provided")
            plan = Plan.model_validate(plan_payload)
        step_id = str(contract_payload.get("_step_id") or contract_payload.get("step_id") or "step_1")
        contract = self._pending_contracts.pop((state.run_id, step_id), None)
        if contract is None:
            contract = StepContract.model_validate(contract_payload)
        _log.info("resume_approved_step start plan_id=%s step_id=%s status=approved", pid, step_id)
        yield ApprovalResolved(
            ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
            plan_id=plan.id, step_id=step_id, decision="approved",
        )
        exec_flow = self._find_flow_by_plan(pid)
        exec_chat = exec_flow.chat_id if exec_flow else None
        if exec_chat:
            self._set_phase(exec_chat, AnalysisPhase.EXECUTING)
            _log.info("analysis_flow chat_id=%s -> executing plan_id=%s", exec_chat, pid)
        cancel = await self._acquire_run(state.run_id)
        run_id = f"run_{uuid4().hex}"
        try:
            request = StepExecutionRequest(
                id=contract.id,
                workspace_id=contract.workspace_id, run_id=run_id,
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
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=run_id,
                task_id=handle.task_id, step_id=contract.step_id, plan_id=plan.id,
            )
            # Initial running status
            running_status = await self.worker.get_task(handle.task_id)
            if running_status is not None:
                yield StepTaskStatusChanged(
                    ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=run_id,
                    task_id=handle.task_id, status=running_status,
                )
            envelope = await self.worker.wait(handle.task_id)
            yield StepTaskStatusChanged(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=run_id,
                task_id=handle.task_id, status=envelope.status,
            )
            yield StepCompleted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=run_id,
                task_id=handle.task_id, envelope=envelope,
            )
            if exec_chat:
                self._set_phase(
                    exec_chat,
                    AnalysisPhase.DONE
                    if envelope.status.status == "completed"
                    else AnalysisPhase.FAILED,
                )
                _log.info(
                    "analysis_flow chat_id=%s -> %s plan_id=%s",
                    exec_chat,
                    "done" if envelope.status.status == "completed" else "failed",
                    pid,
                )
            promoted = []
            if envelope.status.status == "completed":
                promoted = await self._promote_step_artifacts(
                    workspace_dir, envelope.diagnostics.get("step_result_path", ""), run_id
                )
                _log.info("artifacts_promoted run_id=%s count=%d", run_id, len(promoted))
            yield ArtifactsReady(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=run_id,
                step_id=contract.step_id, artifacts=envelope.artifacts,
            )
            final_text = _summarize_step_execution(workspace_dir, envelope)
            if promoted:
                final_text += f"\n\nOutputs saved to: {', '.join(str(p.relative_to(Path(workspace_dir))) for p in promoted)}"
            yield FinalMessage(
                ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=run_id,
                assistant_message_id=f"asg_{uuid4().hex[:12]}",
                text=final_text,
                usage={},
            )

            async def _post_worker_doctor():
                semantic_runner = DoctorRunner(
                    self.doctor, self.persistence,
                    runtime=self.runtime,
                    knowledge_manager=self.knowledge_manager,
                    chat_store=self.chat_store,
                )
                async for event in semantic_runner.run(
                    workspace_id=state.workspace_id,
                    workspace_dir=str(workspace_dir),
                    trigger="post_worker_execution",
                    chat_id=None,
                    run_id=run_id,
                    mode="semantic",
                ):
                    if isinstance(event, DoctorFinding):
                        _log.info("post_worker_doctor_finding category=%s severity=%s", event.category, event.severity)
                    elif isinstance(event, DoctorActionProposed):
                        if event.action in ("cleanup", "promote") and self.knowledge_manager:
                            _apply_safe_action(self.knowledge_manager, str(workspace_dir), {"action": event.action, "target": event.target})

            asyncio.create_task(_post_worker_doctor())

            _log.info("resume_approved_step end plan_id=%s step_id=%s status=%s",
                       pid, step_id, getattr(envelope.status, "status", "unknown"))
        finally:
            await self._release_run(state.run_id)
            if exec_chat:
                self._drop_flow(exec_chat)
            if pid:
                self._pending_plans.pop(pid, None)
                self._append_pending_plan(pid, {
                    "action": "resolved",
                    "resolution": "approved",
                })

    async def resume_with_clarification(
        self,
        *,
        workspace_dir: Path,
        state: RunStateRecord,
        clarification_text: str,
    ) -> AsyncIterator[HarnessEvent]:
        cleared = state.model_copy(update={"state": RunState.CLARIFYING, "pending_clarification_id": None})
        cleared.active_agent_mode = state.active_agent_mode  # explicit: profile continuity across clarification resume (model_copy already carries it; kept to document intent)
        async for ev in self.run_turn(
            cleared, workspace_dir=workspace_dir, chat_id=state.run_id,
            user_input=clarification_text,
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

    async def _generate_step_code(
        self,
        state: RunStateRecord,
        *,
        step: dict[str, Any],
        workspace_dir: Path,
        correction: str | None = None,
    ) -> list[str]:
        """Gen-2: internal, non-persisted generation of one step's Python.

        The model writes a fenced ```python block (no JSON escaping). The
        runtime stops at the closing fence (`stop=["```"]`). Returns the
        fenced code as `code_lines`; empty list when nothing usable came back
        (the caller decides whether to retry or fail).
        """
        purpose = str(step.get("purpose") or "").strip()
        declared_inputs = [str(p) for p in (step.get("declared_inputs") or [])]
        expected_outputs = [str(p) for p in (step.get("expected_outputs") or ["result.txt"])]
        schema = _workspace_schema_snapshot(workspace_dir)
        user_lines = [
            f"Step purpose: {purpose}",
            f"Declared input paths: {', '.join(declared_inputs) or '(none)'}",
            f"Expected output files (write each, name must appear literally): "
            f"{', '.join(expected_outputs)}",
            "",
            "Workspace file schemas:",
            schema,
        ]
        if correction:
            user_lines += ["", f"Your previous code was rejected: {correction}", "Fix it."]
        request = RuntimeRequest(
            messages=[
                RuntimeMessage(role="system", content=_GEN2_SYSTEM_PROMPT),
                RuntimeMessage(role="user", content="\n".join(user_lines)),
            ],
            max_completion_tokens=_GEN2_MAX_TOKENS,
            stop=["```"],
            request_id=f"req_{uuid4().hex[:12]}",
            correlation_id=state.run_id,
        )
        buffer: list[str] = []
        async with self._runtime_lock:
            async for ev in self.runtime.stream(request):
                if ev.type == "text_delta" and ev.text:
                    buffer.append(ev.text)
        return extract_fenced_code("".join(buffer))

    async def _force_plan_tool_call(
        self,
        state: RunStateRecord,
        *,
        flow: AnalysisFlow,
        workspace_dir: Path,
        chat_id: str,
        run_id: str,
        correction: str | None = None,
    ) -> dict[str, Any] | None:
        """Dedicated, non-persisted generation that FORCES the analyst to emit
        one code-free `analysis_plan` tool call (Gap A). Returns the parsed
        `arguments` dict, or None if the model still failed to emit a valid
        code-free call. Not relying on the model volunteering the call in free
        chat is the whole point — `stop=["</tool_call>"]` plus a tiny JSON
        target makes malform near-zero (this is why a GBNF grammar is
        unnecessary)."""
        schema = _workspace_schema_snapshot(workspace_dir)
        user_lines = [
            f"Analysis request: {flow.original_request or state.run_id}",
            "",
            "Workspace file schemas:",
            schema,
        ]
        if flow.inspection_summary:
            user_lines += ["", f"Inspection notes: {flow.inspection_summary}"]
        if correction:
            user_lines += ["", f"Your previous attempt was rejected: {correction}"]
        request = RuntimeRequest(
            messages=[
                RuntimeMessage(role="system", content=_FORCE_PLAN_SYSTEM_PROMPT),
                RuntimeMessage(role="user", content="\n".join(user_lines)),
            ],
            max_completion_tokens=_FORCE_PLAN_MAX_TOKENS,
            stop=["</tool_call>"],
            request_id=f"req_{uuid4().hex[:12]}",
            correlation_id=run_id,
        )
        buffer: list[str] = []
        async with self._runtime_lock:
            async for ev in self.runtime.stream(request):
                if ev.type == "text_delta" and ev.text:
                    buffer.append(ev.text)
        raw = "".join(buffer).strip()
        if not raw:
            return None
        # The stop token consumed the closing tag — re-append before parsing.
        if "</tool_call>" not in raw:
            raw = f"{raw}</tool_call>"
        try:
            parsed = parse_tool_call_block(raw)
        except ToolCallParseError:
            return None
        if parsed.name != "analysis_plan":
            return None
        args = parsed.arguments or {}
        if not str(args.get("goal") or "").strip() or not args.get("steps"):
            return None
        return args

    def _build_plan_from_arguments(
        self,
        state: RunStateRecord,
        *,
        goal: str,
        steps: list[dict[str, Any]],
    ) -> tuple[Plan, list[StepContract]]:
        return self.analysis_service.build_plan_from_arguments(state, goal=goal, steps=steps)

    async def _analysis_plan_events(
        self,
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        args: dict[str, Any],
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        async for ev in self.analysis_service.analysis_plan_events(
            workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            args=args,
            event_command=event_command,
        ):
            yield ev

    async def _finalize_plan(
        self,
        state: RunStateRecord,
        plan,
        contracts: list[StepContract],
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        async for ev in self.analysis_service.finalize_plan(
            state, plan, contracts,
            workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            event_command=event_command,
        ):
            yield ev

    async def _assemble_plan_events(
        self,
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        args: dict[str, Any],
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        async for ev in self.analysis_service.assemble_plan_events(
            workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            args=args,
            event_command=event_command,
        ):
            yield ev

    def _validate_generated_step(
        self, state: RunStateRecord, goal: str, step: dict[str, Any],
    ) -> str | None:
        return self.analysis_service.validate_generated_step(state, goal, step)

    def _make_plan_analysis_handler(self):
        async def handler(ctx: CommandContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
            async for ev in self.analysis_service.analysis_plan_events(
                workspace_id=ctx.workspace_id,
                chat_id=ctx.chat_id,
                run_id=ctx.run_id,
                args=args,
                event_command="plan_analysis",
            ):
                yield ev
        return handler

    def _handle_plan_analysis(self, ctx: CommandContext, args: dict[str, Any]):
        return self._make_plan_analysis_handler()(ctx, args)

    async def _handle_request_execution(
        self, ctx: CommandContext, args: dict[str, Any],
    ) -> AsyncIterator[HarnessEvent]:
        async for ev in self.analysis_service.analysis_request_execution_events(
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            args=args,
            event_command="request_execution",
        ):
            yield ev

    async def _analysis_request_execution_events(
        self,
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        args: dict[str, Any],
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        async for ev in self.analysis_service.analysis_request_execution_events(
            workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            args=args,
            event_command=event_command,
        ):
            yield ev

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
