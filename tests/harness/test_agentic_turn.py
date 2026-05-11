"""Tests for `Orchestrator.run_agentic_turn` — the Layer 3-owned agentic control loop.

Covers tool dispatch, empty-output retry, mode handoff acceptance, and
approval-gate termination. Uses a FakeRuntime that scripts what the LLM
"emits" each iteration so the loop can be driven deterministically.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from harness.command_registry import (
    ArgSpec, CommandContext, HarnessCommandDescriptor, HarnessCommandRegistry,
)
from harness.control import RunStateRecord
from harness.events import (
    ApprovalRequired, CommandCompleted, CommandStarted, FinalMessage, HarnessEvent,
    ModeHandoffAccepted, ToolCallExecuted,
)
from harness.orchestrator import Orchestrator
from runtime.protocol import Runtime
from runtime.types import RuntimeEvent, RuntimeRequest, RuntimeStatus, TokenPressure


class _Scenario:
    """One scripted runtime stream: text deltas, tool_calls, finish."""

    def __init__(self, text: str = "", tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.text = text
        self.tool_calls = tool_calls or []


class FakeRuntime:
    """Scriptable Runtime. Each stream() call consumes the next scenario."""

    chat_format = "gemma"

    def __init__(self, scenarios: list[_Scenario]) -> None:
        self.scenarios = list(scenarios)
        self.calls: list[RuntimeRequest] = []

    async def context_window(self) -> int:
        return 8192

    async def token_pressure(self, request: RuntimeRequest) -> TokenPressure:
        return TokenPressure(
            request_id=request.request_id,
            context_window=8192, prompt_tokens=100,
            reserved_completion_tokens=2048, total_tokens=2148, pressure_ratio=0.26,
            over_threshold=False,
        )

    async def validate_request(self, request: RuntimeRequest) -> None:
        return None

    async def status(self) -> RuntimeStatus:
        return "ready"

    async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]:
        self.calls.append(request)
        scenario = self.scenarios.pop(0) if self.scenarios else _Scenario()
        seq = 0
        if scenario.text:
            yield RuntimeEvent(
                type="text_delta", request_id=request.request_id, seq=seq,
                text=scenario.text,
            )
            seq += 1
        for tc in scenario.tool_calls:
            yield RuntimeEvent(
                type="tool_call", request_id=request.request_id, seq=seq, tool_call=tc,
            )
            seq += 1
        yield RuntimeEvent(
            type="finish", request_id=request.request_id, seq=seq,
            finish_reason="stop", usage={"prompt_tokens": 100, "completion_tokens": 10},
        )


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspaces" / "w_test"
    (ws / "data").mkdir(parents=True)
    (ws / "memory").mkdir(parents=True)
    (ws / "state").mkdir(parents=True)
    (ws / "data" / "sales.csv").write_text("a,b\n1,2\n3,4\n")
    return ws


def _provider(table: dict[str, str] | None = None):
    table = table or {
        "interaction": "interaction prompt",
        "analyst": "analyst prompt",
        "knowledge": "knowledge prompt",
        "clarification": "clarification prompt",
    }
    return lambda mode: table.get(mode, "")


def _state() -> RunStateRecord:
    return RunStateRecord(workspace_id="w_test", active_agent_mode="interaction")


@pytest.mark.asyncio
async def test_simple_text_response(tmp_path, workspace):
    runtime = FakeRuntime([_Scenario(text="hello world")])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="hi",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    finals = [e for e in events if e.event_name == "FinalMessage"]
    assert finals and finals[-1].text == "hello world"
    assert len(runtime.calls) == 1


@pytest.mark.asyncio
async def test_tool_loop_dispatches_list_files(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{"name": "list_files", "arguments": {}}]),
        _Scenario(text="you have data/sales.csv"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    state = _state()
    # Workspace must exist via workspace_manager (orchestrator registers via list_files command).
    await orch.create_workspace("w_test")
    real_ws = (tmp_path / "workspaces" / "w_test")
    (real_ws / "data").mkdir(parents=True, exist_ok=True)
    (real_ws / "data" / "sales.csv").write_text("a,b\n1,2\n")

    events = [e async for e in orch.run_agentic_turn(
        state, workspace_dir=real_ws, chat_id="c1", user_input="what files?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    executed = [e for e in events if isinstance(e, ToolCallExecuted)]
    finals = [e for e in events if e.event_name == "FinalMessage"]
    assert executed and executed[0].tool_name == "list_files"
    assert "files" in executed[0].result
    assert finals and "sales.csv" in finals[-1].text
    # Second runtime call must include TOOL_RESULT in last user message
    last_user_msg = runtime.calls[1].messages[-1].content
    assert "TOOL_RESULT" in last_user_msg


@pytest.mark.asyncio
async def test_handoff_reruns_under_target_mode(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{"name": "handoff_to_analyst", "arguments": {}}]),
        _Scenario(text="analyst answer"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="tell me about it",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    handoffs = [e for e in events if isinstance(e, ModeHandoffAccepted)]
    finals = [e for e in events if e.event_name == "FinalMessage"]
    assert len(handoffs) == 1
    assert handoffs[0].from_mode == "interaction"
    assert handoffs[0].to_mode == "analyst"
    assert finals and finals[-1].text == "analyst answer"


@pytest.mark.asyncio
async def test_double_handoff_blocked(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{"name": "handoff_to_analyst", "arguments": {}}]),
        _Scenario(tool_calls=[{"name": "handoff_to_analyst", "arguments": {}}]),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    handoffs = [e for e in events if isinstance(e, ModeHandoffAccepted)]
    assert len(handoffs) == 1
    assert len(runtime.calls) == 2  # loop terminated; no third call


@pytest.mark.asyncio
async def test_empty_output_retried_once(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(text=""),  # empty → harness emits TurnFailed(empty_output)
        _Scenario(text="recovered"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    fails = [e for e in events if e.event_name == "TurnFailed"]
    finals = [e for e in events if e.event_name == "FinalMessage"]
    assert len(fails) == 1
    assert finals and finals[-1].text == "recovered"


@pytest.mark.asyncio
async def test_empty_output_gives_up_after_one_retry(tmp_path, workspace):
    runtime = FakeRuntime([_Scenario(text=""), _Scenario(text="")])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    fails = [e for e in events if e.event_name == "TurnFailed"]
    assert len(fails) == 2
    assert len(runtime.calls) == 2


@pytest.mark.asyncio
async def test_approval_required_terminates_loop(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{
            "name": "plan_analysis",
            "arguments": {
                "goal": "count rows",
                "steps": [{
                    "purpose": "count",
                    "code": "from pathlib import Path\nPath('result.txt').write_text('1')\nprint(1)",
                    "declared_inputs": [],
                    "expected_outputs": ["result.txt"],
                }],
            },
        }]),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="count rows",
        requested_mode="analyst", prompt_provider=_provider(),
    )]
    approvals = [e for e in events if isinstance(e, ApprovalRequired)]
    assert approvals
    # Loop must terminate on approval — no second runtime call
    assert len(runtime.calls) == 1


@pytest.mark.asyncio
async def test_invalid_plan_analysis_is_repaired_once_internally(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{
            "name": "plan_analysis",
            "arguments": {
                "goal": "add revenue per unit",
                "steps": [{
                    "code": "from pathlib import Path\nPath('result.txt').write_text('ok')",
                    "declared_inputs": ["data/sales.csv"],
                    "expected_outputs": ["result.txt"],
                }],
            },
        }]),
        _Scenario(tool_calls=[{
            "name": "plan_analysis",
            "arguments": {
                "goal": "add revenue per unit",
                "steps": [{
                    "purpose": "Add revenue_per_unit from existing columns.",
                    "code": "from pathlib import Path\nPath('result.txt').write_text('ok')",
                    "declared_inputs": ["data/sales.csv"],
                    "expected_outputs": ["result.txt"],
                }],
            },
        }]),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1",
        user_input="add revenue_per_unit to @data/sales.csv",
        requested_mode="analyst", prompt_provider=_provider(),
    )]

    approvals = [e for e in events if isinstance(e, ApprovalRequired)]
    assert approvals
    assert len(runtime.calls) == 2
    repair_prompt = runtime.calls[1].messages[-1].content
    assert "STRICT PLAN_ANALYSIS REPAIR" in repair_prompt
    assert "add revenue_per_unit to @data/sales.csv" in repair_prompt
    assert "data/sales.csv" in repair_prompt
    assert "derived column" in repair_prompt
    assert "rolling calculation" in repair_prompt


@pytest.mark.asyncio
async def test_repeated_invalid_plan_analysis_reports_no_code_ran(tmp_path, workspace):
    invalid_tool_call = {
        "name": "plan_analysis",
        "arguments": {
            "goal": "add revenue per unit",
            "steps": [{
                "code": "from pathlib import Path\nPath('result.txt').write_text('ok')",
                "declared_inputs": ["data/sales.csv"],
                "expected_outputs": ["result.txt"],
            }],
        },
    }
    runtime = FakeRuntime([
        _Scenario(tool_calls=[invalid_tool_call]),
        _Scenario(tool_calls=[invalid_tool_call]),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1",
        user_input="add revenue_per_unit to @data/sales.csv",
        requested_mode="analyst", prompt_provider=_provider(),
    )]

    assert not [e for e in events if isinstance(e, ApprovalRequired)]
    finals = [e for e in events if isinstance(e, FinalMessage)]
    assert finals
    assert "No code ran" in finals[-1].text
    assert "'purpose' is required" in finals[-1].text
    assert len(runtime.calls) == 2


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_and_recovers(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{"name": "nonexistent_tool", "arguments": {}}]),
        _Scenario(text="recovered"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    executed = [e for e in events if isinstance(e, ToolCallExecuted)]
    finals = [e for e in events if e.event_name == "FinalMessage"]
    assert executed and "error" in executed[0].result
    assert finals and finals[-1].text == "recovered"
