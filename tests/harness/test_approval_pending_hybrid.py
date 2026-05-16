import pytest

from harness.analysis_flow import AnalysisFlow, AnalysisPhase
from harness.control import Plan, PlanStep, RunStateRecord
from harness.events import ApprovalRequired, FinalMessage, PlanReady, RuntimeDelta
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeEvent, TokenPressure


class RecordingRuntime:
    def __init__(self):
        self.calls = []

    async def stream(self, request):
        self.calls.append(request)
        yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0,
                           text="It uses two steps because the data is split.")
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


def _seed_plan(orch: Orchestrator) -> Plan:
    step = PlanStep(
        workspace_id="w_0001", plan_id="plan_x", step_order=1,
        purpose="Count hires", kind="code",
        declared_inputs=["data/employees.csv"], expected_outputs=["result.txt"],
        code="from pathlib import Path\nPath('result.txt').write_text('1')",
    )
    plan = Plan(
        id="plan_x", workspace_id="w_0001", run_id="run_x", goal="hire rate",
        steps=[step], requires_code_execution=True,
    )
    orch._pending_plans["plan_x"] = plan
    return plan


def _flow(orch: Orchestrator) -> None:
    orch._analysis_flows["c1"] = AnalysisFlow(
        chat_id="c1", run_id="run_x", workspace_id="w_0001",
        phase=AnalysisPhase.APPROVAL_PENDING, plan_id="plan_x",
        original_request="hire rate?",
    )


async def _run(orch, text):
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    return [
        e async for e in orch.run_agentic_turn(
            state, workspace_dir=orch.app_root, chat_id="c1",
            user_input=text, requested_mode="interaction",
            prompt_provider=_provider, max_iterations=2,
        )
    ]


@pytest.mark.asyncio
async def test_approve_is_deterministic_no_model_turn(tmp_path) -> None:
    rt = RecordingRuntime()
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    _seed_plan(orch)
    _flow(orch)

    events = await _run(orch, "ok proceed")

    assert [e for e in events if isinstance(e, PlanReady)]
    assert [e for e in events if isinstance(e, ApprovalRequired)]
    assert not [e for e in events if isinstance(e, RuntimeDelta)]
    assert rt.calls == []  # NO model turn → cannot hallucinate
    assert orch._get_flow("c1").phase is AnalysisPhase.APPROVAL_PENDING


@pytest.mark.asyncio
async def test_show_plan_renders_stashed_plan_no_model(tmp_path) -> None:
    rt = RecordingRuntime()
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    _seed_plan(orch)
    _flow(orch)

    events = await _run(orch, "show me the plan")

    pr = [e for e in events if isinstance(e, PlanReady)]
    assert pr and pr[0].plan_id == "plan_x"
    assert not [e for e in events if isinstance(e, ApprovalRequired)]
    assert rt.calls == []
    assert orch._get_flow("c1").phase is AnalysisPhase.APPROVAL_PENDING


@pytest.mark.asyncio
async def test_reject_cancels_and_drops_flow(tmp_path) -> None:
    rt = RecordingRuntime()
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    _seed_plan(orch)
    _flow(orch)

    events = await _run(orch, "cancel")

    assert [e for e in events if isinstance(e, FinalMessage)]
    assert rt.calls == []
    assert orch._get_flow("c1") is None
    assert "plan_x" not in orch._pending_plans


@pytest.mark.asyncio
async def test_freeform_question_runs_grounded_model_turn(tmp_path) -> None:
    rt = RecordingRuntime()
    orch = Orchestrator(runtime=rt, app_root=tmp_path)
    _seed_plan(orch)
    _flow(orch)

    events = await _run(orch, "why does it need two steps?")

    assert rt.calls, "free-form question must run a model turn"
    injected = rt.calls[0]
    blob = " ".join(m.content for m in injected.messages)
    assert "AWAITING YOUR APPROVAL" in blob
    assert "hire rate" in blob  # plan goal grounded into context
    assert [e for e in events if isinstance(e, FinalMessage)]
    # Flow remains pending (question did not approve/reject).
    assert orch._get_flow("c1").phase is AnalysisPhase.APPROVAL_PENDING
