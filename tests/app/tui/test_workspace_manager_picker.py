from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from app.tui.file_picker import FilePicker
from app.tui.screens.workspace_manager import WorkspaceManagerScreen
from textual.app import App, ComposeResult


class _FakeSession:
    def __init__(self, app_root: Path) -> None:
        self.app_root = app_root

    async def list_workspaces(self):
        return []


class _Harness(App[None]):
    def __init__(self, session) -> None:
        super().__init__()
        self.session = session

    async def on_mount(self) -> None:
        await self.push_screen(
            WorkspaceManagerScreen(session=self.session, active_workspace_id="w_0001")
        )


@pytest.mark.asyncio
async def test_workspace_manager_mounts_file_picker(tmp_path: Path):
    (tmp_path / "workspaces" / "w_0001" / "data").mkdir(parents=True)
    session = _FakeSession(tmp_path)
    app = _Harness(session)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen.query_one("#workspace_file_panel", FilePicker)
        assert picker is not None
