from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from harness.events import CommandCompleted, HarnessEvent
from harness.tools.registry import ToolContext


CONTROL_TOOL_NAMES = [
    "answer_directly",
    "handoff_to_analyst",
    "handoff_to_knowledge",
    "request_clarification",
    "respond_to_user",
]


def make_control_handler(name: str):
    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        yield CommandCompleted(
            ts=datetime.now(UTC),
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            command=name,
            result={"ok": True, "note": f"{name} consumed by control loop", "arguments": args},
        )

    return handler
