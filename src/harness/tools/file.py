from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from harness.events import CommandCompleted, CommandStarted, HarnessEvent
from harness.tools.registry import ToolContext


def make_file_read_handler(orchestrator: Any) -> Any:
    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        operation = str(args.get("operation") or "")
        path = str(args.get("path") or "")
        workspace_id = ctx.workspace_id or ""
        workspace_dir = orchestrator.workspace_manager.workspaces_dir / workspace_id

        yield CommandStarted(
            ts=datetime.now(UTC),
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            command="file_read",
            arguments=args,
        )

        if not workspace_dir.exists():
            result: dict[str, Any] = {"error": "workspace not found"}
        elif operation == "list":
            result = {
                "workspace_id": workspace_id,
                "files": orchestrator.workspace_file_service.list_files(workspace_dir),
            }
        elif operation == "inspect":
            result = orchestrator.workspace_file_service.inspect_file(workspace_dir, path)
        elif operation == "content":
            if not path:
                result = {"error": "missing required arg 'path'"}
            else:
                result = orchestrator.workspace_file_service.read_content(
                    workspace_dir,
                    path,
                    max_bytes=int(args.get("max_bytes") or 65536),
                    encoding=str(args.get("encoding") or "utf-8"),
                )
        else:
            result = {"error": f"unknown file_read operation: {operation}"}

        yield CommandCompleted(
            ts=datetime.now(UTC),
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            command="file_read",
            result=result,
        )

    return handler
