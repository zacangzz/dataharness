"""Runtime bridge tests — migrated to async run_turn (was sync handle_turn + RuntimeResponse)."""
from pathlib import Path

from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeEvent


class CapturingRuntime:
    def __init__(self) -> None:
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        yield RuntimeEvent(
            type="text_delta", request_id=request.request_id, seq=0,
            text="Use the workspace status command.",
        )
        yield RuntimeEvent(
            type="finish", request_id=request.request_id, seq=1,
            finish_reason="stop", usage={"prompt_tokens": 5, "completion_tokens": 8},
        )

    async def context_window(self):
        return 4096

    async def token_pressure(self, request):
        from runtime.types import TokenPressure
        return TokenPressure(
            request_id=request.request_id, context_window=4096,
            prompt_tokens=18, reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=18 + request.max_completion_tokens,
            pressure_ratio=0.1, over_threshold=False,
        )

    async def validate_request(self, request):
        return None

    async def status(self):
        return "ready"


async def test_orchestrator_builds_prompt_and_calls_single_runtime(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text('{"style": "concise"}')
    runtime = CapturingRuntime()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    events = [e async for e in Orchestrator(runtime=runtime, app_root=tmp_path).run_turn(
        state,
        workspace_dir=workspace,
        chat_id="c1",
        user_input="show status",
        prompt_text="You are the interaction mode for the local data analysis application.",
    )]
    final = next(e for e in events if e.event_name == "FinalMessage")
    assert final.text == "Use the workspace status command."
    assert events[0].event_name == "TurnStarted"
    assert events[1].mode == "interaction"  # ModeActivated
    request = runtime.requests[0]
    assert request.messages[0].role == "system"
    assert "interaction mode" in request.messages[0].content
    assert request.messages[-1].content == "show status"
