from __future__ import annotations

import hashlib
from pathlib import Path

from app.agents.types import PromptPackage
from harness.command_registry import HarnessCommandRegistry


MODE_INTENTS = {
    "interaction": [
        "answer_directly",
        "handoff_to_analyst",
        "handoff_to_knowledge",
        "request_clarification",
    ],
    "analyst": [
        "knowledge_lookup",
        "plan_analysis",
        "request_execution",
        "inspect_artifacts",
        "record_provenance",
        "respond_to_user",
    ],
    "knowledge": [
        "store_workspace_knowledge",
        "update_preferences",
        "record_gap",
        "save_function_candidate",
    ],
    "clarification": [
        "request_clarification",
    ],
}


def _tool_catalog(mode: str) -> str:
    commands = []  # HarnessCommandRegistry has no supported_commands(); tool catalog deferred to runtime
    intents = MODE_INTENTS.get(mode, [])
    command_lines = "\n".join(f"- `{command}`" for command in commands)
    intent_lines = "\n".join(f"- `{intent}`" for intent in intents)
    return "\n".join(
        [
            "Available harness tool calls:",
            "These are the only exposed harness command names. Do not invent tool names.",
            command_lines,
            "",
            f"Allowed {mode} intents:",
            intent_lines,
            "",
            "Tool call format:",
            '<tool_call>{"name":"workspace_status","arguments":{}}</tool_call>',
        ]
    )


class PromptPackageRegistry:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir

    def load(self, mode: str) -> PromptPackage:
        parts = []
        system_prompt = self.prompts_dir / "system.md"
        if system_prompt.exists():
            parts.append(system_prompt.read_text())
        parts.extend(
            [
                (self.prompts_dir / f"{mode}.md").read_text(),
                _tool_catalog(mode),
                (self.prompts_dir / "response_format.md").read_text(),
            ]
        )
        prompt_text = "\n\n".join(parts)
        package_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        return PromptPackage(
            mode=mode,
            template_version="v1",
            prompt_text=prompt_text,
            package_hash=package_hash,
        )
