from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from typing import TYPE_CHECKING

from harness.doctor import Doctor
from harness.events import (
    CommandCompleted, CommandProgress, CommandStarted, DoctorActionProposed,
    DoctorFinding, DoctorReportReady, DoctorStarted, HarnessEvent,
)

if TYPE_CHECKING:
    from harness.persistence import HarnessPersistence


PHASES = (
    "scan_sources",
    "review_validity",
    "review_lineage",
    "review_tmp",
    "review_memory",
    "assemble_recommendations",
)


class DoctorRunner:
    def __init__(self, doctor: Doctor | None = None, persistence: "HarnessPersistence | None" = None) -> None:
        self.doctor = doctor or Doctor()
        self.persistence = persistence

    async def run(
        self,
        *,
        workspace_id: str,
        workspace_dir: Path,
        trigger: str,
        chat_id: str | None = None,
        run_id: str | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        report_id = f"doctor_{uuid4().hex[:12]}"
        ts = datetime.now(UTC)
        yield CommandStarted(
            ts=ts, workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command="doctor", arguments={"trigger": trigger},
        )
        yield DoctorStarted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            trigger=trigger, report_id=report_id,
        )

        total = len(PHASES)
        findings_by_phase: dict[str, list[DoctorFinding]] = {}
        actions_by_phase: dict[str, list[DoctorActionProposed]] = {}

        for idx, phase in enumerate(PHASES, start=1):
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase=phase, phase_index=idx, phase_total=total,
                message=None,
            )
            findings, actions = self._run_phase(phase, workspace_dir, report_id, workspace_id, chat_id, run_id)
            findings_by_phase[phase] = findings
            actions_by_phase[phase] = actions
            for f in findings:
                yield f
            for a in actions:
                yield a

        all_findings = [f for fs in findings_by_phase.values() for f in fs]
        all_actions = [a for acts in actions_by_phase.values() for a in acts]
        summary_counts = {
            "info": sum(1 for f in all_findings if f.severity == "info"),
            "warn": sum(1 for f in all_findings if f.severity == "warn"),
            "error": sum(1 for f in all_findings if f.severity == "error"),
        }
        recommendations = [a.rationale for a in all_actions]
        action_records = [a.model_dump(mode="json") for a in all_actions]
        tmp_action_rows = self._persist_report(
            report_id=report_id, workspace_id=workspace_id,
            workspace_dir=workspace_dir, trigger=trigger,
            findings_by_phase=findings_by_phase, actions_by_phase=actions_by_phase,
            recommendations=recommendations,
        )
        if tmp_action_rows:
            action_records = tmp_action_rows
        yield DoctorReportReady(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            report_id=report_id, summary_counts=summary_counts,
            recommendations=recommendations, action_records=action_records,
        )
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command="doctor", result={"report_id": report_id},
        )

    def _run_phase(
        self, phase: str, workspace_dir: Path, report_id: str,
        workspace_id: str, chat_id: str | None, run_id: str | None,
    ) -> tuple[list[DoctorFinding], list[DoctorActionProposed]]:
        if phase == "review_tmp":
            tmp_dir = workspace_dir / "artifacts" / "tmp"
            items = sorted(p for p in tmp_dir.rglob("*") if p.is_file()) if tmp_dir.exists() else []
            live_refs, promote_map = self._classify_tmp_items(items)
            review = self.doctor.review_tmp_items(
                items,
                trigger_context="doctor_runner",
                live_refs=live_refs,
                promote_map=promote_map,
            )
            findings = [
                DoctorFinding(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id, category="tmp", severity="info",
                    summary=f"tmp contains {len(items)} items", details={"count": len(items)},
                )
            ]
            actions = [
                DoctorActionProposed(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id,
                    action=self._event_action(record["action"]),
                    target=str(record["item_path"]),
                    rationale=str(record["reason"]),
                    destination_path=record.get("destination_path"),
                )
                for record in review["tmp_actions"]
                if record["action"] != "deleted"
            ]
            return findings, actions
        return [
            DoctorFinding(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                report_id=report_id, category=self._category(phase), severity="info",
                summary=f"{phase} ok", details={},
            )
        ], []

    @staticmethod
    def _category(phase: str) -> str:
        return {
            "scan_sources": "source", "review_validity": "validity",
            "review_lineage": "lineage", "review_tmp": "tmp",
            "review_memory": "memory", "assemble_recommendations": "memory",
        }[phase]

    @staticmethod
    def _event_action(action: str) -> str:
        return {
            "promoted": "promote",
            "kept_temporarily": "keep",
            "deleted": "cleanup",
        }.get(action, "review")

    def _classify_tmp_items(self, items: list[Path]) -> tuple[set[str], dict[str, str]]:
        live_refs: set[str] = set()
        promote_map: dict[str, str] = {}
        for item in items:
            if item.name != "step.py":
                continue
            step_dir = item.parent
            result_path = step_dir / "step_result.json"
            result = self._read_step_result(result_path)
            if result.get("status") == "ok" and not result.get("failure_summary"):
                promote_map[str(item)] = "function"
            else:
                for evidence in step_dir.glob("*"):
                    if evidence.is_file():
                        live_refs.add(str(evidence))
        return live_refs, promote_map

    @staticmethod
    def _read_step_result(path: Path) -> dict[str, object]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _persist_report(
        self,
        *,
        report_id: str,
        workspace_id: str,
        workspace_dir: Path,
        trigger: str,
        findings_by_phase: dict,
        actions_by_phase: dict,
        recommendations: list[str],
    ) -> list[dict]:
        if self.persistence is None:
            return []
        from harness.control import DoctorReport, TmpAction
        tmp_dir = workspace_dir / "artifacts" / "tmp"
        items = sorted(p for p in tmp_dir.rglob("*") if p.is_file()) if tmp_dir.exists() else []
        live_refs, promote_map = self._classify_tmp_items(items)
        tmp_review = self.doctor.review_tmp_items(
            items, trigger_context="doctor_runner",
            live_refs=live_refs, promote_map=promote_map,
        )
        report_record = DoctorReport(
            id=report_id,
            workspace_id=workspace_id,
            status="ok",
            trigger=trigger,
            source_findings=[f.model_dump(mode="json") for f in findings_by_phase.get("scan_sources", [])],
            validity_changes=[f.model_dump(mode="json") for f in findings_by_phase.get("review_validity", [])],
            lineage_findings=[f.model_dump(mode="json") for f in findings_by_phase.get("review_lineage", [])],
            tmp_review=list(tmp_review["tmp_review"]),
            tmp_actions=list(tmp_review["tmp_actions"]),
            recommendations=list(recommendations),
        )
        self.persistence.save_model("doctor_history", "id", report_record.id, report_record)
        rows: list[dict] = []
        for action in tmp_review["tmp_actions"]:
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
            self.persistence.save_model("tmp_actions", "id", tmp_action.id, tmp_action)
            rows.append(tmp_action.model_dump(mode="json"))
        return rows
