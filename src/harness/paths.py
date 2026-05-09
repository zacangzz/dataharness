from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class AppPaths(BaseModel):
    root: Path
    app_dir: Path
    app_store_path: Path
    harness_dir: Path
    telemetry_dir: Path
    logs_dir: Path
    workspaces_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        return cls(
            root=root,
            app_dir=root / "app",
            app_store_path=root / "app" / "app.json",
            harness_dir=root / "harness",
            telemetry_dir=root / "harness" / "telemetry",
            logs_dir=root / "harness" / "logs",
            workspaces_dir=root / "workspaces",
        )


class WorkspacePaths(BaseModel):
    root: Path
    data_dir: Path
    artifacts_dir: Path
    tmp_artifacts_dir: Path
    memory_dir: Path
    preferences_path: Path
    notes_dir: Path
    gaps_dir: Path
    functions_dir: Path
    state_dir: Path
    workspace_db_path: Path

    @classmethod
    def from_workspace_dir(cls, root: Path) -> "WorkspacePaths":
        return cls(
            root=root,
            data_dir=root / "data",
            artifacts_dir=root / "artifacts",
            tmp_artifacts_dir=root / "artifacts" / "tmp",
            memory_dir=root / "memory",
            preferences_path=root / "memory" / "preferences.json",
            notes_dir=root / "memory" / "notes",
            gaps_dir=root / "memory" / "notes" / "gaps",
            functions_dir=root / "memory" / "functions",
            state_dir=root / "state",
            workspace_db_path=root / "state" / "workspace.db",
        )

    def relative(self, path: Path) -> Path:
        return path.relative_to(self.root)
