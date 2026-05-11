import pytest
from pydantic import ValidationError

from runtime.types import (
    RuntimeMessage, RuntimeRequest, RuntimeEvent, TokenPressure,
)


def test_runtime_message_roles():
    for role in ("system", "user", "assistant", "tool"):
        m = RuntimeMessage(role=role, content="x")
        assert m.role == role


def test_runtime_message_invalid_role():
    with pytest.raises(ValidationError):
        RuntimeMessage(role="other", content="x")


def test_runtime_request_defaults():
    r = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content="hi")],
        max_completion_tokens=128,
        request_id="req_1",
    )
    assert r.temperature == 1.0
    assert r.top_k == 64
    assert r.top_p == 0.95
    assert r.stop == []
    assert r.tools == []
    assert r.correlation_id is None


def test_runtime_event_text_delta():
    e = RuntimeEvent(type="text_delta", request_id="r1", seq=0, text="hello")
    assert e.text == "hello"


def test_runtime_event_finish_carries_usage():
    e = RuntimeEvent(
        type="finish", request_id="r1", seq=10,
        finish_reason="stop", usage={"prompt_tokens": 5, "completion_tokens": 3},
    )
    assert e.usage["completion_tokens"] == 3


def test_token_pressure_over_threshold_true():
    p = TokenPressure(
        request_id="r", context_window=1000, prompt_tokens=900,
        reserved_completion_tokens=0, total_tokens=900, pressure_ratio=0.9,
        over_threshold=True,
    )
    assert p.over_threshold is True
