from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_compact_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="compact",
            slash_alias="/compact",
            short_description="Compact active chat history",
            arguments=[],
            available=True,
            affected_resource="chat",
            expected_event_types=["ChatHistoryCompacted", "CommandCompleted"],
            example_usage="/compact",
        ),
        orchestrator._handle_compact,
    )
