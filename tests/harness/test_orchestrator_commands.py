from datetime import UTC, datetime

import pytest

from harness.services.chat import ChatMessage
from harness.core.command_registry import CommandContext
from harness.exceptions import RunAlreadyActive, WorkspaceSwitchBlocked
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(runtime=None, app_root=tmp_path)


async def test_list_commands_includes_required_set(orch):
    descs = await orch.list_commands(CommandContext(
        workspace_id="w", chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    ))
    names = {d.name for d in descs}
    required = {
        "doctor", "compact", "cancel_run", "retry_step", "revise_goal",
        "stop_after_current_step", "rerun_step", "challenge_conclusion",
        "mark_result_trusted", "mark_result_invalidated", "inspect_artifact",
        "memory_review", "provenance_inspect", "switch_workspace",
        "workspace_status", "workspace_inventory", "validity_inspect", "help",
        "create_chat", "list_chats", "view_chat", "resume_chat", "delete_chat",
    }
    assert required.issubset(names), required - names


async def test_help_returns_full_descriptor(orch):
    res = await orch.help("doctor")
    assert res.not_found is False
    assert res.commands[0].name == "doctor"


async def test_help_unknown_returns_not_found(orch):
    res = await orch.help("nope")
    assert res.not_found is True


async def test_handle_direct_command_doctor_emits_full_sequence(orch, tmp_path):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    events = [e async for e in orch.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    names = [e.event_name for e in events]
    assert names[0] == "CommandStarted"
    assert "DoctorStarted" in names
    assert "DoctorReportReady" in names
    assert names[-1] == "CommandCompleted"


async def test_activate_workspace_blocked_when_run_active(orch, tmp_path):
    await orch.create_workspace("w1")
    await orch.create_workspace("w2")
    orch._active_run_id = "fake_run"
    with pytest.raises(WorkspaceSwitchBlocked):
        await orch.activate_workspace("w2", force=False)
    orch._active_run_id = None


async def test_compact_context_command_removed(orch):
    res = await orch.help("compact_context")
    assert res.not_found is True


async def test_compact_command_preserves_implicit_chat_context(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    summary = await orch.create_chat(workspace_id="w1", title=None)

    events = [e async for e in orch.handle_direct_command(
        state, command="compact", arguments={"chat_id": summary.chat_id},
    )]

    compact_events = [e for e in events if e.event_name == "ChatHistoryCompacted"]
    completed = [e for e in events if e.event_name == "CommandCompleted"][0]
    assert compact_events
    assert compact_events[0].chat_id == summary.chat_id
    assert completed.chat_id == summary.chat_id
    assert "error" not in completed.result


async def test_manual_compact_replaces_all_chat_messages(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    summary = await orch.create_chat(workspace_id="w1", title=None)
    for index in range(5):
        await orch.chat_store.append_message(summary.chat_id, ChatMessage(
            message_id=f"m{index}",
            role="user" if index % 2 == 0 else "assistant",
            text=f"message {index}",
            ts=datetime.now(UTC),
            turn_id=None,
            active_mode="interaction",
            token_estimate=2,
        ))

    events = [e async for e in orch.handle_direct_command(
        state, command="compact", arguments={"chat_id": summary.chat_id},
    )]

    record = await orch.view_chat(summary.chat_id)
    completed = [
        e for e in events
        if e.event_name == "ChatHistoryCompacted" and e.status == "completed"
    ][0]
    assert record.message_count == 1
    assert record.messages[0].role == "compacted_summary"
    assert completed.replaced_turn_count == 5


async def test_create_chat_command_actually_creates(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    events = [e async for e in orch.handle_direct_command(state, command="create_chat", arguments={"title": "t"})]
    completed = [e for e in events if e.event_name == "CommandCompleted"][0]
    assert "chat" in completed.result
    assert completed.result["chat"]["title"] == "t"


async def test_list_chats_command_returns_chats(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    await orch.create_chat(workspace_id="w1", title="a")
    events = [e async for e in orch.handle_direct_command(state, command="list_chats", arguments={})]
    completed = [e for e in events if e.event_name == "CommandCompleted"][0]
    assert len(completed.result["chats"]) == 1


async def test_switch_workspace_command_activates_workspace(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    await orch.create_workspace("w2")

    events = [e async for e in orch.handle_direct_command(
        state, command="switch_workspace", arguments={"workspace_id": "w2"},
    )]

    completed = [e for e in events if e.event_name == "CommandCompleted"][0]
    assert completed.command == "switch_workspace"
    assert completed.result["snapshot"]["workspace_id"] == "w2"


async def test_cancel_run_command_no_active_run_reports_error(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    events = [e async for e in orch.handle_direct_command(
        state, command="cancel_run", arguments={"reason": "user"},
    )]
    names = [e.event_name for e in events]
    assert names[0] == "CommandStarted"
    assert names[-1] == "CommandCompleted"
    assert "TurnCancelled" not in names
    completed = events[-1]
    assert completed.command == "cancel_run"
    assert completed.result.get("error") == "no active run"


async def test_cancel_run_command_cancels_active_run(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    orch._active_run_id = "run_abc"
    import asyncio
    orch._cancel_flags["run_abc"] = asyncio.Event()
    try:
        events = [e async for e in orch.handle_direct_command(
            state, command="cancel_run", arguments={"reason": "user_request"},
        )]
    finally:
        orch._active_run_id = None
        orch._cancel_flags.pop("run_abc", None)
    names = [e.event_name for e in events]
    assert names[0] == "CommandStarted"
    assert "TurnCancelled" in names
    assert names[-1] == "CommandCompleted"
    cancelled = next(e for e in events if e.event_name == "TurnCancelled")
    assert cancelled.run_id == "run_abc"
    assert cancelled.reason == "user_request"
    completed = events[-1]
    assert completed.result.get("run_id") == "run_abc"
    assert completed.result.get("reason") == "user_request"


async def test_cancel_run_descriptor_marked_available(orch):
    res = await orch.help("cancel_run")
    assert res.not_found is False
    desc = res.commands[0]
    assert desc.available is True
    assert desc.disabled_reason is None
    assert {a.name for a in desc.arguments} == {"reason"}


async def test_memory_review_command_lists_proposals(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence
    from harness.services.knowledge import KnowledgeManager

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    workspace_dir = orch.workspace_manager.workspaces_dir / "w1"
    km = KnowledgeManager(workspace_dir=workspace_dir, persistence=persistence)
    p1 = km.propose_update(run_id="r1", memory_target="note:a.md", source_refs=["src"], proposed_content="alpha")
    p2 = km.propose_update(run_id="r2", memory_target="note:b.md", source_refs=["src"], proposed_content="beta")

    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="memory_review", arguments={},
    )]
    names = [e.event_name for e in events]
    assert names[0] == "CommandStarted"
    assert names[-1] == "CommandCompleted"
    completed = events[-1]
    proposals = completed.result["proposals"]
    ids = {p["id"] for p in proposals}
    assert {p1.id, p2.id}.issubset(ids)
    assert completed.result["count"] == 2


async def test_memory_review_command_filters_by_status(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence
    from harness.services.knowledge import KnowledgeManager

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    workspace_dir = orch.workspace_manager.workspaces_dir / "w1"
    km = KnowledgeManager(workspace_dir=workspace_dir, persistence=persistence)
    km.propose_update(run_id="r1", memory_target="note:a.md", source_refs=[], proposed_content="alpha")
    p2 = km.propose_update(run_id="r2", memory_target="note:b.md", source_refs=[], proposed_content="beta")
    rec = persistence.db.load_record("memory_update_proposals", "id", p2.id)
    rec["status"] = "applied"
    persistence.db.save_record("memory_update_proposals", "id", p2.id, rec)

    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="memory_review", arguments={"status": "applied"},
    )]
    completed = events[-1]
    proposals = completed.result["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["id"] == p2.id


async def test_memory_review_descriptor_marked_available(orch):
    res = await orch.help("memory_review")
    desc = res.commands[0]
    assert desc.available is True
    assert desc.disabled_reason is None
    assert {a.name for a in desc.arguments} == {"status"}


async def test_inspect_artifact_returns_file_metadata(tmp_path):
    orch = Orchestrator(runtime=None, app_root=tmp_path)
    await orch.create_workspace("w1")
    workspace_dir = orch.workspace_manager.workspaces_dir / "w1"
    artifact = workspace_dir / "artifacts" / "out.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("hello world\n")

    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="inspect_artifact", arguments={"path": "artifacts/out.txt"},
    )]
    completed = events[-1]
    assert completed.command == "inspect_artifact"
    assert completed.result["exists"] is True
    assert completed.result["path"] == "artifacts/out.txt"
    assert completed.result["size_bytes"] == 12
    assert "hello world" in completed.result["content_head"]


async def test_inspect_artifact_rejects_path_escape(tmp_path):
    orch = Orchestrator(runtime=None, app_root=tmp_path)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="inspect_artifact", arguments={"path": "../escape.txt"},
    )]
    completed = events[-1]
    assert "error" in completed.result
    assert "outside workspace" in completed.result["error"].lower()


async def test_inspect_artifact_missing_file_reports_not_exists(tmp_path):
    orch = Orchestrator(runtime=None, app_root=tmp_path)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="inspect_artifact", arguments={"path": "artifacts/missing.txt"},
    )]
    completed = events[-1]
    assert completed.result["exists"] is False


async def test_inspect_artifact_descriptor_marked_available(orch):
    res = await orch.help("inspect_artifact")
    desc = res.commands[0]
    assert desc.available is True
    assert {a.name for a in desc.arguments} == {"path"}


async def test_provenance_inspect_returns_lineage(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "lineage_records", "artifact_path", "artifacts/a.csv",
        {
            "id": "lineage:env1:artifacts/a.csv",
            "run_id": "r1", "step_id": "s1",
            "artifact_path": "artifacts/a.csv",
            "source_envelope_id": "env1",
            "source_files": {"data/in.csv": "sha256:abc"},
            "executed_code_hash": "sha256:code",
            "fingerprint_id": "sha256:fp",
            "validity_id": "validity:artifacts/a.csv:ok",
        },
    )

    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="provenance_inspect", arguments={"path": "artifacts/a.csv"},
    )]
    completed = events[-1]
    assert completed.result["found"] is True
    lineage = completed.result["lineage"]
    assert lineage["artifact_path"] == "artifacts/a.csv"
    assert lineage["run_id"] == "r1"
    assert lineage["fingerprint_id"] == "sha256:fp"


async def test_provenance_inspect_missing_returns_not_found(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="provenance_inspect", arguments={"path": "artifacts/nope.csv"},
    )]
    completed = events[-1]
    assert completed.result["found"] is False


async def test_provenance_inspect_descriptor_marked_available(orch):
    res = await orch.help("provenance_inspect")
    desc = res.commands[0]
    assert desc.available is True
    assert {a.name for a in desc.arguments} == {"path"}


async def test_validity_inspect_returns_all_records(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "validity_state", "id", "validity:artifacts/a.csv:ok",
        {"id": "validity:artifacts/a.csv:ok", "subject_id": "artifacts/a.csv",
         "subject_kind": "artifact", "status": "ok"},
    )
    persistence.db.save_record(
        "validity_state", "id", "validity:artifacts/b.csv:stale",
        {"id": "validity:artifacts/b.csv:stale", "subject_id": "artifacts/b.csv",
         "subject_kind": "artifact", "status": "stale"},
    )
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="validity_inspect", arguments={},
    )]
    completed = events[-1]
    assert completed.command == "validity_inspect"
    assert completed.result["count"] == 2
    assert {r["status"] for r in completed.result["records"]} == {"ok", "stale"}


async def test_validity_inspect_filters_by_subject_id(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "validity_state", "id", "validity:artifacts/a.csv:ok",
        {"id": "validity:artifacts/a.csv:ok", "subject_id": "artifacts/a.csv",
         "subject_kind": "artifact", "status": "ok"},
    )
    persistence.db.save_record(
        "validity_state", "id", "validity:artifacts/b.csv:stale",
        {"id": "validity:artifacts/b.csv:stale", "subject_id": "artifacts/b.csv",
         "subject_kind": "artifact", "status": "stale"},
    )
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="validity_inspect", arguments={"subject_id": "artifacts/a.csv"},
    )]
    completed = events[-1]
    assert completed.result["count"] == 1
    assert completed.result["records"][0]["status"] == "ok"
    assert completed.result["subject_id_filter"] == "artifacts/a.csv"


async def test_validity_inspect_descriptor_marked_available(orch):
    res = await orch.help("validity_inspect")
    desc = res.commands[0]
    assert desc.available is True
    assert {a.name for a in desc.arguments} == {"subject_id"}


async def test_mark_result_trusted_writes_validity_record(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "step_records", "id", "step_42",
        {"id": "step_42", "workspace_id": "w1", "plan_id": "p", "step_order": 1,
         "purpose": "x", "kind": "code"},
    )
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="mark_result_trusted",
        arguments={"step_id": "step_42", "reason": "spot-checked output"},
    )]
    completed = events[-1]
    assert completed.command == "mark_result_trusted"
    assert completed.result["step_id"] == "step_42"
    assert completed.result["status"] == "revalidated"
    records = persistence.db.list_records("validity_state")
    assert len(records) == 1
    rec = records[0]
    assert rec["subject_id"] == "step_42"
    assert rec["subject_kind"] == "step"
    assert rec["status"] == "revalidated"
    assert rec["reason"] == "spot-checked output"


async def test_mark_result_trusted_requires_step_id(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    with pytest.raises(ValueError, match="step_id"):
        async for _ in orch.handle_direct_command(
            state, command="mark_result_trusted", arguments={},
        ):
            pass


async def test_mark_result_trusted_rejects_unknown_step(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="mark_result_trusted",
        arguments={"step_id": "ghost_step"},
    )]
    completed = events[-1]
    assert "error" in completed.result
    assert "ghost_step" in completed.result["error"]
    records = persistence.db.list_records("validity_state")
    assert records == []


async def test_mark_result_trusted_accepts_known_step(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "step_records", "id", "step_known",
        {"id": "step_known", "workspace_id": "w1", "plan_id": "plan_1",
         "step_order": 1, "purpose": "x", "kind": "code"},
    )
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="mark_result_trusted",
        arguments={"step_id": "step_known"},
    )]
    completed = events[-1]
    assert completed.result["step_id"] == "step_known"
    assert completed.result["status"] == "revalidated"


async def test_mark_result_trusted_descriptor_marked_available(orch):
    res = await orch.help("mark_result_trusted")
    desc = res.commands[0]
    assert desc.available is True
    arg_names = {a.name for a in desc.arguments}
    assert "step_id" in arg_names


async def test_mark_result_invalidated_writes_validity_record(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "step_records", "id", "step_99",
        {"id": "step_99", "workspace_id": "w1", "plan_id": "p", "step_order": 1,
         "purpose": "x", "kind": "code"},
    )
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="mark_result_invalidated",
        arguments={"step_id": "step_99", "reason": "input data changed upstream"},
    )]
    completed = events[-1]
    assert completed.result["step_id"] == "step_99"
    assert completed.result["status"] == "needs_review"
    records = persistence.db.list_records("validity_state")
    assert len(records) == 1
    rec = records[0]
    assert rec["subject_id"] == "step_99"
    assert rec["subject_kind"] == "step"
    assert rec["status"] == "needs_review"
    assert rec["reason"] == "input data changed upstream"


async def test_mark_result_invalidated_overwrites_prior_trusted(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "step_records", "id", "s1",
        {"id": "s1", "workspace_id": "w1", "plan_id": "p", "step_order": 1,
         "purpose": "x", "kind": "code"},
    )
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    [e async for e in orch.handle_direct_command(
        state, command="mark_result_trusted", arguments={"step_id": "s1"},
    )]
    [e async for e in orch.handle_direct_command(
        state, command="mark_result_invalidated", arguments={"step_id": "s1"},
    )]
    records = persistence.db.list_records("validity_state")
    assert len(records) == 1
    assert records[0]["status"] == "needs_review"


async def test_mark_result_invalidated_descriptor_marked_available(orch):
    res = await orch.help("mark_result_invalidated")
    desc = res.commands[0]
    assert desc.available is True
    arg_names = {a.name for a in desc.arguments}
    assert "step_id" in arg_names


async def test_challenge_conclusion_writes_review_proposal(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="challenge_conclusion",
        arguments={"target": "run_42", "reason": "sample size too small"},
    )]
    completed = events[-1]
    assert completed.command == "challenge_conclusion"
    assert completed.result["target"] == "run_42"
    records = persistence.db.list_records("review_proposals")
    assert len(records) == 1
    rec = records[0]
    assert rec["kind"] == "challenge_conclusion"
    assert rec["target"] == "run_42"
    assert rec["reason"] == "sample size too small"
    assert rec["status"] == "open"


async def test_challenge_conclusion_descriptor_marked_available(orch):
    res = await orch.help("challenge_conclusion")
    desc = res.commands[0]
    assert desc.available is True
    arg_names = {a.name for a in desc.arguments}
    assert {"target", "reason"} <= arg_names


async def test_challenge_conclusion_records_unique_proposals(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    [e async for e in orch.handle_direct_command(
        state, command="challenge_conclusion",
        arguments={"target": "run_a", "reason": "r1"},
    )]
    [e async for e in orch.handle_direct_command(
        state, command="challenge_conclusion",
        arguments={"target": "run_b", "reason": "r2"},
    )]
    records = persistence.db.list_records("review_proposals")
    assert len(records) == 2
    assert {r["target"] for r in records} == {"run_a", "run_b"}


async def test_stop_after_current_step_marks_active_run(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    orch._active_run_id = "run_abc"
    events = [e async for e in orch.handle_direct_command(
        state, command="stop_after_current_step",
        arguments={"reason": "user requested graceful stop"},
    )]
    completed = events[-1]
    assert completed.command == "stop_after_current_step"
    assert completed.result["run_id"] == "run_abc"
    assert completed.result["status"] == "stop_requested"
    assert "run_abc" in orch._stop_after_step_run_ids


async def test_stop_after_current_step_with_explicit_run_id(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    events = [e async for e in orch.handle_direct_command(
        state, command="stop_after_current_step",
        arguments={"run_id": "run_xyz"},
    )]
    completed = events[-1]
    assert completed.result["run_id"] == "run_xyz"
    assert "run_xyz" in orch._stop_after_step_run_ids


async def test_stop_after_current_step_no_active_run_returns_error(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")
    orch._active_run_id = None
    events = [e async for e in orch.handle_direct_command(
        state, command="stop_after_current_step", arguments={},
    )]
    completed = events[-1]
    assert "error" in completed.result
    assert orch._stop_after_step_run_ids == set()


async def test_stop_after_current_step_descriptor_marked_available(orch):
    res = await orch.help("stop_after_current_step")
    desc = res.commands[0]
    assert desc.available is True


async def test_revise_goal_updates_plan_record(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "plan_records", "id", "plan_1",
        {"id": "plan_1", "workspace_id": "w1", "run_id": "r1",
         "goal": "old goal", "steps": [], "requires_code_execution": False},
    )
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="revise_goal",
        arguments={"plan_id": "plan_1", "new_goal": "refined goal text"},
    )]
    completed = events[-1]
    assert completed.command == "revise_goal"
    assert completed.result["plan_id"] == "plan_1"
    assert completed.result["new_goal"] == "refined goal text"
    assert completed.result["previous_goal"] == "old goal"
    rec = persistence.db.load_record("plan_records", "id", "plan_1")
    assert rec["goal"] == "refined goal text"


async def test_revise_goal_missing_plan_returns_error(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="revise_goal",
        arguments={"plan_id": "missing", "new_goal": "x"},
    )]
    completed = events[-1]
    assert "error" in completed.result


async def test_revise_goal_appends_audit_record(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    persistence.db.save_record(
        "plan_records", "id", "plan_2",
        {"id": "plan_2", "workspace_id": "w1", "run_id": "r1",
         "goal": "v1", "steps": [], "requires_code_execution": False},
    )
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    [e async for e in orch.handle_direct_command(
        state, command="revise_goal",
        arguments={"plan_id": "plan_2", "new_goal": "v2"},
    )]
    history = persistence.db.list_records("run_state_history")
    revisions = [r for r in history if r.get("event") == "goal_revised"]
    assert len(revisions) == 1
    assert revisions[0]["plan_id"] == "plan_2"
    assert revisions[0]["previous_goal"] == "v1"
    assert revisions[0]["new_goal"] == "v2"


async def test_revise_goal_descriptor_marked_available(orch):
    res = await orch.help("revise_goal")
    desc = res.commands[0]
    assert desc.available is True
    arg_names = {a.name for a in desc.arguments}
    assert {"plan_id", "new_goal"} <= arg_names


async def test_retry_step_records_request(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="retry_step",
        arguments={"step_id": "step_5", "reason": "transient timeout"},
    )]
    completed = events[-1]
    assert completed.command == "retry_step"
    assert completed.result["step_id"] == "step_5"
    assert completed.result["action"] == "retry"
    assert orch._step_action_requests["step_5"] == "retry"
    records = persistence.db.list_records("step_action_history")
    assert len(records) == 1
    assert records[0]["action"] == "retry"
    assert records[0]["step_id"] == "step_5"
    assert records[0]["reason"] == "transient timeout"


async def test_retry_step_descriptor_marked_available(orch):
    res = await orch.help("retry_step")
    desc = res.commands[0]
    assert desc.available is True
    assert "step_id" in {a.name for a in desc.arguments}


async def test_rerun_step_records_request(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in orch.handle_direct_command(
        state, command="rerun_step",
        arguments={"step_id": "step_7", "reason": "force fresh fingerprint"},
    )]
    completed = events[-1]
    assert completed.result["step_id"] == "step_7"
    assert completed.result["action"] == "rerun"
    assert orch._step_action_requests["step_7"] == "rerun"
    records = persistence.db.list_records("step_action_history")
    assert len(records) == 1
    assert records[0]["action"] == "rerun"


async def test_rerun_step_descriptor_marked_available(orch):
    res = await orch.help("rerun_step")
    desc = res.commands[0]
    assert desc.available is True


async def test_rerun_overrides_retry_request_for_same_step(tmp_path):
    from harness.core.db import WorkspaceDb
    from harness.core.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    orch = Orchestrator(runtime=None, app_root=tmp_path, persistence=persistence)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    [e async for e in orch.handle_direct_command(
        state, command="retry_step", arguments={"step_id": "s1"},
    )]
    [e async for e in orch.handle_direct_command(
        state, command="rerun_step", arguments={"step_id": "s1"},
    )]
    assert orch._step_action_requests["s1"] == "rerun"
    records = persistence.db.list_records("step_action_history")
    assert len(records) == 2
    assert {r["action"] for r in records} == {"retry", "rerun"}


async def test_workspace_status_command_returns_snapshot(orch):
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await orch.create_workspace("w1")

    events = [e async for e in orch.handle_direct_command(
        state, command="workspace_status", arguments={},
    )]

    completed = [e for e in events if e.event_name == "CommandCompleted"][0]
    assert completed.command == "workspace_status"
    assert completed.result["snapshot"]["workspace_id"] == "w1"
