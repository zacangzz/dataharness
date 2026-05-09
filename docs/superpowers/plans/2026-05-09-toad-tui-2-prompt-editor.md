# Toad TUI Prompt Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-line prompt with a multiline Textual prompt editor that preserves slash hints and adds `@` file mention insertion.

**Architecture:** Keep prompt behavior inside Layer 4. `PromptBar` remains the app-facing widget, but delegates text editing to a small `PromptEditor` wrapper and file mention selection to `FilePicker` from Plan 1.

**Tech Stack:** Python 3.14, Textual `TextArea`, Textual `OptionList`, file picker from `src/app/tui/file_picker.py`, pytest, pytest-asyncio.

**Repository Rule:** Do not commit during execution unless the user grants permission. End with verification and a checkpoint summary.

---

## Prerequisite

Complete `docs/superpowers/plans/2026-05-09-toad-tui-1-file-picker.md` first.

## File Structure

- Create `src/app/tui/prompt_editor.py`: `PromptEditor` TextArea wrapper with stable `text`, `set_text`, `insert_text`, and submission message behavior.
- Modify `src/app/tui/prompt_bar.py`: replace `Input` with `PromptEditor`, preserve slash hints, integrate file picker.
- Modify `src/app/tui/app.py`: update prompt submission event handling from `Input.Submitted` to prompt editor messages.
- Modify `src/app/tui/dataharness.tcss`: style prompt editor, hint list, and file picker overlay.
- Modify tests in `tests/app/tui/test_prompt_bar.py`.
- Add `tests/app/tui/test_prompt_editor.py`.

---

### Task 1: PromptEditor Wrapper

**Files:**
- Create: `src/app/tui/prompt_editor.py`
- Test: `tests/app/tui/test_prompt_editor.py`

- [ ] **Step 1: Write failing PromptEditor tests**

Add `tests/app/tui/test_prompt_editor.py`:

```python
import pytest
from textual.app import App, ComposeResult

from app.tui.prompt_editor import PromptEditor


class PromptEditorHarness(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.submitted: str | None = None

    def compose(self) -> ComposeResult:
        yield PromptEditor(id="editor")

    def on_prompt_editor_submitted(self, event: PromptEditor.Submitted) -> None:
        self.submitted = event.text


@pytest.mark.asyncio
async def test_prompt_editor_set_insert_and_text_buffer():
    app = PromptEditorHarness()
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", PromptEditor)
        editor.set_text("hello")
        editor.insert_text("\nworld")

        assert editor.text == "hello\nworld"


@pytest.mark.asyncio
async def test_prompt_editor_ctrl_j_inserts_newline_without_submit():
    app = PromptEditorHarness()
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", PromptEditor)
        editor.set_text("hello")
        editor.focus()
        await pilot.press("ctrl+j")

        assert editor.text == "hello\n"
        assert app.submitted is None


@pytest.mark.asyncio
async def test_prompt_editor_enter_submits_text():
    app = PromptEditorHarness()
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", PromptEditor)
        editor.set_text("run analysis")
        editor.focus()
        await pilot.press("enter")

        assert app.submitted == "run analysis"
        assert editor.text == ""
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_editor.py -q
```

Expected: import failure for `app.tui.prompt_editor`.

- [ ] **Step 3: Implement PromptEditor**

Create `src/app/tui/prompt_editor.py`:

```python
from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class PromptEditor(TextArea):
    can_focus = True

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(text="", language="markdown", show_line_numbers=False, **kwargs)

    @property
    def text(self) -> str:
        return self.document.text

    def set_text(self, text: str) -> None:
        self.load_text(text)
        self.move_cursor((len(self.document.lines) - 1, len(self.document.lines[-1])))

    def insert_text(self, text: str) -> None:
        self.insert(text)

    def clear_text(self) -> None:
        self.load_text("")

    def submit(self) -> None:
        value = self.text.strip()
        if not value:
            return
        self.clear_text()
        self.post_message(self.Submitted(value))

    def on_key(self, event: events.Key) -> None:
        if event.key == "ctrl+j":
            self.insert_text("\n")
            event.stop()
            event.prevent_default()
            return
        if event.key == "enter":
            self.submit()
            event.stop()
            event.prevent_default()
```

- [ ] **Step 4: Run PromptEditor tests**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_editor.py -q
```

Expected: all pass.

---

### Task 2: Replace PromptBar Input While Preserving Slash Hints

**Files:**
- Modify: `src/app/tui/prompt_bar.py`
- Modify: `src/app/tui/app.py`
- Test: `tests/app/tui/test_prompt_bar.py`

- [ ] **Step 1: Update prompt tests for editor API**

Modify `tests/app/tui/test_prompt_bar.py` imports:

```python
from app.tui.prompt_editor import PromptEditor
```

Update the first test:

```python
@pytest.mark.asyncio
async def test_prompt_bar_replaces_plain_user_input(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()

        prompt = app.query_one("#prompt_bar", PromptBar)
        assert prompt.editor.id == "user_input"
        assert isinstance(prompt.editor, PromptEditor)
```

Add a multiline submission test:

```python
@pytest.mark.asyncio
async def test_prompt_bar_multiline_editor_submits_to_app(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        prompt.prefill("line one\nline two")
        prompt.editor.submit()
        await pilot.pause()

        assert "line one" in app.query_one("#conversation").text_buffer()
        assert "line two" in app.query_one("#conversation").text_buffer()
```

- [ ] **Step 2: Run prompt tests to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_bar.py -q
```

Expected: failures because `PromptBar.editor` does not exist and app still listens for `Input.Submitted`.

- [ ] **Step 3: Modify PromptBar composition and API**

In `src/app/tui/prompt_bar.py`, replace `Input` import/use with:

```python
from app.tui.prompt_editor import PromptEditor
```

Change `compose`:

```python
    def compose(self):
        yield Static("", id="prompt_status")
        yield PromptEditor(id="user_input")
        yield Static("", id="prompt_hints")
        yield OptionList(id="prompt_hint_options")
```

Replace `input` property with compatible aliases:

```python
    @property
    def editor(self) -> PromptEditor:
        return self.query_one("#user_input", PromptEditor)

    @property
    def input(self) -> PromptEditor:
        return self.editor
```

Update `prefill` and `_prefill_argument` to use `set_text`:

```python
    def prefill(self, text: str) -> None:
        self.editor.set_text(text)
```

Where current code reads `self.input.value`, use `self.editor.text`. Where it writes `self.input.value`, use `self.editor.set_text(...)`.

- [ ] **Step 4: Update app submission handling**

In `src/app/tui/app.py`, import:

```python
from app.tui.prompt_editor import PromptEditor
```

Replace `on_input_submitted` with:

```python
    async def on_prompt_editor_submitted(self, event: PromptEditor.Submitted) -> None:
        text = event.text.strip()
        if not text:
            return
        await self.submit_user_text(text)
```

Keep the old `on_input_submitted` only if other screens still emit `Input.Submitted`; it should ignore non-prompt inputs as it does now.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_editor.py tests/app/tui/test_prompt_bar.py -q
```

Expected: all pass after updating value access.

---

### Task 3: Integrate `@` File Mentions

**Files:**
- Modify: `src/app/tui/prompt_bar.py`
- Modify: `src/app/tui/dataharness.tcss`
- Test: `tests/app/tui/test_prompt_bar.py`

- [ ] **Step 1: Add failing tests for file mention picker**

Append to `tests/app/tui/test_prompt_bar.py`:

```python
@pytest.mark.asyncio
async def test_prompt_bar_at_opens_file_picker_and_inserts_file(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        prompt.prefill("analyze @sal")
        await prompt.refresh_hints(prompt.editor.text)
        await pilot.press("enter")
        await pilot.pause()

        assert "@data/sales.csv" in prompt.editor.text


@pytest.mark.asyncio
async def test_prompt_bar_quotes_file_mentions_with_spaces(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "monthly sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        prompt.prefill("analyze @monthly")
        await prompt.refresh_hints(prompt.editor.text)
        await pilot.press("enter")
        await pilot.pause()

        assert '@"data/monthly sales.csv"' in prompt.editor.text
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_bar.py -q
```

Expected: failures because `@` handling is not implemented.

- [ ] **Step 3: Add file picker to PromptBar**

In `src/app/tui/prompt_bar.py`, import:

```python
from app.tui.file_picker import FilePicker, format_file_mention
```

Change `compose` to include a hidden picker:

```python
        yield FilePicker(self._workspace_dir(), id="prompt_file_picker")
```

Add helper methods:

```python
    def _workspace_dir(self) -> Path:
        return self.session.app_root / "workspaces" / self.state.workspace_id

    def _file_query(self, text: str) -> str | None:
        cursor_text = text
        at_index = cursor_text.rfind("@")
        if at_index < 0:
            return None
        token = cursor_text[at_index + 1 :]
        if " " in token and not token.startswith('"'):
            return None
        return token.strip('"')

    def _show_file_picker(self, query: str) -> None:
        picker = self.query_one("#prompt_file_picker", FilePicker)
        picker.index.workspace_dir = self._workspace_dir()
        picker.index.invalidate()
        picker.refresh_query(query)
        picker.display = True
```

Update `refresh_hints` before slash handling:

```python
        file_query = self._file_query(text)
        if file_query is not None:
            self.query_one("#prompt_hints", Static).update("")
            self._set_hint_options([])
            self._show_file_picker(file_query)
            return
        self.query_one("#prompt_file_picker", FilePicker).display = False
```

Add selected handler:

```python
    @on(FilePicker.Selected, "#prompt_file_picker")
    def on_file_picker_selected(self, event: FilePicker.Selected) -> None:
        text = self.editor.text
        at_index = text.rfind("@")
        if at_index < 0:
            return
        prefix = text[:at_index]
        suffix = " "
        self.editor.set_text(prefix + format_file_mention(event.path) + suffix)
        self.query_one("#prompt_file_picker", FilePicker).display = False
        event.stop()
```

- [ ] **Step 4: Style prompt file picker**

Add to `src/app/tui/dataharness.tcss`:

```css
#prompt_file_picker {
    max-height: 10;
    border: solid $primary;
    padding: 0 1;
}

#prompt_file_picker:focus {
    border: heavy $accent;
}
```

- [ ] **Step 5: Run prompt tests**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_editor.py tests/app/tui/test_file_picker.py tests/app/tui/test_prompt_bar.py -q
```

Expected: all pass.

---

### Task 4: Checkpoint Verification

**Files:**
- Verify: `src/app/tui/prompt_editor.py`
- Verify: `src/app/tui/prompt_bar.py`
- Verify: `src/app/tui/app.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/app/tui/test_prompt_editor.py tests/app/tui/test_file_picker.py tests/app/tui/test_prompt_bar.py -q
```

Expected: all pass.

- [ ] **Step 2: Run keyboard/navigation tests**

Run:

```bash
uv run pytest tests/app/tui/test_keyboard_navigation.py tests/app/tui/test_textual_app.py -q
```

Expected: pass after updating tests that assumed `Input`.

- [ ] **Step 3: Report checkpoint**

Report:

```text
Prompt editor checkpoint:
- Replaced single-line Input with PromptEditor/TextArea.
- Preserved slash hints and app submission.
- Integrated @ file mentions through FilePicker.
- Verified focused prompt and app tests.
```

