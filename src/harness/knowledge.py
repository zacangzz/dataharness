from __future__ import annotations

import json
from pathlib import Path
import re

from harness.control import MemoryUpdateProposal
from harness.persistence import HarnessPersistence


class MemoryWriteForbidden(PermissionError):
    """Raised when memory/ is written through any path other than KnowledgeManager."""


def guarded_external_memory_write(workspace_dir: Path, relative_path: str, content: str) -> None:
    """Spec §6.13 + §10.8: KnowledgeManager is the ONLY writer under memory/.

    Any other module that attempts to write under memory/ MUST go through this guard,
    which always raises. Real writes go through KnowledgeManager.apply / update_preferences.
    """
    target = (workspace_dir / relative_path).resolve()
    memory_root = (workspace_dir / "memory").resolve()
    if memory_root in target.parents or target == memory_root:
        raise MemoryWriteForbidden(
            f"refusing direct memory write to {relative_path}; route via KnowledgeManager"
        )
    raise MemoryWriteForbidden(f"path {relative_path} is not inside memory/")


class KnowledgeManager:
    def __init__(
        self,
        *,
        workspace_dir: Path | None = None,
        persistence: HarnessPersistence | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.persistence = persistence

    def load_preferences(self, memory_dir: Path) -> dict[str, object]:
        path = memory_dir / "preferences.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def update_preferences(self, memory_dir: Path, values: dict[str, object]) -> None:
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / "preferences.json"
        current = self.load_preferences(memory_dir)
        current.update(values)
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")

    def rescan_workspace_memory(self, memory_dir: Path, *, trigger_context: str) -> dict[str, object]:
        notes_dir = memory_dir / "notes"
        gaps_dir = memory_dir / "notes" / "gaps"
        functions_dir = memory_dir / "functions"
        return {
            "trigger_context": trigger_context,
            "preferences": self.load_preferences(memory_dir),
            "notes": sorted(path.name for path in notes_dir.glob("*.md")) if notes_dir.exists() else [],
            "gaps": sorted(path.name for path in gaps_dir.glob("*.md")) if gaps_dir.exists() else [],
            "functions": sorted(path.name for path in functions_dir.glob("*.py")) if functions_dir.exists() else [],
        }

    def synthesize_from_user_teaching(
        self,
        *,
        run_id: str,
        text: str,
        source_refs: list[str],
    ) -> dict[str, object]:
        target = "function_candidate" if text.startswith("def ") else "note"
        return {
            "run_id": run_id,
            "memory_target": target,
            "source_refs": source_refs,
            "proposed_content": text,
            "conflicts": [],
            "status": "proposed",
        }

    def check_function_freshness(
        self,
        function_path: Path,
        *,
        current_validity: dict[str, str],
        depends_on: list[str],
    ) -> dict[str, object]:
        if not function_path.exists():
            return {"reusable": False, "reason": "function file is missing"}
        for dependency in depends_on:
            status = current_validity.get(dependency, "needs_review")
            if status not in {"ok", "revalidated"}:
                return {"reusable": False, "reason": f"dependency {dependency} is {status}"}
        return {"reusable": True, "reason": "all dependencies are fresh"}

    def propose_update(
        self,
        *,
        run_id: str,
        memory_target: str,
        source_refs: list[str],
        proposed_content: str,
    ) -> MemoryUpdateProposal:
        conflicts = self._detect_conflicts(memory_target, proposed_content)
        proposal = MemoryUpdateProposal(
            workspace_id=self._workspace_id(),
            run_id=run_id,
            memory_target=memory_target,
            source_refs=source_refs,
            proposed_content=proposed_content,
            conflicts=conflicts,
            status="pending",
        )
        if self.persistence is not None:
            self.persistence.save_model("memory_update_proposals", "id", proposal.id, proposal)
        return proposal

    def _detect_conflicts(self, memory_target: str, proposed_content: str) -> list[str]:
        if self.workspace_dir is None:
            return []
        try:
            target = self._resolve_memory_target(memory_target)
        except ValueError:
            return []
        if target.exists() and target.read_text().rstrip() != proposed_content.rstrip():
            return [f"existing content at {target.relative_to(self.workspace_dir)} differs"]
        return []

    def apply(self, proposal_id: str, *, decision: str) -> dict[str, object]:
        if self.workspace_dir is None:
            raise ValueError("workspace_dir is required to apply memory updates")
        if self.persistence is None:
            raise ValueError("persistence is required to apply memory updates")
        proposal = self.persistence.db.load_record("memory_update_proposals", "id", proposal_id)
        if proposal.get("conflicts"):
            raise ValueError("cannot apply memory update with unresolved conflicts")
        if decision != "approved":
            proposal["status"] = "rejected"
            self.persistence.save_dict("memory_update_proposals", "id", proposal_id, proposal)
            return proposal

        target = self._resolve_memory_target(str(proposal["memory_target"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(proposal["proposed_content"]).rstrip() + "\n")
        proposal["status"] = "applied"
        proposal["applied_path"] = str(target.relative_to(self.workspace_dir))
        self.persistence.save_dict("memory_update_proposals", "id", proposal_id, proposal)
        return proposal

    def _workspace_id(self) -> str:
        if self.workspace_dir is None:
            return "workspace"
        return self.workspace_dir.name

    def _resolve_memory_target(self, memory_target: str) -> Path:
        assert self.workspace_dir is not None
        kind, _, name = memory_target.partition(":")
        safe_name = name or self._slug(str(memory_target)) + ".md"
        if kind == "note":
            return self.workspace_dir / "memory" / "notes" / safe_name
        if kind == "gap":
            return self.workspace_dir / "memory" / "notes" / "gaps" / safe_name
        if kind == "function":
            return self.workspace_dir / "memory" / "functions" / safe_name
        if kind == "preferences":
            return self.workspace_dir / "memory" / "preferences.json"
        raise ValueError(f"unsupported memory target: {memory_target}")

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "memory-update"
