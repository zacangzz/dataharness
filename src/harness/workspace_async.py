from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from harness.app_store import AppStore
from harness.chat import ChatStore
from harness.exceptions import WorkspaceNotFound
from harness.workspace import bootstrap_workspace


class WorkspaceSummary(BaseModel):
    workspace_id: str
    workspace_dir: Path
    created_at: datetime
    last_activated_at: datetime | None
    chat_count: int
    source_count: int
    health: Literal["ready", "busy", "degraded", "error"]


class WorkspaceIngestResult(BaseModel):
    workspace_id: str
    accepted: list[Path] = Field(default_factory=list)
    rejected: list[dict] = Field(default_factory=list)
    source_records_added: int = 0


class AsyncWorkspaceManager:
    """Layer 3 async-shaped workspace service.

    Filesystem operations here are bounded app-state updates; long-running data
    execution still belongs to Layer 2.
    """

    def __init__(self, *, app_root: Path, chat_store: ChatStore | None = None) -> None:
        self.app_root = app_root
        self.workspaces_dir = app_root / "workspaces"
        self.app_store_path = app_root / "app" / "app.json"
        self.chat_store = chat_store

    async def list_workspaces(self) -> list[WorkspaceSummary]:
        if not self.workspaces_dir.exists():
            return []
        return [
            await self._summary(path.name)
            for path in sorted(self.workspaces_dir.iterdir())
            if path.is_dir()
        ]

    async def create_workspace(self, workspace_id: str) -> WorkspaceSummary:
        workspace_dir = bootstrap_workspace(self.workspaces_dir / workspace_id)
        self._register(workspace_id, workspace_dir)
        return await self._summary(workspace_id)

    async def rename_workspace(self, old_id: str, new_id: str) -> WorkspaceSummary:
        old_dir = self.workspaces_dir / old_id
        if not old_dir.exists():
            raise WorkspaceNotFound(workspace_id=old_id)
        new_dir = self.workspaces_dir / new_id
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        old_dir.rename(new_dir)
        store = AppStore.load(self.app_store_path)
        store.known_workspaces.pop(old_id, None)
        store.known_workspaces[new_id] = str(new_dir)
        store.recent_workspaces = [new_id if item == old_id else item for item in store.recent_workspaces]
        if store.last_opened_workspace == old_id:
            store.last_opened_workspace = new_id
        store.save()
        return await self._summary(new_id)

    async def delete_workspace(self, workspace_id: str) -> WorkspaceSummary:
        summary = await self._summary(workspace_id)
        workspace_dir = self.workspaces_dir / workspace_id
        if not workspace_dir.exists():
            raise WorkspaceNotFound(workspace_id=workspace_id)
        if self.chat_store is not None:
            await self.chat_store.cascade_delete_for_workspace(workspace_id)
        shutil.rmtree(workspace_dir)
        store = AppStore.load(self.app_store_path)
        store.known_workspaces.pop(workspace_id, None)
        store.recent_workspaces = [item for item in store.recent_workspaces if item != workspace_id]
        if store.last_opened_workspace == workspace_id:
            store.last_opened_workspace = store.recent_workspaces[0] if store.recent_workspaces else None
        store.save()
        return summary

    async def activate_workspace(self, workspace_id: str, *, force: bool = False) -> WorkspaceSummary:
        workspace_dir = self.workspaces_dir / workspace_id
        if not workspace_dir.exists():
            raise WorkspaceNotFound(workspace_id=workspace_id)
        self._register(workspace_id, workspace_dir)
        telemetry_dir = Path(workspace_dir) / "state" / "telemetry"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        return await self._summary(workspace_id)

    async def ingest_files(self, workspace_id: str, paths: list[Path]) -> WorkspaceIngestResult:
        workspace_dir = self.workspaces_dir / workspace_id
        if not workspace_dir.exists():
            raise WorkspaceNotFound(workspace_id=workspace_id)
        data_dir = workspace_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        accepted: list[Path] = []
        rejected: list[dict] = []
        for source in paths:
            try:
                src = Path(source).expanduser().resolve()
                if not src.is_file():
                    rejected.append({"source_path": str(source), "reason": "not a file"})
                    continue
                dest = data_dir / src.name
                if dest.exists():
                    dest = self._deduplicate_dest(data_dir, src.name)
                shutil.copy2(src, dest)
                accepted.append(dest.relative_to(workspace_dir))
            except Exception as exc:  # noqa: BLE001
                rejected.append({"source_path": str(source), "reason": str(exc)})
        return WorkspaceIngestResult(
            workspace_id=workspace_id,
            accepted=accepted,
            rejected=rejected,
            source_records_added=len(accepted),
        )

    def _register(self, workspace_id: str, workspace_dir: Path) -> None:
        AppStore.load(self.app_store_path).register_workspace(workspace_id, workspace_dir)

    async def _summary(self, workspace_id: str) -> WorkspaceSummary:
        workspace_dir = self.workspaces_dir / workspace_id
        if not workspace_dir.exists():
            raise WorkspaceNotFound(workspace_id=workspace_id)
        data_dir = workspace_dir / "data"
        source_count = sum(1 for item in data_dir.rglob("*") if item.is_file()) if data_dir.exists() else 0
        chats_dir = workspace_dir / "chats"
        chat_count = sum(1 for item in chats_dir.iterdir() if item.is_dir()) if chats_dir.exists() else 0
        created_at = datetime.fromtimestamp(workspace_dir.stat().st_ctime, UTC)
        store = AppStore.load(self.app_store_path)
        last_activated_at = None
        if store.last_opened_workspace == workspace_id:
            last_activated_at = datetime.now(UTC)
        return WorkspaceSummary(
            workspace_id=workspace_id,
            workspace_dir=workspace_dir,
            created_at=created_at,
            last_activated_at=last_activated_at,
            chat_count=chat_count,
            source_count=source_count,
            health="ready",
        )

    def _deduplicate_dest(self, data_dir: Path, filename: str) -> Path:
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        index = 2
        while True:
            candidate = data_dir / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1
