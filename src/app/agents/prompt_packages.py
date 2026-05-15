from __future__ import annotations

import hashlib
from pathlib import Path

from app.agents.types import PromptPackage
from harness.tools.registry import HarnessToolRegistry


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


def _tool_catalog(mode: str, tool_registry: HarnessToolRegistry | None) -> str:
    if tool_registry is None:
        tool_lines = "- (no harness tools available)"
    else:
        lines = []
        for desc in tool_registry.list_tools():
            args_parts = []
            for arg in desc.arguments:
                suffix = "" if arg.required else "?"
                args_parts.append(f"{arg.name}:{arg.type}{suffix}")
            args_str = ", ".join(args_parts)
            lines.append(f"- `{desc.name}({args_str})` — {desc.short_description}")
        tool_lines = "\n".join(lines) or "- (no harness tools available)"
    intents = MODE_INTENTS.get(mode, [])
    intent_lines = "\n".join(f"- `{intent}`" for intent in intents)
    return "\n".join(
        [
            "Available harness tool calls:",
            "These are the only exposed harness tool names. Do not invent tool names.",
            tool_lines,
            "",
            f"Allowed {mode} intents:",
            intent_lines,
            "",
            "Tool call format (one per emission):",
            '<tool_call>{"name":"file_read","arguments":{"operation":"list"}}</tool_call>',
            '<tool_call>{"name":"file_read","arguments":{"operation":"inspect","path":"data/sales.csv"}}</tool_call>',
        ]
    )


class PromptPackageRegistry:
    def __init__(
        self,
        prompts_dir: Path,
        *,
        tool_registry: HarnessToolRegistry | None = None,
    ) -> None:
        self.prompts_dir = prompts_dir
        self.tool_registry = tool_registry

    def load(self, mode: str) -> PromptPackage:
        parts = []
        system_prompt = self.prompts_dir / "system.md"
        if system_prompt.exists():
            parts.append(system_prompt.read_text())
        parts.extend(
            [
                (self.prompts_dir / f"{mode}.md").read_text(),
                _tool_catalog(mode, self.tool_registry),
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
