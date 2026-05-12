from pathlib import Path

from app.agents.interaction import InteractionMode
from app.agents.prompt_packages import PromptPackageRegistry


def test_interaction_prompt_text_instructs_model_to_emit_clarification_tool_call() -> None:
    prompts_dir = Path("src/app/agents/prompts")
    mode = InteractionMode(PromptPackageRegistry(prompts_dir))
    turn = mode.build_turn("rate")
    text = turn["package"].prompt_text.lower()
    assert "request_clarification" in text
    assert "tool_call" in text
    assert "request_clarification" in turn["allowed_harness_intents"]
