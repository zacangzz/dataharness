from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harness.fingerprints import lazy_fingerprint
from harness.validity import ValidityState, classify

if TYPE_CHECKING:
    from harness.persistence import HarnessPersistence


PROMOTION_TARGETS = {
    "function": "memory/functions",
    "note": "memory/notes",
    "gap": "memory/notes/gaps",
    "artifact": "artifacts",
}


class TmpCleanupBlocked(RuntimeError):
    pass


class Doctor:
    def check_source_file(
        self,
        path: Path,
        *,
        stored_size: int | None,
        stored_mtime_ns: int | None,
        stored_fingerprint: str | None,
    ) -> dict[str, Any]:
        result = lazy_fingerprint(
            path,
            stored_size=stored_size,
            stored_mtime_ns=stored_mtime_ns,
            stored_fingerprint=stored_fingerprint,
        )
        if result.action == "missing":
            return {
                "path": str(path),
                "action": "missing",
                "validity_status": ValidityState.BROKEN_LINEAGE.value,
                "fingerprint": stored_fingerprint,
            }
        validity = classify(
            fingerprint_action=result.action,
            stored_fingerprint=stored_fingerprint,
            new_fingerprint=result.fingerprint,
        )
        return {
            "path": str(path),
            "action": result.action,
            "validity_status": validity.value,
            "size_bytes": result.size_bytes,
            "modified_time_ns": result.modified_time_ns,
            "fingerprint": result.fingerprint,
        }

    def review_tmp_items(
        self,
        items: list[Path],
        *,
        trigger_context: str,
        live_refs: set[str],
        promote_map: dict[str, str],
    ) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        for item in items:
            item_key = str(item)
            if item_key in live_refs:
                action = "kept_temporarily"
                destination = None
                reason = "tmp item has an active provenance, run, failure, artifact, or review reference"
            elif item_key in promote_map:
                action = "promoted"
                target = PROMOTION_TARGETS[promote_map[item_key]]
                destination = f"{target}/{item.name}"
                reason = f"tmp item classified as reusable {promote_map[item_key]}"
            else:
                action = "deleted"
                destination = None
                reason = "tmp item has no live references and no promotion classification"
            actions.append(
                {
                    "item_path": item_key,
                    "trigger_context": trigger_context,
                    "action": action,
                    "destination_path": destination,
                    "reason": reason,
                    "decision_source": "deterministic",
                    "applied": False,
                }
            )
        return {"tmp_review": actions, "tmp_actions": actions}

    def run(
        self,
        workspace_dir: Path | None = None,
        *,
        trigger_context: str = "manual",
        tmp_items: list[Path] | None = None,
        persistence: "HarnessPersistence | None" = None,
        workspace_id: str | None = None,
        live_refs: set[str] | None = None,
        promote_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run doctor sweep. When persistence provided, writes DoctorReport + TmpAction rows
        per spec §6.12 acceptance ('row written on every invocation').
        """
        if tmp_items is None and workspace_dir is not None:
            tmp_items = self._discover_tmp_items(workspace_dir)
        tmp_items = tmp_items or []
        tmp = self.review_tmp_items(
            tmp_items,
            trigger_context=trigger_context,
            live_refs=live_refs or set(),
            promote_map=promote_map or {},
        )
        report: dict[str, Any] = {
            "trigger": trigger_context,
            "status": "ok",
            "source_findings": [],
            "validity_changes": [],
            "lineage_findings": [],
            "tmp_review": tmp["tmp_review"],
            "tmp_actions": tmp["tmp_actions"],
            "recommendations": [],
        }
        if persistence is not None and workspace_id is not None:
            self._persist(report, persistence=persistence, workspace_id=workspace_id)
        return report

    def apply_tmp_action(
        self,
        action_record: dict[str, Any],
        *,
        workspace_dir: Path,
    ) -> dict[str, Any]:
        """Spec §6.12 acceptance: cleanup MUST come after a recorded TmpAction.
        Caller must persist the TmpAction row before calling this; raises if `applied` already True.
        """
        if action_record.get("applied"):
            raise TmpCleanupBlocked("tmp action already applied")
        item = Path(str(action_record["item_path"]))
        kind = str(action_record["action"])
        if kind == "deleted":
            if item.exists():
                item.unlink()
        elif kind == "promoted":
            destination = workspace_dir / str(action_record["destination_path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if item.exists():
                item.rename(destination)
        elif kind == "kept_temporarily":
            pass
        else:
            raise ValueError(f"unknown tmp action: {kind}")
        applied_record = dict(action_record)
        applied_record["applied"] = True
        return applied_record

    def _discover_tmp_items(self, workspace_dir: Path) -> list[Path]:
        tmp_root = workspace_dir / "artifacts" / "tmp"
        if not tmp_root.exists():
            return []
        return sorted(p for p in tmp_root.rglob("*") if p.is_file())

    def _persist(
        self,
        report: dict[str, Any],
        *,
        persistence: "HarnessPersistence",
        workspace_id: str,
    ) -> None:
        from harness.control import DoctorReport, TmpAction  # avoid circular

        report_record = DoctorReport(
            workspace_id=workspace_id,
            status=str(report.get("status", "ok")),
            trigger=str(report["trigger"]),
            source_findings=list(report["source_findings"]),
            validity_changes=list(report["validity_changes"]),
            lineage_findings=list(report["lineage_findings"]),
            tmp_review=list(report["tmp_review"]),
            tmp_actions=list(report["tmp_actions"]),
            recommendations=list(report["recommendations"]),
        )
        persistence.save_model("doctor_history", "id", report_record.id, report_record)
        report["doctor_report_id"] = report_record.id
        action_records: list[dict[str, Any]] = []
        for action in report["tmp_actions"]:
            tmp_action = TmpAction(
                workspace_id=workspace_id,
                doctor_report_id=report_record.id,
                item_path=str(action["item_path"]),
                action=str(action["action"]),
                destination_path=action.get("destination_path"),
                reason=str(action["reason"]),
                decision_source=str(action["decision_source"]),
                applied=bool(action["applied"]),
            )
            persistence.save_model("tmp_actions", "id", tmp_action.id, tmp_action)
            payload = tmp_action.model_dump(mode="json")
            action.update({"id": tmp_action.id})
            action_records.append(payload)
        report["tmp_action_records"] = action_records
