from __future__ import annotations

from typing import TYPE_CHECKING

from harness.core.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_chat_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    for n, args_spec, resource in [
        ("create_chat", [ArgSpec(name="title", type="str", required=False, description="title", example=None)], "chat"),
        ("list_chats", [], "chat"),
        ("view_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
        ("resume_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
        ("delete_chat", [ArgSpec(name="chat_id", type="chat_id", required=True, description="chat id", example="chat_x")], "chat"),
    ]:
        registry.register(
            HarnessCommandDescriptor(
                name=n, slash_alias=f"/{n}", short_description=n.replace("_", " "),
                arguments=args_spec, available=True, affected_resource=resource,
                expected_event_types=["CommandStarted", "CommandCompleted"], example_usage=f"/{n}",
            ),
            orchestrator._make_chat_handler(n),
        )
