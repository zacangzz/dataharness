import pytest

from app.session import AppSession
from harness.command_registry import CommandContext
from harness.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_all_harness_commands_are_reachable_from_l4_command_list(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    session = AppSession(orchestrator=orch)
    ctx = CommandContext(
        workspace_id=None,
        chat_id=None,
        run_id=None,
        has_pending_approval=False,
        has_pending_clarification=False,
    )

    harness_command_names = {d.name for d in orch.registry.help().commands}
    l4_command_names = {d.name for d in await session.list_commands(ctx)}

    assert harness_command_names
    assert harness_command_names <= l4_command_names
