from __future__ import annotations

from pathlib import Path

import pytest

from app.tui.file_picker import FilePicker
from app.tui.screens.file_ingest import FileIngestScreen
from textual.app import App


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Path]]] = []

    async def ingest_files(self, workspace_id: str, paths: list[Path]):
        self.calls.append((workspace_id, list(paths)))
        return {"workspace_id": workspace_id, "files": [str(p) for p in paths]}


class _Harness(App[None]):
    def __init__(self, session, root: Path) -> None:
        super().__init__()
        self.session = session
        self.root_path = root
        self.dismissed: object = None

    async def on_mount(self) -> None:
        def _on(result):
            self.dismissed = result

        await self.push_screen(
            FileIngestScreen(
                session=self.session,
                workspace_id="w_0001",
                initial_root=self.root_path,
            ),
            _on,
        )


@pytest.mark.asyncio
async def test_file_ingest_screen_mounts(tmp_path: Path):
    (tmp_path / "x.csv").write_text("x")
    session = _FakeSession()
    app = _Harness(session, tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen.query_one("#ingest_picker", FilePicker)
        assert picker.allow_multiselect is True


@pytest.mark.asyncio
async def test_file_ingest_screen_calls_ingest_files_on_confirm(tmp_path: Path):
    (tmp_path / "x.csv").write_text("x")
    session = _FakeSession()
    app = _Harness(session, tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen.query_one("#ingest_picker", FilePicker)
        picker._selected.add("x.csv")
        picker.refresh_query("")
        picker._select_current()
        await pilot.pause()
        await pilot.pause()
        assert session.calls
        workspace_id, paths = session.calls[0]
        assert workspace_id == "w_0001"
        assert paths == [tmp_path / "x.csv"]


@pytest.mark.asyncio
async def test_file_ingest_screen_change_root(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "h.csv").write_text("h")
    session = _FakeSession()
    app = _Harness(session, home)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FileIngestScreen)
        prior = screen._root
        await screen.action_change_root()
        await pilot.pause()
        assert screen._root != prior
