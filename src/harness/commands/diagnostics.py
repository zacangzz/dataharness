from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_diagnostics_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="doctor", slash_alias="/doctor",
            short_description="Run the harness doctor diagnostic",
            arguments=[ArgSpec(name="trigger", type="str", required=False, description="trigger label", example="manual")],
            available=True, disabled_reason=None, affected_resource="doctor",
            expected_event_types=["DoctorStarted", "CommandProgress", "DoctorFinding", "DoctorReportReady", "CommandCompleted"],
            example_usage="/doctor",
        ),
        orchestrator._handle_doctor,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="compact", slash_alias="/compact",
            short_description="Compact active chat history",
            arguments=[],
            available=True, affected_resource="chat",
            expected_event_types=["ChatHistoryCompacted", "CommandCompleted"],
            example_usage="/compact",
        ),
        orchestrator._handle_compact,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="help", slash_alias="/help", short_description="Show command help",
            arguments=[ArgSpec(name="command", type="str", required=False, description="command name", example="doctor")],
            available=True, affected_resource="run",
            expected_event_types=["CommandCompleted"], example_usage="/help inspect_artifact",
        ),
        orchestrator._handle_help,
    )
