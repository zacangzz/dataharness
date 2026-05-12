import pytest

from runtime.types import RuntimeMessage, ModelBehaviorError, RuntimeEvent, RuntimeInputError, RuntimeRequest


async def collect_text(runtime, request):
    pieces = []
    finish = None
    async for ev in runtime.stream(request):
        if ev.type == "text_delta":
            pieces.append(ev.text or "")
        if ev.type == "finish":
            finish = ev
    return "".join(pieces), finish


def test_runtime_request_keeps_message_order() -> None:
    request = RuntimeRequest(
        messages=[
            RuntimeMessage(role="system", content="sys"),
            RuntimeMessage(role="user", content="hello"),
        ],
        max_completion_tokens=128,
        request_id="req-1",
    )
    assert [message.role for message in request.messages] == ["system", "user"]
    assert request.max_completion_tokens == 128


def test_runtime_event_supports_reasoning_finish_and_tool_calls() -> None:
    text_event = RuntimeEvent(type="text_delta", request_id="r", seq=0, text="hel")
    reasoning_event = RuntimeEvent(type="reasoning_delta", request_id="r", seq=1, text="thinking")
    tool_event = RuntimeEvent(
        type="tool_call",
        request_id="r",
        seq=2,
        tool_call={"name": "doctor", "arguments": {"mode": "manual"}},
    )
    finish_event = RuntimeEvent(
        type="finish", request_id="r", seq=3,
        finish_reason="stop", usage={"prompt_tokens": 12, "completion_tokens": 8}
    )
    assert text_event.type == "text_delta"
    assert reasoning_event.type == "reasoning_delta"
    assert tool_event.tool_call["name"] == "doctor"
    assert finish_event.usage["prompt_tokens"] == 12


def test_runtime_errors_are_specific_exception_types() -> None:
    with pytest.raises(RuntimeInputError):
        raise RuntimeInputError("over budget")
    with pytest.raises(ModelBehaviorError):
        raise ModelBehaviorError("malformed tool call")
