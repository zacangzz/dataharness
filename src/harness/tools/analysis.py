"""Analysis tool family (Layer 3).

Bridges the model-facing `analysis_plan` / `analysis_request_execution`
tool calls to harness-owned analysis services. Legacy `plan_analysis` /
`request_execution` remain commands only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from harness.events import HarnessEvent
from harness.tools.registry import ToolContext


def make_analysis_plan_handler(orchestrator):
    """Run model-facing analysis plan creation.

    Model emits a code-free plan; the harness synthesizes each step's code
    via gen-2. The command path keeps using code supplied directly.
    """

    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        async for ev in orchestrator.analysis_service.assemble_plan_events(
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            args=args,
            event_command="analysis_plan",
        ):
            yield ev

    return handler


def make_analysis_request_execution_handler(orchestrator):
    """Run model-facing approval re-request."""

    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        async for ev in orchestrator.analysis_service.analysis_request_execution_events(
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            args=args,
            event_command="analysis_request_execution",
        ):
            yield ev

    return handler
