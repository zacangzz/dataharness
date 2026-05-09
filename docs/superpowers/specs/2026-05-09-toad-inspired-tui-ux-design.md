# Toad-Inspired DataHarness TUI UX Design

Date: 2026-05-09

## Purpose

Upgrade the DataHarness Textual interface with user-facing improvements inspired by `batrachianai/toad`: a richer prompt editor, an `@` file picker, streaming Markdown conversation rendering, and a more useful workspace/sidebar navigation model.

This spec supersedes `docs/superpowers/specs/2026-05-07-posting-inspired-tui-ux-design.md` for future TUI work. The earlier Posting-inspired work remains useful background for command providers, focused help, jump navigation, and Textual-native styling, but this spec is the current design target.

## References

Toad patterns to adapt:

- Markdown prompt editor with mouse support, multiline editing, code fence highlighting, and useful shortcuts.
- `@` file mention workflow with fuzzy search, live refinement, `enter` insertion, and `tab` switch to a tree browser.
- Streaming Markdown output with rendered code fences, tables, block quotes, and lists.
- Sidebar/session surfaces that make navigation and current state visible.
- Context-sensitive footer/help behavior where important keys change with focus.
- Python 3.14 runtime floor.

Source references:

- `https://github.com/batrachianai/toad`
- `https://github.com/batrachianai/toad/tree/main/src/toad`
- `https://gitextract.com/batrachianai/toad`

## Licensing Position

The project owner is comfortable with AGPL-3.0 compatibility for this work.

Implementation may either reimplement Toad concepts in DataHarness style or adapt small source-level pieces from Toad where that is genuinely better. Any copied or closely adapted Toad source must:

- Keep AGPL-3.0 compatibility intact.
- Preserve attribution in file comments or a dedicated notice file.
- Stay isolated in Layer 4 TUI modules unless a non-UI utility is explicitly needed.
- Avoid importing Toad as a runtime dependency unless the implementation plan proves that is cleaner than local adaptation.

## Scope

In scope:

- Prompt UX.
- Conversation rendering.
- File picker and file mention insertion.
- Workspace/sidebar navigation.
- Python 3.14 project floor, already reflected in active project metadata.

Out of scope:

- Toad shell integration.
- Agent app store behavior.
- ACP provider integration.
- Multi-agent concurrent execution.
- Beautiful diff rendering.
- Full settings system beyond small TUI state needed for the four scoped areas.
- Layer 1 runtime, Layer 2 worker, or Layer 3 orchestration rewrites.

## Architecture Rules

DataHarness keeps its four-layer architecture.

- Layer 4 TUI talks through `AppSession`.
- Layer 4 must not import `runtime.*` directly.
- Layer 4 must not bypass `AppSession` to manipulate `Orchestrator`.
- Layer 3 remains the source of command descriptors, workspace records, chat records, status snapshots, and app events.
- File discovery for the active workspace may read workspace files directly from the active workspace path only when the data is purely presentational. If the picker needs metadata that belongs to Layer 3, add or use an `AppSession` facade method.

Primary edit areas:

- `src/app/tui/app.py`
- `src/app/tui/prompt_bar.py`
- `src/app/tui/widgets.py`
- `src/app/tui/dataharness.tcss`
- `src/app/tui/screens/workspace_manager.py`
- new Layer 4 modules under `src/app/tui/` for prompt editing, file picking, Markdown conversation blocks, and sidebar/workspace surfaces.

Packaging must continue to include TCSS and any new TUI assets in the PyInstaller/spec/build configuration.

## User Experience Goals

The TUI should feel like a focused local data workbench, not a generic chat log.

The primary screen should make these things obvious without extra commands:

- Which workspace is active.
- Which chat is active.
- Whether the local runtime is ready, loading, running, or failed.
- What the agent is currently doing.
- Which files are available in the workspace.
- Which commands or file mentions are available from the prompt.
- What happened during the current or most recent turn.

The user should be able to stay in the keyboard flow:

- Type a prompt.
- Mention files with `@`.
- Use slash commands with completion.
- Inspect workspace files/chats/status in the sidebar.
- Read formatted Markdown and code output without losing context.

## Proposed Approach

Use a staged Layer 4 rewrite of the TUI surfaces, not a wholesale Toad port.

This is the recommended approach because DataHarness already has strong app/harness boundaries, command descriptors, status events, workspaces, chats, and tests. Directly porting Toad would bring shell/agent-store/session concepts that do not fit DataHarness. Rebuilding the four selected Toad-inspired behaviors in DataHarness terms gives the UX benefit without diluting the local data-analysis model.

Rejected alternatives:

- Direct Toad vendoring as the full TUI shell. This would fight the existing architecture and pull in unrelated shell/session/agent-provider concepts.
- Cosmetic-only styling. This would not solve the current prompt, file mention, or conversation rendering limitations.

## Component Design

### 1. Prompt Editor

Replace the current single-line `Input` inside `PromptBar` with a prompt editor widget.

Required behavior:

- Supports multiline input.
- Preserves existing normal-message submission through `DataHarnessApp.submit_user_text`.
- Keeps slash command hints and argument candidates.
- Adds `@` file mention detection at the cursor.
- Shows completions without shifting the main conversation layout.
- Supports mouse cursor placement, paste, selection, and common editing keys supported by Textual.
- Keeps the prompt focused after command errors, candidate failures, and completed turns.
- Shows concise prompt status: active mode, run state, runtime status, and hint state.

Keyboard behavior:

- `enter` submits when no completion overlay is active and the prompt is in single-submit mode.
- `shift+enter` inserts a newline.
- `ctrl+j` also inserts a newline for terminals where `shift+enter` is unreliable.
- `escape` closes the active hint/file overlay first; if no overlay is active, it leaves prompt text intact.
- `up` and `down` navigate completion overlays when visible.
- `tab` switches file picker modes when the file picker is visible.

Implementation guidance:

- Prefer Textual `TextArea` or a small subclass over inventing an editor from scratch.
- Keep the public prompt API close to the current `PromptBar`: `input`/editor access, `prefill`, `refresh_hints`, `update_status`, `update_state`, and `text_buffer` equivalents.
- Existing tests that query `#prompt_bar` should still have a stable way to inspect and edit prompt text.

### 2. File Mention Picker

Add a reusable file picker for active workspace files and replace the current ad hoc workspace file list with it where practical.

Required behavior:

- Typing `@` in the prompt opens a file picker overlay.
- Typing after `@` fuzzy-filters active workspace files and directories.
- `enter` inserts the selected path into the prompt.
- `tab` toggles between fuzzy list mode and tree browse mode.
- `escape` dismisses the picker without changing prompt text.
- Picker results are workspace-relative paths.
- Hidden files are excluded by default.
- Common generated/runtime directories are excluded by default: `.git`, `.venv`, `__pycache__`, `.pytest_cache`, app runtime logs, and other ignored internal runtime directories.
- Selection inserts a stable mention format: `@path/to/file.csv`.
- Paths with spaces are inserted in a parseable quoted form: `@"path with spaces.csv"`.

Data rules:

- The picker reads from the active workspace directory, prioritizing `data/` and user-supplied files.
- If the workspace later has artifact references from Layer 3, the picker can add an artifact source group through `AppSession`.
- File mention insertion does not itself read file contents into the prompt. It only inserts a reference. The harness/runtime prompt assembly remains responsible for interpreting references.

Performance rules:

- File scanning must not block typing on normal workspaces.
- Cache scanned paths per workspace and invalidate on workspace switch.
- Use bounded result lists for the overlay.
- Fuzzy search should handle a few thousand files comfortably.

Workspace manager reuse:

- `WorkspaceManagerScreen` should use the same file listing/picker model for its right-side file panel.
- The workspace manager remains a workspace selector, but its file panel should become navigable and useful rather than static text.

### 3. Conversation Rendering

Replace plain `RichLog` transcript rendering with structured conversation blocks.

Required behavior:

- User messages render as distinct user blocks.
- Assistant messages render as Markdown blocks.
- Streaming assistant output updates progressively without duplicating final text.
- Markdown rendering supports headings, lists, block quotes, tables, links as text, and fenced code blocks.
- Code fences use syntax highlighting where Textual/Rich supports it.
- Plain text remains safe: no Rich markup injection from model output.
- Resumed chats rehydrate into the same block structure.
- The conversation remains scrollable and keeps scroll-to-end behavior during active streaming unless the user has intentionally scrolled away.

Implementation guidance:

- Use Textual `Markdown`/`MarkdownStream` patterns where possible.
- Introduce small block widgets rather than rewriting the whole conversation as one string on every delta.
- Keep `ConversationPane.text_buffer()` for tests and diagnostics.
- Preserve app event handling: `AppRuntimeDelta` appends streaming fragments, `AppFinalMessage` finalizes the active assistant block, failures discard or annotate the streaming block.

Failure and cancellation rendering:

- Failed turns should leave a compact failure block with error code and summary.
- Cancelled turns should render a compact cancellation block.
- Runtime/tool/thinking fragments can be hidden in V1 unless already exposed through events.

### 4. Workspace And Sidebar Navigation

Turn the sidebar into a navigation and status surface, not only a text log.

Required behavior:

- Sidebar has stable sections:
  - Workspace summary.
  - Active chat.
  - Files.
  - Recent run trace.
  - Commands.
  - Doctor findings.
  - Failures.
- Sections should be visually separated and independently understandable.
- Files and chats should be navigable where data exists.
- Sidebar should update on workspace switch, chat resume, command progress, doctor events, and status snapshots.
- Bounded history remains; long logs must not make the UI unusable.

Workspace manager behavior:

- Shows workspaces as a navigable list.
- Shows selected workspace files using the reusable file picker/list model.
- Shows selected workspace chat count and source count.
- Keeps existing create, switch, delete, and close actions.
- Handles active-run workspace switch errors cleanly. If Layer 3 reports that switching is blocked by an active run, the screen should show a clear inline error and keep the current workspace active.

Navigation keys:

- `f2` opens workspace manager.
- `ctrl+p` opens command palette.
- `f1` opens focused help.
- `ctrl+o` opens jump navigation.
- `j`/`k` move in navigable lists.
- `enter` activates selected list items.
- `escape` closes overlays/modals before leaving the main screen.

## Data Flow

Prompt submission:

1. User edits prompt text.
2. Prompt editor manages slash and file overlays locally.
3. Submission sends text to `DataHarnessApp.submit_user_text`.
4. `DataHarnessApp` routes slash commands or user turns through `AppSession`.
5. App events update conversation, sidebar, workspace bar, prompt status, and run trace.

File mention:

1. User types `@`.
2. Prompt editor asks the file picker model for active workspace candidates.
3. File picker filters candidates as the query changes.
4. User selects a file.
5. Prompt editor inserts the workspace-relative mention.
6. Prompt text is submitted normally when the user submits.

Conversation streaming:

1. `AppRuntimeDelta` arrives through `EventConsumer`.
2. Conversation pane appends the fragment to the active assistant Markdown stream.
3. `AppFinalMessage` finalizes the block and clears streaming state.
4. Chat rehydration rebuilds blocks from stored messages.

Sidebar updates:

1. Status snapshots update workspace, mode, run state, and runtime state.
2. Command events update command progress.
3. Doctor events update doctor section.
4. Turn lifecycle events update run trace and active phase.
5. Workspace/chat actions update selected workspace/chat sections.

## Error Handling

- Prompt editor construction failure: fall back to a minimal single-line input and notify the user.
- Slash descriptor load failure: keep normal prompt submission available and show a prompt-local warning.
- File scan failure: show an empty picker with the error summary and keep typing available.
- File path no longer exists at selection time: dismiss picker and show a prompt-local warning.
- Markdown render failure: render the affected message as plain text.
- Streaming finalization mismatch: avoid duplicate final text by treating final message as authoritative and clearing any active stream buffer.
- Workspace switch blocked: show inline error in workspace manager and keep app state unchanged.
- Sidebar section update failure: preserve the previous rendered state and notify with low severity.

## Testing

Add or update focused tests for:

- Python floor remains `>=3.14` in `pyproject.toml` and `uv.lock`.
- Layer 4 boundary remains intact: TUI does not import `runtime.*` or direct orchestration internals.
- Prompt editor supports multiline text and submission.
- `shift+enter` or `ctrl+j` inserts newline without submitting.
- Slash hints still show command descriptors and argument candidates.
- Typing `@` opens file picker candidates for active workspace files.
- File picker inserts workspace-relative file mentions.
- File picker quotes paths with spaces.
- File picker excludes hidden/generated/runtime directories.
- `tab` toggles fuzzy list/tree mode.
- Workspace switch invalidates file picker cache.
- Conversation renders user and assistant blocks separately.
- Assistant Markdown renders code fences/lists/tables without Rich markup injection.
- Streaming deltas do not duplicate final messages.
- Chat resume rehydrates structured conversation blocks.
- Sidebar sections update from status, command, doctor, failure, workspace, and chat events.
- Workspace manager uses the reusable file list/picker model.
- TCSS packaging includes any new styles.

Run at minimum:

- `uv run pytest tests/app/tui -q`
- `uv run pytest -q`

For visual regressions, use Textual pilot tests and screenshot checks where stable. Browser-based review is intentionally not part of this workflow.

## Implementation Order

1. Add file picker model and overlay, with tests for scan/filter/insert behavior.
2. Replace prompt input with prompt editor while preserving slash hints and app submission.
3. Add `@` file mention integration to the prompt editor.
4. Replace conversation plain-text rerendering with structured user/assistant blocks and Markdown streaming.
5. Refactor sidebar into section widgets backed by existing app events.
6. Update workspace manager to reuse the file picker/list model.
7. Update TCSS for overlay, prompt, Markdown blocks, sidebar sections, and focused states.
8. Update packaging coverage for new TUI files/assets if needed.
9. Run TUI tests and full test suite under Python 3.14.

## Acceptance Criteria

- The main TUI opens under Python 3.14.
- The prompt is multiline and keeps existing slash command behavior.
- `@` opens a file picker for the active workspace.
- File picker selection inserts a correct workspace-relative mention.
- Assistant output renders as Markdown while streaming.
- Resumed chats render with the same structured conversation UI.
- Sidebar shows workspace, chat, files, run trace, commands, doctor findings, and failures as separate readable sections.
- Workspace manager still supports create/switch/delete/close and has a navigable file panel.
- Existing Layer 4 tests pass after targeted updates.
- Full test suite passes.
- `CODEMAP.md` is updated if imports, definitions, inheritance, or call relationships change during implementation.

