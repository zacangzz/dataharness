from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
        base = self.workspace_dir
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIPPED_DIRS)
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                full = Path(dirpath) / name
                rel = full.relative_to(base).as_posix()
                entries.append(WorkspaceFileEntry(rel))
                if len(entries) >= self.max_entries:
                    self._cache = entries
                    return list(entries)
        entries.sort(key=lambda e: e.path)
        self._cache = entries
        return list(entries)


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


from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import OptionList, Static, Tree
from textual.widgets.option_list import Option


class FilePicker(Widget):
    can_focus = True

    class Selected(Message):
        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class Confirmed(Message):
        def __init__(self, paths: list[str]) -> None:
            self.paths = paths
            super().__init__()

    class Dismissed(Message):
        pass

    def __init__(
        self,
        workspace_dir: Path | None = None,
        *,
        root: Path | None = None,
        allow_multiselect: bool = False,
        mode_default: Literal["fuzzy", "tree"] = "fuzzy",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        effective_root = root if root is not None else workspace_dir
        if effective_root is None:
            effective_root = Path.cwd()
        self.index = WorkspaceFileIndex(effective_root)
        self.mode = mode_default
        self.allow_multiselect = allow_multiselect
        self._query = ""
        self._targets: dict[str, str] = {}
        self._selected: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="file_picker_modes")
            yield OptionList(id="file_picker_options")
            yield Tree("workspace", id="file_picker_tree")

    def on_mount(self) -> None:
        # Show widget for the active mode.
        self.query_one("#file_picker_options", OptionList).display = self.mode == "fuzzy"
        self.query_one("#file_picker_tree", Tree).display = self.mode == "tree"
        self.refresh_query("")

    def _render_modes(self) -> None:
        try:
            label = self.query_one("#file_picker_modes", Static)
        except Exception:
            return
        if self.mode == "fuzzy":
            text = f"[tree view]  fuzzy search   @{self._query}"
        else:
            text = f"tree view  [fuzzy search]   @{self._query}"
        label.update(text)

    def _label_for(self, path: str) -> str:
        if not self.allow_multiselect:
            return path
        prefix = "▣ " if path in self._selected else "  "
        return f"{prefix}{path}"

    def refresh_query(self, query: str) -> None:
        self._query = query
        entries = filter_file_entries(self.index.scan(), query)
        option_list = self.query_one("#file_picker_options", OptionList)
        self._targets = {f"file:{i}": entry.path for i, entry in enumerate(entries)}
        option_list.set_options(
            Option(self._label_for(entry.path), id=f"file:{i}")
            for i, entry in enumerate(entries)
        )
        option_list.highlighted = 0 if entries else None
        self._build_tree(entries)
        self._render_modes()

    def toggle_mode(self) -> None:
        self.mode = "tree" if self.mode == "fuzzy" else "fuzzy"
        self.query_one("#file_picker_options", OptionList).display = self.mode == "fuzzy"
        self.query_one("#file_picker_tree", Tree).display = self.mode == "tree"
        self._render_modes()
        self.focus_picker()

    def focus_picker(self) -> None:
        self.display = True
        try:
            if self.mode == "fuzzy":
                self.query_one("#file_picker_options", OptionList).focus()
            else:
                self.query_one("#file_picker_tree", Tree).focus()
        except Exception:
            pass

    def dismiss_picker(self) -> None:
        self.display = False
        self.post_message(self.Dismissed())

    def update_root(self, new_root: Path) -> None:
        self.index = WorkspaceFileIndex(new_root)
        self._selected.clear()
        self.refresh_query("")

    def _build_tree(self, entries: list[WorkspaceFileEntry]) -> None:
        tree = self.query_one("#file_picker_tree", Tree)
        tree.clear()
        root = tree.root
        # Build hierarchy: dict-tree of dirs -> child dicts; leaves are mapped to full rel path.
        hierarchy: dict = {}
        for entry in entries:
            parts = entry.path.split("/")
            node = hierarchy
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = entry.path  # leaf

        def populate(parent, mapping: dict) -> None:
            for name in sorted(mapping.keys(), key=lambda k: (not isinstance(mapping[k], dict), k)):
                value = mapping[name]
                if isinstance(value, dict):
                    sub = parent.add(name)
                    populate(sub, value)
                else:
                    label = self._label_for(value) if self.allow_multiselect else name
                    parent.add_leaf(label, data=value)

        populate(root, hierarchy)
        try:
            root.expand()
        except Exception:
            pass

    def _highlighted_path(self) -> str | None:
        if self.mode == "fuzzy":
            option = self.query_one("#file_picker_options", OptionList).highlighted_option
            if option is not None and option.id is not None and option.id in self._targets:
                return self._targets[option.id]
            return None
        node = self.query_one("#file_picker_tree", Tree).cursor_node
        if node is not None and isinstance(node.data, str):
            return node.data
        return None

    def _toggle_selected(self) -> None:
        if not self.allow_multiselect:
            return
        path = self._highlighted_path()
        if path is None:
            return
        if path in self._selected:
            self._selected.remove(path)
        else:
            self._selected.add(path)
        self.refresh_query(self._query)

    def _select_current(self) -> None:
        if self.allow_multiselect and self._selected:
            self.post_message(self.Confirmed(list(self._selected)))
            return
        path = self._highlighted_path()
        if path is not None:
            self.post_message(self.Selected(path))

    def on_key(self, event: events.Key) -> None:
        if event.key == "tab":
            self.toggle_mode()
            event.stop()
            event.prevent_default()
        elif event.key == "space" and self.allow_multiselect:
            self._toggle_selected()
            event.stop()
            event.prevent_default()
        elif event.key == "enter":
            self._select_current()
            event.stop()
            event.prevent_default()
        elif event.key == "escape":
            self.dismiss_picker()
            event.stop()
            event.prevent_default()

    @on(OptionList.OptionSelected, "#file_picker_options")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is not None and event.option.id in self._targets:
            path = self._targets[event.option.id]
            if self.allow_multiselect:
                # Selecting a row in multiselect mode toggles selection rather than confirming.
                if path in self._selected:
                    self._selected.remove(path)
                else:
                    self._selected.add(path)
                self.refresh_query(self._query)
            else:
                self.post_message(self.Selected(path))
            event.stop()
