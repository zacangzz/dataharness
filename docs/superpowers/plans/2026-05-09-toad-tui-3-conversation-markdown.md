# Toad TUI Markdown Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render DataHarness conversations as structured user/assistant blocks with Markdown assistant output and reliable streaming finalization.

**Architecture:** Keep event flow unchanged. `DataHarnessApp` still calls `ConversationPane.append_user`, `append_assistant_delta`, `finalize_assistant`, `discard_streaming`, and `rehydrate_from_record`; `ConversationPane` changes its internals from full-string `RichLog` rerendering to block widgets.

**Tech Stack:** Python 3.14, Textual `VerticalScroll`, Textual `Markdown`, `Static`, pytest, pytest-asyncio.

**Repository Rule:** Do not commit during execution unless the user grants permission. End with verification and a checkpoint summary.

---

## Prerequisite

This plan can run after Plan 1. It does not require the prompt editor plan, but it should be merged with prompt changes carefully because both touch `src/app/tui/widgets.py` and `src/app/tui/dataharness.tcss`.

## File Structure

- Create `src/app/tui/conversation.py`: `UserMessageBlock`, `AssistantMessageBlock`, `SystemMessageBlock`, and streaming buffer helpers.
- Modify `src/app/tui/widgets.py`: make `ConversationPane` a scrollable block container or a wrapper around one.
- Modify `src/app/tui/app.py`: only if query type expectations change.
- Modify `src/app/tui/dataharness.tcss`: style conversation blocks and Markdown.
- Add `tests/app/tui/test_conversation_markdown.py`.
- Update existing `tests/app/tui/test_textual_app.py` where it asserts `ConversationPane` inheritance details.

---

### Task 1: Message Block Widgets

**Files:**
- Create: `src/app/tui/conversation.py`
- Test: `tests/app/tui/test_conversation_markdown.py`

- [ ] **Step 1: Write failing block tests**

Add `tests/app/tui/test_conversation_markdown.py`:

```python
import pytest
from textual.app import App, ComposeResult

from app.tui.conversation import AssistantMessageBlock, UserMessageBlock


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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_conversation_markdown.py -q
```

Expected: import failure for `app.tui.conversation`.

- [ ] **Step 3: Implement message blocks**

Create `src/app/tui/conversation.py`:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static


class UserMessageBlock(Static):
    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self._text = text
        self.add_class("message-user")

    def text_buffer(self) -> str:
        return self._text


class AssistantMessageBlock(Vertical):
    def __init__(self, text: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self.add_class("message-assistant")

    def compose(self) -> ComposeResult:
        yield Markdown(self._text, id="assistant_markdown")

    def update_text(self, text: str) -> None:
        self._text = text
        markdown = self.query_one("#assistant_markdown", Markdown)
        markdown.update(text)

    def append_delta(self, text: str) -> None:
        if text:
            self.update_text(self._text + text)

    def text_buffer(self) -> str:
        return self._text


class SystemMessageBlock(Static):
    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self._text = text
        self.add_class("message-system")

    def text_buffer(self) -> str:
        return self._text
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/app/tui/test_conversation_markdown.py -q
```

Expected: pass.

---

### Task 2: Replace ConversationPane Internals

**Files:**
- Modify: `src/app/tui/widgets.py`
- Test: `tests/app/tui/test_conversation_markdown.py`
- Test: `tests/app/tui/test_textual_app.py`

- [ ] **Step 1: Add failing ConversationPane behavior tests**

Append:

```python
from app.tui.widgets import ConversationPane


@pytest.mark.asyncio
async def test_conversation_pane_streaming_does_not_duplicate_final_text(tmp_path):
    from app.events import AppRuntimeDelta

    app = App()
    pane = ConversationPane(id="conversation")
    async with app.run_test() as pilot:
        await app.mount(pane)
        pane.append_user("question")
        pane.append_assistant_delta(AppRuntimeDelta(text="hello", delta_type="text"))
        pane.append_assistant_delta(AppRuntimeDelta(text=" world", delta_type="text"))
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_conversation_markdown.py -q
```

Expected: failure because `append_failure` does not exist and `ConversationPane` still rerenders one string.

- [ ] **Step 3: Modify ConversationPane**

In `src/app/tui/widgets.py`, change `ConversationPane` to use `VerticalScroll`:

```python
from textual.containers import VerticalScroll
from app.tui.conversation import AssistantMessageBlock, SystemMessageBlock, UserMessageBlock
```

Replace class base and methods:

```python
class ConversationPane(VerticalScroll):
    can_focus = True
    help = HelpData(
        title="Conversation",
        description="Shows the current chat transcript and streamed assistant responses.",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._blocks: list[object] = []
        self._streaming_block: AssistantMessageBlock | None = None

    def append_user(self, text: str) -> None:
        block = UserMessageBlock(text)
        self._blocks.append(block)
        self.mount(block)
        self.scroll_end(animate=False)

    def append_assistant(self, text: str) -> None:
        block = AssistantMessageBlock(text)
        self._blocks.append(block)
        self.mount(block)
        self.scroll_end(animate=False)

    def append_assistant_delta(self, event) -> None:
        if self._streaming_block is None:
            self._streaming_block = AssistantMessageBlock("")
            self._blocks.append(self._streaming_block)
            self.mount(self._streaming_block)
        self._streaming_block.append_delta(event.text)
        self.scroll_end(animate=False)

    def finalize_assistant(self, text: str) -> None:
        if self._streaming_block is None:
            self.append_assistant(text)
            return
        self._streaming_block.update_text(text)
        self._streaming_block = None
        self.scroll_end(animate=False)

    def append_failure(self, summary: str, error_code: str) -> None:
        self.discard_streaming()
        block = SystemMessageBlock(f"{error_code}: {summary}")
        self._blocks.append(block)
        self.mount(block)
        self.scroll_end(animate=False)

    def discard_streaming(self) -> None:
        self._streaming_block = None

    def text_buffer(self) -> str:
        parts: list[str] = []
        for block in self._blocks:
            text_buffer = getattr(block, "text_buffer", None)
            if callable(text_buffer):
                parts.append(text_buffer())
        return "\n".join(parts)
```

- [ ] **Step 4: Update app failure handling**

In `src/app/tui/app.py`, update `_handle_turn_failed`:

```python
    def _handle_turn_failed(self, event) -> None:
        self._trace.failed(event.failure_summary, event.error_code)
        conversation = self.query_one("#conversation", ConversationPane)
        conversation.append_failure(event.failure_summary, event.error_code)
        self.query_one("#sidebar", SidebarPane).failure(event.failure_summary, event.error_code)
        self._refresh_trace_widgets()
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/app/tui/test_conversation_markdown.py tests/app/tui/test_textual_app.py -q
```

Expected: pass after adjusting tests that assumed `RichLog`.

---

### Task 3: Chat Rehydration And Styling

**Files:**
- Modify: `src/app/tui/widgets.py`
- Modify: `src/app/tui/dataharness.tcss`
- Test: `tests/app/tui/test_conversation_markdown.py`

- [ ] **Step 1: Add rehydration test**

Append:

```python
@pytest.mark.asyncio
async def test_conversation_rehydrates_user_and_assistant_blocks(tmp_path):
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from harness.chat import ChatMessage

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
```

- [ ] **Step 2: Implement async-safe rehydration**

In `ConversationPane.rehydrate_from_record`:

```python
    def rehydrate_from_record(self, record) -> None:
        self.remove_children()
        self._blocks = []
        self._streaming_block = None
        for message in record.messages:
            if message.role == "user":
                self.append_user(message.text)
            elif message.role == "assistant":
                self.append_assistant(message.text)
            else:
                block = SystemMessageBlock(message.text)
                self._blocks.append(block)
                self.mount(block)
```

If Textual requires awaiting child removal in the current version, wrap the rebuild in an async method and make `DataHarnessApp.action_resume_chat` await it. Keep a synchronous `text_buffer` either way.

- [ ] **Step 3: Add TCSS**

Add:

```css
.message-user {
    margin: 1 0 0 0;
    padding: 0 1;
    border-left: solid $accent;
}

.message-assistant {
    margin: 1 0 0 0;
    padding: 0 1;
    border-left: solid $primary;
}

.message-system {
    margin: 1 0 0 0;
    padding: 0 1;
    color: $warning;
    border-left: solid $warning;
}
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/app/tui/test_conversation_markdown.py tests/app/tui/test_textual_app.py tests/app/tui/test_event_streaming.py -q
```

Expected: pass.

---

### Task 4: Checkpoint Verification

**Files:**
- Verify: `src/app/tui/conversation.py`
- Verify: `src/app/tui/widgets.py`
- Verify: `src/app/tui/app.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/app/tui/test_conversation_markdown.py tests/app/tui/test_textual_app.py tests/app/tui/test_event_streaming.py -q
```

Expected: all pass.

- [ ] **Step 2: Report checkpoint**

Report:

```text
Markdown conversation checkpoint:
- Added structured user/assistant/system blocks.
- Assistant output uses Markdown rendering.
- Streaming finalization avoids duplicate final text.
- Chat rehydration rebuilds block structure.
```

