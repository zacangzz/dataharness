from datetime import UTC, datetime
from pathlib import Path

from harness.chat import ChatMessage
from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeEvent, TokenPressure


class PressuredRuntime:
    def __init__(self, *, over_threshold: bool) -> None:
        self.over_threshold = over_threshold
        self.requests: list = []

    async def stream(self, request):
        self.requests.append(request)
        yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0, text="done")
        yield RuntimeEvent(type="finish", request_id=request.request_id, seq=1, finish_reason="stop", usage={})

    async def context_window(self):
        return 1024

    async def token_pressure(self, request):
        prompt_tokens = 900 if self.over_threshold else 100
        total = prompt_tokens + request.max_completion_tokens
        return TokenPressure(
            request_id=request.request_id,
            context_window=1024,
            prompt_tokens=prompt_tokens,
            reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=total,
            pressure_ratio=total / 1024,
            over_threshold=self.over_threshold,
        )

    async def validate_request(self, request):
        return None

    async def status(self):
        return "ready"


async def collect(agen):
    return [event async for event in agen]


async def seed_old_chat(orchestrator: Orchestrator, workspace_id: str) -> str:
    summary = await orchestrator.create_chat(workspace_id=workspace_id, title=None)
    for index in range(12):
        role = "user" if index % 2 == 0 else "assistant"
        await orchestrator.chat_store.append_message(summary.chat_id, ChatMessage(
            message_id=f"m{index}",
            role=role,
            text=f"old message {index}",
            ts=datetime.now(UTC),
            turn_id=None,
            active_mode="interaction",
            token_estimate=4,
        ))
    return summary.chat_id


async def test_orchestrator_compacts_chat_before_runtime_when_pressure_over_threshold(tmp_path: Path) -> None:
    runtime = PressuredRuntime(over_threshold=True)
    orchestrator = Orchestrator(runtime=runtime, app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    chat_id = await seed_old_chat(orchestrator, "w_0001")

    await collect(orchestrator.run_turn(
        state,
        workspace_dir=tmp_path / "workspaces" / "w_0001",
        chat_id=chat_id,
        user_input="hi",
        requested_mode="interaction",
        prompt_text="prompt",
    ))

    record = await orchestrator.view_chat(chat_id)
    assert record.compaction_count == 1
    assert record.messages[0].role == "compacted_summary"
    turn_requests = [request for request in runtime.requests if request.correlation_id == state.run_id]
    assert len(turn_requests) == 1
    assert any("PRIOR CHAT SUMMARY" in message.content for message in turn_requests[0].messages)


async def test_orchestrator_skips_compaction_when_pressure_is_below_threshold(tmp_path: Path) -> None:
    runtime = PressuredRuntime(over_threshold=False)
    orchestrator = Orchestrator(runtime=runtime, app_root=tmp_path)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    chat_id = await seed_old_chat(orchestrator, "w_0001")

    await collect(orchestrator.run_turn(
        state,
        workspace_dir=tmp_path / "workspaces" / "w_0001",
        chat_id=chat_id,
        user_input="hi",
        requested_mode="interaction",
        prompt_text="prompt",
    ))

    record = await orchestrator.view_chat(chat_id)
    assert record.compaction_count == 0
    assert all(message.role != "compacted_summary" for message in record.messages)
    assert len(runtime.requests) == 1
