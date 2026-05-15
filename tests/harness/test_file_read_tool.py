import pytest

from harness.events import CommandCompleted
from harness.orchestrator import Orchestrator
from harness.tools.registry import ToolContext


async def _complete(orch, name, ctx, args):
    validated = orch.tool_registry.validate(name, args)
    handler = orch.tool_registry.get_handler(name)
    events = [event async for event in handler(ctx, validated)]
    return next(event for event in events if isinstance(event, CommandCompleted))


def _ctx(workspace_id="w1"):
    return ToolContext(
        workspace_id=workspace_id,
        chat_id=None,
        run_id=None,
        has_pending_approval=False,
        has_pending_clarification=False,
    )


async def test_file_read_list_operation(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    ws = await orch.create_workspace("w1")
    (ws.workspace_dir / "data").mkdir(parents=True, exist_ok=True)
    (ws.workspace_dir / "data" / "sales.csv").write_text("a,b\n1,2\n")

    completed = await _complete(
        orch,
        "file_read",
        _ctx(),
        {"operation": "list"},
    )

    assert any(item["path"].endswith("sales.csv") for item in completed.result["files"])


async def test_file_read_inspect_operation(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    ws = await orch.create_workspace("w1")
    (ws.workspace_dir / "data").mkdir(parents=True, exist_ok=True)
    (ws.workspace_dir / "data" / "sales.csv").write_text("a,b\n1,2\n")

    completed = await _complete(
        orch,
        "file_read",
        _ctx(),
        {"operation": "inspect", "path": "data/sales.csv"},
    )

    assert completed.result["kind"] == "csv"
    assert completed.result["columns"] == ["a", "b"]


async def test_file_read_content_operation(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    ws = await orch.create_workspace("w1")
    (ws.workspace_dir / "data").mkdir(parents=True, exist_ok=True)
    (ws.workspace_dir / "data" / "notes.md").write_text("hello")

    completed = await _complete(
        orch,
        "file_read",
        _ctx(),
        {"operation": "content", "path": "data/notes.md"},
    )

    assert completed.result["content"] == "hello"


async def test_file_read_rejects_unknown_operation(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    await orch.create_workspace("w1")

    with pytest.raises(ValueError, match="invalid value"):
        orch.tool_registry.validate("file_read", {"operation": "delete", "path": "data/notes.md"})
