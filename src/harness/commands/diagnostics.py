from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_diagnostics_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="help",
            slash_alias="/help",
            short_description="Show command help",
            arguments=[
                ArgSpec(
                    name="command",
                    type="str",
                    required=False,
                    description="command name",
                    example="doctor",
                )
            ],
            available=True,
            affected_resource="run",
            expected_event_types=["CommandCompleted"],
            example_usage="/help inspect_artifact",
        ),
        orchestrator._handle_help,
    )
