import json

import pytest

from harness.core.analysis_flow import AnalysisFlow, AnalysisPhase
from harness.control import RunStateRecord
from harness.events import FinalMessage
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeEvent, TokenPressure


class ProseRuntime:
    """Always prose, never a tool_call — and the prose narrates plan intent."""

    async def stream(self, request):
        yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0,
                           text="I will use the analysis_plan tool to outline the steps.")
        yield RuntimeEvent(type="finish", request_id=request.request_id, seq=1,
                           finish_reason="stop", usage={})

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


def _logged_phases(tmp_path) -> list[str]:
    log = tmp_path / "state" / "analysis_flows.jsonl"
    phases = []
    for line in log.read_text().splitlines():
        entry = json.loads(line)
        fd = entry.get("flow_data")
        if fd:
            phases.append(fd["phase"])
    return phases


@pytest.mark.asyncio
async def test_analyst_entry_creates_inspecting_flow(tmp_path) -> None:
    orch = Orchestrator(runtime=ProseRuntime(), app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="hire rates over last 2 months?", max_iterations=1,
        )
    ]

    # Flow creation is recorded even though the flow later resolves.
    log = tmp_path / "state" / "analysis_flows.jsonl"
    created = [
        json.loads(line) for line in log.read_text().splitlines()
        if json.loads(line).get("flow_data", {}).get("phase") == "inspecting"
    ]
    assert created
    assert created[0]["flow_data"]["original_request"] == "hire rates over last 2 months?"


@pytest.mark.asyncio
async def test_plan_intent_prose_transitions_through_plan_pending(tmp_path) -> None:
    orch = Orchestrator(runtime=ProseRuntime(), app_root=tmp_path)
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id="r1", workspace_id="w_0001",
        phase=AnalysisPhase.INSPECTING, original_request="hire rates?",
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    events = [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="hire rates?", max_iterations=1,
        )
    ]

    # The INSPECTING -> PLAN_PENDING transition is persisted before forcing.
    assert "plan_pending" in _logged_phases(tmp_path)
    # ProseRuntime never emits a tool_call, so forced emission exhausts and
    # the turn fails LOUDLY (no silent return) and the flow is released.
    assert [e for e in events if isinstance(e, FinalMessage)]
    assert orch._get_flow("c1") is None


@pytest.mark.asyncio
async def test_interaction_prose_only_creates_no_flow(tmp_path) -> None:
    orch = Orchestrator(runtime=ProseRuntime(), app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="hello", max_iterations=1,
        )
    ]

    assert orch._get_flow("c1") is None


@pytest.mark.asyncio
async def test_analyst_prose_without_plan_intent_releases_flow(tmp_path) -> None:
    """Conceptual Q&A routed to analyst: no inspection, no plan intent ->
    flow released, turn ends normally with the prose answer."""

    class PlainProse:
        async def stream(self, request):
            yield RuntimeEvent(type="text_delta", request_id=request.request_id,
                               seq=0, text="A hire rate is hires divided by headcount.")
            yield RuntimeEvent(type="finish", request_id=request.request_id,
                               seq=1, finish_reason="stop", usage={})

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

    orch = Orchestrator(runtime=PlainProse(), app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    events = [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="what is a hire rate?", max_iterations=1,
        )
    ]

    assert orch._get_flow("c1") is None
    finals = [e for e in events if isinstance(e, FinalMessage)]
    assert finals and "hire rate" in finals[-1].text
