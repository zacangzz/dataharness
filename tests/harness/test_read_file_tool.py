"""read_file L3 harness tool: returns content, respects workspace boundary,
enforces byte/char caps, detects binary."""

import pytest

from harness.core.command_registry import CommandContext
from harness.orchestrator import Orchestrator
from harness.services.workspace_files import WorkspaceFileService


def _read_workspace_file(wd, rel_path, **kwargs):
    return WorkspaceFileService().read_content(wd, rel_path, **kwargs)


def _ws(tmp_path):
    wd = tmp_path / "workspaces" / "w1"
    wd.mkdir(parents=True)
    return wd


def test_read_file_returns_content(tmp_path):
    wd = _ws(tmp_path)
    (wd / "data").mkdir()
    (wd / "data" / "notes.md").write_text("hello world", encoding="utf-8")
    result = _read_workspace_file(wd, "data/notes.md")
    assert result["content"] == "hello world"
    assert result["size_bytes"] == 11
    assert result["truncated"] is False


def test_read_file_truncates_at_max_bytes(tmp_path):
    wd = _ws(tmp_path)
    (wd / "big.txt").write_text("x" * 1000, encoding="utf-8")
    result = _read_workspace_file(wd, "big.txt", max_bytes=100)
    assert result["content"] == "x" * 100
    assert result["truncated"] is True
    assert result["truncation_reason"] == "max_bytes"
    assert result["size_bytes"] == 1000


def test_read_file_rejects_workspace_escape(tmp_path):
    wd = _ws(tmp_path)
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    result = _read_workspace_file(wd, "../secret.txt")
    assert "error" in result
    assert "escapes" in result["error"]


def test_read_file_missing_file(tmp_path):
    wd = _ws(tmp_path)
    result = _read_workspace_file(wd, "nope.txt")
    assert result["error"] == "not a file"


def test_read_file_binary(tmp_path):
    wd = _ws(tmp_path)
    (wd / "blob.bin").write_bytes(b"\x80\x81\x82\xff")
    result = _read_workspace_file(wd, "blob.bin")
    assert result["error"] == "binary_file"
    assert result["size_bytes"] == 4


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=None, app_root=tmp_path)


async def test_read_file_dispatched_via_registry(orch, tmp_path):
    wd = tmp_path / "workspaces" / "w1"
    wd.mkdir(parents=True)
    (wd / "x.txt").write_text("dispatched", encoding="utf-8")
    handler = orch.registry.get_handler("read_file")
    ctx = CommandContext(
        workspace_id="w1", chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    )
    events = [ev async for ev in handler(ctx, {"path": "x.txt"})]
    completed = next(e for e in events if e.event_name == "CommandCompleted")
    assert completed.result["content"] == "dispatched"


async def test_read_file_command_reports_missing_workspace(orch):
    handler = orch.registry.get_handler("read_file")
    ctx = CommandContext(
        workspace_id="missing", chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    )

    events = [ev async for ev in handler(ctx, {"path": "x.txt"})]

    completed = next(e for e in events if e.event_name == "CommandCompleted")
    assert completed.result == {"error": "workspace not found"}
