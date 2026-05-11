from __future__ import annotations

import pytest

from harness.command_registry import CommandContext
from harness.events import CommandCompleted
from harness.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_list_files_command_returns_inventory(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    ws_id = "w_test"
    summary = await orch.create_workspace(ws_id)
    (summary.workspace_dir / "data" / "sales.csv").write_text("a,b\n1,2\n")

    handler = orch.registry.get_handler("list_files")
    ctx = CommandContext(
        workspace_id=ws_id, chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    )
    completed: CommandCompleted | None = None
    async for ev in handler(ctx, {"workspace_id": ws_id}):
        if isinstance(ev, CommandCompleted):
            completed = ev
    assert completed is not None
    files = completed.result.get("files") or []
    assert any(f["path"].endswith("sales.csv") for f in files)


@pytest.mark.asyncio
async def test_inspect_file_command_returns_schema(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    ws_id = "w_test"
    summary = await orch.create_workspace(ws_id)
    (summary.workspace_dir / "data" / "x.csv").write_text("col1,col2\n1,2\n")

    handler = orch.registry.get_handler("inspect_file")
    ctx = CommandContext(
        workspace_id=ws_id, chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    )
    completed: CommandCompleted | None = None
    async for ev in handler(ctx, {"workspace_id": ws_id, "path": "data/x.csv"}):
        if isinstance(ev, CommandCompleted):
            completed = ev
    assert completed is not None
    assert completed.result["kind"] == "csv"
    assert completed.result["columns"] == ["col1", "col2"]


def test_list_runtime_callable_filter(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    names = {d.name for d in orch.registry.list_runtime_callable()}
    assert "list_files" in names
    assert "inspect_file" in names
    assert "workspace_status" in names
    # Destructive commands must not be exposed
    assert "delete_workspace" not in names
    assert "doctor" not in names
