from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.prompt_packages import PromptPackageRegistry
from app.agents.router import AgentModeRouter
from app.event_mapping import to_app_event
from app.events import (
    AppDoctorActionsApplied, AppDoctorApprovalRequested,
    AppDoctorFinding, AppDoctorNarrationReady, AppDoctorReportReady, AppEvent,
)
from harness.command_registry import CommandContext, HarnessCommandDescriptor, HelpResult
from harness.control import RunStateRecord
from harness.events import DoctorActionsApplied, DoctorApprovalRequested, DoctorNarrationReady
from harness.exceptions import RunAlreadyActive
from harness.orchestrator import Orchestrator
from harness.status import HarnessStatusSnapshot
from observability import Telemetry, bind_turn, resolve_telemetry_dir
from observability.events import EventKind, Layer
from runtime.types import RuntimeMessage, RuntimeRequest


_DOCTOR_PROMPT_PATH = Path(__file__).resolve().parent / "agents" / "prompts" / "doctor_narrator.md"


class AppSession:
    """Layer 4 facade over Layer 3 Orchestrator. Async-only."""

    def __init__(
        self,
        *,
        orchestrator: Orchestrator | None = None,
        mode_router: AgentModeRouter | None = None,
        prompt_registry: PromptPackageRegistry | None = None,
        telemetry: Telemetry | None = None,
        app_root: Path | None = None,
    ) -> None:
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())
        self.app_root = app_root or getattr(orchestrator, "app_root", None) or Path.cwd()
        self.orchestrator = orchestrator or Orchestrator(app_root=self.app_root)
        if hasattr(self.orchestrator, "telemetry"):
            self.orchestrator.telemetry = self.telemetry
        self.mode_router = mode_router or AgentModeRouter(telemetry=self.telemetry)
        self.prompt_registry = prompt_registry or PromptPackageRegistry(
            Path(__file__).resolve().parent / "agents" / "prompts",
            tool_registry=getattr(self.orchestrator, "tool_registry", None),
        )
        self._active = False

    async def run_user_turn(
        self,
        *,
        state: RunStateRecord,
        workspace_dir: Path,
        chat_id: str,
        user_text: str,
    ) -> AsyncIterator[AppEvent]:
        if self._active:
            raise RunAlreadyActive(run_id=state.run_id)
        self._active = True
        turn_id = uuid4()
        try:
            with bind_turn(turn_id):
                self.telemetry.emit(Layer.APP, EventKind.TURN_START, payload={"input_chars": len(user_text)})
                # L4 owns: initial mode pick + prompt provision (§8.3 step 2).
                # L3 owns: agentic loop, tool dispatch, retry, handoff (§6.3, §8.1).
                decision = self.mode_router.route(user_text)

                def prompt_provider(mode: str) -> str:
                    return self.prompt_registry.load(mode).prompt_text

                async for h_ev in self.orchestrator.run_agentic_turn(
                    state, workspace_dir=workspace_dir, chat_id=chat_id, user_input=user_text,
                    requested_mode=decision.mode, prompt_provider=prompt_provider,
                ):
                    yield to_app_event(h_ev)
                self.telemetry.emit(Layer.APP, EventKind.TURN_END, payload={"chat_id": chat_id})
        finally:
            self._active = False

    async def resume_approved_step(
        self, *, workspace_dir: Path, state: RunStateRecord,
        contract_payload: dict, approval,
        plan_id: str | None = None, plan_payload: dict | None = None,
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.resume_approved_step(
            workspace_dir=workspace_dir, state=state,
            plan_id=plan_id, plan_payload=plan_payload,
            contract_payload=contract_payload, approval=approval,
        ):
            yield to_app_event(h_ev)

    async def resume_with_clarification(
        self, *, workspace_dir: Path, state: RunStateRecord, clarification_text: str,
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.resume_with_clarification(
            workspace_dir=workspace_dir, state=state, clarification_text=clarification_text,
        ):
            yield to_app_event(h_ev)

    async def handle_direct_command(
        self, state: RunStateRecord, *, command: str, arguments: dict[str, Any],
    ) -> AsyncIterator[AppEvent]:
        findings: list[AppDoctorFinding] = []
        report: AppDoctorReportReady | None = None
        async for h_ev in self.orchestrator.handle_direct_command(
            state, command=command, arguments=arguments,
        ):
            app_ev = to_app_event(h_ev)
            yield app_ev
            if command == "doctor":
                if isinstance(app_ev, AppDoctorFinding):
                    findings.append(app_ev)
                elif isinstance(app_ev, AppDoctorReportReady):
                    report = app_ev
        if command == "doctor" and report is not None:
            async for ev in self._stream_doctor_narration_and_approval(state, report, findings):
                yield ev

    async def _stream_doctor_narration_and_approval(
        self,
        state: RunStateRecord,
        report: AppDoctorReportReady,
        findings: list[AppDoctorFinding],
    ) -> AsyncIterator[AppEvent]:
        action_records = self._collect_tmp_actions(report.report_id)
        proposed = [r for r in action_records if not r.get("applied") and r.get("action") != "kept_temporarily"]
        action_summaries = [
            f"{r.get('action')}: {r.get('item_path')}"
            + (f" -> {r['destination_path']}" if r.get("destination_path") else "")
            for r in proposed
        ]
        base = dict(
            ts=datetime.now(UTC), workspace_id=state.workspace_id,
            chat_id=report.chat_id, run_id=None,
        )
        if not proposed:
            counts = report.summary_counts or {}
            narration = (
                f"Doctor sweep clean: tmp empty, no cleanup needed. "
                f"Findings: {counts.get('info', 0)} info, "
                f"{counts.get('warn', 0)} warn, {counts.get('error', 0)} error."
            )
            yield to_app_event(DoctorNarrationReady(
                **base, report_id=report.report_id,
                narration_text=narration, action_summaries=[],
            ))
            yield to_app_event(DoctorActionsApplied(
                **base, report_id=report.report_id,
                applied_count=0, skipped_count=0, details=[],
            ))
            return
        narration = await self._render_doctor_narration(findings, action_summaries)
        yield to_app_event(DoctorNarrationReady(
            **base, report_id=report.report_id,
            narration_text=narration, action_summaries=action_summaries,
        ))
        question = "Apply all proposed actions? (yes / no)"
        yield to_app_event(DoctorApprovalRequested(
            **base, report_id=report.report_id,
            question=question, action_count=len(proposed),
        ))

    async def handle_doctor_approval(
        self, *, state: RunStateRecord, workspace_dir: Path, report_id: str, decision: str,
        action_ids: list[str] | None = None,
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.apply_doctor_actions(
            report_id=report_id, decision=decision,
            workspace_id=state.workspace_id, workspace_dir=workspace_dir,
            action_ids=action_ids,
        ):
            yield to_app_event(h_ev)

    def _collect_tmp_actions(self, report_id: str) -> list[dict[str, Any]]:
        persistence = getattr(self.orchestrator, "persistence", None)
        if persistence is None:
            return []
        try:
            rows = persistence.db.list_records("tmp_actions")
        except Exception:
            return []
        return [r for r in rows if r.get("doctor_report_id") == report_id]

    async def _render_doctor_narration(
        self, findings: list[AppDoctorFinding], action_summaries: list[str],
    ) -> str:
        findings_payload = [
            {"category": f.category, "severity": f.severity, "summary": f.summary, "details": f.details}
            for f in findings
        ]
        runtime = getattr(self.orchestrator, "runtime", None)
        if runtime is None:
            return self._fallback_doctor_narration(findings_payload, action_summaries)
        try:
            template = _DOCTOR_PROMPT_PATH.read_text()
        except Exception:
            return self._fallback_doctor_narration(findings_payload, action_summaries)
        prompt = template.format(
            findings_json=json.dumps(findings_payload, indent=2),
            actions_text="\n".join(action_summaries) or "(none)",
        )
        request = RuntimeRequest(
            messages=[
                RuntimeMessage(role="system", content=prompt),
                RuntimeMessage(role="user", content="Produce the narration now."),
            ],
            max_completion_tokens=320,
            request_id=f"req_doctor_{uuid4().hex[:8]}",
        )
        chunks: list[str] = []
        try:
            async for ev in runtime.stream(request):
                if getattr(ev, "type", None) == "text_delta":
                    chunks.append(getattr(ev, "text", "") or "")
        except Exception:
            return self._fallback_doctor_narration(findings_payload, action_summaries)
        text = "".join(chunks).strip()
        return text or self._fallback_doctor_narration(findings_payload, action_summaries)

    @staticmethod
    def _fallback_doctor_narration(
        findings_payload: list[dict[str, Any]], action_summaries: list[str],
    ) -> str:
        lines = [f"Doctor sweep produced {len(findings_payload)} finding(s)."]
        for f in findings_payload:
            lines.append(f"- [{f['severity']}] {f['summary']}")
        if action_summaries:
            lines.append("Proposed cleanup:")
            lines.extend(f"- {s}" for s in action_summaries)
        else:
            lines.append("No cleanup actions to apply.")
        lines.append("Apply all proposed actions? (yes / no)")
        return "\n".join(lines)

    async def cancel_run(self, run_id: str, reason: str):
        return to_app_event(await self.orchestrator.cancel_run(run_id, reason=reason))

    async def compact_chat_history(self, chat_id: str) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.compact_chat_history(chat_id):
            yield to_app_event(h_ev)

    async def list_commands(self, context: CommandContext | None = None) -> list[HarnessCommandDescriptor]:
        return await self.orchestrator.list_commands(context)

    async def help(self, command: str | None = None) -> HelpResult:
        return await self.orchestrator.help(command)

    async def list_chats(self, workspace_id: str):
        return await self.orchestrator.list_chats(workspace_id)

    async def create_chat(self, workspace_id: str, title: str | None = None):
        return await self.orchestrator.create_chat(workspace_id=workspace_id, title=title)

    async def view_chat(self, chat_id: str):
        return await self.orchestrator.view_chat(chat_id)

    async def resume_chat(self, chat_id: str) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.resume_chat(chat_id):
            yield to_app_event(h_ev)

    async def delete_chat(self, chat_id: str):
        return await self.orchestrator.delete_chat(chat_id)

    async def list_workspaces(self):
        return await self.orchestrator.list_workspaces()

    async def create_workspace(self, workspace_id: str):
        return await self.orchestrator.create_workspace(workspace_id)

    async def rename_workspace(self, old_id: str, new_id: str):
        return await self.orchestrator.rename_workspace(old_id, new_id)

    async def delete_workspace(self, workspace_id: str):
        return await self.orchestrator.delete_workspace(workspace_id)

    async def activate_workspace(self, workspace_id: str, force: bool = False) -> HarnessStatusSnapshot:
        return await self.orchestrator.activate_workspace(workspace_id, force=force)

    async def ingest_files(self, workspace_id: str, paths: list[Path]):
        return await self.orchestrator.ingest_files(workspace_id, paths)

    async def status_snapshot(self, workspace_id: str | None = None) -> HarnessStatusSnapshot:
        return await self.orchestrator.status_snapshot(workspace_id=workspace_id)

    async def watch_status(self):
        async for snap in self.orchestrator.watch_status():
            yield snap

    def get_pending_plan(self, plan_id: str):
        """Retrieve a pending plan by id, delegating to orchestrator."""
        plan = self.orchestrator._pending_plans.get(plan_id)
        if plan is None:
            return None
        if hasattr(plan, "model_dump"):
            return plan.model_dump(mode="json")
        return plan


# Migration alias — kept only so existing import sites resolve until cleanup.
DataAnalysisAppSession = AppSession
