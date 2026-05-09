from __future__ import annotations

from app.agents.prompt_packages import PromptPackageRegistry


class KnowledgeMode:
    def __init__(self, registry: PromptPackageRegistry) -> None:
        self.registry = registry

    def build_turn(self, user_text: str) -> dict[str, object]:
        return {
            "package": self.registry.load("knowledge"),
            "user_text": user_text,
            "allowed_harness_intents": [
                "store_workspace_knowledge",
                "update_preferences",
                "record_gap",
                "save_function_candidate",
                "request_clarification",
            ],
        }
