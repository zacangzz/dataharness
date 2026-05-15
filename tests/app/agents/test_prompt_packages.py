from pathlib import Path

from app.agents.prompt_packages import PromptPackageRegistry
from harness.orchestrator import Orchestrator


def test_prompt_registry_hashes_prompt_package_contents(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "interaction.md").write_text("hello")
    (prompts_dir / "response_format.md").write_text("format")
    registry = PromptPackageRegistry(prompts_dir)
    package = registry.load("interaction")
    assert package.mode == "interaction"
    assert len(package.package_hash) == 64
    assert "format" in package.prompt_text


def test_prompt_registry_includes_shared_system_prompt_when_present(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system.md").write_text("shared data analysis identity")
    (prompts_dir / "interaction.md").write_text("interaction")
    (prompts_dir / "response_format.md").write_text("format")

    package = PromptPackageRegistry(prompts_dir).load("interaction")

    assert package.prompt_text.startswith("shared data analysis identity")
    assert "interaction" in package.prompt_text
    assert "format" in package.prompt_text


def test_interaction_prompt_defines_data_analysis_identity_and_capability_answer() -> None:
    package = PromptPackageRegistry(Path("src/app/agents/prompts")).load("interaction")
    text = package.prompt_text.lower()

    assert "data analysis" in text
    assert "data science" in text
    assert "what can you do" in text
    assert "request_clarification" in text
    assert "tool_call" in text
    assert "making casual conversation" not in text
    assert "large language model" not in text


def test_prompt_package_includes_mode_intents_for_interaction() -> None:
    package = PromptPackageRegistry(Path("src/app/agents/prompts")).load("interaction")
    text = package.prompt_text

    assert "Allowed interaction intents" in text
    assert "`handoff_to_analyst`" in text
    assert "`handoff_to_knowledge`" in text
    assert "`request_clarification`" in text


def test_prompt_package_advertises_tool_registry_not_commands(tmp_path) -> None:
    """The tool catalog is now built from the HarnessToolRegistry, so registered
    tools (file_read, control intents) appear and harness commands
    (doctor/compact) no longer do.

    NOTE: `interaction.md` body still mentions the old list_files/inspect_file/
    read_file names; rewriting the prompt body to use `file_read` is Task 5.
    This test asserts only on the registry-driven catalog behaviour Task 4 owns.
    """
    orch = Orchestrator(app_root=tmp_path)
    package = PromptPackageRegistry(
        Path("src/app/agents/prompts"),
        tool_registry=orch.tool_registry,
    ).load("interaction")
    text = package.prompt_text

    # Registry-driven catalog advertises the registered tools.
    assert "file_read" in text
    assert "handoff_to_analyst" in text
    assert "answer_directly" in text

    # Harness commands are no longer surfaced as runtime-callable tool sigs.
    assert "doctor(" not in text
    assert "compact(" not in text


def test_analyst_prompt_prefers_code_lines_for_plan_analysis() -> None:
    package = PromptPackageRegistry(Path("src/app/agents/prompts")).load("analyst")
    text = package.prompt_text

    assert '"code_lines":["import pandas as pd","from pathlib import Path"' in text
    assert "Use `code_lines` instead of a multi-line `code` string" in text
