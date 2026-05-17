from pathlib import Path

from harness.services.knowledge import KnowledgeManager


def test_knowledge_manager_reads_and_updates_preferences(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    manager = KnowledgeManager()
    manager.update_preferences(memory, {"style": "concise"})
    assert manager.load_preferences(memory) == {"style": "concise"}


def test_knowledge_manager_rescans_notes_functions_and_preferences(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    (memory / "notes").mkdir(parents=True)
    (memory / "notes" / "gaps").mkdir()
    (memory / "functions").mkdir()
    (memory / "preferences.json").write_text('{"style":"concise"}')
    (memory / "notes" / "attrition.md").write_text("Attrition note")
    (memory / "notes" / "gaps" / "unknown-grade.md").write_text("Grade mapping unclear")
    (memory / "functions" / "attrition.py").write_text("def attrition():\n    return 1\n")
    report = KnowledgeManager().rescan_workspace_memory(memory, trigger_context="doctor")
    assert report["preferences"] == {"style": "concise"}
    assert report["notes"] == ["attrition.md"]
    assert report["gaps"] == ["unknown-grade.md"]
    assert report["functions"] == ["attrition.py"]


def test_user_teaching_becomes_reviewable_memory_update_proposal() -> None:
    proposal = KnowledgeManager().synthesize_from_user_teaching(
        run_id="run_1",
        text="remember that attrition = total leavers / average headcount",
        source_refs=["chat:12"],
    )
    assert proposal["memory_target"] == "note"
    assert proposal["status"] == "proposed"
    assert proposal["source_refs"] == ["chat:12"]


def test_saved_function_reuse_requires_freshness_check(tmp_path: Path) -> None:
    function = tmp_path / "memory" / "functions" / "attrition.py"
    function.parent.mkdir(parents=True)
    function.write_text("def attrition():\n    return 1\n")
    result = KnowledgeManager().check_function_freshness(
        function,
        current_validity={"data/employees.csv": "changed"},
        depends_on=["data/employees.csv"],
    )
    assert result["reusable"] is False
    assert result["reason"] == "dependency data/employees.csv is changed"


def test_propose_update_creates_pending_proposal(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.services.knowledge import KnowledgeManager
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    persistence = HarnessPersistence(db)
    workspace = tmp_path / "w_0001"
    (workspace / "memory" / "notes").mkdir(parents=True)
    manager = KnowledgeManager(workspace_dir=workspace, persistence=persistence)
    proposal = manager.propose_update(
        run_id="run_1",
        memory_target="note:attrition.md",
        source_refs=["chat:1"],
        proposed_content="Attrition is computed as leavers / avg headcount.",
    )
    assert proposal.status == "pending"
    stored = persistence.db.load_record("memory_update_proposals", "id", proposal.id)
    assert stored["memory_target"] == "note:attrition.md"


def test_apply_writes_file_and_marks_applied(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.services.knowledge import KnowledgeManager
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    persistence = HarnessPersistence(db)
    workspace = tmp_path / "w_0001"
    (workspace / "memory" / "notes").mkdir(parents=True)
    manager = KnowledgeManager(workspace_dir=workspace, persistence=persistence)
    proposal = manager.propose_update(
        run_id="run_1",
        memory_target="note:attrition.md",
        source_refs=["chat:1"],
        proposed_content="Note body.",
    )
    applied = manager.apply(proposal.id, decision="approved")
    assert applied["status"] == "applied"
    note = workspace / "memory" / "notes" / "attrition.md"
    assert note.read_text().rstrip() == "Note body."


def test_apply_blocked_by_unresolved_conflict(tmp_path):
    import pytest
    from harness.core.db import WorkspaceDb
    from harness.services.knowledge import KnowledgeManager
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    persistence = HarnessPersistence(db)
    workspace = tmp_path / "w_0001"
    (workspace / "memory" / "notes").mkdir(parents=True)
    (workspace / "memory" / "notes" / "attrition.md").write_text("old content\n")
    manager = KnowledgeManager(workspace_dir=workspace, persistence=persistence)
    proposal = manager.propose_update(
        run_id="run_1",
        memory_target="note:attrition.md",
        source_refs=["chat:1"],
        proposed_content="new content",
    )
    assert proposal.conflicts
    with pytest.raises(ValueError, match="unresolved conflicts"):
        manager.apply(proposal.id, decision="approved")


def test_external_memory_write_blocked(tmp_path):
    import pytest
    from harness.services.knowledge import MemoryWriteForbidden, guarded_external_memory_write

    workspace = tmp_path / "w_0001"
    (workspace / "memory" / "notes").mkdir(parents=True)
    with pytest.raises(MemoryWriteForbidden):
        guarded_external_memory_write(workspace, "memory/notes/sneaky.md", "bypass")
