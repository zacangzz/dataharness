# Toad TUI Sidebar And Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the sidebar and workspace manager into navigable, structured DataHarness status surfaces.

**Architecture:** Keep sidebar rendering in Layer 4 and feed it only from existing app events, status snapshots, and `AppSession` facade calls. Reuse the file picker/list model from Plan 1 for workspace file panels.

**Tech Stack:** Python 3.14, Textual `Static`, `OptionList`, `ListView`, `VerticalScroll`, pytest, pytest-asyncio.

**Repository Rule:** Do not commit during execution unless the user grants permission. End with verification and a checkpoint summary.

---

## Prerequisite

Complete `docs/superpowers/plans/2026-05-09-toad-tui-1-file-picker.md` first. This plan can run before or after the prompt/conversation plans if edits are merged carefully.

## File Structure

- Create `src/app/tui/sidebar.py`: small section renderers and `SidebarState`.
- Modify `src/app/tui/widgets.py`: replace text-only `SidebarPane` internals with structured sections while preserving current public methods.
- Modify `src/app/tui/screens/workspace_manager.py`: reuse file index/list model, make file panel navigable.
- Modify `src/app/tui/dataharness.tcss`: style sidebar sections and workspace manager panels.
- Add `tests/app/tui/test_sidebar_sections.py`.
- Update `tests/app/tui/test_textual_app.py` and `tests/app/tui/test_keyboard_navigation.py` as needed.

---

### Task 1: Sidebar State And Section Rendering

**Files:**
- Create: `src/app/tui/sidebar.py`
- Test: `tests/app/tui/test_sidebar_sections.py`

- [ ] **Step 1: Write failing pure rendering tests**

Add `tests/app/tui/test_sidebar_sections.py`:

```python
from app.tui.sidebar import SidebarState


def test_sidebar_state_renders_stable_sections():
    state = SidebarState()
    state.update_status(
        workspace_id="w_0001",
        run_state="idle",
        active_mode="interaction",
        runtime_status="ready",
        chat_id="chat_1",
    )
    state.set_files(["data/sales.csv"])
    state.set_chats(["chat_1"])
    state.update_trace(["turn started"])

    text = state.text_buffer()

    assert "WORKSPACE" in text
    assert "CHAT" in text
    assert "FILES" in text
    assert "TRACE" in text
    assert "COMMANDS" in text
    assert "DOCTOR" in text
    assert "FAILURES" in text
    assert "data/sales.csv" in text
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_sidebar_sections.py -q
```

Expected: import failure for `app.tui.sidebar`.

- [ ] **Step 3: Implement SidebarState**

Create `src/app/tui/sidebar.py`:

```python
from __future__ import annotations

from collections import deque


class SidebarState:
    def __init__(self) -> None:
        self.workspace_id = "unknown"
        self.run_state = "starting"
        self.active_mode = "interaction"
        self.runtime_status = "checking"
        self.chat_id: str | None = None
        self.files: list[str] = []
        self.chats: list[str] = []
        self.trace: deque[str] = deque(maxlen=20)
        self.commands: deque[str] = deque(maxlen=12)
        self.doctor: deque[str] = deque(maxlen=8)
        self.failure = "no failures"

    def update_status(
        self,
        *,
        workspace_id: str,
        run_state: str,
        active_mode: str,
        runtime_status: str,
        chat_id: str | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.run_state = run_state
        self.active_mode = active_mode
        self.runtime_status = runtime_status
        self.chat_id = chat_id

    def set_files(self, files: list[str]) -> None:
        self.files = files[:12]

    def set_chats(self, chats: list[str]) -> None:
        self.chats = chats[:8]

    def update_trace(self, lines: list[str]) -> None:
        self.trace.clear()
        self.trace.extend(lines)

    def command_started(self, command: str) -> None:
        self.commands.append(f"/{command}: running")

    def command_progress(self, command: str, phase: str, phase_index: int, phase_total: int) -> None:
        self.commands.append(f"/{command}: {phase} {phase_index}/{phase_total}")

    def command_completed(self, text: str) -> None:
        self.commands.append(text)

    def append_doctor(self, text: str) -> None:
        self.doctor.append(text)

    def set_failure(self, summary: str, error_code: str) -> None:
        self.failure = f"{error_code}: {summary}"

    def text_buffer(self) -> str:
        files = "\n".join(self.files) or "no files"
        chats = "\n".join(self.chats) or (self.chat_id or "no active chat")
        trace = "\n".join(self.trace) or "no trace yet"
        commands = "\n".join(self.commands) or "no commands yet"
        doctor = "\n".join(self.doctor) or "no doctor findings"
        return (
            f"WORKSPACE\n{self.workspace_id}\nstate: {self.run_state}\n"
            f"mode: {self.active_mode}\nruntime: {self.runtime_status}\n\n"
            f"CHAT\n{chats}\n\n"
            f"FILES\n{files}\n\n"
            f"TRACE\n{trace}\n\n"
            f"COMMANDS\n{commands}\n\n"
            f"DOCTOR\n{doctor}\n\n"
            f"FAILURES\n{self.failure}"
        )
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/app/tui/test_sidebar_sections.py -q
```

Expected: pass.

---

### Task 2: Wire SidebarPane To SidebarState

**Files:**
- Modify: `src/app/tui/widgets.py`
- Test: `tests/app/tui/test_sidebar_sections.py`
- Test: `tests/app/tui/test_textual_app.py`

- [ ] **Step 1: Add SidebarPane compatibility test**

Append:

```python
import pytest
from textual.app import App, ComposeResult

from app.tui.widgets import SidebarPane


class SidebarHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield SidebarPane(id="sidebar")


@pytest.mark.asyncio
async def test_sidebar_pane_preserves_existing_update_methods():
    app = SidebarHarness()
    async with app.run_test() as pilot:
        sidebar = app.query_one("#sidebar", SidebarPane)
        sidebar.update_status(
            workspace_id="w_0001",
            run_state="idle",
            active_mode="interaction",
            runtime_status="ready",
        )
        sidebar.update_files(["data/sales.csv"])
        sidebar.update_chats(["chat_1"])

        text = sidebar.text_buffer()
        assert "WORKSPACE" in text
        assert "data/sales.csv" in text
        assert "chat_1" in text
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/app/tui/test_sidebar_sections.py -q
```

Expected: failure because `update_files` and `update_chats` do not exist.

- [ ] **Step 3: Modify SidebarPane**

In `src/app/tui/widgets.py`, import:

```python
from app.tui.sidebar import SidebarState
```

Replace the text buffers inside `SidebarPane` with:

```python
class SidebarPane(RichLog):
    can_focus = True
    help = HelpData(
        title="Sidebar",
        description="Shows workspace, chat, files, run trace, command progress, doctor findings, and failures.",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(min_width=1, wrap=True, highlight=False, markup=False, **kwargs)
        self._state = SidebarState()
        self._refresh_text()

    def update_status(
        self,
        *,
        workspace_id: str,
        run_state: str,
        active_mode: str,
        runtime_status: str = "checking",
        chat_id: str | None = None,
    ) -> None:
        self._state.update_status(
            workspace_id=workspace_id,
            run_state=run_state,
            active_mode=active_mode,
            runtime_status=runtime_status,
            chat_id=chat_id,
        )
        self._refresh_text()

    def update_files(self, files: list[str]) -> None:
        self._state.set_files(files)
        self._refresh_text()

    def update_chats(self, chats: list[str]) -> None:
        self._state.set_chats(chats)
        self._refresh_text()

    def update_trace(self, lines: list[str]) -> None:
        self._state.update_trace(lines)
        self._refresh_text()

    def text_buffer(self) -> str:
        return self._state.text_buffer()

    def _refresh_text(self) -> None:
        self.clear()
        self.write(self.text_buffer(), scroll_end=True)
```

Keep existing `command_started`, `command_progress`, `command_completed`, `append_doctor_finding`, `doctor_report`, and `failure` method names, but implement them by mutating `self._state` and refreshing text.

- [ ] **Step 4: Run sidebar tests**

Run:

```bash
uv run pytest tests/app/tui/test_sidebar_sections.py tests/app/tui/test_textual_app.py -q
```

Expected: pass after compatibility methods are preserved.

---

### Task 3: Workspace Manager File Panel Uses File Index

**Files:**
- Modify: `src/app/tui/screens/workspace_manager.py`
- Test: `tests/app/tui/test_workspace_manager.py` if present, otherwise add to `tests/app/tui/test_textual_app.py`

- [ ] **Step 1: Add workspace manager file panel test**

Add to a TUI workspace manager test file:

```python
import pytest

from app.tui.app import DataHarnessApp
from app.tui.screens.workspace_manager import WorkspaceManagerScreen


@pytest.mark.asyncio
async def test_workspace_manager_file_panel_uses_workspace_relative_paths(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        screen = WorkspaceManagerScreen(session=app._session, active_workspace_id="w_0001")
        await app.push_screen(screen)
        await pilot.pause()

        assert "data/sales.csv" in screen.text_buffer()
```

- [ ] **Step 2: Run test to verify failure or current mismatch**

Run:

```bash
uv run pytest tests/app/tui -q
```

Expected: fail if current panel only shows `sales.csv` instead of `data/sales.csv`.

- [ ] **Step 3: Use WorkspaceFileIndex in workspace manager**

In `src/app/tui/screens/workspace_manager.py`, import:

```python
from app.tui.file_picker import WorkspaceFileIndex
```

Replace `_list_files`:

```python
    def _list_files(self, data_dir: Path) -> list[str]:
        workspace_dir = data_dir.parent
        return [entry.path for entry in WorkspaceFileIndex(workspace_dir).scan()]
```

Keep `_refresh_files` updating `#workspace_file_list`.

- [ ] **Step 4: Run workspace tests**

Run:

```bash
uv run pytest tests/app/tui/test_keyboard_navigation.py tests/app/tui/test_textual_app.py -q
```

Expected: pass.

---

### Task 4: Refresh Sidebar Files And Chats On Workspace Changes

**Files:**
- Modify: `src/app/tui/app.py`
- Test: `tests/app/tui/test_sidebar_sections.py`

- [ ] **Step 1: Add app sidebar refresh test**

Append:

```python
from app.tui.widgets import SidebarPane


@pytest.mark.asyncio
async def test_app_refreshes_sidebar_files_after_workspace_snapshot(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        app.apply_workspace_snapshot(
            {
                "workspace_id": "w_0001",
                "run_state": "idle",
                "active_mode": "interaction",
                "runtime_status": "ready",
            }
        )
        await pilot.pause()

        sidebar = app.query_one("#sidebar", SidebarPane)
        assert "data/sales.csv" in sidebar.text_buffer()
```

- [ ] **Step 2: Implement sidebar file refresh helper**

In `src/app/tui/app.py`, import:

```python
from app.tui.file_picker import WorkspaceFileIndex
```

Add:

```python
    async def _refresh_sidebar_resources(self) -> None:
        sidebar = self.query_one("#sidebar", SidebarPane)
        files = [entry.path for entry in WorkspaceFileIndex(self._workspace_dir).scan()]
        sidebar.update_files(files)
        try:
            chats = await self._session.list_chats(self._state.workspace_id)
        except Exception:
            sidebar.update_chats([])
        else:
            sidebar.update_chats([chat.chat_id for chat in chats])
```

Call it from `on_mount` and after workspace snapshots:

```python
        self.run_worker(self._refresh_sidebar_resources())
```

In `apply_workspace_snapshot`, after status handling:

```python
        self.run_worker(self._refresh_sidebar_resources())
```

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/app/tui/test_sidebar_sections.py tests/app/tui/test_textual_app.py -q
```

Expected: pass.

---

### Task 5: Checkpoint Verification

**Files:**
- Verify: `src/app/tui/sidebar.py`
- Verify: `src/app/tui/widgets.py`
- Verify: `src/app/tui/screens/workspace_manager.py`
- Verify: `src/app/tui/app.py`

- [ ] **Step 1: Run focused sidebar/workspace tests**

Run:

```bash
uv run pytest tests/app/tui/test_sidebar_sections.py tests/app/tui/test_keyboard_navigation.py tests/app/tui/test_textual_app.py -q
```

Expected: all pass.

- [ ] **Step 2: Report checkpoint**

Report:

```text
Sidebar/workspace checkpoint:
- Sidebar state renders workspace, chat, files, trace, commands, doctor, and failures.
- Workspace manager file panel uses the shared file index.
- Sidebar resources refresh on mount and workspace switch.
```

