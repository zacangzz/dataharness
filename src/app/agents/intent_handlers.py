from __future__ import annotations

import json
import re
from typing import Any, Protocol


class KnowledgeManagerProtocol(Protocol):
    def propose_update(
        self,
        *,
        memory_target: str,
        source_refs: list[str],
        proposed_content: str,
        conflicts: list[str] | None = None,
    ) -> Any: ...


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-") or "untitled"


def handle_knowledge_intent(manager: KnowledgeManagerProtocol, *, tool_call: dict[str, Any]) -> Any:
    name = tool_call.get("name")
    arguments = tool_call.get("arguments") or {}
    source_refs = list(arguments.get("source_refs") or [])

    if name == "store_workspace_knowledge":
        target = f"memory/notes/{_slug(arguments['title'])}.md"
        return manager.propose_update(
            memory_target=target,
            source_refs=source_refs,
            proposed_content=arguments["content"],
        )
    if name == "update_preferences":
        return manager.propose_update(
            memory_target="memory/preferences.json",
            source_refs=source_refs,
            proposed_content=json.dumps({arguments["key"]: arguments["value"]}),
        )
    if name == "record_gap":
        target = f"memory/notes/gaps/{_slug(arguments['description'])[:40]}.md"
        return manager.propose_update(
            memory_target=target,
            source_refs=source_refs,
            proposed_content=arguments["description"],
        )
    if name == "save_function_candidate":
        target = f"memory/functions/{_slug(arguments['name'])}.py"
        return manager.propose_update(
            memory_target=target,
            source_refs=source_refs,
            proposed_content=arguments["code"],
        )
    raise ValueError(f"unknown knowledge intent: {name}")
