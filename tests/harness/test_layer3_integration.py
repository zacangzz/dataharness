from pathlib import Path

from harness import bootstrap_workspace
from harness.context import ContextManager
from harness.control import RunStateRecord
from harness.db import WorkspaceDb
from harness.doctor import Doctor
from harness.knowledge import KnowledgeManager
from harness.orchestrator import Orchestrator
from harness.provenance import ClaimChecker


async def test_layer3_barebones_harness_can_operate_workspace(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspaces" / "w_0001")
    data_file = workspace / "data" / "employees.csv"
    data_file.write_text("employee_id\n1\n")

    db = WorkspaceDb(workspace / "state" / "workspace.db")
    db.connect()
    assert "run_records" in db.list_tables()

    knowledge = KnowledgeManager()
    knowledge.update_preferences(workspace / "memory", {"style": "concise"})
    context = ContextManager().rebuild(
        workspace_dir=workspace,
        session_ledger=[],
        validity_states=[],
        chat_history=["not authoritative"],
    )
    assert context["preferences"] == {"style": "concise"}

    doctor_result = Doctor().check_source_file(
        data_file,
        stored_size=None,
        stored_mtime_ns=None,
        stored_fingerprint=None,
    )
    assert doctor_result["validity_status"] == "ok"

    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    orch = Orchestrator(app_root=tmp_path)
    events = [e async for e in orch.handle_direct_command(state, command="workspace_status", arguments={})]
    assert any(e.event_name == "CommandCompleted" for e in events)

    claims = ClaimChecker().check_claims(
        [{"text": "Employee file was inspected", "evidence_refs": ["data/employees.csv"]}]
    )
    assert claims["unsupported"] == []
