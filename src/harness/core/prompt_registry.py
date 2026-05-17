from __future__ import annotations

from pathlib import Path


ALLOWED_LAYER3_PROMPTS = ["compaction", "doctor", "knowledge_reconcile"]


class HarnessPromptRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def allowed_prompts(self) -> list[str]:
        return list(ALLOWED_LAYER3_PROMPTS)

    def load(self, name: str) -> str:
        if name not in ALLOWED_LAYER3_PROMPTS:
            raise ValueError(f"prompt is not a Layer 3 operational prompt: {name}")
        return (self.root / f"{name}.md").read_text()
