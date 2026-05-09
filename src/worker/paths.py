from __future__ import annotations

from pathlib import Path


def build_step_tmp_dir(workspace_dir: Path, *, run_id: str, step_id: str) -> Path:
    return workspace_dir / "artifacts" / "tmp" / run_id / step_id


def to_workspace_relative(workspace_dir: Path, path: Path) -> Path:
    resolved_workspace = workspace_dir.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_workspace):
        raise ValueError(f"Path {path!r} is not under workspace {workspace_dir!r}")
    return resolved_path.relative_to(resolved_workspace)


def as_posix_workspace_relative(workspace_dir: Path, path: Path) -> str:
    return to_workspace_relative(workspace_dir, path).as_posix()
