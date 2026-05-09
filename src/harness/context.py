from __future__ import annotations

import json
from pathlib import Path


class ContextManager:
    def rebuild(
        self,
        *,
        workspace_dir: Path,
        session_ledger: list[str],
        validity_states: list[str],
        chat_history: list[str],
    ) -> dict[str, object]:
        preferences_path = workspace_dir / "memory" / "preferences.json"
        preferences = json.loads(preferences_path.read_text()) if preferences_path.exists() else {}
        notes_dir = workspace_dir / "memory" / "notes"
        notes = []
        if notes_dir.exists():
            notes = [path.read_text() for path in sorted(notes_dir.glob("*.md"))]
        return {
            "preferences": preferences,
            "memory_notes": "\n".join(notes),
            "session_ledger": session_ledger,
            "validity_states": validity_states,
            "chat_history_loaded": False,
        }

    def compact(
        self,
        entries: list[str],
        *,
        active_plan_id: str,
        current_step_id: str,
        unresolved_failures: list[str],
    ) -> dict[str, object]:
        operational_atoms = [
            entry for entry in entries if entry.startswith("tool_call:") or entry.startswith("tool_output:")
        ]
        return {
            "durable": False,
            "summary": "\n".join(operational_atoms),
            "active_plan_id": active_plan_id,
            "current_step_id": current_step_id,
            "unresolved_failures": unresolved_failures,
        }
