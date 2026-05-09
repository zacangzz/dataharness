from pathlib import Path

from harness.context import ContextManager
from harness.prompt_registry import HarnessPromptRegistry


def test_context_rebuild_uses_durable_sources_not_chat_history(tmp_path: Path) -> None:
    (tmp_path / "memory" / "notes").mkdir(parents=True)
    (tmp_path / "memory" / "preferences.json").write_text('{"style":"concise"}')
    (tmp_path / "memory" / "notes" / "dataset.md").write_text("Dataset uses employee_id.")
    manager = ContextManager()
    context = manager.rebuild(
        workspace_dir=tmp_path,
        session_ledger=["run_1 step_1 completed"],
        validity_states=["employees.csv:ok"],
        chat_history=["old chat that must not be authoritative"],
    )
    assert "Dataset uses employee_id." in context["memory_notes"]
    assert context["chat_history_loaded"] is False


def test_compaction_preserves_operational_atoms_and_is_not_durable() -> None:
    manager = ContextManager()
    compacted = manager.compact(
        entries=["user asks", "tool_call: execute", "tool_output: step_result.json"],
        active_plan_id="plan_1",
        current_step_id="step_1",
        unresolved_failures=["schema_mismatch"],
    )
    assert compacted["durable"] is False
    assert compacted["active_plan_id"] == "plan_1"
    assert "tool_call: execute" in compacted["summary"]
    assert "tool_output: step_result.json" in compacted["summary"]


def test_prompt_registry_allows_only_layer3_operational_prompts(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "compaction.md").write_text("compact")
    (prompts / "doctor.md").write_text("doctor")
    (prompts / "knowledge_reconcile.md").write_text("knowledge")
    registry = HarnessPromptRegistry(prompts)
    assert registry.allowed_prompts() == ["compaction", "doctor", "knowledge_reconcile"]
    assert registry.load("doctor") == "doctor"
