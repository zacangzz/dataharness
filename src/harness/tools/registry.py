from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from harness.events import HarnessEvent

ToolFamily = Literal["core", "control", "analysis", "knowledge"]
ToolArgType = Literal["str", "int", "float", "bool", "path", "json"]


class ToolContext(BaseModel):
    workspace_id: str | None
    chat_id: str | None
    run_id: str | None
    has_pending_approval: bool
    has_pending_clarification: bool


class ToolArgSpec(BaseModel):
    name: str
    type: ToolArgType
    required: bool
    description: str
    example: str | None = None
    allowed_values: list[str] | None = None
    regex: str | None = None


class ToolDescriptor(BaseModel):
    name: str
    family: ToolFamily
    short_description: str
    arguments: list[ToolArgSpec] = Field(default_factory=list)


ToolHandler = Callable[[ToolContext, dict[str, Any]], AsyncIterator[HarnessEvent]]


class HarnessToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[ToolDescriptor, ToolHandler]] = {}

    def register(self, descriptor: ToolDescriptor, handler: ToolHandler) -> None:
        self._handlers[descriptor.name] = (descriptor, handler)

    def list_tools(self) -> list[ToolDescriptor]:
        return sorted((descriptor for descriptor, _ in self._handlers.values()), key=lambda d: d.name)

    def get_handler(self, name: str) -> ToolHandler:
        if name not in self._handlers:
            raise KeyError(name)
        return self._handlers[name][1]

    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._handlers:
            raise ValueError(f"unknown tool: {name}")
        descriptor, _ = self._handlers[name]
        validated: dict[str, Any] = {}
        for spec in descriptor.arguments:
            if spec.required and spec.name not in arguments:
                raise ValueError(f"missing required arg '{spec.name}' for {name}")
            if spec.name in arguments:
                value = self._coerce(spec, arguments[spec.name])
                if spec.allowed_values is not None and str(value) not in spec.allowed_values:
                    allowed = ", ".join(spec.allowed_values)
                    raise ValueError(f"invalid value for '{spec.name}' in {name}: {value!r}; expected one of {allowed}")
                if spec.regex is not None and not re.fullmatch(spec.regex, str(value)):
                    raise ValueError(f"'{spec.name}' for {name} does not match required pattern")
                validated[spec.name] = value
        return validated

    def _coerce(self, spec: ToolArgSpec, value: Any) -> Any:
        if spec.type == "json":
            return value
        if spec.type in {"str", "path"}:
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
