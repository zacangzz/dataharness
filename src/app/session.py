from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.prompt_packages import PromptPackageRegistry
from app.agents.router import AgentModeRouter
from app.event_mapping import to_app_event
from app.events import AppEvent
from harness.command_registry import CommandContext, HarnessCommandDescriptor, HelpResult
from harness.control import RunStateRecord
from harness.exceptions import RunAlreadyActive
from harness.orchestrator import Orchestrator
from harness.status import HarnessStatusSnapshot
from observability import Telemetry, bind_turn, resolve_telemetry_dir
from observability.events import EventKind, Layer


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
            Path(__file__).resolve().parent / "agents" / "prompts"
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
                decision = self.mode_router.route(user_text)
                package = self.prompt_registry.load(decision.mode)
                async for h_ev in self.orchestrator.run_turn(
                    state, workspace_dir=workspace_dir, chat_id=chat_id,
                    user_input=user_text, requested_mode=decision.mode,
                    prompt_text=package.prompt_text,
                ):
                    yield to_app_event(h_ev)
                self.telemetry.emit(Layer.APP, EventKind.TURN_END, payload={"chat_id": chat_id})
        finally:
            self._active = False

    async def resume_approved_step(
        self, *, workspace_dir: Path, state: RunStateRecord,
        plan_payload: dict, contract_payload: dict, approval,
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.resume_approved_step(
            workspace_dir=workspace_dir, state=state,
            plan_payload=plan_payload, contract_payload=contract_payload, approval=approval,
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
        async for h_ev in self.orchestrator.handle_direct_command(
            state, command=command, arguments=arguments,
        ):
            yield to_app_event(h_ev)

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


# Migration alias — kept only so existing import sites resolve until cleanup.
DataAnalysisAppSession = AppSession
