import pytest

from harness.core.analysis_flow import AnalysisFlow, AnalysisPhase
from harness.control import RunStateRecord
from harness.events import ModeHandoffAccepted
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeEvent, TokenPressure


class ProseRuntime:
    """Emits prose only — no tool_call, finish=stop."""

    async def stream(self, request):
        yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0, text="I will plan.")
        yield RuntimeEvent(type="finish", request_id=request.request_id, seq=1, finish_reason="stop", usage={})

    async def context_window(self):
        return 4096

    async def token_pressure(self, request):
        return TokenPressure(
            request_id=request.request_id, context_window=4096, prompt_tokens=1,
            reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=1 + request.max_completion_tokens,
            pressure_ratio=0.1, over_threshold=False,
        )

    async def validate_request(self, request):
        return None

    async def status(self):
        return "ready"


@pytest.mark.asyncio
async def test_in_flight_flow_forces_analyst_mode(tmp_path) -> None:
    orch = Orchestrator(runtime=ProseRuntime(), app_root=tmp_path)
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id="r1", workspace_id="w_0001",
        phase=AnalysisPhase.INSPECTING, original_request="hire rates?",
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    events = [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="ok proceed", max_iterations=2,
        )
    ]

    # Sticky override forces the analyst profile despite interaction routing.
    assert state.active_agent_mode == "analyst"
    sticky = [
        e for e in events
        if isinstance(e, ModeHandoffAccepted) and e.reason == "analysis_flow_sticky"
    ]
    assert sticky and sticky[0].from_mode == "interaction" and sticky[0].to_mode == "analyst"


@pytest.mark.asyncio
async def test_no_flow_keeps_routed_mode(tmp_path) -> None:
    orch = Orchestrator(runtime=ProseRuntime(), app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    events = [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="hello", max_iterations=1,
        )
    ]

    assert state.active_agent_mode == "interaction"
    assert not [
        e for e in events
        if isinstance(e, ModeHandoffAccepted) and e.reason == "analysis_flow_sticky"
    ]


@pytest.mark.asyncio
async def test_terminal_flow_does_not_stick(tmp_path) -> None:
    orch = Orchestrator(runtime=ProseRuntime(), app_root=tmp_path)
    # A DONE flow that somehow lingers in the dict must not override mode.
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id="r1", workspace_id="w_0001",
        phase=AnalysisPhase.DONE,
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    events = [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="hi", max_iterations=1,
        )
    ]

    assert state.active_agent_mode == "interaction"
    assert not [
        e for e in events
        if isinstance(e, ModeHandoffAccepted) and e.reason == "analysis_flow_sticky"
    ]
