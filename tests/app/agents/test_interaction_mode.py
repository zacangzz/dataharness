from pathlib import Path

from app.agents.interaction import InteractionMode
from app.agents.prompt_packages import PromptPackageRegistry


def test_interaction_mode_builds_prompt_turn_and_allowed_intents(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "interaction.md").write_text("interaction")
    (prompts_dir / "response_format.md").write_text("format")
    mode = InteractionMode(PromptPackageRegistry(prompts_dir))
    turn = mode.build_turn("what is the attrition rate?")
    assert turn["package"].mode == "interaction"
    assert "handoff_to_analyst" in turn["allowed_harness_intents"]
    assert "request_clarification" in turn["allowed_harness_intents"]
