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

# The model-callable surface is the harness tool registry. Legacy command names
# such as `plan_analysis` remain commands only and must not dispatch as tools.


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
async def test_tool_loop_dispatches_file_read(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{"name": "file_read", "arguments": {"operation": "list"}}]),
        _Scenario(text="you have data/sales.csv"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    state = _state()
    # Workspace must exist via workspace_manager (file_read reads from workspaces_dir).
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
    assert executed and executed[0].tool_name == "file_read"
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
    """Empty output is retried until max_iterations exhausted."""
    runtime = FakeRuntime([_Scenario(text=""), _Scenario(text="")])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    fails = [e for e in events if e.event_name == "TurnFailed"]
    assert len(fails) == 4
    assert len(runtime.calls) == 4


@pytest.mark.asyncio
async def test_unhandled_turn_failure_terminates_agentic_loop(tmp_path, workspace):
    class ErrorRuntime(FakeRuntime):
        async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]:
            self.calls.append(request)
            yield RuntimeEvent(
                type="error",
                request_id=request.request_id,
                seq=0,
                error_code="runtime_error",
                error_message="backend crashed",
            )

    runtime = ErrorRuntime([_Scenario(text="should not run")])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    fails = [e for e in events if e.event_name == "TurnFailed"]
    assert len(fails) == 1
    assert fails[0].error_code == "runtime_error"
    assert len(runtime.calls) == 1


@pytest.mark.asyncio
async def test_approval_required_terminates_loop(tmp_path, workspace):
    # Two-step: gen-1 emits a CODE-FREE plan; gen-2 supplies the code.
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{
            "name": "analysis_plan",
            "arguments": {
                "goal": "count rows",
                "steps": [{
                    "purpose": "count rows in sales",
                    "declared_inputs": ["data/sales.csv"],
                    "expected_outputs": ["result.txt"],
                }],
            },
        }]),
        _Scenario(text=_fenced(_GOOD_STEP_CODE)),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="count rows",
        requested_mode="analyst", prompt_provider=_provider(),
    )]
    approvals = [e for e in events if isinstance(e, ApprovalRequired)]
    assert approvals
    # gen-1 plan + one gen-2 code generation, then loop terminates on approval.
    assert len(runtime.calls) == 2


@pytest.mark.asyncio
async def test_invalid_plan_analysis_is_repaired_once_internally(tmp_path, workspace):
    # gen-1 emits a structurally bad plan (missing purpose) → one code-free
    # shape-repair retry → valid plan → gen-2 → approval.
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{
            "name": "analysis_plan",
            "arguments": {
                "goal": "add revenue per unit",
                "steps": [{
                    "declared_inputs": ["data/sales.csv"],
                    "expected_outputs": ["result.txt"],
                }],
            },
        }]),
        _Scenario(tool_calls=[{
            "name": "analysis_plan",
            "arguments": {
                "goal": "add revenue per unit",
                "steps": [{
                    "purpose": "Add revenue_per_unit from existing columns.",
                    "declared_inputs": ["data/sales.csv"],
                    "expected_outputs": ["result.txt"],
                }],
            },
        }]),
        _Scenario(text=_fenced(_GOOD_STEP_CODE)),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1",
        user_input="add revenue_per_unit to @data/sales.csv",
        requested_mode="analyst", prompt_provider=_provider(),
    )]

    approvals = [e for e in events if isinstance(e, ApprovalRequired)]
    assert approvals
    assert len(runtime.calls) == 3  # gen-1 bad, gen-1 repaired, gen-2 code
    repair_prompt = runtime.calls[1].messages[-1].content
    assert "STRICT ANALYSIS_PLAN REPAIR" in repair_prompt
    assert "Do NOT write code" in repair_prompt  # code-free repair shape
    assert '"code_lines":["import pandas' not in repair_prompt  # old code example gone
    assert "add revenue_per_unit to @data/sales.csv" in repair_prompt
    assert "data/sales.csv" in repair_prompt


@pytest.mark.asyncio
async def test_command_plan_analysis_keeps_supplied_code_no_gen2(tmp_path, workspace):
    """Command path (`_analysis_plan_events`) is unchanged: it accepts code
    supplied directly and must NOT invoke gen-2 (no runtime call)."""
    runtime = FakeRuntime([])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch._analysis_plan_events(
        workspace_id="w_test", chat_id="c1", run_id="r1",
        args={
            "goal": "count rows",
            "steps": [{
                "purpose": "count",
                "code_lines": [
                    "from pathlib import Path",
                    "Path('result.txt').write_text('1')",
                    "print(1)",
                ],
                "declared_inputs": [],
                "expected_outputs": ["result.txt"],
            }],
        },
        event_command="plan_analysis",
    )]
    assert any(e.event_name == "ApprovalRequired" for e in events)
    assert any(e.event_name == "PlanReady" for e in events)
    assert len(runtime.calls) == 0  # command path never runs gen-2


@pytest.mark.asyncio
async def test_runtime_error_diagnostics_are_preserved_on_turn_failed(tmp_path, workspace):
    class DiagnosticsRuntime(FakeRuntime):
        async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]:
            self.calls.append(request)
            yield RuntimeEvent(
                type="error",
                request_id=request.request_id,
                seq=0,
                error_code="parse_error",
                error_message="malformed tool call",
                diagnostics={"parse_error_snippet": "bad json"},
            )

    runtime = DiagnosticsRuntime([])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)

    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="analyst", prompt_provider=_provider(),
    )]

    fails = [e for e in events if e.event_name == "TurnFailed"]
    assert fails
    assert fails[0].details["diagnostics"] == {"parse_error_snippet": "bad json"}


@pytest.mark.asyncio
async def test_repeated_invalid_plan_analysis_reports_no_code_ran(tmp_path, workspace):
    invalid_tool_call = {
        "name": "analysis_plan",
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


@pytest.mark.asyncio
async def test_control_intents_are_registered_as_tools(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    names = {tool.name for tool in orch.tool_registry.list_tools()}

    assert "answer_directly" in names
    assert "handoff_to_analyst" in names
    assert "handoff_to_knowledge" in names
    assert "request_clarification" in names
    assert "respond_to_user" in names


@pytest.mark.asyncio
async def test_model_tool_call_cannot_dispatch_harness_command(tmp_path, workspace):
    """Harness commands (e.g. `doctor`) are not in the tool registry and so
    cannot be dispatched from a model tool_call — only registered tools can."""
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{"name": "doctor", "arguments": {}}]),
        _Scenario(text="recovered"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]
    executed = [e for e in events if isinstance(e, ToolCallExecuted)]
    assert executed and "error" in executed[0].result
    assert "unknown tool: doctor" in executed[0].result["error"]


@pytest.mark.asyncio
async def test_model_tool_call_cannot_dispatch_legacy_plan_analysis_command(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{
            "name": "plan_analysis",
            "arguments": {
                "goal": "count rows",
                "steps": [{
                    "purpose": "count",
                    "code_lines": [
                        "from pathlib import Path",
                        "Path('result.txt').write_text('1')",
                        "print(1)",
                    ],
                    "declared_inputs": [],
                    "expected_outputs": ["result.txt"],
                }],
            },
        }]),
        _Scenario(text="recovered"),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)

    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="chat_active",
        user_input="count rows", requested_mode="analyst", prompt_provider=_provider(),
    )]

    executed = [e for e in events if isinstance(e, ToolCallExecuted)]
    approvals = [e for e in events if isinstance(e, ApprovalRequired)]
    assert not approvals
    assert executed and executed[0].tool_name == "plan_analysis"
    assert executed[0].result["error"] == "unknown tool: plan_analysis"


@pytest.mark.asyncio
async def test_analysis_tool_events_keep_active_chat_id(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{
            "name": "analysis_plan",
            "arguments": {
                "goal": "count rows",
                "steps": [{
                    "purpose": "count rows in sales",
                    "declared_inputs": ["data/sales.csv"],
                    "expected_outputs": ["result.txt"],
                }],
            },
        }]),
        _Scenario(text=_fenced(_GOOD_STEP_CODE)),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)

    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="chat_active",
        user_input="count rows", requested_mode="analyst", prompt_provider=_provider(),
    )]

    command_events = [e for e in events if isinstance(e, (CommandStarted, CommandCompleted))]
    assert command_events
    assert {event.chat_id for event in command_events} == {"chat_active"}


@pytest.mark.asyncio
async def test_knowledge_propose_update_creates_pending_proposal_with_run_id(tmp_path, workspace):
    from harness.db import WorkspaceDb
    from harness.knowledge import KnowledgeManager
    from harness.persistence import HarnessPersistence

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    persistence = HarnessPersistence(db)
    knowledge_manager = KnowledgeManager(workspace_dir=workspace, persistence=persistence)
    runtime = FakeRuntime([
        _Scenario(tool_calls=[{
            "name": "knowledge_propose_update",
            "arguments": {
                "operation": "note",
                "title": "attrition",
                "content": "Attrition is leavers / average headcount.",
                "source_refs": ["chat:chat_active"],
            },
        }]),
        _Scenario(text="recorded"),
    ])
    state = _state()
    orch = Orchestrator(
        runtime=runtime,
        app_root=tmp_path,
        persistence=persistence,
        knowledge_manager=knowledge_manager,
    )

    events = [e async for e in orch.run_agentic_turn(
        state, workspace_dir=workspace, chat_id="chat_active",
        user_input="remember this", requested_mode="knowledge", prompt_provider=_provider(),
    )]

    executed = [e for e in events if isinstance(e, ToolCallExecuted)]
    assert executed and executed[0].result["ok"] is True
    records = persistence.db.list_records("memory_update_proposals")
    assert len(records) == 1
    assert records[0]["run_id"] == state.run_id
    assert records[0]["status"] == "pending"


def test_analysis_plan_is_registered_as_tool(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    tool_names = {d.name for d in orch.tool_registry.list_tools()}
    assert "analysis_plan" in tool_names
    assert "knowledge_recall" in tool_names
    assert "knowledge_propose_update" in tool_names
    assert "analysis_request_execution" in tool_names
    assert "plan_analysis" not in tool_names

    # Old names remain available as harness commands.
    command_names = {d.name for d in orch.registry.help().commands}
    assert "plan_analysis" in command_names
    assert "recall_knowledge" in command_names


@pytest.mark.asyncio
async def test_valid_tool_call_survives_trailing_incomplete_structured_error(tmp_path, workspace):
    """A valid tool_call followed by a truncated second block must still dispatch.

    Models sometimes emit one complete <tool_call> then start a second that is
    cut off at finish, producing an `incomplete_structured_content` error event.
    The first, valid tool_call must not be discarded.
    """

    class TrailingErrorRuntime(FakeRuntime):
        async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]:
            self.calls.append(request)
            if len(self.calls) == 1:
                yield RuntimeEvent(
                    type="tool_call", request_id=request.request_id, seq=0,
                    tool_call={"name": "file_read", "arguments": {"operation": "list"}},
                )
                yield RuntimeEvent(
                    type="error", request_id=request.request_id, seq=1,
                    error_code="incomplete_structured_content",
                    error_message='incomplete structured content at finish: <tool_call>{\n"name":"',
                )
                return
            yield RuntimeEvent(
                type="text_delta", request_id=request.request_id, seq=0,
                text="you have data/sales.csv",
            )
            yield RuntimeEvent(
                type="finish", request_id=request.request_id, seq=1,
                finish_reason="stop", usage={},
            )

    runtime = TrailingErrorRuntime([])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    await orch.create_workspace("w_test")
    real_ws = tmp_path / "workspaces" / "w_test"
    (real_ws / "data").mkdir(parents=True, exist_ok=True)
    (real_ws / "data" / "sales.csv").write_text("a,b\n1,2\n")

    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=real_ws, chat_id="c1", user_input="what files?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]

    executed = [e for e in events if isinstance(e, ToolCallExecuted)]
    finals = [e for e in events if e.event_name == "FinalMessage"]
    fails = [e for e in events if e.event_name == "TurnFailed"]
    assert executed and executed[0].tool_name == "file_read"
    assert finals and "sales.csv" in finals[-1].text
    # A usable tool_call was emitted; the truncated tail must not surface as a
    # turn failure to the UI.
    assert not fails, f"spurious TurnFailed surfaced: {[f.error_code for f in fails]}"


@pytest.mark.asyncio
async def test_incomplete_structured_content_classified_by_error_code_and_retried(tmp_path, workspace):
    """`incomplete_structured_content` must be treated as recoverable via its
    error_code, not by sniffing the failure_summary text."""

    class TruncatedRuntime(FakeRuntime):
        async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]:
            self.calls.append(request)
            if len(self.calls) == 1:
                # No "tool_call"/"malformed" substring in the message: proves
                # classification must use error_code, not text sniffing.
                yield RuntimeEvent(
                    type="error", request_id=request.request_id, seq=0,
                    error_code="incomplete_structured_content",
                    error_message="stream truncated mid structure",
                )
                return
            yield RuntimeEvent(
                type="text_delta", request_id=request.request_id, seq=0,
                text="recovered after nudge",
            )
            yield RuntimeEvent(
                type="finish", request_id=request.request_id, seq=1,
                finish_reason="stop", usage={},
            )

    runtime = TruncatedRuntime([])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]

    finals = [e for e in events if e.event_name == "FinalMessage"]
    assert len(runtime.calls) == 2, "expected one repair retry"
    assert finals and finals[-1].text == "recovered after nudge"


@pytest.mark.asyncio
async def test_exhausted_malformed_retry_yields_final_message(tmp_path, workspace):
    """When the model keeps emitting malformed tool calls, the user must get an
    explicit FinalMessage, not a silent dead turn."""

    class AlwaysTruncatedRuntime(FakeRuntime):
        async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]:
            self.calls.append(request)
            yield RuntimeEvent(
                type="error", request_id=request.request_id, seq=0,
                error_code="incomplete_structured_content",
                error_message="stream truncated mid structure",
            )

    runtime = AlwaysTruncatedRuntime([])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch.run_agentic_turn(
        _state(), workspace_dir=workspace, chat_id="c1", user_input="?",
        requested_mode="interaction", prompt_provider=_provider(),
    )]

    finals = [e for e in events if e.event_name == "FinalMessage"]
    assert finals, "exhausted malformed retry must surface a FinalMessage"
    assert "tool" in finals[-1].text.lower()
    assert len(runtime.calls) == 2, "one initial + one repair retry, then give up"


@pytest.mark.asyncio
async def test_generate_step_code_returns_fenced_code_lines(tmp_path, workspace):
    """Gen-2: _generate_step_code runs an internal, non-persisted generation,
    stops at the closing fence, and returns the fenced Python as code_lines.
    The prompt must carry the step purpose + workspace schema."""
    fenced = (
        "Sure, here is the code:\n"
        "```python\n"
        "import pandas as pd\n"
        'df = pd.read_csv("data/sales.csv")\n'
        'Path("result.txt").write_text(str(len(df)))\n'
        "print(len(df))\n"
        "```\n"
    )
    runtime = FakeRuntime([_Scenario(text=fenced)])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    step = {
        "purpose": "count rows in sales",
        "declared_inputs": ["data/sales.csv"],
        "expected_outputs": ["result.txt"],
    }

    code_lines = await orch._generate_step_code(
        _state(), step=step, workspace_dir=workspace,
    )

    assert code_lines == [
        "import pandas as pd",
        'df = pd.read_csv("data/sales.csv")',
        'Path("result.txt").write_text(str(len(df)))',
        "print(len(df))",
    ]
    assert len(runtime.calls) == 1
    req = runtime.calls[0]
    assert req.stop == ["```"]
    # standalone generation: only system+user, no chat history rows
    assert [m.role for m in req.messages] == ["system", "user"]
    prompt_text = "\n".join(m.content for m in req.messages)
    assert "count rows in sales" in prompt_text
    assert "data/sales.csv" in prompt_text  # schema snapshot + declared input
    assert "result.txt" in prompt_text      # expected output named


def _fenced(code: str) -> str:
    return f"```python\n{code}\n```\n"


_GOOD_STEP_CODE = (
    "import pandas as pd\n"
    "from pathlib import Path\n"
    'df = pd.read_csv("data/sales.csv")\n'
    'Path("result.txt").write_text(str(len(df)))\n'
    "print(len(df))"
)


def _plan_args():
    return {
        "goal": "count rows",
        "steps": [{
            "purpose": "count rows in sales",
            "declared_inputs": ["data/sales.csv"],
            "expected_outputs": ["result.txt"],
        }],
    }


@pytest.mark.asyncio
async def test_assemble_plan_happy_path(tmp_path, workspace):
    runtime = FakeRuntime([_Scenario(text=_fenced(_GOOD_STEP_CODE))])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch._assemble_plan_events(
        workspace_id="w_test", chat_id="c1", run_id="r1",
        args=_plan_args(), event_command="analysis_plan",
    )]
    names = [e.event_name for e in events]
    assert names[0] == "CommandStarted"
    progress = [e for e in events if e.event_name == "CommandProgress"]
    assert len(progress) == 1
    assert progress[0].phase_index == 1 and progress[0].phase_total == 1
    assert "PlanReady" in names
    approvals = [e for e in events if e.event_name == "ApprovalRequired"]
    assert len(approvals) == 1  # single approval gate
    completed = [e for e in events if e.event_name == "CommandCompleted"]
    assert completed and completed[-1].result.get("plan_id")
    assert len(runtime.calls) == 1  # one gen-2, no retry


@pytest.mark.asyncio
async def test_assemble_plan_retries_bad_gen2_once_then_recovers(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(text=_fenced("print(1)")),          # missing result.txt ref
        _Scenario(text=_fenced(_GOOD_STEP_CODE)),     # corrected
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch._assemble_plan_events(
        workspace_id="w_test", chat_id="c1", run_id="r1",
        args=_plan_args(), event_command="analysis_plan",
    )]
    names = [e.event_name for e in events]
    assert len(runtime.calls) == 2  # initial + one gen-2 retry
    assert "PlanReady" in names
    assert any(e.event_name == "ApprovalRequired" for e in events)
    # correction must be fed back into the retry prompt
    assert "rejected" in runtime.calls[1].messages[-1].content.lower()


@pytest.mark.asyncio
async def test_assemble_plan_exhausted_gen2_yields_error_no_approval(tmp_path, workspace):
    runtime = FakeRuntime([
        _Scenario(text=_fenced("print(1)")),
        _Scenario(text=_fenced("print(2)")),
    ])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch._assemble_plan_events(
        workspace_id="w_test", chat_id="c1", run_id="r1",
        args=_plan_args(), event_command="analysis_plan",
    )]
    assert len(runtime.calls) == 2  # one initial + one retry, then give up
    assert not any(e.event_name == "ApprovalRequired" for e in events)
    completed = [e for e in events if e.event_name == "CommandCompleted"]
    assert completed and "after one retry" in completed[-1].result.get("error", "")


@pytest.mark.asyncio
async def test_assemble_plan_shape_error_skips_gen2(tmp_path, workspace):
    runtime = FakeRuntime([])
    orch = Orchestrator(runtime=runtime, app_root=tmp_path)
    events = [e async for e in orch._assemble_plan_events(
        workspace_id="w_test", chat_id="c1", run_id="r1",
        args={"goal": "g", "steps": []}, event_command="analysis_plan",
    )]
    assert len(runtime.calls) == 0  # no gen-2 when plan shape invalid
    completed = [e for e in events if e.event_name == "CommandCompleted"]
    assert completed and "steps" in completed[-1].result.get("error", "")
    assert not any(e.event_name == "ApprovalRequired" for e in events)
