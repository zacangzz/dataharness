from __future__ import annotations

from app.agents.prompt_packages import PromptPackageRegistry


class InteractionMode:
    def __init__(self, registry: PromptPackageRegistry) -> None:
        self.registry = registry

    def build_turn(self, user_text: str) -> dict[str, object]:
        return {
            "package": self.registry.load("interaction"),
            "user_text": user_text,
            "allowed_harness_intents": [
                "answer_directly",
                "handoff_to_analyst",
                "handoff_to_knowledge",
                "request_clarification",
            ],
        }
