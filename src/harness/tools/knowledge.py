"""Knowledge tool family (Layer 3).

`knowledge_recall` bridges to the harness-owned recall service.
`knowledge_propose_update` maps an operation-based
tool call onto the existing `handle_knowledge_intent` dispatcher so
memory writes stay harness-owned (spec §6.13, §3.4).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from harness.events import CommandCompleted, CommandStarted, HarnessEvent
from harness.services.knowledge_intents import handle_knowledge_intent
from harness.tools.registry import ToolContext

# operation (model-facing) -> legacy knowledge-intent name
_OPERATION_TO_INTENT = {
    "note": "store_workspace_knowledge",
    "preference": "update_preferences",
    "gap": "record_gap",
    "function_candidate": "save_function_candidate",
}


def make_knowledge_recall_handler(orchestrator):
    """Run model-facing knowledge recall."""

    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        async for ev in orchestrator._recall_knowledge_events(
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            args=args,
            event_command="knowledge_recall",
        ):
            yield ev

    return handler


def make_knowledge_propose_update_handler(orchestrator):
    """Maps an operation-based tool call onto handle_knowledge_intent.

    The model emits e.g. ``{"operation": "note", "title": ...,
    "content": ...}``. We translate ``operation`` to the legacy intent
    name and forward the remaining arguments unchanged so the existing
    intent dispatcher continues to own the memory-target mapping.
    """

    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        yield CommandStarted(
            ts=datetime.now(UTC),
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            command="knowledge_propose_update",
            arguments=args,
        )
        manager = getattr(orchestrator, "knowledge_manager", None)
        if manager is None:
            yield CommandCompleted(
                ts=datetime.now(UTC),
                workspace_id=ctx.workspace_id,
                chat_id=ctx.chat_id,
                run_id=ctx.run_id,
                command="knowledge_propose_update",
                result={"error": "knowledge manager unavailable"},
            )
            return
        operation = str(args.get("operation") or "note")
        intent_name = _OPERATION_TO_INTENT.get(operation)
        if intent_name is None:
            allowed = ", ".join(sorted(_OPERATION_TO_INTENT))
            yield CommandCompleted(
                ts=datetime.now(UTC),
                workspace_id=ctx.workspace_id,
                chat_id=ctx.chat_id,
                run_id=ctx.run_id,
                command="knowledge_propose_update",
                result={"error": f"unknown operation {operation!r}; expected one of {allowed}"},
            )
            return
        intent_args = {k: v for k, v in args.items() if k != "operation"}
        try:
            rec = handle_knowledge_intent(
                manager,
                run_id=ctx.run_id or "",
                tool_call={"name": intent_name, "arguments": intent_args},
            )
            payload = rec.model_dump(mode="json") if hasattr(rec, "model_dump") else str(rec)
            yield CommandCompleted(
                ts=datetime.now(UTC),
                workspace_id=ctx.workspace_id,
                chat_id=ctx.chat_id,
                run_id=ctx.run_id,
                command="knowledge_propose_update",
                result={"ok": True, "record": payload},
            )
        except Exception as exc:  # noqa: BLE001
            yield CommandCompleted(
                ts=datetime.now(UTC),
                workspace_id=ctx.workspace_id,
                chat_id=ctx.chat_id,
                run_id=ctx.run_id,
                command="knowledge_propose_update",
                result={"error": f"{type(exc).__name__}: {exc}"},
            )

    return handler
