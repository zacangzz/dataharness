from datetime import UTC, datetime

from app.event_mapping import to_app_event
from harness.events import (
    FinalMessage, RuntimeDelta, TurnStarted,
)


def base():
    return dict(ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r")


def test_turn_started_maps():
    h = TurnStarted(**base(), turn_id="t", user_message_id="u", active_mode="m")
    a = to_app_event(h)
    assert a.event_name == "AppTurnStarted"
    assert a.turn_id == "t"


def test_runtime_delta_maps_text():
    h = RuntimeDelta(**base(), request_id="req", seq=1, delta_type="text", text="hi", tool_call=None)
    a = to_app_event(h)
    assert a.event_name == "AppRuntimeDelta"
    assert a.text == "hi"


def test_final_message_maps_with_usage():
    h = FinalMessage(**base(), assistant_message_id="a", text="done", usage={"completion_tokens": 5})
    a = to_app_event(h)
    assert a.event_name == "AppFinalMessage"
    assert a.usage["completion_tokens"] == 5
