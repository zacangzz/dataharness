from pathlib import Path

from app.agents.knowledge import KnowledgeMode
from app.agents.prompt_packages import PromptPackageRegistry


def test_knowledge_mode_builds_prompt_turn_for_memory_capture(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "knowledge.md").write_text("knowledge")
    (prompts_dir / "response_format.md").write_text("format")
    mode = KnowledgeMode(PromptPackageRegistry(prompts_dir))
    result = mode.build_turn("remember that attrition = total leavers / average headcount")
    assert result["package"].mode == "knowledge"
    assert "knowledge_recall" in result["allowed_harness_intents"]
    assert "knowledge_propose_update" in result["allowed_harness_intents"]
    assert "store_workspace_knowledge" not in result["allowed_harness_intents"]
