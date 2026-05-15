from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_provenance_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="inspect_artifact", slash_alias="/inspect_artifact",
            short_description="Inspect an artifact file in the active workspace",
            arguments=[ArgSpec(
                name="path", type="artifact_path", required=True,
                description="workspace-relative path",
                example="artifacts/tmp/run_1/step_1/output.txt",
            )],
            available=True, affected_resource="artifact",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/inspect_artifact artifacts/out.txt",
        ),
        orchestrator._handle_inspect_artifact,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="provenance_inspect", slash_alias="/provenance_inspect",
            short_description="Inspect lineage for an artifact",
            arguments=[ArgSpec(
                name="path", type="artifact_path", required=True,
                description="workspace-relative artifact path",
                example="artifacts/out.csv",
            )],
            available=True, affected_resource="provenance",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/provenance_inspect artifacts/out.csv",
        ),
        orchestrator._handle_provenance_inspect,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="validity_inspect", slash_alias="/validity_inspect",
            short_description="Inspect validity_state records",
            arguments=[ArgSpec(
                name="subject_id", type="str", required=False,
                description="filter records by subject_id (artifact path or step id)",
                example="artifacts/out.csv",
            )],
            available=True, affected_resource="provenance",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/validity_inspect artifacts/out.csv",
        ),
        orchestrator._handle_validity_inspect,
    )
