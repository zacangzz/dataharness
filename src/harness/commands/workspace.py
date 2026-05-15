from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_workspace_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    for n, args_spec in [
        ("list_workspaces", []),
        ("create_workspace", [ArgSpec(name="workspace_id", type="workspace_id", required=True, description="workspace id", example="w_0002")]),
        ("rename_workspace", [
            ArgSpec(name="old_id", type="workspace_id", required=True, description="current workspace id", example="w_old"),
            ArgSpec(name="new_id", type="workspace_id", required=True, description="new workspace id", example="w_new"),
        ]),
        ("delete_workspace", [ArgSpec(name="workspace_id", type="workspace_id", required=True, description="workspace id", example="w_0002")]),
        ("switch_workspace", [
            ArgSpec(name="workspace_id", type="workspace_id", required=True, description="workspace id", example="w_0002"),
            ArgSpec(name="force", type="bool", required=False, description="cancel active run before switching", example="false"),
        ]),
        ("workspace_status", []),
        ("workspace_inventory", []),
        ("list_files", []),
        ("inspect_file", [ArgSpec(name="path", type="path", required=True, description="workspace-relative file path", example="data/sales.csv")]),
        ("read_file", [
            ArgSpec(name="path", type="path", required=True, description="workspace-relative file path", example="data/notes.md"),
            ArgSpec(name="max_bytes", type="int", required=False, description="byte cap for content (default 65536)", example="65536"),
            ArgSpec(name="encoding", type="str", required=False, description="text encoding (default utf-8)", example="utf-8"),
        ]),
    ]:
        registry.register(
            HarnessCommandDescriptor(
                name=n, slash_alias=f"/{n}", short_description=n.replace("_", " "),
                arguments=args_spec, available=True, affected_resource="workspace",
                expected_event_types=["CommandStarted", "StatusChanged", "CommandCompleted"],
                example_usage=f"/{n}",
            ),
            orchestrator._make_workspace_handler(n),
        )
