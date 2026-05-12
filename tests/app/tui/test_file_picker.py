from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from app.tui.file_picker import (
    FilePicker,
    WorkspaceFileEntry,
    WorkspaceFileIndex,
    filter_file_entries,
    format_file_mention,
)


def test_workspace_file_index_lists_visible_workspace_files(tmp_path: Path):
    workspace = tmp_path / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "data" / "sales.csv").write_text("a,b\n1,2\n")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("hidden")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "x.pyc").write_text("compiled")

    index = WorkspaceFileIndex(workspace)
    entries = index.scan()

    assert [entry.path for entry in entries] == ["data/sales.csv"]


def test_format_file_mention_quotes_paths_with_spaces():
    assert format_file_mention("data/sales.csv") == "@data/sales.csv"
    assert format_file_mention("data/monthly sales.csv") == '@"data/monthly sales.csv"'


def test_filter_file_entries_prefers_subsequence_matches():
    entries = [
        WorkspaceFileEntry("data/sales.csv"),
        WorkspaceFileEntry("data/customer_notes.md"),
        WorkspaceFileEntry("reports/annual_sales.md"),
    ]

    matches = filter_file_entries(entries, "sal", limit=2)

    assert [entry.path for entry in matches] == [
        "data/sales.csv",
        "reports/annual_sales.md",
    ]


class FilePickerHarness(App[None]):
    def __init__(self, workspace_dir: Path) -> None:
        super().__init__()
        self.workspace_dir = workspace_dir
        self.selected: str | None = None

    def compose(self) -> ComposeResult:
        yield FilePicker(self.workspace_dir, id="picker")

    def on_file_picker_selected(self, event: FilePicker.Selected) -> None:
        self.selected = event.path


@pytest.mark.asyncio
async def test_file_picker_selects_highlighted_file(tmp_path: Path):
    workspace = tmp_path / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "data" / "sales.csv").write_text("x")
    app = FilePickerHarness(workspace)

    async with app.run_test() as pilot:
        picker = app.query_one("#picker", FilePicker)
        picker.refresh_query("sal")
        await pilot.pause()
        await pilot.press("enter")

        assert app.selected == "data/sales.csv"


@pytest.mark.asyncio
async def test_file_picker_tab_toggles_tree_mode(tmp_path: Path):
    workspace = tmp_path / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "data" / "sales.csv").write_text("x")
    app = FilePickerHarness(workspace)

    async with app.run_test() as pilot:
        picker = app.query_one("#picker", FilePicker)
        assert picker.mode == "fuzzy"
        await pilot.press("tab")
        assert picker.mode == "tree"


@pytest.mark.asyncio
async def test_file_picker_tree_is_hierarchical(tmp_path: Path):
    workspace = tmp_path / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "data" / "sales.csv").write_text("x")
    (workspace / "data" / "notes.md").write_text("y")
    (workspace / "data" / "reports").mkdir()
    (workspace / "data" / "reports" / "annual.md").write_text("z")
    app = FilePickerHarness(workspace)
    async with app.run_test() as pilot:
        picker = app.query_one("#picker", FilePicker)
        await pilot.pause()
        from textual.widgets import Tree
        tree = picker.query_one("#file_picker_tree", Tree)
        children_labels = [str(child.label) for child in tree.root.children]
        assert "data" in children_labels
        data_node = next(c for c in tree.root.children if str(c.label) == "data")
        sub_labels = [str(child.label) for child in data_node.children]
        assert "reports" in sub_labels


@pytest.mark.asyncio
async def test_file_picker_focus_picker_focuses_inner(tmp_path: Path):
    workspace = tmp_path / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "data" / "x.csv").write_text("x")
    app = FilePickerHarness(workspace)
    async with app.run_test() as pilot:
        picker = app.query_one("#picker", FilePicker)
        picker.focus_picker()
        await pilot.pause()
        from textual.widgets import OptionList
        assert app.focused is picker.query_one("#file_picker_options", OptionList)


@pytest.mark.asyncio
async def test_file_picker_dismissed_message_emitted(tmp_path: Path):
    workspace = tmp_path / "w_0001"
    workspace.mkdir(parents=True)
    received: list[FilePicker.Dismissed] = []

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            yield FilePicker(workspace, id="picker")

        def on_file_picker_dismissed(self, event: FilePicker.Dismissed) -> None:
            received.append(event)

    app = _Harness()
    async with app.run_test() as pilot:
        picker = app.query_one("#picker", FilePicker)
        picker.dismiss_picker()
        await pilot.pause()
        assert picker.display is False
        assert received


@pytest.mark.asyncio
async def test_file_picker_multiselect_emits_confirmed(tmp_path: Path):
    workspace = tmp_path / "w"
    workspace.mkdir(parents=True)
    (workspace / "a.csv").write_text("a")
    (workspace / "b.csv").write_text("b")
    received: list[list[str]] = []

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            yield FilePicker(workspace, allow_multiselect=True, id="picker")

        def on_file_picker_confirmed(self, event: FilePicker.Confirmed) -> None:
            received.append(list(event.paths))

    app = _Harness()
    async with app.run_test() as pilot:
        picker = app.query_one("#picker", FilePicker)
        picker._selected.add("a.csv")
        picker.refresh_query("")
        picker._select_current()
        await pilot.pause()
        assert received == [["a.csv"]]


@pytest.mark.asyncio
async def test_file_picker_update_root_swaps_index(tmp_path: Path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    (root_a / "data").mkdir(parents=True)
    (root_b / "data").mkdir(parents=True)
    (root_a / "data" / "x.csv").write_text("x")
    (root_b / "data" / "y.csv").write_text("y")
    app = FilePickerHarness(root_a)
    async with app.run_test() as pilot:
        picker = app.query_one("#picker", FilePicker)
        picker.update_root(root_b)
        await pilot.pause()
        paths = [e.path for e in picker.index.scan()]
        assert paths == ["data/y.csv"]
