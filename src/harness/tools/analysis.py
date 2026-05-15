"""Analysis tool family (Layer 3).

Bridges the model-facing `analysis_plan` / `analysis_request_execution`
tool calls to the harness-owned `plan_analysis` / `request_execution`
command handlers. The command handlers remain the single source of plan
validation + approval-gate behavior; these tool handlers only adapt the
context type and forward the arguments unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from harness.events import HarnessEvent
from harness.tools.registry import ToolContext


def _command_context(ctx: ToolContext):
    from harness.command_registry import CommandContext

    return CommandContext(
        workspace_id=ctx.workspace_id,
        chat_id=ctx.chat_id,
        run_id=ctx.run_id,
        has_pending_approval=ctx.has_pending_approval,
        has_pending_clarification=ctx.has_pending_clarification,
    )


def make_analysis_plan_handler(orchestrator):
    """Delegates to the existing `plan_analysis` command handler.

    `plan_analysis` expects `goal` (str) + `steps` (list). Arguments are
    forwarded verbatim so plan validation stays in one place.
    """

    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        plan_handler = orchestrator.registry.get_handler("plan_analysis")
        async for ev in plan_handler(_command_context(ctx), args):
            yield ev

    return handler


def make_analysis_request_execution_handler(orchestrator):
    """Delegates to the existing `request_execution` command handler.

    `request_execution` expects `plan_id` + `step_id`.
    """

    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        req_handler = orchestrator.registry.get_handler("request_execution")
        async for ev in req_handler(_command_context(ctx), args):
            yield ev

    return handler
