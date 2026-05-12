"""run_agentic_turn must only persist the original user input, not the
synthetic tool-followup re-prompt it constructs internally. Verifies that
chat history is not polluted with [TOOL_RESULT]/[ASSISTANT_DRAFT] envelopes."""

from __future__ import annotations

import pytest

from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator
from test_agentic_turn import FakeRuntime, _Scenario, _provider  # type: ignore


def _state() -> RunStateRecord:
    return RunStateRecord(workspace_id="w_test", active_agent_mode="interaction")


@pytest.mark.asyncio
async def test_only_original_user_input_persisted(tmp_path):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{"name": "list_files", "arguments": {}}]),
        _Scenario(text="answer using files"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    await orch.create_workspace("w_test")
    ws = tmp_path / "workspaces" / "w_test"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    (ws / "data" / "x.csv").write_text("a,b\n1,2\n")

    state = _state()
    _ = [e async for e in orch.run_agentic_turn(
        state, workspace_dir=ws, chat_id="c1", user_input="what files?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]

    record = await orch.chat_store.view_chat("c1")
    user_msgs = [m for m in record.messages if m.role == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0].text == "what files?"
    # synthetic envelopes never reach durable history
    assert "[TOOL_RESULT" not in user_msgs[0].text
    assert "[ASSISTANT_DRAFT" not in user_msgs[0].text


@pytest.mark.asyncio
async def test_assistant_draft_wrapper_stripped_before_persist(tmp_path):
    # Model leaks [ASSISTANT_DRAFT] markers in its plain text reply.
    runtime = FakeRuntime([
        _Scenario(text="[ASSISTANT_DRAFT]hello world[/ASSISTANT_DRAFT]"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    await orch.create_workspace("w_test")
    ws = tmp_path / "workspaces" / "w_test"

    _ = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=ws, chat_id="c2", user_input="hi",
        requested_mode="interaction", prompt_provider=_provider(),
    )]

    record = await orch.chat_store.view_chat("c2")
    asst = [m for m in record.messages if m.role == "assistant"]
    assert len(asst) == 1
    assert "[ASSISTANT_DRAFT" not in asst[0].text
    assert "[/ASSISTANT_DRAFT" not in asst[0].text
    assert asst[0].text == "hello world"
