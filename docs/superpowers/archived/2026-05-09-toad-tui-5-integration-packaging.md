# Toad TUI Integration And Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the Toad-inspired TUI changes, update styles/packaging/CODEMAP, and verify the full Python 3.14 app.

**Architecture:** This is the final cross-cutting pass after the feature plans. It should not add major behavior; it reconciles imports, TCSS, packaging, tests, and documentation.

**Tech Stack:** Python 3.14, Textual >=8.2.4, uv, pytest, PyInstaller/spec packaging files.

**Repository Rule:** Do not commit during execution unless the user grants permission. Git status/diff may fail because of documented object database corruption, so rely on explicit file inspection and test output.

---

## Prerequisites

Complete these plans first:

- `docs/superpowers/plans/2026-05-09-toad-tui-1-file-picker.md`
- `docs/superpowers/plans/2026-05-09-toad-tui-2-prompt-editor.md`
- `docs/superpowers/plans/2026-05-09-toad-tui-3-conversation-markdown.md`
- `docs/superpowers/plans/2026-05-09-toad-tui-4-sidebar-workspace.md`

---

### Task 1: Consolidate TCSS

**Files:**
- Modify: `src/app/tui/dataharness.tcss`
- Test: existing TUI tests plus screenshot-capable Textual pilot tests if available.

- [ ] **Step 1: Add stable style sections**

Ensure `src/app/tui/dataharness.tcss` contains sections for:

```css
#prompt_bar {
    height: auto;
}

#user_input {
    min-height: 3;
    max-height: 10;
}

#prompt_hint_options {
    max-height: 8;
    overflow-y: auto;
}

#prompt_file_picker {
    max-height: 10;
    overflow-y: auto;
}

.message-user,
.message-assistant,
.message-system {
    width: 100%;
}

.sidebar-section {
    margin: 0 0 1 0;
}
```

Do not introduce decorative gradients, large hero styling, or one-note palettes. Keep the UI dense and operational.

- [ ] **Step 2: Run TUI tests**

Run:

```bash
uv run pytest tests/app/tui -q
```

Expected: all pass.

---

### Task 2: Packaging Coverage

**Files:**
- Inspect/Modify: `hragent.spec`
- Inspect/Modify: `scripts/build_app.sh`
- Modify tests only if packaging assertions currently miss new assets.
- Test: `tests/app/tui/test_tcss_packaging.py` and packaging tests under `tests/packaging` if present.

- [ ] **Step 1: Inspect packaging references**

Run:

```bash
rg -n "dataharness\\.tcss|app/tui|collect.*app|--add-data|datas=" hragent.spec scripts tests
```

Expected: see existing TCSS/package coverage locations.

- [ ] **Step 2: Update packaging only if new non-Python assets exist**

If only Python modules and `dataharness.tcss` changed, no extra data entries are needed beyond existing TCSS coverage.

If a new TUI asset file exists, add it beside the TCSS package entry. For PyInstaller command-style scripts, use this shape:

```bash
--add-data "src/app/tui/dataharness.tcss:app/tui"
```

For `.spec` files, use this shape:

```python
datas=[
    ("src/app/tui/dataharness.tcss", "app/tui"),
]
```

- [ ] **Step 3: Run packaging tests**

Run:

```bash
uv run pytest tests/app/tui/test_tcss_packaging.py -q
```

If packaging tests exist:

```bash
uv run pytest tests/packaging -q
```

Expected: all pass, or no `tests/packaging` directory exists.

---

### Task 3: Layer Boundary And CODEMAP

**Files:**
- Modify: `CODEMAP.md`
- Test: `tests/app/tui/test_layer_boundaries.py`

- [ ] **Step 1: Run layer-boundary tests**

Run:

```bash
uv run pytest tests/app/tui/test_layer_boundaries.py -q
```

Expected: pass. If it fails because new TUI modules import `runtime.*` or orchestration internals, fix the imports by routing through `AppSession` or local Layer 4 helpers.

- [ ] **Step 2: Update CODEMAP import graph**

Add new modules under the `src/app/tui` section. Use the actual final import relationships. The expected shape after all plans is:

```text
src/app/tui/conversation.py             → (none)
src/app/tui/file_picker.py              → (none)
src/app/tui/prompt_editor.py            → (none)
src/app/tui/sidebar.py                  → (none)
src/app/tui/prompt_bar.py               → app.tui.file_picker, app.tui.help, app.tui.prompt_editor
src/app/tui/widgets.py                  → app.tui.conversation, app.tui.help, app.tui.sidebar
src/app/tui/app.py                      → app.session, app.tui.commands, app.tui.event_consumer,
                                           app.tui.file_picker, app.tui.help, app.tui.jump,
                                           app.tui.prompt_bar, app.tui.prompt_editor,
                                           app.tui.run_trace, app.tui.screens, app.tui.widgets,
                                           app.tui.screens.workspace_manager
src/app/tui/screens/workspace_manager.py→ app.tui.file_picker
```

- [ ] **Step 3: Update CODEMAP inheritance graph**

Add the new Textual classes to the Textual subclass list. Use actual final bases. Expected additions:

```text
- `TextArea` ← `PromptEditor` (prompt_editor.py)
- `Widget` ← `FilePicker` (file_picker.py)
- `Vertical` ← `AssistantMessageBlock` (conversation.py)
- `Static` ← `UserMessageBlock`, `SystemMessageBlock` (conversation.py)
```

If `ConversationPane` changes from `RichLog` to `VerticalScroll`, update the existing `RichLog` and `VerticalScroll` entries accordingly.

- [ ] **Step 4: Update CODEMAP definitions**

Add definitions:

```text
| `PromptEditor` | `src/app/tui/prompt_editor.py` |
| `FilePicker` | `src/app/tui/file_picker.py` |
| `WorkspaceFileIndex` | `src/app/tui/file_picker.py` |
| `WorkspaceFileEntry` | `src/app/tui/file_picker.py` |
| `SidebarState` | `src/app/tui/sidebar.py` |
| `UserMessageBlock` | `src/app/tui/conversation.py` |
| `AssistantMessageBlock` | `src/app/tui/conversation.py` |
| `SystemMessageBlock` | `src/app/tui/conversation.py` |
```

- [ ] **Step 5: Run boundary tests again**

Run:

```bash
uv run pytest tests/app/tui/test_layer_boundaries.py -q
```

Expected: pass.

---

### Task 4: Python 3.14 And Full Verification

**Files:**
- Verify: `pyproject.toml`
- Verify: `uv.lock`
- Verify: all implementation files.

- [ ] **Step 1: Verify Python version**

Run:

```bash
uv run python --version
```

Expected:

```text
Python 3.14.4
```

Any Python 3.14.x version is acceptable if it satisfies `requires-python = ">=3.14"`.

- [ ] **Step 2: Verify active Python floor**

Run:

```bash
rg -n 'requires-python = ">=3.14"' pyproject.toml uv.lock
```

Expected: matches in both files.

- [ ] **Step 3: Run all TUI tests**

Run:

```bash
uv run pytest tests/app/tui -q
```

Expected: all pass.

- [ ] **Step 4: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: all pass. Existing Python 3.14 deprecation warnings may remain if unrelated to TUI behavior.

---

### Task 5: Manual TUI Smoke

**Files:**
- Verify runtime app entrypoint only.

- [ ] **Step 1: Start Textual app through project entrypoint**

Run:

```bash
uv run python -c "from cli import build_app; build_app().run()"
```

Expected: DataHarness opens with:

- Multiline prompt.
- Workspace bar.
- Conversation pane.
- Sidebar sections.
- `F2` workspace manager.
- `@` file picker when typing file mentions in a workspace with files.

- [ ] **Step 2: Exit app**

Use the app’s normal quit path, such as `/exit` or the existing quit binding if available.

- [ ] **Step 3: Document any manual issue**

If a visual or interaction issue appears, add it to `Issues.md` with:

```markdown
## Toad TUI smoke issue: <short name>
- Observed: <what happened>
- Expected: <what should happen>
- Scope: Layer 4 TUI
- Status: documented during integration smoke
```

---

### Task 6: Final Checkpoint

**Files:**
- Verify all touched files.

- [ ] **Step 1: Summarize implemented surface**

Report:

```text
Toad TUI integration checkpoint:
- Prompt editor: implemented and tested.
- File picker: implemented and tested.
- Conversation Markdown: implemented and tested.
- Sidebar/workspace navigation: implemented and tested.
- Packaging/CODEMAP: updated where structure changed.
- Verification: <commands run and results>.
```

- [ ] **Step 2: Note Git limitation**

If Git still fails, include:

```text
Git status/diff were not available because the repository object database issue documented in Issues.md is still present.
```

