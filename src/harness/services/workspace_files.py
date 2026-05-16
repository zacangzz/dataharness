from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.context import list_workspace_files, read_file_schema


READ_FILE_CHAR_CAP = 32_000


class WorkspaceFileService:
    def list_files(self, workspace_dir: Path) -> list[dict[str, Any]]:
        return list_workspace_files(workspace_dir) if workspace_dir.exists() else []

    def inspect_file(self, workspace_dir: Path, rel_path: str) -> dict[str, Any]:
        if not workspace_dir.exists():
            return {"error": "workspace not found"}
        if not rel_path:
            return {"error": "missing required arg 'path'"}
        return read_file_schema(workspace_dir, rel_path)

    def read_content(
        self,
        workspace_dir: Path,
        rel_path: str,
        *,
        max_bytes: int = 65536,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        if not workspace_dir.exists():
            return {"error": "workspace not found"}
        try:
            wd = workspace_dir.resolve()
            target = (wd / rel_path).resolve()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"invalid path: {exc}"}
        if wd != target and wd not in target.parents:
            return {"error": "path escapes workspace"}
        if not target.exists() or not target.is_file():
            return {"error": "not a file"}
        size = target.stat().st_size
        cap = max(1, int(max_bytes))
        try:
            data = target.read_bytes()[:cap]
            content = data.decode(encoding)
        except UnicodeDecodeError:
            return {"path": rel_path, "size_bytes": size, "error": "binary_file"}
        truncated = size > cap
        truncation_reason = "max_bytes" if truncated else None
        if len(content) > READ_FILE_CHAR_CAP:
            content = content[:READ_FILE_CHAR_CAP]
            truncated = True
            truncation_reason = "token_budget"
        return {
            "path": rel_path,
            "size_bytes": size,
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "content": content,
        }
