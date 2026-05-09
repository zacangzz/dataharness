import asyncio
from collections.abc import AsyncIterator

import pytest

from harness.events import (
    HarnessEvent, TurnStarted, RuntimeDelta, FinalMessage,
)
from harness.exceptions import RunAlreadyActive
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord
from runtime.types import RuntimeEvent, RuntimeRequest


class FakeRuntime:
    def __init__(self, deltas):
        self._deltas = deltas

    async def stream(self, request):
        seq = 0
        for d in self._deltas:
            yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=seq, text=d)
            seq += 1
        yield RuntimeEvent(
            type="finish", request_id=request.request_id, seq=seq,
            finish_reason="stop", usage={"prompt_tokens": 1, "completion_tokens": len(self._deltas)},
        )

    async def context_window(self): return 4096
    async def token_pressure(self, request):
        from runtime.types import TokenPressure
        return TokenPressure(
            request_id=request.request_id, context_window=4096,
            prompt_tokens=10, reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=10 + request.max_completion_tokens,
            pressure_ratio=0.05, over_threshold=False,
        )
    async def validate_request(self, request): return None
    async def status(self): return "ready"


@pytest.fixture
def orch(tmp_path):
    rt = FakeRuntime(["hel", "lo"])
    o = Orchestrator(runtime=rt, app_root=tmp_path)
    return o


def make_state():
    return RunStateRecord(workspace_id="w1", active_agent_mode="interaction")


async def collect(agen: AsyncIterator[HarnessEvent]):
    return [ev async for ev in agen]


async def test_run_turn_emits_turnstarted_then_deltas_then_final(orch, tmp_path):
    state = make_state()
    events = await collect(orch.run_turn(
        state, workspace_dir=tmp_path, chat_id="c1", user_input="hi",
    ))
    types = [e.event_name for e in events]
    assert types[0] == "TurnStarted"
    assert "RuntimeDelta" in types
    assert types[-1] == "FinalMessage"
    final = events[-1]
    assert final.text == "hello"


async def test_concurrent_run_raises_run_already_active(orch, tmp_path):
    state = make_state()
    agen = orch.run_turn(state, workspace_dir=tmp_path, chat_id="c1", user_input="hi")
    await agen.__anext__()
    with pytest.raises(RunAlreadyActive):
        async for _ in orch.run_turn(state, workspace_dir=tmp_path, chat_id="c1", user_input="hi2"):
            pass
    async for _ in agen:
        pass


async def test_cancel_run_returns_turncancelled(orch, tmp_path):
    state = make_state()
    agen = orch.run_turn(state, workspace_dir=tmp_path, chat_id="c1", user_input="hi")
    first = await agen.__anext__()
    cancelled = await orch.cancel_run(first.run_id, reason="user")
    assert cancelled.event_name == "TurnCancelled"
    assert cancelled.reason == "user"
    # Drain
    async for _ in agen:
        pass


async def test_orchestrator_close_drains_status_broker(orch, tmp_path):
    # Start the broker by calling watch_status once
    snap_iter = orch.watch_status()
    first_snap = await snap_iter.__anext__()
    assert first_snap is not None

    broker = orch._status_broker
    assert broker is not None
    assert len(broker._subscribers) == 1

    # close() should signal the subscriber and drain it
    close_task = asyncio.create_task(orch.close())
    # Drain the generator; it should terminate after close sends _CLOSE sentinel
    async for _ in snap_iter:
        pass
    await close_task

    assert len(broker._subscribers) == 0
