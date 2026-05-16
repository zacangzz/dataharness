import pytest

from harness.analysis_flow import AnalysisFlow, AnalysisPhase
from harness.control import RunStateRecord
from harness.events import ApprovalRequired, FinalMessage
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeEvent, TokenPressure

_TOOL_CALL = (
    '<tool_call>{"name":"analysis_plan","arguments":{"goal":"hire rate",'
    '"steps":[{"purpose":"count hires","declared_inputs":["data/employees.csv"],'
    '"expected_outputs":["result.txt"]}]}}'
)  # NOTE: closing </tool_call> intentionally omitted (stop token cut it).

_FENCED = "```python\nfrom pathlib import Path\nPath('result.txt').write_text('1')\n```"


class ScriptRuntime:
    """Routes by request.stop: force-call vs gen-2 vs main turn."""

    def __init__(self, *, force_outputs: list[str]):
        self.force_outputs = list(force_outputs)
        self.captured: list = []

    async def stream(self, request):
        self.captured.append(request)
        stop = request.stop or []
        if stop == ["</tool_call>"]:
            text = self.force_outputs.pop(0) if self.force_outputs else ""
        elif stop == ["```"]:
            text = _FENCED
        else:
            text = "I will use the analysis_plan tool to outline the steps."
        if text:
            yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0, text=text)
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


def _provider(mode: str) -> str:
    return f"PROMPT[{mode}]"


@pytest.mark.asyncio
async def test_force_plan_tool_call_returns_parsed_args(tmp_path) -> None:
    rt = ScriptRuntime(force_outputs=[_TOOL_CALL])
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")
    flow = AnalysisFlow(
        chat_id="c1", run_id=state.run_id, workspace_id="w_0001",
        phase=AnalysisPhase.PLAN_PENDING, original_request="hire rate?",
    )

    args = await orch._force_plan_tool_call(
        state, flow=flow, workspace_dir=tmp_path, chat_id="c1", run_id=state.run_id,
    )

    assert args is not None
    assert args["goal"] == "hire rate"
    assert args["steps"][0]["purpose"] == "count hires"
    # Dedicated minimal request: stop token + system/user only, not persisted.
    assert len(rt.captured) == 1
    assert rt.captured[0].stop == ["</tool_call>"]
    assert len(rt.captured[0].messages) == 2
    assert not (tmp_path / "workspaces" / "w_0001" / "chats").exists()


@pytest.mark.asyncio
async def test_force_plan_tool_call_returns_none_on_prose(tmp_path) -> None:
    rt = ScriptRuntime(force_outputs=["just some prose, no tool call here"])
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")
    flow = AnalysisFlow(
        chat_id="c1", run_id=state.run_id, workspace_id="w_0001",
        phase=AnalysisPhase.PLAN_PENDING, original_request="hire rate?",
    )

    args = await orch._force_plan_tool_call(
        state, flow=flow, workspace_dir=tmp_path, chat_id="c1", run_id=state.run_id,
    )
    assert args is None


@pytest.mark.asyncio
async def test_plan_pending_forced_emission_reaches_approval(tmp_path) -> None:
    rt = ScriptRuntime(force_outputs=[_TOOL_CALL])
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id="r1", workspace_id="w_0001",
        phase=AnalysisPhase.INSPECTING, original_request="hire rate?",
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    events = [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="hire rate?", requested_mode="analyst",
            prompt_provider=_provider, max_iterations=2,
        )
    ]

    assert [e for e in events if isinstance(e, ApprovalRequired)]
    flow = orch._get_flow("c1")
    assert flow is not None
    assert flow.phase is AnalysisPhase.APPROVAL_PENDING
    assert flow.plan_id is not None


@pytest.mark.asyncio
async def test_forced_emission_retry_then_recover(tmp_path) -> None:
    rt = ScriptRuntime(force_outputs=["nope, prose", _TOOL_CALL])
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id="r1", workspace_id="w_0001",
        phase=AnalysisPhase.INSPECTING, original_request="hire rate?",
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    events = [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="hire rate?", requested_mode="analyst",
            prompt_provider=_provider, max_iterations=2,
        )
    ]

    assert [e for e in events if isinstance(e, ApprovalRequired)]
    assert orch._get_flow("c1").phase is AnalysisPhase.APPROVAL_PENDING


@pytest.mark.asyncio
async def test_forced_emission_exhausted_fails_loudly(tmp_path) -> None:
    rt = ScriptRuntime(force_outputs=["prose one", "prose two"])
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id="r1", workspace_id="w_0001",
        phase=AnalysisPhase.INSPECTING, original_request="hire rate?",
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")

    events = [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=tmp_path, chat_id="c1",
            user_input="hire rate?", requested_mode="analyst",
            prompt_provider=_provider, max_iterations=2,
        )
    ]

    assert [e for e in events if isinstance(e, FinalMessage)]
    assert orch._get_flow("c1") is None  # flow dropped on FAILED
