from pathlib import Path

from app.agents.analyst import AnalystMode
from app.agents.prompt_packages import PromptPackageRegistry


def test_analyst_mode_builds_prompt_turn_with_harness_intents(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "analyst.md").write_text("analyst")
    (prompts_dir / "response_format.md").write_text("format")
    mode = AnalystMode(PromptPackageRegistry(prompts_dir))
    result = mode.build_turn("calculate attrition rate")
    assert result["package"].mode == "analyst"
    assert "plan_analysis" in result["allowed_harness_intents"]
    assert "inspect_artifacts" in result["allowed_harness_intents"]
