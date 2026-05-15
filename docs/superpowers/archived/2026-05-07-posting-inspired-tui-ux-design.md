# Posting-Inspired DataHarness TUI UX Design

Date: 2026-05-07

## Purpose

Improve the DataHarness Textual interface by adapting the strongest UI and UX decisions from `darrenburns/posting` while preserving DataHarness layer boundaries.

This is not a port of Posting's HTTP client domain. It is an application of its Textual patterns: command discovery, contextual hints, keyboard navigation, focused help, status visibility, and CSS-driven interaction states.

## Reference Patterns

Posting patterns to adapt:

- `App` owns global bindings, command providers, themes, watchers, and app lifecycle.
- `Screen` owns workflow-local state such as layout, focus behavior, selected resources, and expanded sections.
- Textual command providers expose context-aware command palette results instead of static command lists.
- Input widgets provide contextual autocomplete and inline hints based on cursor position and current state.
- Select/list widgets support terminal-native navigation such as `j`, `k`, `l`, `enter`, and `escape`.
- Jump overlay maps stable widget IDs to short keys for fast spatial navigation.
- Focused-widget help is generated from widget-local help metadata and current bindings.
- Status and trace widgets expose async operation phases, not only final results.
- TCSS carries interaction details such as focus states, compact mode, disabled states, status colors, and modal styling.

## Architecture

DataHarness keeps the existing layered architecture:

- Layer 4 TUI talks only to `AppSession`.
- Layer 4 does not import or call `harness.orchestrator` directly.
- Layer 3 remains the source of command descriptors, status snapshots, workspace records, chat records, run events, and command execution.

The TUI should evolve from a simple app shell into a Textual-native interaction layer:

- `DataHarnessApp` owns global bindings, command providers, theme/style setup, status watcher workers, and app lifecycle telemetry.
- A main TUI workflow screen may be introduced when the current `compose()` method becomes too broad. That screen owns selected workspace/chat, focus rules, expanded panes, and local navigation state.
- Domain widgets remain small and message-oriented. Examples: `PromptBar`, `WorkspaceBar`, `ConversationPane`, `StatusSidebar`, `RunTracePane`, `CommandHintDropdown`, `HelpScreen`, and `JumpOverlay`.

## Components

### Command Provider

Replace the static command palette screen with a Textual command provider backed by `AppSession.list_commands()`.

Behavior:

- Searchable commands are built from `HarnessCommandDescriptor`.
- Unavailable commands are either hidden or clearly marked with `disabled_reason`.
- Command availability reflects current context: workspace, chat, active run, pending approval, pending clarification, and selected artifact.
- Selecting a command should either execute it immediately when no arguments are required or focus the prompt bar with a prefilled slash command and argument placeholders.

The existing slash grammar remains supported for CLI parity.

### Prompt Bar

Replace the plain `Input(id="user_input")` with a composed prompt bar.

Behavior:

- Shows active mode, run state, and current command hint.
- Submits normal chat text through `DataHarnessApp.submit_user_text()`.
- When text starts with `/`, displays command suggestions.
- When a selected command requires arguments, displays argument name, type, description, and example usage.
- Argument candidates are context-sensitive where data exists:
  - workspace IDs for workspace arguments
  - chat IDs for chat arguments
  - run IDs for run arguments
  - step IDs for step arguments
  - artifact paths for artifact arguments

Candidate loading must go through `AppSession` methods or future Layer 4 facade methods, not direct Layer 3 imports.

### Keyboard Navigation

Add consistent navigation across TUI surfaces.

Behavior:

- `ctrl+p` opens the command palette.
- `f1` or `ctrl+?` opens help for the focused widget.
- `ctrl+o` opens jump mode.
- `f2` continues to open workspace management.
- List and select screens support `j`, `k`, `enter`, `l`, and `escape`.
- Agent mode selection may support direct keys: `i` interaction, `a` analyst, `k` knowledge.

### Jump Mode

Add a Posting-style jump overlay using stable DataHarness widget IDs.

Initial jump targets:

- `1`: prompt bar/input
- `2`: conversation
- `3`: status/sidebar
- `w`: workspace manager
- `c`: chat manager when available
- `p`: plan/process surface when available

The overlay should ignore hidden widgets and restore previous focus when dismissed.

### Focused Help

Add lightweight `HelpData` and a `HelpScreen`.

Behavior:

- Major widgets define help metadata.
- Help screen renders the focused widget name, description, and current keybindings.
- Help is modal, dismissible with `escape`, and restores focus when closed.
- Permanent instructional text in the main UI should be reduced once focused help exists.

### Status And Run Trace

Make async progress visible in a compact, predictable way.

Behavior:

- `WorkspaceBar` shows workspace, chat, mode, run state, runtime status, and current phase.
- Sidebar shows detailed command/run phase history with bounded storage.
- Optional compact markers show phase state for route, prompt build, model stream, tool execution, artifact write, validation, and final response.
- Failures include phase, error code, summary, and offered action where available.

The TUI should consume existing app events first. If a phase is missing, document the missing event rather than importing deeper layers.

### TCSS And Theme Behavior

Move inline app CSS into a dedicated TCSS file.

Behavior:

- Focused pane states are visually obvious.
- Compact mode reduces padding and borders while preserving readability.
- Status severity classes cover success, warning, error, running, disabled, and unavailable states.
- Command palette, autocomplete dropdowns, modal screens, jump labels, and help screen have dedicated styles.

Packaging must include the TCSS file in the app bundle.

## Data Flow

Command palette:

1. TUI builds command context from current Layer 4 state.
2. TUI calls `AppSession.list_commands(context)`.
3. Provider converts descriptors into searchable Textual hits.
4. Selection either executes no-argument commands or moves the prompt bar into argument collection mode.
5. Execution uses `AppSession.handle_direct_command()`.
6. App events update conversation, sidebar, status bar, and trace surfaces.

Prompt hints:

1. User types in the prompt bar.
2. Prompt bar parses current token and cursor position.
3. It asks a hint provider for command or argument candidates.
4. Hint provider uses cached command descriptors and Layer 4 facade data.
5. Selection updates input text without executing until submitted.

Status updates:

1. `AppSession.watch_status()` streams status snapshots.
2. `DataHarnessApp` or the main screen updates reactive UI state.
3. Widgets render state via classes and concise text.
4. Detailed run/command events are appended to bounded sidebar/trace buffers.

## Error Handling

- Command descriptor load failure: notify the user and keep slash input usable.
- Candidate load failure: show no suggestions, keep typing/submission usable, and append a sidebar warning.
- Invalid slash command or invalid arguments: show the validation error near the prompt and via notification.
- Command execution failure: emit existing app error telemetry, update sidebar failure state, and keep the prompt focused.
- Jump target missing or hidden: ignore it and leave focus unchanged.
- Help requested with no focused widget: show app-level help.
- TCSS load/package failure: app must still start with a minimal fallback style.

## Testing

Focused tests should cover:

- TUI still does not import `harness.orchestrator` directly.
- Command provider lists required Layer 3 commands and marks unavailable commands.
- Command search filters results and preserves descriptor metadata.
- Prompt bar suggests commands after `/`.
- Prompt bar suggests workspace/chat IDs for matching command argument positions.
- Selecting a command with required arguments pre-fills the prompt rather than executing prematurely.
- No-argument command execution still streams app events into existing widgets.
- Jump overlay focuses visible target widgets and ignores hidden targets.
- Focused help renders widget help and keybindings.
- Status bar updates on status snapshots and command/run progress events.
- TCSS file is included in packaging configuration.

## Scope Boundaries

In scope:

- Interaction model, command discovery, hints, navigation, focused help, status visibility, and styling.

Out of scope:

- Rewriting Layer 3 command behavior.
- Changing the slash grammar.
- Adding a full user settings system before the interaction model is stable.
- Copying Posting source wholesale.
- Replacing the existing async `AppSession` boundary.

## Implementation Order

1. Command provider and Textual command palette.
2. Prompt bar with command and argument hints.
3. Status bar and run trace improvements.
4. Keyboard navigation and jump overlay.
5. Focused-widget help.
6. TCSS extraction and compact/focus styling.
7. Optional TUI settings after behavior stabilizes.

