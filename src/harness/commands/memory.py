from __future__ import annotations

from typing import TYPE_CHECKING

from harness.core.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_memory_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="memory_review", slash_alias="/memory_review",
            short_description="List memory update proposals",
            arguments=[ArgSpec(
                name="status", type="str", required=False,
                description="filter by status (pending|approved|applied|rejected)",
                example="pending",
            )],
            available=True, affected_resource="memory",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/memory_review pending",
        ),
        orchestrator._handle_memory_review,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="recall_knowledge", slash_alias="/recall_knowledge",
            short_description="Search saved knowledge (notes, preferences, functions) for relevant information",
            arguments=[ArgSpec(
                name="query", type="str", required=True,
                description="What to search for",
                example="pandas",
            )],
            available=True, affected_resource="memory",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage='/recall_knowledge "data cleaning"',
        ),
        orchestrator._handle_recall_knowledge,
        availability=lambda ctx: (True, None),
    )
