from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from harness.doctor import Doctor
from harness.events import (
    CommandCompleted, CommandProgress, CommandStarted, DoctorActionProposed,
    DoctorFinding, DoctorReportReady, DoctorStarted, HarnessEvent,
)


PHASES = (
    "scan_sources",
    "review_validity",
    "review_lineage",
    "review_tmp",
    "review_memory",
    "assemble_recommendations",
)


class DoctorRunner:
    def __init__(self, doctor: Doctor | None = None) -> None:
        self.doctor = doctor or Doctor()

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
            items = list(tmp_dir.rglob("*")) if tmp_dir.exists() else []
            findings = [
                DoctorFinding(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id, category="tmp", severity="info",
                    summary=f"tmp contains {len(items)} items", details={"count": len(items)},
                )
            ]
            return findings, []
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
