# Collection of Lesssons Learnt

## Packaged worker subprocesses must dispatch before TUI startup
- In source mode, `PythonStepExecutor` can run `sys.executable -m worker.sandbox_bootstrap <config>`. In a PyInstaller onefile binary, `sys.executable` is `dist/dataharness`, so the same argv becomes `dist/dataharness -m worker.sandbox_bootstrap <config>`.
- The CLI must intercept that private `-m worker.sandbox_bootstrap` target before normal argparse/TUI startup. If it falls through to `build_app()`, the child process launches the TUI and the parent worker eventually reports a misleading `execution timed out`.
- Increasing `ResourceLimits.timeout_seconds` is only a usability limit change; it does not fix packaged bootstrap misrouting.

## Textual prompt focus and copy behavior need app-level handling
- When a child widget such as `PromptBar` needs to restore focus after an overlay/picker interaction, call `self.app.set_focus(target)` rather than a widget-local `set_focus`; otherwise focus restoration can silently fail and leave the prompt inactive.
- DataHarness should expose its own copy action for TUI text. Textual has screen selection support, but app/system bindings can make `ctrl+c` ambiguous; bind copy explicitly and fall back to focused widget `text_buffer()` for panes like conversation/sidebar.

## Dist run logs show packaged behavior may lag source fixes
- When checking `dist/` behavior, treat chat logs and telemetry as the source of truth for the packaged binary that ran, not the current `src/` tree. Example: current runtime source has EOS buffering tests, but the latest `dist` chat still contains leaked `end_of_turn>` and `[/start_of_turn]` tags.
- Worker duplicate suspicion should be checked against both chat timestamps and `dist/harness/telemetry/worker.events.jsonl`: in the 2026-05-11 latest run, the same sales query was submitted twice by the user and Layer 2 dispatched twice, both failing policy validation because the generated script imported `os`.
- Doctor tmp/script reuse is not implemented just because the spec describes it. Current `DoctorRunner` only reports tmp item counts; reusable scripts remain under `artifacts/tmp/.../step.py` unless a promotion path writes them to `memory/functions/`.
- Layer rule correction: `read_file` is a Layer 3 workspace fact tool and should not format CSVs as markdown tables. Presentation-only CSV/TSV rendering belongs in Layer 4 conversation display.
- The `import os` failure should be fixed by pre-approval validation using the same worker import policy plus prompt wording that lists allowed imports exactly; do not add `os` to the worker allowlist unless the sandbox policy intentionally changes.

## Toad-inspired TUI work should stay DataHarness-specific
- For DataHarness, the useful Toad patterns are the Markdown prompt editor, `@` fuzzy file picker with tree fallback, streaming Markdown conversation blocks, and navigable sidebar/session surfaces.
- Do not port Toad wholesale: shell integration, agent store, ACP provider management, multi-agent execution, and diff views are outside the current DataHarness TUI scope.
- AGPL-3.0 compatibility is acceptable for this project, but copied or closely adapted Toad code should preserve attribution and stay isolated in Layer 4 unless a non-UI utility is explicitly approved.
- Split implementation into independent plans: file picker first, prompt editor second, Markdown conversation third, sidebar/workspace fourth, and integration/packaging last. This keeps shared dependencies clear and makes each checkpoint testable.

## Python 3.14 migration uses active project metadata plus uv sync
- The live Python floor for packaging is `pyproject.toml` `requires-python`; historical `docs/superpowers/plans/*` references to Python 3.12 are not active dependency metadata.
- After changing `requires-python`, run `uv sync` so `uv.lock` updates its top-level `requires-python` field and the local editable package is rebuilt in the active environment.
- In the sandbox, `uv sync` may need approval to access the normal uv cache under `~/.cache/uv`.

## Posting-style Textual UX maps cleanly onto Layer 4
- Posting's strongest reusable TUI patterns are Textual command providers, cursor-aware autocomplete, stable-ID jump navigation, focused-widget help, reactive status surfaces, and TCSS-driven focus/compact states.
- For DataHarness, these should live in Layer 4 and use `AppSession`/command descriptors/status events rather than importing Layer 3 internals directly.
- Jump overlays must target focusable widgets; map prompt jumps to `#user_input` and mark static jump surfaces focusable when they are intended destinations.

## PyInstaller dynamic imports need explicit packaging coverage
- When a packaged binary fails with a PyInstaller wrapper error, inspect `dist/harness/logs/bootstrap.log` for the real Python exception before changing runtime code.
- `src/cli.py` dynamically imports `harness.factory` and `harness.workspace`, so `scripts/build_app.sh` must package those modules explicitly; only hidden-importing `app.tui.app` and collecting `observability`, `textual`, and `llama_cpp` is insufficient.
- `scripts/build_app.sh` also needs hidden imports for `app.session`, `harness.control`, `runtime.config`, and collect-submodules for `app`, `harness`, `runtime`, and `worker` so dynamic DataHarness packaging paths survive PyInstaller analysis.
- For a single PyInstaller data file, the `--add-data` destination must be the target directory, not the full target file path; otherwise `src/app/tui/dataharness.tcss:app/tui/dataharness.tcss` extracts as `app/tui/dataharness.tcss/dataharness.tcss`.
- Packaging verification should include `uv run pytest tests/packaging/test_build_app_script.py -q`, `bash scripts/build_app.sh`, and running `dist/dataharness` until the Textual UI renders.

## Layer 1 async bridge owns llama-cpp sync streaming
- `llama-cpp-python` 0.3.20 high-level APIs expose sync `create_chat_completion` and `create_completion` streaming iterators, not native async APIs; Layer 1 should provide async runtime semantics through its own private queue/bridge internals.

## Chat management belongs to workspace app records
- Chat management is now workspace-scoped persistent app records under `<app_root>/chats`; Layer 3 owns list/create/view/resume/delete/compact operations, and Layer 4 only renders controls.

## Layer 4 async TUI commands route through Layer 3 descriptors
- The async Layer 4 TUI must expose context-available Layer 3 functions through Layer 3 command descriptors, including the command palette and slash commands such as `/doctor`; doctor must emit verbose Layer 3 events for Layer 4 rendering.

## Async workspace API is a required Layer 3 module
- `Orchestrator` imports `harness.workspace_async`; if that module is missing, async harness/app tests fail during collection before behavior is exercised.
- The workspace manager must expose async-shaped create/list/rename/delete/activate/ingest methods and cascade chat deletion through `<app_root>/chats/<workspace_id>/`.

## Textual helper names must not shadow widget internals
- Do not define widget helper methods named `_render`; Textual calls `Widget._render()` internally for measurement and expects a renderable return value.
- Conversation-first TUI layout is easier to validate when secondary status, command output, doctor findings, and failure details are consolidated into one sidebar instead of many empty panes.
- Every terminal turn lifecycle event rendered in conversation should also update `RunTrace` and refresh trace widgets, otherwise workspace phase/sidebar trace can drift after runtime deltas.
- For long-lived chat/sidebar transcript surfaces, use Textual scroll view-backed widgets such as `RichLog`; plain `Static.update(...)` text can render visible content without producing a usable scroll range.
- Slash hint popups should be real selectable widgets (`OptionList`) with prompt-level key routing, not static hint text, so the input can keep focus while up/down/page keys move the highlighted command.

## Factory-built orchestrators must inherit the active app root
- The CLI can open a workspace under the packaged app root while an orchestrator created without `app_root` silently falls back to cwd; workspace commands then list/switch against the wrong directory even though the TUI status bar shows the opened workspace id.
- When wiring Layer 4 through `harness.factory`, derive the app root from `<app_root>/workspaces/<workspace_id>` and pass it through `Orchestrator` and `AppSession`.

## Validity classifier vocabulary must match async spec
- `ValidityState` must expose `ok`, `changed`, `stale`, `needs_review`, `revalidated`, and `broken_lineage`; legacy `missing`/`unvalidated` are gone.
- `classify(...)` must be flag-aware (stale, needs-review, revalidated, fingerprint changes); ignoring these drifts artifact validity from spec.

## `.gitignore` rules must be anchored when names collide with `src/` subdirs
- Repo root has a runtime data dir `harness/`, but `src/harness/` and `tests/harness/` share the name; an unanchored `harness/` rule silently hides new source/test files.
- Use `/harness/` (leading slash) so only the repo-root data directory is ignored. Verify with `git check-ignore -v <path>`.

## CLI must parse args before constructing the TUI
- `src/cli.py` constructs the Textual app inside `main()`; if argparse runs after construction, `./dist/dataharness --help` launches the UI instead of printing help.
- Parse CLI args first so argparse can exit cleanly for `--help`/`--version` before any Textual import side-effects.

## Async runtime spec removes sync worker execution path
- `Orchestrator` no longer exposes `dispatch_step(...)`; the async approval/resume path submits and waits via `worker.submit(...)`/`worker.wait(...)`.
- Do not reintroduce `worker.execute(...)` callers; a removal scan should report zero `.execute(...)` matches in src.

## Missing runtime must be visible to users
- A `None` LLM runtime must never produce an empty assistant response. Surface `runtime_not_loaded` as a failed turn and show `runtime_status` in the TUI status line.
- The packaged CLI entrypoint must pass the default `LlamaCppRuntime` factory into `build_app`; keeping the runtime optional is useful for tests, but production startup needs the factory.
- Lazy runtime imports need explicit PyInstaller hidden imports. `runtime.config` is not enough when `_default_runtime_factory(...)` imports `runtime.llama_cpp_runtime` dynamically.

## Gemma chat_format silently drops the `system` role
- llama-cpp's `chat_format="gemma"` template has no system slot; sending `RuntimeMessage(role="system", ...)` results in the persona prompt being dropped before reaching the model. Symptom: the model returns its base identity (e.g. "I am a large language model, trained by Google") regardless of the Layer 4b agent prompt.
- `RuntimeRequestBuilder.build_messages` must be aware of the active chat_format. When the format starts with `gemma`, fold persona + durable context + prior summaries into a `[SYSTEM]...[/SYSTEM]` block prefixed onto the first user turn instead.
- Plumbing: `LlamaCppRuntime.chat_format` is exposed as a property, declared on the `Runtime` Protocol, and `Orchestrator.run_turn` rebuilds `RuntimeRequestBuilder` whenever the runtime's `chat_format` changes (not only when `context_window` changes).

## EOS tokens leak into stored text when stripped per chunk
- llama-cpp commonly streams `<end_of_turn>` (and other EOS literals) split across chunk boundaries. A per-chunk `str.replace` strip is a no-op on partial chunks, so the bytes flow through `emit_content_events` as `text_delta` and into chat persistence. Replayed assistant history then contaminates the next turn and confuses the model.
- The fix is the same buffered prefix-suffix pattern that `marker_prefix_suffix` already applies to `TOOL_START`/`THINK_START`. Add `eos_prefix_suffix` and `strip_full_eos`, run them inside `emit_content_events`, and remove the per-chunk `strip_eos` from the streaming loop. At finish, drop any trailing EOS prefix still in the buffer rather than emitting it.

## Orchestrator persists user message before building runtime messages — do not duplicate
- `Orchestrator.run_turn` appends the user message to the chat store and then passes the resulting `chat_record` into `RuntimeRequestBuilder.build_messages`. The current user turn is therefore already inside `chat_record.messages` and gets emitted by the recent-turns loop.
- `build_messages` must not unconditionally append `current_user_text` again; guard the append on whether the last `recent` message already matches the current user turn. Tests asserting `msgs[-1].content == current_user_text` should be updated to use a "exactly-once" assertion instead.

## Textual `@on(Message, css_selector)` requires `control` attribute on the message class
- Using `@on(FilePicker.Selected, "#workspace_file_panel")` raises `OnDecoratorError: The message class must have a control to match with the on decorator`. Custom Message subclasses without a `control` ClassVar cannot be filtered by CSS selector — fall back to the framework `on_<message_name>` naming convention or a plain `@on(MessageClass)` without selector.

## Textual `Tree` hierarchical population requires nested `node.add` then leaves
- `tree.root.add_leaf(path_with_slashes)` makes a flat list. Real hierarchy needs `node = parent.add(name)` for each path component and `node.add_leaf(filename, data=full_path)` only at the leaf. After populating, call `tree.root.expand()` so the user sees children.

## Agentic loop belongs in the Harness, NOT the Application layer
- An earlier iteration placed the agentic loop (`TurnRunner`) in `src/app/agents/`. That was wrong per spec §8.1 ("the application session is a thin Layer 4 adapter… it may not become a second orchestrator"), §7.14 (agents must use harness services for tool dispatch and clarification handoffs), §7.15 (agents may not own platform retry or repair logic), §8.4 (harness owns "validation of structured outputs and tool calls"), and §6.3 step 9 (harness decides "continue, retry, replan, ask for clarification, switch modes, or finish").
- The agentic loop is now `Orchestrator.run_agentic_turn(state, *, workspace_dir, chat_id, user_input, requested_mode, prompt_provider, max_iterations)` in Layer 3. It owns durable_context build, single-stream invocation via `run_turn`, tool-call dispatch via `_dispatch_tool_call`, follow-up `[TOOL_RESULT]` message construction, empty-output retry, and mid-turn mode handoff acceptance (emits `ModeHandoffAccepted` and reloads prompt via the provider callback).
- Layer 4 stays thin: `AppSession.run_user_turn` picks the initial mode via `AgentModeRouter` (§8.3 step 2), defines a `prompt_provider(mode) -> str` callback that loads from `PromptPackageRegistry`, calls `orchestrator.run_agentic_turn(...)` once, maps harness events to App events for the TUI. Knowledge intent handlers moved from `app/agents/intent_handlers.py` to `harness/knowledge_intents.py` because memory writes are workspace truth (§3.4, §6.13).
- Harness emits `RuntimeDelta`, `TurnPaused`, `ModeHandoffAccepted`, `ToolCallExecuted`, `ApprovalRequired`, `FinalMessage`, `TurnFailed`. App rendering layer never decides "what next" — it only renders what L3 emits.
- The prompt-provider callback is the narrow injection point that lets L3 reload Layer 4-owned prompt packages mid-turn (per §8.2 "Layer 3 must not import Layer 4 application modules" — the App injects, the harness consumes).

## Empty-buffer disposition is harness mechanics, not an app decision
- When the runtime emits only `<tool_call>` XML (parsed out of the text buffer), `Orchestrator.run_turn` yields `TurnPaused(reason="awaiting_tool_dispatch", pending_tool_calls=[…])` instead of writing an empty assistant row. When the runtime emits nothing at all it yields `TurnFailed(error_code="empty_output")`. The harness's `run_agentic_turn` layer applies the retry policy (one nudge retry on `empty_output`); no hollow `asg_…` rows ever land in chat history.

## Workspace context is plumbed via run_turn parameter; built by harness
- `Orchestrator.run_turn(...)` accepts `durable_context: str = ""` (passed straight into `RuntimeRequestBuilder.build_messages`). It is no longer hardcoded empty.
- `Orchestrator.run_agentic_turn` builds it via `Orchestrator._build_durable_context_block(workspace_id, workspace_dir)` which composes `status_snapshot` + `context_manager.build(workspace_dir, token_budget=…, status_text=…)`. App layer never touches workspace files directly.
- `harness/context.py` exposes `list_workspace_files()` and `read_file_schema()` as filesystem-pure helpers reused by both the durable-context builder and the `list_files` / `inspect_file` runtime-callable harness commands.

## Plans must originate from the LLM via `plan_analysis` tool_call, not keyword triggers
- The earlier `if active_mode == "analyst" and "compare" in user_input.lower()` substring trigger in `Orchestrator.run_turn` is gone. Plans are no longer auto-built from a keyword. The model emits `<tool_call>{"name":"plan_analysis","arguments":{"goal":"…","steps":[{"purpose","code","declared_inputs","expected_outputs"}]}}</tool_call>` and the `plan_analysis` harness command builds a real `Plan` + `StepContract`, stashes the contract in `_pending_contracts`, and emits `PlanReady` + `ApprovalRequired`.
- `HarnessCommandRegistry` gained a `"json"` ArgType so nested `steps: list[dict]` survives `validate()` without coercion.
- Code text in the contract originates entirely from L1 Runtime (the LLM); L3 only validates and packages; L4 gates user approval; L2 executes via the existing `resume_approved_step` → `PythonStepExecutor` path. Layers stay in lane.

## Mode handoff is an App-layer control signal, not a harness command
- `handoff_to_analyst` / `handoff_to_knowledge` are intent labels in `MODE_INTENTS`, not registered commands. Earlier `TurnRunner._dispatch` looked them up in `Orchestrator.registry` → `KeyError` → fed `{"error":"unknown tool"}` back to the model → infinite loop.
- Fix: TurnRunner now treats `_HANDOFF_INTENTS` as terminal control signals. On detection it emits `AppModeHandoff(target_mode=…)`, reloads the prompt package for that mode, sets `handoff_used=True` (one handoff per turn cap), and re-runs the original `user_text` under the new mode. Subsequent handoffs in the same turn become terminal no-ops.
- App TurnRunner also short-circuits the loop on `AppApprovalRequired`. After `plan_analysis` emits an approval gate the loop terminates and waits for the user, instead of dispatching the plan tool_call as a "result" and re-prompting.

## Router keyword set must include count/total/aggregation language
- Original `analysis_terms` only covered `analyze, compare, calculate, compute, chart, plot, correlation, regression, forecast, summary`. Queries like "total number of customers", "how many regions", "average amount", "top 5" all stayed in interaction mode. Now expanded with count/total/sum/average/mean/median/max/min/group/filter/distinct/percent/etc plus phrase patterns ("how many", "how much", "number of", "breakdown of").
- Optional `enable_llm_classifier=True` opens an LLM-fallback path with per-text caching for ambiguous cases that pass the keyword filter; off by default to keep routing deterministic and cheap.

## Textual `Static`/`Markdown`/`OptionList` parse content as Rich markup by default — disable for dynamic text
- Any free-form text rendered through `Static`, `Markdown`, or `OptionList` is Rich-markup-parsed unless `markup=False`. Chat history may contain `[TOOL_RESULT]` blocks; harness/pydantic errors contain `[type=..., input_value=..., input_type=dict]`; assistant streams contain `<tool_call>...</tool_call>`. Unbalanced `[` or unknown `[tag]` → `rich.errors.MarkupError` mid-render → Textual layout crashes → PyInstaller binary exits with bare `[PYI-19761:ERROR] Failed to execute script 'cli'` (traceback swallowed).
- Fix: pass `markup=False` to every `Static`/`OptionList` rendering dynamic content. For Static subclasses without an explicit `__init__`, add `def __init__(self, *args, **kwargs): kwargs.setdefault("markup", False); super().__init__(*args, **kwargs)`. The internal flag set by the kwarg is `_render_markup` — tests can assert `getattr(widget, "_render_markup", True) is False`.
- For `Markdown`, strip `<tool_call>...</tool_call>` blocks before update (regex `r"<tool_call>.*?</tool_call>"` with `re.DOTALL`). Markdown tolerates `[...]` better than Static's markup parser, but raw XML tags confuse rendering.
- PyInstaller binaries silently swallow tracebacks. Add a top-level `try/except BaseException` in `src/cli.py` that writes the full traceback to `dist/harness/logs/app_crash.log` before re-raising.

## Approval UX: inline banner above prompt, not full-screen `push_screen`
- `ApprovalScreen` as a `push_screen` modal was obtrusive: blacked out conversation + plan pane just to confirm one decision. Replaced with `ApprovalBanner(Vertical)` in `src/app/tui/widgets.py` mounted between `ConversationPane` and `PromptBar`, hidden by default (`display = False`), shown via `banner.show(plan=…, step_contract=…)`.
- Banner emits `ApprovalBanner.ApprovalDecisionMade(plan, step_contract, decision)` via `post_message`. App listens with `@on(ApprovalBanner.ApprovalDecisionMade)` and routes to the existing `handle_approval_decision` — no change to `resume_approved_step` downstream.
- Keybindings `a`/`r`/`v` bound on the banner; buttons mirror them. The banner sets `self.display = False` in `__init__` so tests without TCSS still see it hidden initially.
- Same pattern applied to clarification: `ClarificationBar` replaces `ClarificationScreen`. Input + Submit/Dismiss; Enter submits via `on_input_submitted`; Escape dismisses; emits `ClarificationSubmitted(text)` and `ClarificationDismissed` messages.
- Test note: `pilot.click(...)` on a widget toggled visible only by `display=True` (without the TCSS `.visible` class actually loaded) is flaky — buttons may not register hits in the harness. Prefer testing via key bindings (`pilot.press("a")`, `pilot.press("escape")`) or via `Input.value = "..."` then `pilot.press("enter")`. Reserve `pilot.click` for cases where TCSS is loaded.

## Cache Plan in L3 orchestrator; pass only `plan_id` from L4 back into `resume_approved_step`

- `ApprovalRequired` (harness/events.py) carries `plan_id + step` (a step dict) — NOT the full Plan. L4 must NOT reconstruct a Plan dict from these fields: it will be missing `workspace_id, run_id, goal, requires_code_execution`, and `Plan.model_validate` raises `ValidationError` at `orchestrator.py:resume_approved_step`. That error then routes through a Textual notification widget → renders as Rich markup → `MarkupError` on stderr (the `[type=missing, input_value={...}, input_type=dict]` brackets are the trigger).
- Fix: orchestrator stashes the Plan in `_pending_plans: dict[str, Plan]` keyed by `plan.id` at the same site as `_pending_contracts` (after building the plan in `_make_plan_analysis_handler`). `resume_approved_step` accepts `plan_id` and resolves via the cache. Plan is popped in the `finally` block after the step runs.
- L4 passes `plan_id=plan.get("id")` only — banner stores only the id, not a synthetic plan dict.

## Agentic loop must NOT persist its synthetic tool-followup re-prompts

- `run_agentic_turn` re-enters `run_turn` with `current_input = _format_tool_followup(...)` — a string containing `[TOOL_RESULT name=...]...[/TOOL_RESULT]` and `[ASSISTANT_DRAFT]…[/ASSISTANT_DRAFT]`. Without guarding, `run_turn` persists this as a fresh **user-role** message via `chat_store.append_message`. Implementation detail leaks into durable chat history; subsequent turns see polluted context and the model replies prose-only without tool calls.
- Fix: `run_turn` takes `persist_user_message: bool = True`. `run_agentic_turn` tracks `first_iter` and passes `False` on every continuation (tool-followup, handoff re-run, empty-output retry).
- Also: gemma-class models echo `[ASSISTANT_DRAFT]…[/ASSISTANT_DRAFT]` wrappers from the prompt examples back into their replies. Strip with `_ASSISTANT_DRAFT_TAG_RE` before `append_message(role="assistant", …)` and before yielding `FinalMessage.text`. Also strip in `_format_tool_followup` before re-wrapping `assistant_partial`, to prevent nested `[ASSISTANT_DRAFT][ASSISTANT_DRAFT]…[/ASSISTANT_DRAFT][/ASSISTANT_DRAFT]`.
- Defensive display cleanup: extended `src/app/tui/conversation.py:_clean` to strip `[ASSISTANT_DRAFT]` markers, `[TOOL_RESULT …]…[/TOOL_RESULT]` blocks, and the trailing "Use the tool result(s) above…" hint. `rehydrate_from_record` skips messages that clean to empty (older polluted chats).
- Prompt hygiene: added "NEVER emit `[ASSISTANT_DRAFT]` or `[TOOL_RESULT]` tags yourself" line to `interaction.md` and `analyst.md`.

## L3 vs L2 for new tools

- L2 worker = sandboxed Python execution for user/analyst-supplied code (permission envelope, artifact verification, resource limits).
- L3 harness tool = deterministic, workspace-bounded, no user code. `list_files`, `inspect_file`, and now `read_file` all live here. Pattern: register via the `("name", [ArgSpec(...)])` table in the workspace-handler factory loop in `orchestrator.py`, add a branch in `_make_workspace_handler`'s dispatch, and implement a module-level helper (`_read_workspace_file`) for the unit-testable core.
- `read_file` enforces: workspace boundary via `wd.resolve()` parent check, `max_bytes` byte cap (default 64 KB), char cap `_READ_FILE_CHAR_CAP = 32_000` for context-window safety, `UnicodeDecodeError` → `{"error": "binary_file"}`.


## Tool-call JSON must tolerate control chars inside string values

- Symptom: `ModelBehaviorError: malformed tool call: invalid tool_call json: Invalid control character at: line N column M`. Cause: model emits literal `\n`/`\t`/`\r` inside a JSON string value of `<tool_call>{...}</tool_call>`. `json.loads` is strict by default.
- Fix in `src/runtime/tool_calls.py:_match_and_parse`: 3-tier parse — (1) strict, (2) `json.loads(raw, strict=False)` (stdlib permissive mode allows control chars in strings), (3) sanitizer `_escape_control_chars_in_strings` that escapes `\n\r\t` and `<0x20` chars while tracking quote/escape state. Existing `repair_tool_call_block` benefits transparently.
- Tests: `tests/runtime/test_tool_calls_control_chars.py` covers literal newline, tab, CR, `\x01`, and preserved escaped quotes.

## Read_file behavior: summarize, do not paste verbatim

- Without explicit guidance, model whim decides whether `read_file` results get pasted raw (markdown dumps poorly in TUI) or summarized. Fix in prompts only — no code path change.
- Added to `interaction.md` and `analyst.md`: "After a `read_file` `[TOOL_RESULT]` returns, do NOT paste file contents verbatim. Summarize in 2–4 sentences."

## TUI prompt bar fluid sizing

- `#user_input` was fixed `height:3 min:3 max:6`. Changed to `height:auto; min-height:1; max-height:4; overflow-y:auto`. `PromptEditor` extends `TextArea`, which natively grows with content; `overflow-y:auto` triggers scroll past 4 lines.

## Chat persistence moved inside per-workspace dir

- Was: `app_root/chats/<wid>/<cid>`. Now: `app_root/workspaces/<wid>/chats/<cid>`. Workspace rename/delete naturally cascades chats — `workspace_async.rename_workspace` no longer needs separate `chats/` rename; `delete_workspace` lets `shutil.rmtree(workspace_dir)` handle it (still defers to `ChatStore.cascade_delete_for_workspace` for in-memory pending cleanup + result records).
- `ChatStore.__init__` runs `_migrate_legacy_layout()` once: walks `app_root/chats/<wid>/*` → `workspaces/<wid>/chats/<*>`, then removes the empty legacy dirs. Safe on cold start; no-op if legacy absent.
- `ChatStore` iterates `_iter_workspace_chat_roots()` (lists `workspaces/<wid>/chats`) instead of a single root for unknown-chat resolution (`_load_record`, `register_chat`, `delete_chat`). `list_chats` and `cascade_delete_for_workspace` use the direct `_workspace_chats_dir(wid)` resolver.
- Workspace `dist/` binaries already shipped with old layout — first launch after upgrade triggers migration; existing chats reappear under the new path.

## Sidebar FILES restricted to workspace `data/`

- `WorkspaceFileIndex.scan` now walks only `workspace_dir/"data"`. Rel paths remain relative to the workspace root (still `data/foo.csv`), so `@` file mentions and `format_file_mention` are unchanged. `memory/`, `state/`, `chats/`, and other workspace internals no longer surface in the sidebar or `@` picker.
- `list_files` (L3 harness command) already filtered to `data/` via `list_workspace_files` — both paths now agree.

## Tool-call JSON: tolerate key aliases + retry agentic loop on malformed parse

- Symptom: turn dies silently — assistant message never persisted, runtime.log shows `finish_reason='unknown'`, no retry stream. Root cause: model emits `<tool_call>{"tool_name":"x","parameters":{...}}` (or extra keys, or missing `arguments`). `parse_tool_call_block` strict `set(payload) != {"name","arguments"}` check fails → `repair_tool_call_block` only fixes non-dict `arguments` → both raise `ToolCallParseError` → `event_from_tool_call_text` raises `ModelBehaviorError` → `SyncToAsyncBridge._produce` swallows + emits synthetic `error` event with `error_code="runtime_exception"` → `run_turn` yields `TurnFailed` + returns.
- Critical gap: `run_agentic_turn` only retried on `error_code == "empty_output"`. All other `TurnFailed` codes (incl. `runtime_exception`) silently terminate — no retry, no recovery, no visible recovery path.
- Fix `src/runtime/tool_calls.py`: `_normalize_payload` accepts name aliases (`tool_name`/`function`/`function_name`/`tool`) and args aliases (`parameters`/`args`/`params`/`input`); ignores extra keys; defaults missing `arguments` to `{}`; coerces non-dict args to `{"value": x}`. `repair_tool_call_block` now reuses the normalizer. Parse error includes 200-char raw snippet for forensics.
- Fix `src/harness/orchestrator.py:run_agentic_turn`: detect `TurnFailed` whose `failure_summary` mentions "malformed tool", "tool_call", or "modelbehavior"; retry once with explicit nudge ("emit exactly one valid block: ... strict JSON — no literal newlines/tabs in string values, no extra keys").
- Tests: alias/extra-key/coerce/default-args coverage in `test_tool_calls_control_chars.py`; `test_tool_calls.py` updated — strict-rejection-of-missing-arguments replaced with default-to-empty; added missing-name rejection.
- Lesson: when introducing a recovery code path in a multi-iteration loop, audit every error_code branch — silent termination on unhandled codes leaves the user staring at a dead chat.
