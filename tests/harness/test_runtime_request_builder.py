from datetime import UTC, datetime

from harness.chat import (
    ChatMessage, ChatRecord, RuntimeRequestBuilder,
)


def make_msg(role, text, mode=None):
    return ChatMessage(
        message_id="m", role=role, text=text, ts=datetime.now(UTC),
        turn_id=None, active_mode=mode, token_estimate=max(len(text)//4, 1),
    )


def make_record(messages):
    return ChatRecord(
        chat_id="c", workspace_id="w", title=None,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        last_active_mode=None, last_run_id=None,
        message_count=len(messages),
        token_estimate=sum(m.token_estimate for m in messages),
        last_compacted_at=None, compaction_count=0, messages=messages,
    )


def test_builder_includes_system_then_durable_then_chat_then_user():
    b = RuntimeRequestBuilder(context_window=4096)
    msgs = b.build_messages(
        active_mode_prompt="ANALYST",
        durable_context="MEMORY",
        chat_record=make_record([
            make_msg("user", "first"), make_msg("assistant", "answer"),
        ]),
        current_user_text="latest",
    )
    roles = [m.role for m in msgs]
    contents = [m.content for m in msgs]
    assert roles[0] == "system" and "ANALYST" in contents[0]
    assert any("MEMORY" in c for c in contents)
    assert msgs[-1].role == "user" and msgs[-1].content == "latest"


def test_builder_does_not_duplicate_current_user_when_in_chat_record():
    b = RuntimeRequestBuilder(context_window=4096)
    msgs = b.build_messages(
        active_mode_prompt="P",
        durable_context="",
        chat_record=make_record([
            make_msg("assistant", "prior reply"),
            make_msg("user", "latest"),
        ]),
        current_user_text="latest",
    )
    user_latest = [m for m in msgs if m.role == "user" and m.content == "latest"]
    assert len(user_latest) == 1


def test_builder_gemma_merges_system_into_first_user():
    b = RuntimeRequestBuilder(context_window=4096, chat_format="gemma")
    msgs = b.build_messages(
        active_mode_prompt="PERSONA",
        durable_context="WORKSPACE",
        chat_record=None,
        current_user_text="hello",
    )
    assert all(m.role != "system" for m in msgs)
    assert msgs[-1].role == "user"
    assert "[SYSTEM]" in msgs[-1].content
    assert "PERSONA" in msgs[-1].content
    assert "WORKSPACE" in msgs[-1].content
    assert msgs[-1].content.endswith("hello")


def test_builder_gemma_merges_system_only_on_first_user_in_history():
    b = RuntimeRequestBuilder(context_window=4096, chat_format="gemma")
    msgs = b.build_messages(
        active_mode_prompt="PERSONA",
        durable_context="",
        chat_record=make_record([
            make_msg("user", "first"),
            make_msg("assistant", "ok"),
            make_msg("user", "second"),
        ]),
        current_user_text="second",
    )
    assert all(m.role != "system" for m in msgs)
    user_msgs = [m for m in msgs if m.role == "user"]
    assert "[SYSTEM]" in user_msgs[0].content
    assert "PERSONA" in user_msgs[0].content
    assert user_msgs[0].content.endswith("first")
    for u in user_msgs[1:]:
        assert "[SYSTEM]" not in u.content


def test_builder_keeps_recent_8_turns_only():
    older = [make_msg("user" if i % 2 == 0 else "assistant", f"old{i}") for i in range(20)]
    b = RuntimeRequestBuilder(context_window=4096)
    msgs = b.build_messages(
        active_mode_prompt="P", durable_context="",
        chat_record=make_record(older), current_user_text="now",
    )
    user_msgs = [m for m in msgs if m.role == "user"]
    # 8 recent (4u/4a) + final user input
    assert sum(1 for m in user_msgs if m.content != "now") <= 4


def test_builder_respects_completion_reservation_25_pct():
    b = RuntimeRequestBuilder(context_window=1000)
    assert b.completion_reservation == 250


def test_builder_includes_compacted_summary_marker():
    msgs_in = [
        make_msg("compacted_summary", "OLD-SUMMARY"),
        make_msg("user", "after"),
        make_msg("assistant", "ok"),
    ]
    b = RuntimeRequestBuilder(context_window=4096)
    msgs = b.build_messages(
        active_mode_prompt="P", durable_context="",
        chat_record=make_record(msgs_in), current_user_text="now",
    )
    assert any("OLD-SUMMARY" in m.content for m in msgs if m.role == "system")
