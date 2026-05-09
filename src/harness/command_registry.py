from __future__ import annotations

import shlex
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from harness.events import HarnessEvent


ArgType = Literal[
    "str", "int", "float", "bool", "path",
    "chat_id", "workspace_id", "run_id", "step_id", "artifact_path",
]


class ArgSpec(BaseModel):
    name: str
    type: ArgType
    required: bool
    description: str
    example: str | None = None


class CommandContext(BaseModel):
    workspace_id: str | None
    chat_id: str | None
    run_id: str | None
    has_pending_approval: bool
    has_pending_clarification: bool


class HarnessCommandDescriptor(BaseModel):
    name: str
    slash_alias: str
    short_description: str
    arguments: list[ArgSpec] = Field(default_factory=list)
    available: bool = True
    disabled_reason: str | None = None
    affected_resource: Literal[
        "workspace", "chat", "run", "plan", "step", "artifact",
        "memory", "provenance", "doctor",
    ]
    expected_event_types: list[str] = Field(default_factory=list)
    example_usage: str


class HelpResult(BaseModel):
    commands: list[HarnessCommandDescriptor] = Field(default_factory=list)
    not_found: bool = False


CommandHandler = Callable[
    [CommandContext, dict[str, Any]],
    AsyncIterator[HarnessEvent],
]


class HarnessCommandRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[HarnessCommandDescriptor, CommandHandler]] = {}
        self._availability: dict[str, Callable[[CommandContext], tuple[bool, str | None]]] = {}

    def register(
        self,
        descriptor: HarnessCommandDescriptor,
        handler: CommandHandler,
        *,
        availability: Callable[[CommandContext], tuple[bool, str | None]] | None = None,
    ) -> None:
        self._handlers[descriptor.name] = (descriptor, handler)
        if availability is not None:
            self._availability[descriptor.name] = availability

    def list_descriptors(self, ctx: CommandContext) -> list[HarnessCommandDescriptor]:
        out: list[HarnessCommandDescriptor] = []
        for name, (desc, _) in self._handlers.items():
            available, reason = self._availability.get(
                name, lambda _c, d=desc: (d.available, d.disabled_reason)
            )(ctx)
            out.append(desc.model_copy(update={"available": available, "disabled_reason": reason}))
        return sorted(out, key=lambda d: d.name)

    def help(self, command: str | None = None) -> HelpResult:
        if command is None:
            return HelpResult(commands=[d for d, _ in self._handlers.values()], not_found=False)
        if command not in self._handlers:
            return HelpResult(commands=[], not_found=True)
        return HelpResult(commands=[self._handlers[command][0]])

    def validate(self, command: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if command not in self._handlers:
            raise ValueError(f"unknown command: {command}")
        desc, _ = self._handlers[command]
        validated: dict[str, Any] = {}
        for spec in desc.arguments:
            if spec.required and spec.name not in arguments:
                raise ValueError(f"missing required arg '{spec.name}' for {command}")
            if spec.name in arguments:
                validated[spec.name] = self._coerce(spec, arguments[spec.name])
        return validated

    def get_handler(self, command: str) -> CommandHandler:
        return self._handlers[command][1]

    def _coerce(self, spec: ArgSpec, value: Any) -> Any:
        if spec.type in {"str", "path", "chat_id", "workspace_id", "run_id", "step_id", "artifact_path"}:
            return str(value)
        if spec.type == "int":
            return int(value)
        if spec.type == "float":
            return float(value)
        if spec.type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).lower() in {"1", "true", "yes", "on"}
        return value


def parse_slash(text: str) -> tuple[str, list[str]]:
    """Positional-only slash grammar from spec §8.

    /<command> [<arg> [<arg> ...]]
    Quoted args allowed for whitespace. No named flags.
    """
    if not text.startswith("/"):
        raise ValueError("slash commands must start with '/'")
    body = text[1:].strip()
    if not body:
        raise ValueError("empty slash command")
    parts = shlex.split(body, posix=True)
    if any(p.startswith("--") or (p.startswith("-") and len(p) > 1 and not p[1].isdigit()) for p in parts[1:]):
        raise ValueError("named flags not supported in V1 slash grammar")
    return parts[0], parts[1:]
