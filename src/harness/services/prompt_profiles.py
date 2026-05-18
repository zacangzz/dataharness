from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from harness.tools.registry import HarnessToolRegistry


class RenderedPrompt(BaseModel):
    mode: str
    template_version: str
    prompt_text: str
    package_hash: str


MODE_TOOL_NAMES = {
    "interaction": [
        "answer_directly",
        "file_read",
        "handoff_to_analyst",
        "handoff_to_knowledge",
        "request_clarification",
    ],
    "analyst": [
        "analysis_plan",
        "analysis_request_execution",
        "file_read",
        "knowledge_recall",
        "respond_to_user",
    ],
    "knowledge": [
        "knowledge_recall",
        "knowledge_propose_update",
        "respond_to_user",
    ],
    "clarification": [
        "request_clarification",
    ],
}


def _tool_catalog(mode: str, tool_registry: HarnessToolRegistry | None) -> str:
    if tool_registry is None:
        tool_lines = "- (no harness tools available)"
        tool_names = MODE_TOOL_NAMES.get(mode, [])
    else:
        descs = tool_registry.list_tools()
        lines = []
        for desc in descs:
            args_parts = []
            for arg in desc.arguments:
                suffix = "" if arg.required else "?"
                args_parts.append(f"{arg.name}:{arg.type}{suffix}")
            args_str = ", ".join(args_parts)
            lines.append(f"- `{desc.name}({args_str})` — {desc.short_description}")
        tool_lines = "\n".join(lines) or "- (no harness tools available)"
        registered_names = {desc.name for desc in descs}
        tool_names = [name for name in MODE_TOOL_NAMES.get(mode, []) if name in registered_names]
    allowed_lines = "\n".join(f"- `{name}`" for name in tool_names) or "- (no mode-specific tools)"
    return "\n".join(
        [
            "Available harness tool calls:",
            "These are the only exposed harness tool names. Do not invent tool names.",
            tool_lines,
            "",
            f"Allowed {mode} tool names:",
            allowed_lines,
            "",
            "Tool call format (one per emission):",
            '<tool_call>{"name":"file_read","arguments":{"operation":"list"}}</tool_call>',
            '<tool_call>{"name":"file_read","arguments":{"operation":"inspect","path":"data/sales.csv"}}</tool_call>',
        ]
    )


class PromptProfileRegistry:
    def __init__(
        self,
        prompts_dir: Path,
        *,
        tool_registry: HarnessToolRegistry | None = None,
    ) -> None:
        self.prompts_dir = prompts_dir
        self.tool_registry = tool_registry
        self._cache: dict[str, RenderedPrompt] = {}

    def load(self, mode: str) -> RenderedPrompt:
        cached = self._cache.get(mode)
        if cached is not None:
            return cached
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
        package = RenderedPrompt(
            mode=mode,
            template_version="v1",
            prompt_text=prompt_text,
            package_hash=package_hash,
        )
        self._cache[mode] = package
        return package
