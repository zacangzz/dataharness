from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.app_store import AppStore
from harness.paths import WorkspacePaths


DEFAULT_WORKSPACE_ID = "w_0001"


@dataclass(frozen=True)
class ActiveWorkspace:
    workspace_id: str
    workspace_dir: Path


def bootstrap_workspace(workspace_dir: Path) -> Path:
    paths = WorkspacePaths.from_workspace_dir(workspace_dir)
    for directory in [
        paths.data_dir,
        paths.artifacts_dir,
        paths.tmp_artifacts_dir,
        paths.notes_dir,
        paths.gaps_dir,
        paths.functions_dir,
        paths.state_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.preferences_path.exists():
        paths.preferences_path.write_text("{}\n")
    return workspace_dir


class WorkspaceManager:
    def __init__(self, app_root: Path) -> None:
        self.app_root = app_root
        self.workspaces_dir = app_root / "workspaces"
        self.app_store_path = app_root / "app" / "app.json"

    def open_default_workspace(self) -> ActiveWorkspace:
        return self.open_workspace(DEFAULT_WORKSPACE_ID)

    def open_workspace(self, workspace_id: str) -> ActiveWorkspace:
        workspace_dir = bootstrap_workspace(self.workspaces_dir / workspace_id)
        AppStore.load(self.app_store_path).register_workspace(workspace_id, workspace_dir)
        return ActiveWorkspace(workspace_id=workspace_id, workspace_dir=workspace_dir)
