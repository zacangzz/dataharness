"""
Workspace file browser — a small self-contained Textual browser inspired by
the browsr workflow, but embedded inside hragent.

It presents a directory tree for the active workspace and a lightweight preview
panel for the selected file or directory.
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Label, Static


_TEXT_PREVIEW_BYTES = 16_384
_TEXT_PREVIEW_LINES = 200
_BINARY_EXTENSIONS = {
    ".parquet",
    ".xlsx",
    ".xls",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".feather",
    ".arrow",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
}


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size)} B"


def _visible_children(path: Path) -> list[str]:
    return sorted(
        child.name + ("/" if child.is_dir() else "")
        for child in path.iterdir()
        if not child.name.startswith(".")
    )


def _relative_label(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _describe_path(path: Path) -> str:
    if not path.exists():
        return "Missing path"
    if path.is_dir():
        return f"Directory\nItems: {len(_visible_children(path))}\nPath: {path}"
    return (
        f"File\nSize: {_format_bytes(path.stat().st_size)}\n"
        f"Suffix: {path.suffix or '(none)'}\nPath: {path}"
    )


def read_preview_text(path: Path) -> str:
    """Return a small text preview for a workspace file."""
    if not path.exists():
        return "(missing)"
    if path.is_dir():
        children = _visible_children(path)
        if not children:
            return "(empty directory)"
        preview = "\n".join(children[:100])
        if len(children) > 100:
            preview += f"\n... and {len(children) - 100} more"
        return preview

    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return "Binary or structured file preview is not shown in-app."

    try:
        raw = path.read_bytes()[:_TEXT_PREVIEW_BYTES]
    except OSError as exc:
        return f"Failed to read file: {exc}"

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    clipped = lines[:_TEXT_PREVIEW_LINES]
    preview = "\n".join(clipped) if clipped else "(empty file)"
    if len(lines) > _TEXT_PREVIEW_LINES or path.stat().st_size > _TEXT_PREVIEW_BYTES:
        preview += "\n\n... preview truncated ..."
    return preview


class WorkspaceDirectoryTree(DirectoryTree):
    """Directory tree filtered to non-hidden workspace files."""

    def filter_paths(self, paths):
        return [path for path in paths if not path.name.startswith(".")]


class WorkspaceFileBrowser(ModalScreen[None]):
    """Embedded workspace browser with tree navigation and preview panel."""

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Close"),
        Binding("q", "dismiss_screen", "Close"),
        Binding("r", "reload_tree", "Reload"),
    ]

    DEFAULT_CSS = """
    WorkspaceFileBrowser {
        align: center middle;
    }

    #browser-modal {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $primary;
    }

    #browser-tree-panel, #browser-preview-panel {
        width: 1fr;
        height: 100%;
        padding: 1;
    }

    #browser-tree {
        height: 1fr;
        border: round $accent;
    }

    #browser-meta, #browser-preview {
        border: round $primary-background;
        padding: 1;
    }

    #browser-meta {
        height: 5;
        margin-bottom: 1;
    }

    #browser-preview {
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self, workspace_dir: Path, workspace_name: str) -> None:
        super().__init__()
        self._workspace_dir = workspace_dir
        self._workspace_name = workspace_name
        self._selected_path = workspace_dir

    def compose(self) -> ComposeResult:
        with Horizontal(id="browser-modal"):
            with Vertical(id="browser-tree-panel"):
                yield Label(
                    f"Workspace Browser: {self._workspace_name}",
                    id="browser-title",
                )
                yield WorkspaceDirectoryTree(self._workspace_dir, id="browser-tree")
            with Vertical(id="browser-preview-panel"):
                yield Label(str(self._workspace_dir), id="browser-path")
                yield Static("", id="browser-meta")
                yield Static("", id="browser-preview")

    def on_mount(self) -> None:
        self.display_path(self._selected_path)
        self.query_one("#browser-tree", WorkspaceDirectoryTree).focus()

    def action_dismiss_screen(self) -> None:
        self.dismiss()

    def action_reload_tree(self) -> None:
        tree = self.query_one("#browser-tree", WorkspaceDirectoryTree)
        tree.reload()
        self.display_path(self._selected_path)

    def on_directory_tree_file_selected(
        self, event: WorkspaceDirectoryTree.FileSelected
    ) -> None:
        self.display_path(event.path)

    def on_directory_tree_directory_selected(
        self, event: WorkspaceDirectoryTree.DirectorySelected
    ) -> None:
        self.display_path(event.path)

    def display_path(self, path: Path) -> None:
        """Update the metadata and preview panes for a selected path."""
        self._selected_path = path
        self.query_one("#browser-path", Label).update(
            _relative_label(self._workspace_dir, path)
        )
        self.query_one("#browser-meta", Static).update(_describe_path(path))
        self.query_one("#browser-preview", Static).update(read_preview_text(path))
