from __future__ import annotations

import json
import time
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
from harness.knowledge import KnowledgeManager
from runtime.types import RuntimeMessage, RuntimeRequest

if TYPE_CHECKING:
    from harness.chat import ChatStore
    from harness.persistence import HarnessPersistence
    from runtime.protocol import Runtime


PHASES = (
    "scan_sources",
    "review_validity",
    "review_lineage",
    "review_tmp",
    "review_memory",
    "assemble_recommendations",
)


class DoctorRunner:
    def __init__(
        self,
        doctor: Doctor | None = None,
        persistence: "HarnessPersistence | None" = None,
        runtime: "Runtime | None" = None,
        knowledge_manager: KnowledgeManager | None = None,
        chat_store: "ChatStore | None" = None,
    ) -> None:
        self.doctor = doctor or Doctor()
        self.persistence = persistence
        self.runtime = runtime
        self.knowledge_manager = knowledge_manager
        self.chat_store = chat_store

    async def run(
        self,
        *,
        workspace_id: str,
        workspace_dir: Path,
        trigger: str,
        chat_id: str | None = None,
        run_id: str | None = None,
        mode: str = "full",
    ) -> AsyncIterator[HarnessEvent]:
        self.mode = mode
        run_deterministic = mode in ("light", "full")
        run_llm = mode in ("semantic", "full")

        for d in ["notes", "notes/gaps", "functions"]:
            (Path(workspace_dir) / "memory" / d).mkdir(parents=True, exist_ok=True)

        report_id = f"dr_{workspace_id}_{int(time.time())}"
        ts = datetime.now(UTC)
        yield CommandStarted(
            ts=ts, workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command="doctor", arguments={"trigger": trigger},
        )
        yield DoctorStarted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            trigger=trigger, report_id=report_id,
        )

        all_findings: list[DoctorFinding] = []
        all_actions: list[DoctorActionProposed] = []
        phase2_actions: list[DoctorActionProposed] = []

        if run_deterministic:
            # Phase 1: Source Rescan
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="source_rescan", phase_index=1, phase_total=3,
                message="Scanning sources",
            )
            source_findings = await self.doctor.check_all_sources(
                workspace_dir, self.persistence, workspace_id,
            )
            for f in source_findings:
                if f.get("type"):
                    finding = DoctorFinding(
                        ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                        report_id=report_id, category="source",
                        severity="warn" if f["type"] == "drift" else "error",
                        summary=f"{f['source']}: {f['fingerprint_action']}",
                        details=f,
                    )
                    all_findings.append(finding)
                    yield finding
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="source_rescan", phase_index=1, phase_total=3,
                message="Source scan complete",
            )

            # Phase 2: Artifact Inventory (collect actions, yield after old phases)
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="artifact_inventory", phase_index=2, phase_total=3,
                message="Inventorying artifacts",
            )
            tmp_findings = await self.doctor.inventory_tmp_artifacts(
                workspace_dir, self.persistence,
            )
            for f in tmp_findings:
                mapped = "cleanup" if f["proposed_action"] == "cleanup" else "keep"
                action = DoctorActionProposed(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id, action=mapped, target=f["path"],
                    rationale=f"classified as {f['classification']}, age={f['age_days']}d",
                    destination_path=None,
                )
                phase2_actions.append(action)
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="artifact_inventory", phase_index=2, phase_total=3,
                message="Inventory complete",
            )

            # Phase 3: Pending Plan Pruning
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="pending_plan_pruning", phase_index=3, phase_total=3,
                message="Pruning plans",
            )
            plan_findings = await self.doctor.prune_pending_plans(workspace_dir)
            for f in plan_findings:
                finding = DoctorFinding(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id, category="tmp", severity="warn",
                    summary=f.get("type", "unknown"), details=f,
                )
                all_findings.append(finding)
                yield finding
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="pending_plan_pruning", phase_index=3, phase_total=3,
                message="Pruning complete",
            )

        if run_llm:
            # Phase 4: Chat Knowledge Mining
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="knowledge_mining", phase_index=0, phase_total=3,
                message="Mining chat knowledge",
            )
            knowledge_findings = await self._run_chat_knowledge_mining(chat_id, workspace_id, workspace_dir)
            for f in knowledge_findings:
                yield DoctorFinding(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id,
                    category="memory",
                    severity="info",
                    summary=f.get("title", "unknown"),
                    details=f,
                )

            # Phase 5: Script Relevance Assessment
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="script_assessment", phase_index=1, phase_total=3,
                message="Assessing scripts",
            )
            script_findings = await self._run_script_assessment(workspace_dir)
            for f in script_findings:
                yield DoctorActionProposed(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id,
                    action="keep" if f.get("assessment") == "relevant" else "review",
                    target=f.get("script", ""),
                    rationale=f.get("reason", ""),
                    destination_path=None,
                )

            # Phase 6: Knowledge Consistency Check
            yield CommandProgress(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command="doctor", phase="consistency_check", phase_index=2, phase_total=3,
                message="Consistency check",
            )
            consistency_findings = await self._run_consistency_check(workspace_dir)
            for f in consistency_findings:
                yield DoctorFinding(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                    report_id=report_id,
                    category="memory",
                    severity="warn",
                    summary=f.get("description", "unknown"),
                    details=f,
                )

        # Phases 7-8: compilation + report (existing phase loop)
        findings_by_phase: dict[str, list[DoctorFinding]] = {}
        actions_by_phase: dict[str, list[DoctorActionProposed]] = {}
        total = len(PHASES)
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
                all_findings.append(f)
                yield f
            for a in actions:
                all_actions.append(a)
                yield a

        # Yield Phase 2 actions after old phases so old actions appear first
        for a in phase2_actions:
            all_actions.append(a)
            yield a

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

    async def _run_chat_knowledge_mining(self, chat_id, workspace_id, workspace_dir):
        """Phase 4 LLM: Extract knowledge from chat history. Uses streaming JSONL parse."""
        if not self.runtime or not chat_id or not self.chat_store:
            return []

        chat_record = self.chat_store.view_chat(chat_id)
        if not chat_record or not chat_record.messages:
            return []

        recent_turn_ids = [m.turn_id for m in chat_record.messages[-20:] if hasattr(m, 'turn_id') and m.turn_id]
        if self.knowledge_manager and self.knowledge_manager.has_note_for_turns(workspace_dir, recent_turn_ids):
            return []

        recent = chat_record.messages[-20:]
        chat_text = "\n".join(f"[{m.role}]: {m.text[:300]}" for m in recent)

        prompt = f"""You are extracting reusable knowledge from a data analysis conversation.
For each piece of knowledge found, output a JSON object with: type, title, content, confidence.

Types:
- "note": A fact, formula, or definition taught by the user
- "preference": A user preference about how they want data shown or analyzed
- "gap": Something the user asked about but was not resolved

Conversation:
{chat_text}

Output one JSON object per finding, each on its own line:
{{"type":"note","title":"headcount formula","content":"average headcount = total / 6","confidence":"high","source_turn_ids":["turn_xxx"]}}
"""

        request = RuntimeRequest(
            messages=[RuntimeMessage(role="user", content=prompt)],
            max_completion_tokens=1024,
            request_id=f"doctor_knowledge_{workspace_id}",
        )

        findings = []
        buffer = ""
        async for event in self.runtime.stream(request):
            if event.type == "text_delta" and event.text:
                buffer += event.text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        findings.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        buffer = buffer.strip()
        if buffer:
            try:
                findings.append(json.loads(buffer))
            except json.JSONDecodeError:
                pass
        return findings

    async def _run_script_assessment(self, workspace_dir):
        """Phase 5 LLM: Assess saved function relevance."""
        if not self.runtime:
            return []

        funcs_dir = Path(workspace_dir) / "memory" / "functions"
        if not funcs_dir.exists() or not list(funcs_dir.glob("*.py")):
            return []

        scripts_text = ""
        for py_file in funcs_dir.glob("*.py"):
            content = py_file.read_text()[:1000]
            scripts_text += f"\n### {py_file.name}\n```python\n{content}\n```\n"

        prompt = f"""Assess these saved analysis scripts. For each, determine:
- Is it still relevant to the current data?
- Are any scripts solving the same problem (combinable)?
- Are any obsolete?

Scripts:
{scripts_text}

Output one JSON object per finding: {{"script":"name.py","assessment":"relevant|obsolete|combinable_with_<other>","reason":"..."}}
"""

        request = RuntimeRequest(
            messages=[RuntimeMessage(role="user", content=prompt)],
            max_completion_tokens=1024,
            request_id=f"doctor_scripts_{Path(workspace_dir).name}",
        )

        findings = []
        buffer = ""
        async for event in self.runtime.stream(request):
            if event.type == "text_delta" and event.text:
                buffer += event.text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        findings.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        buffer = buffer.strip()
        if buffer:
            try:
                findings.append(json.loads(buffer))
            except json.JSONDecodeError:
                pass
        return findings

    async def _run_consistency_check(self, workspace_dir):
        """Phase 6 LLM: Cross-reference notes, preferences, functions for conflicts."""
        if not self.runtime:
            return []

        notes_dir = Path(workspace_dir) / "memory" / "notes"
        funcs_dir = Path(workspace_dir) / "memory" / "functions"
        prefs_path = Path(workspace_dir) / "memory" / "preferences.json"
        prefs = {}
        if prefs_path.exists():
            prefs = json.loads(prefs_path.read_text() or "{}")

        context = ""
        if notes_dir.exists():
            for note in notes_dir.glob("*.md"):
                context += f"\n[NOTE {note.stem}]: {note.read_text()[:500]}\n"
        if funcs_dir.exists():
            for func in funcs_dir.glob("*.py"):
                context += f"\n[FUNCTION {func.stem}]: {func.read_text()[:500]}\n"
        context += f"\n[PREFERENCES]: {json.dumps(prefs)}\n"

        if not context.strip():
            return []

        prompt = f"""Check this knowledge base for consistency issues:
- Contradictions between notes
- Stale references (mentions files that no longer exist in data/)
- Preferences that conflict with stored notes

Knowledge base:
{context}

Output one JSON per issue: {{"type":"contradiction|stale_reference|preference_conflict","description":"...","affected_items":["note_x","pref_y"]}}
"""

        request = RuntimeRequest(
            messages=[RuntimeMessage(role="user", content=prompt)],
            max_completion_tokens=1024,
            request_id=f"doctor_consistency_{Path(workspace_dir).name}",
        )

        findings = []
        buffer = ""
        async for event in self.runtime.stream(request):
            if event.type == "text_delta" and event.text:
                buffer += event.text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        findings.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        buffer = buffer.strip()
        if buffer:
            try:
                findings.append(json.loads(buffer))
            except json.JSONDecodeError:
                pass
        return findings
