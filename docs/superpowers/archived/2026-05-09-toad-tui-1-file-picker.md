# Toad TUI File Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable workspace file picker model and Textual overlay for `@` file mentions and workspace file panels.

**Architecture:** Keep file discovery in Layer 4 because it only reads workspace-local presentation paths. Expose small pure helpers for scan/filter/mention formatting and a reusable Textual widget for prompt/workspace use.

**Tech Stack:** Python 3.14, `pathlib`, Textual `OptionList` and `Tree`, pytest, pytest-asyncio.

**Repository Rule:** Do not commit during execution unless the user grants permission. End with verification and a checkpoint summary.

---

## File Structure

- Create `src/app/tui/file_picker.py`: `WorkspaceFileEntry`, `WorkspaceFileIndex`, fuzzy filtering, mention formatting, and `FilePicker` widget.
- Modify `src/app/tui/__init__.py`: no exports required unless local style prefers them.
- Add `tests/app/tui/test_file_picker.py`: unit and widget tests for scan/filter/format/toggle/select behavior.
- Later plans will modify `src/app/tui/prompt_bar.py` and `src/app/tui/screens/workspace_manager.py` to consume this module.

---

### Task 1: Pure File Index And Mention Formatting

**Files:**
- Create: `src/app/tui/file_picker.py`
- Test: `tests/app/tui/test_file_picker.py`

- [ ] **Step 1: Write failing tests for scan exclusions and mention formatting**

Add `tests/app/tui/test_file_picker.py`:

```python
from pathlib import Path

from app.tui.file_picker import WorkspaceFileIndex, format_file_mention


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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_file_picker.py -q
```

Expected: import failure for `app.tui.file_picker`.

- [ ] **Step 3: Implement file entry, scan, and mention formatting**

Create `src/app/tui/file_picker.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SKIPPED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "logs",
    "tmp",
}


@dataclass(frozen=True)
class WorkspaceFileEntry:
    path: str
    is_dir: bool = False


def format_file_mention(path: str) -> str:
    if any(ch.isspace() for ch in path):
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        return f'@"{escaped}"'
    return f"@{path}"


class WorkspaceFileIndex:
    def __init__(self, workspace_dir: Path, *, max_entries: int = 5000) -> None:
        self.workspace_dir = workspace_dir
        self.max_entries = max_entries
        self._cache: list[WorkspaceFileEntry] | None = None

    def invalidate(self) -> None:
        self._cache = None

    def scan(self) -> list[WorkspaceFileEntry]:
        if self._cache is not None:
            return list(self._cache)
        entries: list[WorkspaceFileEntry] = []
        if not self.workspace_dir.exists():
            self._cache = []
            return []
        for path in sorted(self.workspace_dir.rglob("*")):
            if len(entries) >= self.max_entries:
                break
            if self._should_skip(path):
                continue
            if path.is_file():
                entries.append(WorkspaceFileEntry(path.as_posix().removeprefix(self.workspace_dir.as_posix() + "/")))
        self._cache = entries
        return list(entries)

    def _should_skip(self, path: Path) -> bool:
        rel_parts = path.relative_to(self.workspace_dir).parts
        return any(part.startswith(".") or part in SKIPPED_DIRS for part in rel_parts)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
uv run pytest tests/app/tui/test_file_picker.py -q
```

Expected: 2 passed.

---

### Task 2: Fuzzy Filtering

**Files:**
- Modify: `src/app/tui/file_picker.py`
- Test: `tests/app/tui/test_file_picker.py`

- [ ] **Step 1: Add failing tests for fuzzy ordering**

Append:

```python
from app.tui.file_picker import filter_file_entries, WorkspaceFileEntry


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
```

- [ ] **Step 2: Run the focused test to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_file_picker.py::test_filter_file_entries_prefers_subsequence_matches -q
```

Expected: import failure for `filter_file_entries`.

- [ ] **Step 3: Implement fuzzy filtering**

Add to `src/app/tui/file_picker.py`:

```python
def _subsequence_score(text: str, query: str) -> int | None:
    if not query:
        return 0
    text_l = text.lower()
    query_l = query.lower()
    pos = -1
    score = 0
    for ch in query_l:
        next_pos = text_l.find(ch, pos + 1)
        if next_pos < 0:
            return None
        gap = next_pos - pos - 1
        score += gap
        pos = next_pos
    return score + len(text_l)


def filter_file_entries(
    entries: list[WorkspaceFileEntry],
    query: str,
    *,
    limit: int = 30,
) -> list[WorkspaceFileEntry]:
    scored: list[tuple[int, WorkspaceFileEntry]] = []
    for entry in entries:
        score = _subsequence_score(entry.path, query)
        if score is not None:
            scored.append((score, entry))
    scored.sort(key=lambda item: (item[0], item[1].path))
    return [entry for _, entry in scored[:limit]]
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/app/tui/test_file_picker.py -q
```

Expected: all tests pass.

---

### Task 3: Textual FilePicker Widget

**Files:**
- Modify: `src/app/tui/file_picker.py`
- Test: `tests/app/tui/test_file_picker.py`

- [ ] **Step 1: Add widget behavior tests**

Append:

```python
import pytest
from textual.app import App, ComposeResult

from app.tui.file_picker import FilePicker


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
```

- [ ] **Step 2: Run widget tests to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_file_picker.py -q
```

Expected: failures because `FilePicker` does not exist.

- [ ] **Step 3: Implement `FilePicker`**

Add imports:

```python
from textual import events, on
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, OptionList, Tree
from textual.widgets.option_list import Option
```

Add widget:

```python
class FilePicker(Widget):
    can_focus = True

    class Selected(Message):
        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    def __init__(self, workspace_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.index = WorkspaceFileIndex(workspace_dir)
        self.mode = "fuzzy"
        self._query = ""
        self._targets: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Label("Files", id="file_picker_title")
        yield OptionList(id="file_picker_options")
        yield Tree("workspace", id="file_picker_tree")

    def on_mount(self) -> None:
        self.query_one("#file_picker_tree", Tree).display = False
        self.refresh_query("")

    def refresh_query(self, query: str) -> None:
        self._query = query
        entries = filter_file_entries(self.index.scan(), query)
        option_list = self.query_one("#file_picker_options", OptionList)
        self._targets = {f"file:{i}": entry.path for i, entry in enumerate(entries)}
        option_list.set_options(Option(entry.path, id=f"file:{i}") for i, entry in enumerate(entries))
        option_list.highlighted = 0 if entries else None
        self._refresh_tree(entries)

    def toggle_mode(self) -> None:
        self.mode = "tree" if self.mode == "fuzzy" else "fuzzy"
        self.query_one("#file_picker_options", OptionList).display = self.mode == "fuzzy"
        self.query_one("#file_picker_tree", Tree).display = self.mode == "tree"

    def _refresh_tree(self, entries: list[WorkspaceFileEntry]) -> None:
        tree = self.query_one("#file_picker_tree", Tree)
        tree.clear()
        root = tree.root
        for entry in entries:
            root.add_leaf(entry.path, data=entry.path)

    def _select_current(self) -> None:
        if self.mode == "fuzzy":
            option = self.query_one("#file_picker_options", OptionList).highlighted_option
            if option is not None and option.id is not None and option.id in self._targets:
                self.post_message(self.Selected(self._targets[option.id]))
        else:
            node = self.query_one("#file_picker_tree", Tree).cursor_node
            if isinstance(node.data, str):
                self.post_message(self.Selected(node.data))

    def on_key(self, event: events.Key) -> None:
        if event.key == "tab":
            self.toggle_mode()
            event.stop()
            event.prevent_default()
        elif event.key == "enter":
            self._select_current()
            event.stop()
            event.prevent_default()

    @on(OptionList.OptionSelected, "#file_picker_options")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is not None and event.option.id in self._targets:
            self.post_message(self.Selected(self._targets[event.option.id]))
            event.stop()
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/app/tui/test_file_picker.py -q
```

Expected: all tests pass.

---

### Task 4: Checkpoint Verification

**Files:**
- Verify: `src/app/tui/file_picker.py`
- Verify: `tests/app/tui/test_file_picker.py`

- [ ] **Step 1: Run focused file picker tests**

Run:

```bash
uv run pytest tests/app/tui/test_file_picker.py -q
```

Expected: all pass.

- [ ] **Step 2: Run existing TUI tests**

Run:

```bash
uv run pytest tests/app/tui -q
```

Expected: existing TUI tests pass or fail only where later plans intentionally change prompt/conversation/sidebar behavior.

- [ ] **Step 3: Report checkpoint**

Report:

```text
File picker checkpoint:
- Added pure file index, fuzzy filter, mention formatting, and FilePicker widget.
- Verified with tests/app/tui/test_file_picker.py.
- No Layer 3/runtime imports added.
```

