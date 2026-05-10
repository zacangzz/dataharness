# Collection of Lesssons Learnt

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
