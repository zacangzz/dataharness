# Toad-Inspired TUI Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement these plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Toad-inspired DataHarness TUI UX spec as small, testable Layer 4 changes.

**Architecture:** Work stays in `src/app/tui` unless an `AppSession` facade method is explicitly needed. The implementation preserves the existing Layer 4 to Layer 3 boundary and updates `CODEMAP.md` whenever import, call, inheritance, or definition relationships change.

**Tech Stack:** Python 3.14, Textual >=8.2.4, Rich/Textual Markdown widgets, pytest, pytest-asyncio, existing `AppSession` async facade.

**Repository Rule:** Do not commit during execution unless the user grants permission. Git status/diff are currently blocked by documented object database corruption, so each plan ends with verification and a checkpoint summary rather than a commit step.

---

## Plan Split

Use many plans, not one large plan. The TUI work has independent risk areas and should be implemented in this order:

1. `docs/superpowers/plans/2026-05-09-toad-tui-1-file-picker.md`
   - Builds workspace-relative file indexing, fuzzy filtering, mention formatting, and a reusable Textual picker widget.
   - This is first because both the prompt and workspace manager depend on the same file model.

2. `docs/superpowers/plans/2026-05-09-toad-tui-2-prompt-editor.md`
   - Replaces the single-line prompt `Input` with a multiline Textual `TextArea` wrapper.
   - Preserves slash hints and integrates the file picker from Plan 1.

3. `docs/superpowers/plans/2026-05-09-toad-tui-3-conversation-markdown.md`
   - Replaces plain full-log rerendering with structured user/assistant blocks and Markdown assistant rendering.
   - Keeps streaming/finalization behavior testable.

4. `docs/superpowers/plans/2026-05-09-toad-tui-4-sidebar-workspace.md`
   - Turns the sidebar and workspace manager file panel into navigable sections backed by existing app events and the file model from Plan 1.

5. `docs/superpowers/plans/2026-05-09-toad-tui-5-integration-packaging.md`
   - Final TCSS, package coverage, layer-boundary checks, `CODEMAP.md`, full suite, and app smoke verification.

## Code Snippet Policy

Plans include code snippets for:

- New tests.
- New public interfaces.
- Key implementation skeletons.
- Wiring points in existing files.

They do not paste a full final implementation for every line. The executing engineer should write production-quality code around the snippets while keeping the public names, behaviors, and tests aligned.

## Cross-Plan Rules

- Keep Textual widget IDs stable where tests or jump/help features depend on them.
- Keep `PromptBar.text_buffer()` and `ConversationPane.text_buffer()` for tests and diagnostics.
- Use ASCII in new files.
- Do not import `runtime.*` from `src/app/tui`.
- Do not call `AppSession.orchestrator` from newly written TUI code.
- Update `CODEMAP.md` after implementation because new modules/classes/imports will be added.
- If any unrelated bug is found, document it in `Issues.md` before continuing.

