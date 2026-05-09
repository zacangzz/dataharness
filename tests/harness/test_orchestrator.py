from datetime import UTC, datetime

from harness.control import ApprovalRecord, Plan, PlanStep, RunStateRecord
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeEvent, TokenPressure


class FakeRuntime:
    async def stream(self, request):
        yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0, text="hello")
        yield RuntimeEvent(type="finish", request_id=request.request_id, seq=1, finish_reason="stop", usage={})

    async def context_window(self):
        return 4096

    async def token_pressure(self, request):
        return TokenPressure(
            request_id=request.request_id,
            context_window=4096,
            prompt_tokens=1,
            reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=1 + request.max_completion_tokens,
            pressure_ratio=0.1,
            over_threshold=False,
        )

    async def validate_request(self, request):
        return None

    async def status(self):
        return "ready"


async def test_orchestrator_run_turn_emits_events(tmp_path) -> None:
    """Async replacement for legacy test_orchestrator_reloads_context_before_routing_turn."""
    orchestrator = Orchestrator(runtime=FakeRuntime(), app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in orchestrator.run_turn(
        state, workspace_dir=tmp_path, chat_id="c1", user_input="show status"
    )]
    names = [e.event_name for e in events]
    assert names[0] == "TurnStarted"
    assert names[-1] == "FinalMessage"


async def test_orchestrator_reports_runtime_not_loaded_instead_of_empty_response(tmp_path) -> None:
    orchestrator = Orchestrator(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    events = [e async for e in orchestrator.run_turn(
        state, workspace_dir=tmp_path, chat_id="c1", user_input="hello"
    )]

    assert events[-1].event_name == "TurnFailed"
    assert events[-1].error_code == "runtime_not_loaded"


def test_orchestrator_blocks_worker_dispatch_without_code_approval() -> None:
    step = PlanStep(
        workspace_id="w_0001",
        plan_id="plan_1",
        step_order=1,
        purpose="Compute",
        kind="code",
        declared_inputs=["data/input.csv"],
        expected_outputs=["artifacts/output.csv"],
    )
    plan = Plan(
        id="plan_1",
        workspace_id="w_0001",
        run_id="run_1",
        goal="Compute",
        steps=[step],
        requires_code_execution=True,
    )
    orchestrator = Orchestrator()
    blocked = orchestrator.prepare_worker_dispatch(plan, approval=None)
    assert blocked["dispatch"] is False
    assert blocked["reason"] == "explicit code execution approval required"
    approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id="run_1",
        target_type="plan",
        target_id="plan_1",
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at=datetime.now(UTC),
    )
    allowed = orchestrator.prepare_worker_dispatch(plan, approval=approval)
    assert allowed["dispatch"] is True
