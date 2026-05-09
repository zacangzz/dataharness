from __future__ import annotations

from pydantic import BaseModel


class PromptPackage(BaseModel):
    mode: str
    template_version: str
    prompt_text: str
    package_hash: str
