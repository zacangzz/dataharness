from datetime import UTC, datetime

from app.events import AppFinalMessage, AppRuntimeDelta, AppTurnStarted
from app.tui.event_consumer import EventConsumer
from app.tui.widgets import ConversationPane


def test_consumer_routes_runtime_delta_to_conversation():
    pane = ConversationPane()
    consumer = EventConsumer({"AppRuntimeDelta": pane.append_assistant_delta,
                              "AppFinalMessage": lambda e: pane.finalize_assistant(e.text),
                              "AppTurnStarted": lambda e: pane.append_user("(user input cached elsewhere)")})

    consumer.dispatch(AppTurnStarted(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        turn_id="t", user_message_id="u", active_mode="m",
    ))
    consumer.dispatch(AppRuntimeDelta(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        delta_type="text", text="hel", tool_call=None,
    ))
    consumer.dispatch(AppRuntimeDelta(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        delta_type="text", text="lo", tool_call=None,
    ))
    consumer.dispatch(AppFinalMessage(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        assistant_message_id="a", text="hello", usage={},
    ))
    rendered = pane.text_buffer()
    assert "hello" in rendered


def test_reasoning_delta_does_not_append_to_conversation():
    pane = ConversationPane()

    pane.append_assistant_delta(AppRuntimeDelta(
        ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
        delta_type="reasoning", text="hidden chain of thought", tool_call=None,
    ))

    assert "hidden chain of thought" not in pane.text_buffer()
    assert pane.text_buffer() == ""
