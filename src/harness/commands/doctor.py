from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_doctor_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="doctor",
            slash_alias="/doctor",
            short_description="Run the harness doctor diagnostic",
            arguments=[
                ArgSpec(
                    name="trigger",
                    type="str",
                    required=False,
                    description="trigger label",
                    example="manual",
                )
            ],
            available=True,
            disabled_reason=None,
            affected_resource="doctor",
            expected_event_types=[
                "DoctorStarted",
                "CommandProgress",
                "DoctorFinding",
                "DoctorReportReady",
                "CommandCompleted",
            ],
            example_usage="/doctor",
        ),
        orchestrator._handle_doctor,
    )
