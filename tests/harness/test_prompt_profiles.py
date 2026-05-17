from pathlib import Path

from harness.orchestrator import Orchestrator
from harness.services.prompt_profiles import PromptProfileRegistry


def test_profile_package_advertises_tools_not_commands(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    reg = PromptProfileRegistry(
        Path("src/harness/prompts"),
        tool_registry=orch.tool_registry,
    )
    text = reg.load("interaction").prompt_text
    assert "file_read" in text
    assert "handoff_to_analyst" in text
    assert "list_files" not in text
    assert "doctor(" not in text


def test_profile_package_hash_stable(tmp_path):
    reg = PromptProfileRegistry(Path("src/harness/prompts"))
    a = reg.load("analyst")
    b = reg.load("analyst")
    assert a.package_hash == b.package_hash
