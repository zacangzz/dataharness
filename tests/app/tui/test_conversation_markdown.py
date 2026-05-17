import pytest
from textual.app import App, ComposeResult

from app.tui.conversation import AssistantMessageBlock, UserMessageBlock
from app.tui.widgets import ConversationPane


class ConversationBlockHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield UserMessageBlock("show sales", id="user")
        yield AssistantMessageBlock("## Result\n\n```python\nprint('ok')\n```", id="assistant")


@pytest.mark.asyncio
async def test_message_blocks_keep_plain_text_buffers():
    app = ConversationBlockHarness()
    async with app.run_test() as pilot:
        assert app.query_one("#user", UserMessageBlock).text_buffer() == "show sales"
        assert "print('ok')" in app.query_one("#assistant", AssistantMessageBlock).text_buffer()


@pytest.mark.asyncio
async def test_conversation_pane_streaming_does_not_duplicate_final_text(tmp_path):
    from app.events import AppRuntimeDelta
    from datetime import UTC, datetime

    app = App()
    pane = ConversationPane(id="conversation")
    async with app.run_test() as pilot:
        await app.mount(pane)
        pane.append_user("question")
        pane.append_assistant_delta(AppRuntimeDelta(
            ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
            delta_type="text", text="hello", tool_call=None,
        ))
        pane.append_assistant_delta(AppRuntimeDelta(
            ts=datetime.now(UTC), workspace_id="w", chat_id="c", run_id="r",
            delta_type="text", text=" world", tool_call=None,
        ))
        pane.finalize_assistant("hello world")

        assert pane.text_buffer().count("hello world") == 1


@pytest.mark.asyncio
async def test_conversation_pane_renders_failure_block(tmp_path):
    app = App()
    pane = ConversationPane(id="conversation")
    async with app.run_test() as pilot:
        await app.mount(pane)
        pane.append_user("question")
        pane.append_failure("runtime failed", "runtime_not_loaded")

        assert "runtime_not_loaded" in pane.text_buffer()
        assert "runtime failed" in pane.text_buffer()


@pytest.mark.asyncio
async def test_conversation_rehydrates_user_and_assistant_blocks(tmp_path):
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from harness.services.chat import ChatMessage

    app = App()
    pane = ConversationPane(id="conversation")
    record = SimpleNamespace(messages=[
        ChatMessage(
            message_id="u1",
            role="user",
            text="question",
            ts=datetime.now(UTC),
            turn_id="t1",
            active_mode="interaction",
            token_estimate=1,
        ),
        ChatMessage(
            message_id="a1",
            role="assistant",
            text="## answer",
            ts=datetime.now(UTC),
            turn_id="t1",
            active_mode="interaction",
            token_estimate=2,
        ),
    ])

    async with app.run_test() as pilot:
        await app.mount(pane)
        pane.rehydrate_from_record(record)

        assert "question" in pane.text_buffer()
        assert "## answer" in pane.text_buffer()
