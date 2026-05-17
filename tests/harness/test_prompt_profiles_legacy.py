from pathlib import Path

from harness.orchestrator import Orchestrator
from harness.services.prompt_profiles import PromptProfileRegistry


def test_prompt_registry_hashes_prompt_package_contents(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "interaction.md").write_text("hello")
    (prompts_dir / "response_format.md").write_text("format")
    registry = PromptProfileRegistry(prompts_dir)
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

    package = PromptProfileRegistry(prompts_dir).load("interaction")

    assert package.prompt_text.startswith("shared data analysis identity")
    assert "interaction" in package.prompt_text
    assert "format" in package.prompt_text


def test_interaction_prompt_defines_data_analysis_identity_and_capability_answer() -> None:
    package = PromptProfileRegistry(Path("src/harness/prompts")).load("interaction")
    text = package.prompt_text.lower()

    assert "data analysis" in text
    assert "data science" in text
    assert "what can you do" in text
    assert "request_clarification" in text
    assert "tool_call" in text
    assert "making casual conversation" not in text
    assert "large language model" not in text


def test_prompt_package_includes_mode_tools_for_interaction() -> None:
    package = PromptProfileRegistry(Path("src/harness/prompts")).load("interaction")
    text = package.prompt_text

    assert "Allowed interaction tool names" in text
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
    package = PromptProfileRegistry(
        Path("src/harness/prompts"),
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
    assert "plan_analysis(" not in text
    assert "`request_execution(" not in text
    assert "workspace_status" not in text
    assert "workspace_inventory" not in text


def test_prompt_package_allowed_intents_are_registered_tool_names(tmp_path) -> None:
    orch = Orchestrator(app_root=tmp_path)
    package = PromptProfileRegistry(
        Path("src/harness/prompts"),
        tool_registry=orch.tool_registry,
    ).load("analyst")
    text = package.prompt_text

    assert "Allowed analyst tool names" in text
    assert "`analysis_plan`" in text
    assert "`analysis_request_execution`" in text
    assert "`plan_analysis`" not in text
    assert "`request_execution`" not in text


def test_analyst_prompt_emits_code_free_plan() -> None:
    package = PromptProfileRegistry(Path("src/harness/prompts")).load("analyst")
    text = package.prompt_text

    # Two-step: the model emits a CODE-FREE plan; the harness writes the code.
    assert "do NOT write any code" in text
    assert '"code_lines":["import pandas as pd' not in text  # old code example gone
    assert '"steps":[{"purpose"' in text
    assert "declared_inputs" in text and "expected_outputs" in text
