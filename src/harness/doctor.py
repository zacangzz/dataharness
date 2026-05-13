from __future__ import annotations

import hashlib
import json
import time
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

    async def check_all_sources(self, workspace_dir: str, persistence, workspace_id: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        data_dir = Path(workspace_dir) / "data"
        if not data_dir.exists():
            return findings
        for src_file in data_dir.iterdir():
            if src_file.is_dir() or src_file.name.startswith('.'):
                continue
            stored = None
            if persistence is not None:
                try:
                    stored = persistence.db.load_record(
                        "source_records", "path",
                        str(src_file.relative_to(workspace_dir)),
                    )
                except (KeyError, Exception):
                    pass
            result = lazy_fingerprint(
                src_file,
                stored_size=stored.get("size") if stored else None,
                stored_mtime_ns=stored.get("mtime_ns") if stored else None,
                stored_fingerprint=stored.get("fingerprint") if stored else None,
            )
            finding: dict[str, Any] = {
                "source": str(src_file.relative_to(workspace_dir)),
                "fingerprint_action": result.action,
            }
            if result.action in ("changed", "missing"):
                finding["validity_state"] = classify(
                    fingerprint_action=result.action,
                    stored_fingerprint=stored.get("fingerprint") if stored else None,
                    new_fingerprint=result.fingerprint,
                ).value
                finding["type"] = "drift" if result.action == "changed" else "missing"
            findings.append(finding)
        return findings

    async def inventory_tmp_artifacts(self, workspace_dir: str, persistence) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        tmp_dir = Path(workspace_dir) / "artifacts" / "tmp"
        if not tmp_dir.exists():
            return findings
        now = time.time()
        active_runs = getattr(self, '_active_run_ids', set())
        for run_dir in tmp_dir.iterdir():
            if not run_dir.is_dir():
                continue
            run_age_days = (now - run_dir.stat().st_mtime) / 86400
            is_active = run_dir.name in active_runs
            for step_dir in run_dir.iterdir():
                if not step_dir.is_dir():
                    continue
                for artifact in step_dir.iterdir():
                    if artifact.name.startswith('.') or artifact.is_symlink():
                        continue
                    relative = str(artifact.relative_to(workspace_dir))
                    age_days = (now - artifact.stat().st_mtime) / 86400
                    if is_active:
                        classification, action, guard = "active_run", "keep", "blocked"
                    elif age_days > 7:
                        classification, action, guard = "stale", "cleanup", "safe"
                    else:
                        classification, action, guard = "orphaned", "keep", "safe"
                    findings.append({
                        "path": relative,
                        "classification": classification,
                        "proposed_action": action,
                        "guard_level": guard,
                        "age_days": round(age_days, 1),
                    })
        return findings

    async def prune_pending_plans(self, workspace_dir: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        path = Path(workspace_dir) / "state" / "pending_plans.jsonl"
        if not path.exists():
            return findings
        now = time.time()
        with open(path, encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                age_days = (now - entry.get("ts", 0)) / 86400
                if entry.get("action") == "resolved" and age_days > 7:
                    findings.append({
                        "type": "pending_plan_tombstone",
                        "plan_id": entry["plan_id"],
                        "age_days": round(age_days, 1),
                    })
                elif entry.get("action") == "created" and age_days > 1:
                    findings.append({
                        "type": "pending_plan_stuck",
                        "plan_id": entry["plan_id"],
                        "goal": entry.get("goal", "unknown"),
                        "age_days": round(age_days, 1),
                        "severity": "warn",
                    })
        return findings

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
