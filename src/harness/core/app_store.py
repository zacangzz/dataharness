from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class AppStore(BaseModel):
    path: Path
    known_workspaces: dict[str, str] = Field(default_factory=dict)
    recent_workspaces: list[str] = Field(default_factory=list)
    last_opened_workspace: str | None = None
    preferences: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "AppStore":
        if not path.exists():
            return cls(path=path)
        payload = json.loads(path.read_text())
        return cls.model_validate({"path": path, **payload})

    def register_workspace(self, workspace_id: str, workspace_path: Path) -> None:
        self.known_workspaces[workspace_id] = str(workspace_path)
        self.last_opened_workspace = workspace_id
        self.recent_workspaces = [workspace_id] + [
            item for item in self.recent_workspaces if item != workspace_id
        ]
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "known_workspaces": self.known_workspaces,
                    "recent_workspaces": self.recent_workspaces,
                    "last_opened_workspace": self.last_opened_workspace,
                    "preferences": self.preferences,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
