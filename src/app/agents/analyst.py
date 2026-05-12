from __future__ import annotations

from app.agents.prompt_packages import PromptPackageRegistry


class AnalystMode:
    def __init__(self, registry: PromptPackageRegistry) -> None:
        self.registry = registry

    def build_turn(self, user_text: str) -> dict[str, object]:
        return {
            "package": self.registry.load("analyst"),
            "user_text": user_text,
            "allowed_harness_intents": [
                "knowledge_lookup",
                "plan_analysis",
                "request_execution",
                "inspect_artifacts",
                "record_provenance",
                "respond_to_user",
                "record_gap",
            ],
        }
