from datetime import UTC, datetime

import pytest

from app.tui.conversation import (
    AssistantMessageBlock, CompactionSummaryBlock, UserMessageBlock,
)
from app.tui.widgets import ConversationPane
from harness.services.chat import ChatMessage, ChatRecord


def _msg(role: str, text: str, idx: int) -> ChatMessage:
    return ChatMessage(
        message_id=f"m{idx}", role=role, text=text, ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=2,
    )


@pytest.mark.asyncio
async def test_rehydrate_renders_compaction_summary_block():
    pane = ConversationPane(id="conversation")
    record = ChatRecord(
        chat_id="c1", workspace_id="w", title=None,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        last_active_mode=None, last_run_id=None,
        message_count=3, token_estimate=6,
        last_compacted_at=datetime.now(UTC), compaction_count=1,
        messages=[
            _msg("compacted_summary", "earlier turns summarized", 0),
            _msg("user", "what now?", 1),
            _msg("assistant", "reply", 2),
        ],
    )
    pane.rehydrate_from_record(record)
    kinds = [type(b).__name__ for b in pane._blocks]
    assert kinds == ["CompactionSummaryBlock", "UserMessageBlock", "AssistantMessageBlock"]
    summary = pane._blocks[0]
    assert isinstance(summary, CompactionSummaryBlock)
    assert "earlier turns summarized" in summary.text_buffer()
