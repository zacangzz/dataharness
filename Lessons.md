# Lessons Learned

This file is a compact reference of durable project lessons. Historical incident
details and resolved bug narratives belong in `Issues.md`; keep this document
focused on current rules, gotchas, and verification cues.

Last reviewed: 2026-05-14.

## Layer Ownership

- Keep the four app layers in their lanes. Layer 1 runtime streams model output;
  Layer 2 worker executes approved user/analyst Python; Layer 3 harness owns
  orchestration, state, validation, workspace facts, memory, and deterministic
  tools; Layer 4 app/TUI renders controls and user interaction.
- New deterministic workspace tools such as `list_files`, `inspect_file`, and
  `read_file` belong in Layer 3, not Layer 2. Register them through the harness
  command registry, keep their core helpers module-level and unit-testable, and
  enforce workspace boundaries there.
- Presentation belongs in Layer 4. For example, `read_file` returns workspace
  facts from Layer 3; CSV/TSV preview formatting, transcript cleanup, and UI
  rendering are Layer 4 responsibilities.
- The agentic loop belongs in the harness. `Orchestrator.run_agentic_turn(...)`
  owns durable context, tool dispatch, retries, mode handoff acceptance, and
  follow-up prompt construction. `AppSession` picks the initial mode, injects a
  prompt-provider callback, and maps harness events to app events.
- Memory writes must remain behind `KnowledgeManager`. Do not add alternate
  write paths under `memory/`.
- Commands that implicitly target UI state, such as `/compact`, need Layer 4 to
  inject the active `chat_id` before calling `handle_direct_command`.
- Chat-creation commands need Layer 4 to apply successful Layer 3 results to
  active UI state: select the new chat, clear or refresh the transcript, and
  refresh chat resources.
- Command context metadata must be preserved before command-argument validation.
  `HarnessCommandRegistry.validate()` intentionally strips undeclared user-facing
  args, so hidden context fields such as `chat_id` must be read from raw
  arguments when building `CommandContext`.
- Manual `/compact` and token-pressure compaction have different retention
  needs. Manual compaction should collapse all active chat messages into one
  summary marker; token-pressure compaction can keep a recent-message window so
  the current runtime turn keeps local context.
- Compaction replacement counts are based on non-summary chat messages. Do not
  apply that count as a raw slice over the full message list after a prior
  compaction summary exists; preserve non-summary messages after the replaced
  range and collapse older summary markers into the new marker.
- TUI compaction completion must refresh both transcript and chat sidebar
  resources. Rehydrating the conversation alone leaves sidebar message counts
  stale even when `metadata.json` was updated correctly.
- Compaction summaries should be DataHarness handoff checkpoints, not transcript
  digests. Keep the runtime compaction prompt canonical in
  `src/harness/prompts/compaction.md`, and keep `ChatCompactor` loading that file
  instead of duplicating prompt text inline. Runtime prompts and deterministic
  fallback summaries should preserve user goal, durable facts, workspace
  file/schema/result references, constraints, and next steps while filtering role
  prefixes, greetings, and test noise.
- A visible chat list is not the same as an active TUI chat. On startup or after
  sidebar refresh, Layer 4 may know chats exist while `_active_chat_id` is still
  `None`; `/compact` should resolve the latest workspace chat before calling
  Layer 3.
- Ensure `DataHarnessApp.apply_workspace_snapshot` preserves the active `chat_id`
  when the workspace has not changed. The Layer 3 `HarnessStatusSnapshot` hardcodes
  `chat_id=None` because the orchestrator does not own the TUI's active chat state.
  Clearing it unconditionally causes context-dependent commands (like `/compact`)
  to fail silently.
- Prefer explicit error reporting in command handlers. A command that cannot
  proceed due to missing context should yield a `CommandCompleted` with an
  `error` result instead of silently returning.

## Runtime Streaming And Tool Calls

- Keep Layer 1 runtime sampling conservative for structured tool prompts:
  `RuntimeRequest.temperature` defaults to `0.2`, while explicit request
  temperatures still pass through unchanged to llama.cpp.
- Treat runtime config flags as untrusted until call sites and disabled-state
  tests prove they are enforced. `RuntimeConfig.enable_reasoning_stream` must
  gate both llama `reasoning_content` deltas and Gemma `<|think|>` parsing.
- Gemma reasoning markers are not stable across templates. Runtime parsing must
  support both `<|channel>thought`/`<channel|>` and legacy
  `<|think|>`/`</|think|>`, stream reasoning progressively, and drop tagged
  reasoning entirely when `enable_reasoning_stream=False`.
- Reasoning and tool-call deltas may update trace/telemetry, but transcript
  rendering must append only normal text deltas. Layer 4 should filter by
  `delta_type` before updating assistant message text.
- `llama-cpp-python` high-level streaming APIs are synchronous; Layer 1 provides
  async semantics through its private bridge/queue code.
- Stream parsers must drain structured tails. A single chunk can contain
  multiple complete `<tool_call>...</tool_call>` blocks, or a complete block
  followed by a partial marker. Loop until no complete block remains, then
  buffer any partial marker instead of emitting it as text.
- Keep parse diagnostics local to one stream invocation. Runtime instance state
  must not leak malformed-tool-call context into later unrelated turns.
- EOS literals such as `<end_of_turn>` can be split across chunks. Strip them
  with buffered prefix/suffix handling inside content emission, not with
  per-chunk `str.replace`.
- Tool-call JSON needs defensive parsing. Accept known name aliases
  (`tool_name`, `function`, `function_name`, `tool`), known argument aliases
  (`parameters`, `args`, `params`, `input`), extra keys, missing arguments as
  `{}`, and literal control characters inside string values.
- When `run_agentic_turn` adds a recovery path, audit every `TurnFailed`
  branch. Malformed tool calls should get one explicit repair nudge instead of
  leaving the user with a silent dead turn.
- Runtime stream tests should assert event order and contiguous sequence values,
  not just event types.

## Chat, Prompt, And Persistence Hygiene

- `Orchestrator.run_turn` persists the user message before building runtime
  messages. `RuntimeRequestBuilder.build_messages` must not append the current
  user text a second time when it is already the latest recent message.
- Synthetic follow-up prompts from `run_agentic_turn` (`[TOOL_RESULT]`,
  `[ASSISTANT_DRAFT]`, handoff re-runs, and retry nudges) must not be persisted
  as user chat messages. Use the `persist_user_message` guard for continuations.
- Strip prompt wrapper artifacts before persistence and display. In particular,
  Gemma-class models may echo `[ASSISTANT_DRAFT]` tags from examples.
- Empty structured output is a harness decision. Runtime output containing only
  parsed tool calls should yield `TurnPaused(reason="awaiting_tool_dispatch")`;
  truly empty output should yield `TurnFailed(error_code="empty_output")` and
  be retried by the harness policy. Do not store hollow assistant rows.
- Gemma `chat_format="gemma"` drops system-role messages. Fold persona, durable
  context, and summaries into a `[SYSTEM]...[/SYSTEM]` block prefixed to the
  first user turn when using Gemma formats. Rebuild the request builder when the
  runtime `chat_format` changes.
- `read_file` prompt guidance should say to summarize returned contents in
  2-4 sentences and not paste file contents verbatim unless the user asks.

## Planning, Approval, And Execution

- Plans originate from the registered `analysis_plan` tool call, not from keyword
  triggers in harness code or legacy command names. The runtime only parses
  structured tool calls; Layer 3 validates names against `HarnessToolRegistry`,
  packages the plan, Layer 4 asks approval, and Layer 2 executes approved code.
- The tools/commands/services split has three separate boundaries: model calls
  go through `HarnessToolRegistry`, user/app commands go through
  `HarnessCommandRegistry`, and reusable Layer 3 implementation belongs in
  `src/harness/services/`. Compatibility shims may remain briefly, but new code
  should import canonical service owners directly.
- `analysis_plan` must validate early: non-empty goal and steps, relative input
  paths, allowed imports using the worker policy, and expected output filenames
  referenced by submitted code before `ApprovalRequired` is emitted. The legacy
  `plan_analysis` name remains a command only.
- Prefer `code_lines` for model-generated `analysis_plan` Python. Embedding
  multi-line code in a JSON `code` string is fragile with local models and can
  fail before Layer 3 validation sees the plan.
- Do not add broad imports such as `os` to the worker allowlist just because the
  model generated them. Tighten pre-approval validation and prompt wording so
  generated code matches the sandbox policy.
- `ApprovalRequired` carries `plan_id` and step data, not a full `Plan`. Layer 4
  should pass only `plan_id` back; the orchestrator owns `_pending_plans` and
  `_pending_contracts` lookup for `resume_approved_step`.
- Inline approval and clarification controls are preferred over full-screen
  Textual screens. Keep approval state in `ApprovalBanner`, and test key paths
  (`a`, `r`, `v`, `escape`, `enter`) instead of relying on flaky click geometry.
- Failure summaries must travel from worker envelopes through diagnostics to the
  TUI. User-visible execution failures should prefer
  `diagnostics["failure_summary"]` over raw stdout.
- Worker subprocess `cwd` is the step tmp dir. Because prompts use
  workspace-relative paths such as `data/sales.csv`, declared inputs must be
  staged under tmp as symlinks before execution. Artifact discovery must exclude
  staged input scaffolding.

## Worker Sandbox

- Layer 2 is for sandboxed user/analyst code only. Keep deterministic
  workspace-bound operations in Layer 3 harness tools.
- The sandbox allowlist is two-phase: static policy validation in
  `worker.policy` and runtime audit/import enforcement in
  `worker.sandbox_bootstrap`. Keep both sides in sync.
- When allowing a stdlib package, include required backing extension modules on
  both sides. Example: `csv` imports `_csv`, so both must be allowlisted.
- Pandas/numpy import chains can perform relative imports and dependency
  imports from already-allowed package code. The runtime guard must distinguish
  package dependency imports from user-level imports while still blocking user
  shell/network imports and audit events such as subprocess/socket operations.
- Frozen workers need PyInstaller-aware code roots. Include `sys._MEIPASS`,
  the frozen executable parent, and `sysconfig` stdlib/site-package roots in
  allowed code roots, and have the child bootstrap self-include its own
  `_MEIPASS` defensively.
- Source mode should remain unchanged when frozen-only paths such as
  `sys._MEIPASS` are absent.

## Packaging And CLI

- In sandboxed agent sessions, run ad hoc `uv run python ...` probes with
  `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src` from the repo root. The default
  uv cache under the user home directory may be blocked by sandbox permissions.
- The packaged worker path is `dist/dataharness -m worker.sandbox_bootstrap
  <config>`. `src/cli.py` must intercept that private dispatch before argparse
  or TUI startup, otherwise the child launches the TUI and the parent reports a
  misleading worker timeout.
- CLI args must be parsed before constructing the Textual app so `--help` and
  `--version` can exit without UI side effects.
- PyInstaller dynamic imports need explicit coverage. Keep `scripts/build_app.sh`
  hidden imports and `--collect-submodules` aligned with dynamic imports in
  `cli.py`, `harness.factory`, runtime factories, and worker bootstrap.
- For PyInstaller `--add-data`, the destination should be the target directory,
  not a full target file path. TCSS and prompt directories must be packaged.
- When a packaged binary fails, inspect packaged logs such as
  `dist/harness/logs/bootstrap.log` or `app_crash.log` before changing runtime
  code. Treat `dist/` chat logs and telemetry as evidence for the binary that
  actually ran, which may lag current `src/` fixes.
- Packaging verification should include the packaging script tests, a fresh
  `bash scripts/build_app.sh`, private worker dispatch smoke testing, and
  launching the binary far enough to render the Textual UI.
- Pydantic v2 requires explicit collection in PyInstaller via `--collect-all pydantic`
  and `--collect-all pydantic_core` to ensure C extensions and submodules are
  included, otherwise it may fail with `ModuleNotFoundError: No module named 'pydantic_core'`.
- A missing runtime must be visible. Production startup should pass the default
  `LlamaCppRuntime` factory, and a `None` runtime should produce a failed turn
  with runtime status instead of an empty assistant response.

## Workspace, Chat, And Context

- Chat persistence is currently per-workspace:
  `<app_root>/workspaces/<workspace_id>/chats/<chat_id>/`. `ChatStore` still
  migrates the old `<app_root>/chats/<workspace_id>/...` layout on startup.
- Factory-built orchestrators must inherit the active app root. Derive it from
  `<app_root>/workspaces/<workspace_id>` and pass it through `Orchestrator` and
  `AppSession`, or workspace commands can point at the wrong app root.
- `harness.workspace_async` is a required Layer 3 module. It must expose
  async-shaped workspace create/list/rename/delete/activate/ingest operations,
  and workspace deletion must cascade chat cleanup.
- Workspace durable context is built by the harness through
  `_build_durable_context_block(...)` and `harness.context`; Layer 4 should not
  read workspace files directly.
- Sidebar files and `@` picker entries should be restricted to workspace
  `data/`. Workspace internals such as `memory/`, `state/`, and `chats/` should
  not surface as selectable user data.
- `ValidityState` vocabulary must match the async spec: `ok`, `changed`,
  `stale`, `needs_review`, `revalidated`, and `broken_lineage`. Do not bring
  back legacy `missing` or `unvalidated` states.
- Anchor ignore rules when names collide with source folders. Use `/harness/`
  for the repo-root runtime data directory so `src/harness/` and
  `tests/harness/` remain trackable.

## Textual TUI

- Restore prompt focus through `self.app.set_focus(target)` after overlays or
  pickers. Widget-local focus helpers can silently fail in nested contexts.
- Terminal copy/paste needs an app-level abstraction. Use Layer 4 native
  clipboard providers where available, keep Textual copy as fallback, make
  transcript message blocks focusable, and fall back to the latest assistant
  reply when no selection is active.
- Paste should target the prompt editor only. Sidebar/status panes do not need
  custom paste behavior.
- Dynamic Textual content should not be Rich-markup parsed unless intended.
  Pass `markup=False` for free-form `Static`/`OptionList` text and strip raw
  `<tool_call>...</tool_call>` blocks before Markdown rendering.
- Do not define widget helper methods named `_render`; Textual uses
  `Widget._render()` internally.
- Long-lived transcript/sidebar surfaces need scroll-capable widgets such as
  `RichLog`; plain `Static.update(...)` can show text without a usable scroll
  range.
- Slash command hints should be real selectable widgets with prompt-level key
  routing, not static hint text.
- `Textual @on(Message, css_selector)` requires the message class to define a
  `control` attribute. For custom messages without one, use plain
  `@on(MessageClass)` or the framework `on_<message_name>` convention.
- Textual `Tree` hierarchy requires nested `node.add(...)` for directories and
  `add_leaf(..., data=full_path)` at leaves. `root.add_leaf("a/b.csv")` creates
  a flat item, not a hierarchy.
- Prompt editor sizing should be fluid: allow `TextArea` to grow with
  `height:auto`, a small min height, a bounded max height, and overflow scroll.
- Conversation-first layout is easier to validate when secondary status,
  command output, doctor findings, and failure details are consolidated in a
  sidebar instead of scattered across mostly empty panes.

## Routing And Prompt Packages

- Mode handoff intents are app-layer control signals, not harness commands.
  Do not register `handoff_to_analyst` or `handoff_to_knowledge` as normal
  commands.
- The router keyword set must cover aggregation language (`count`, `total`,
  `sum`, `average`, `top N`, `how many`, `number of`, `breakdown of`) so data
  questions reach analyst mode. Optional LLM fallback routing should stay
  cached and off by default unless explicitly enabled.
- Toad and Posting are references, not blueprints. Reuse DataHarness-relevant
  Textual ideas such as Markdown prompt editing, fuzzy `@` picker, command
  providers, jump navigation, help surfaces, and reactive status; avoid copying
  unrelated shell integration, provider management, multi-agent, and diff UI.
- If code is copied or closely adapted from AGPL-licensed references, preserve
  attribution and keep it isolated in Layer 4 unless non-UI reuse is approved.

## Python And Dependency Management

- The live Python floor is `pyproject.toml` `requires-python`, mirrored in
  `uv.lock`. Historical docs can mention older versions and are not active
  dependency metadata.
- After changing `requires-python` or dependencies, run `uv sync` so `uv.lock`
  and the local editable install are refreshed. Use `uv`; do not use `pip`
  directly.
- In sandboxed sessions, `uv sync` may need approval because uv wants its normal
  cache under `~/.cache/uv`.

## Verification Habits

- Prefer focused regression tests next to the behavior being protected:
  runtime parser tests for stream handling, harness tests for plan/tool
  semantics, worker tests for sandbox and artifact behavior, and Textual pilot
  tests for UI workflows.
- Under zsh, single-quote `rg` patterns that contain markdown backticks; double
  quotes can execute command substitution before `rg` sees the pattern.
- For package-sensitive fixes, verify both source and frozen paths when
  practical. Source tests passing does not prove the current `dist/` binary has
  the fix.
- When diagnosing duplicate worker dispatch, compare user chat timestamps with
  worker telemetry before assuming the harness submitted the same work twice.
- Specs are aspirational until code and tests prove the behavior. Check the
  implementation before relying on a spec statement such as doctor tmp-script
  promotion or packaged behavior.
- A model may emit one valid `<tool_call>` then a truncated second block. In
  `run_turn`, a runtime `error` event with code `parse_error` or
  `incomplete_structured_content` must NOT fail the turn when
  `collected_tool_calls` is non-empty — break and fall through to
  `awaiting_tool_dispatch` so the valid call still dispatches.
- Classify recoverable LLM failures by `TurnFailed.error_code`
  (`parse_error`, `incomplete_structured_content`, `malformed_tool_call`), not
  by substring-sniffing `failure_summary`. Text sniffing breaks when the
  message lacks "tool_call"/"malformed" (e.g. "stream truncated").
- After the single malformed-tool repair nudge is spent, `run_agentic_turn`
  must yield an explicit `FinalMessage` (plain-language guidance), never a
  bare `return` — a silent dead turn leaves the user with no output.
- `_escape_control_chars_in_strings` only rescues literal control chars, not a
  stray unescaped `"` that prematurely closes a JSON string (e.g. mis-escaped
  `code_lines` f-string `...%\n\""`). Mitigate via prompt guidance: one
  statement per `code_lines` entry, no `\n` inside literals, single quotes
  inside f-strings.
- A weak quantized model emits a COMPLETE `<tool_call>…</tool_call>` pair but
  invalid JSON when the payload is large Python-in-JSON. Diagnose via
  `dist/.../runtime.log`: `finish_reason=unknown` (NOT `length`) rules out a
  token-budget truncation; `event_from_tool_call_text` only fires when the
  closing tag is present, so a `parse_error` there means the model's own JSON
  is broken, not a stream cutoff. Prompt band-aids do not fix this — remove
  code from the JSON entirely.
- `analysis_plan` model path is two-step: gen-1 emits a CODE-FREE plan
  (`{goal, steps:[{purpose, declared_inputs, expected_outputs}]}`); gen-2
  (`_generate_step_code`) is an internal, non-persisted runtime generation
  with `stop=["```"]` that returns fenced ```` ```python ```` via
  `extract_fenced_code` — no JSON escaping burden. Per step: validate
  generated code (reuse `_build_plan_from_arguments` via
  `_validate_generated_step`) with ONE bounded gen-2 retry, then a SINGLE
  approval. The command path (`_analysis_plan_events`/`plan_analysis`) is
  unchanged: code supplied directly, gen-2 NOT invoked.
- Two-step needs a split repair: gen-1 plan-SHAPE errors use the (now
  code-free) `_build_plan_analysis_repair_prompt`; per-step gen-2 code
  failures retry gen-2 only. Keep `_is_repairable_plan_analysis_error`
  matching both (added `"code generation failed"`); exhausted → `FinalMessage`
  (never silent). Share the build tail via `_finalize_plan` so command and
  model paths cannot drift.
- `tests/worker/test_executor.py::test_executor_blocks_dynamic_import_of_disallowed_package`
  can fail with `timeout` (vs `failed`) under full-suite load but passes in
  isolation — sandbox subprocess timing flake, not a regression. Re-run
  isolated before treating a worker-sandbox timeout as a real failure.
