# Tools vs Commands

This document defines how DataHarness uses the words **tool** and **command**.
The distinction matters because the app has both human-facing controls and
model-facing callable actions, and some names intentionally overlap.

## Short Version

| Feature | Commands | Tools |
|---|---|---|
| Primary user | Human user | Runtime model / agent loop |
| Interface | Slash command, command palette, or TUI action | `<tool_call>{...}</tool_call>` emitted by the model |
| Purpose | Control the app, workspace, chat, run, approval, memory, and diagnostics | Let the model inspect workspace state, request analysis, route to another mode, or propose knowledge updates |
| Owner | Layer 3 harness for app commands; Layer 4 for local TUI actions | Layer 3 harness agentic loop and runtime tool-call parser |
| Safety boundary | Direct command handlers validate arguments and operate through harness services | Tool calls are parsed, validated, dispatched by the harness, and may stop at approval gates |
| Example | `/doctor`, `/list_files`, `/compact` | `<tool_call>{"name":"list_files","arguments":{}}</tool_call>` |

The simplest rule:

- A **command** is something the user asks the app to do.
- A **tool** is something the model asks the harness to do during an agentic turn.

## Why The Difference Exists

DataHarness is not a general-purpose coding agent with ambient access to shell
tools such as `Bash`, `Edit`, or `Glob`. It is a local-first data app with
layered boundaries:

- Layer 4 renders the TUI and collects user intent.
- Layer 3 owns orchestration, command semantics, workspace facts, memory, doctor,
  approval, and deterministic tools.
- Layer 2 runs approved Python analysis steps in the worker sandbox.
- Layer 1 streams model output and parses tool-call blocks.

The model can request work, but it does not directly mutate the machine. Data
analysis code reaches the worker only through `plan_analysis`, user approval,
and the approved execution path.

## Category 1: User Commands

User commands are registered in the harness command registry and are available
through slash commands or the command palette. They are the main app-control
surface.

Current registered harness commands:

- `doctor`: run diagnostics and propose cleanup or promotion actions.
- `compact`: compact the active chat history.
- `help`: show command help.
- `create_chat`, `list_chats`, `view_chat`, `resume_chat`, `delete_chat`: manage chats.
- `list_workspaces`, `create_workspace`, `rename_workspace`, `delete_workspace`, `switch_workspace`: manage workspaces.
- `workspace_status`, `workspace_inventory`: inspect workspace-level state.
- `list_files`, `inspect_file`, `read_file`: inspect workspace files.
- `plan_analysis`: build an analysis plan and request approval.
- `request_execution`: re-emit approval for a pending step.
- `cancel_run`: cancel the active run.
- `memory_review`, `recall_knowledge`: inspect memory proposals and saved knowledge.
- `inspect_artifact`, `provenance_inspect`, `validity_inspect`: inspect outputs, lineage, and validity state.
- `mark_result_trusted`, `mark_result_invalidated`: set user validity judgment for a step result.
- `challenge_conclusion`: open a review proposal against a prior conclusion.
- `stop_after_current_step`: request a graceful run stop.
- `revise_goal`: revise a stored plan goal.
- `retry_step`, `rerun_step`: request step reattempts.

The TUI also provides a local app command:

- `exit`: exit the application. The app also accepts `quit` in the same path.

## Category 2: Runtime-Callable Harness Tools

Runtime-callable harness tools are command descriptors that the app advertises
to the model in prompt packages. These are the model-facing subset of harness
commands.

Current advertised runtime-callable tools:

- `workspace_status`
- `workspace_inventory`
- `list_workspaces`
- `list_chats`
- `list_files`
- `inspect_file`
- `plan_analysis`
- `request_execution`
- `recall_knowledge`

These names are still implemented by the harness command registry. The
difference is access path: the model emits a `<tool_call>` block, the runtime
parses it, and the harness validates and dispatches it.

Example:

```json
{"name":"inspect_file","arguments":{"path":"data/sales.csv"}}
```

wrapped as:

```text
<tool_call>{"name":"inspect_file","arguments":{"path":"data/sales.csv"}}</tool_call>
```

## Category 3: Agent Control Intents

Some tool-call names are not normal commands. They are control intents consumed
by the agentic loop.

Terminal or response intents:

- `answer_directly`
- `respond_to_user`
- `request_clarification`

Mode handoff intents:

- `handoff_to_analyst`
- `handoff_to_knowledge`
- `handoff_to_clarification`

These are closer to routing signals than tools. They tell the harness whether
to stop, ask for clarification, or rerun the turn under another mode.

## Category 4: Knowledge Intent Tools

Knowledge-mode tool calls are handled by the harness knowledge intent
dispatcher. They create memory update proposals through `KnowledgeManager`;
they do not bypass the memory ownership rule.

Current knowledge intent tools:

- `store_workspace_knowledge`
- `update_preferences`
- `record_gap`
- `save_function_candidate`

These are model-facing proposal tools. The durable memory write path remains
owned by Layer 3.

## Category 5: Worker Execution

Worker execution is not exposed as a generic shell or Python tool. The model
cannot directly run arbitrary code.

The execution flow is:

1. The model emits `plan_analysis` with a goal and one or more code steps.
2. The harness validates the plan, declared inputs, expected outputs, and worker policy.
3. The app asks the user for approval.
4. The approved step is submitted to the Layer 2 worker sandbox.
5. Results and artifacts return through structured harness events.

This keeps analysis useful while preserving the app boundary: the model plans,
the harness validates, the user approves, and the worker executes.

## Current Edge Case: `read_file`

`read_file` is registered as a harness command and can be dispatched by the
harness if called with valid arguments. It is also referenced in the interaction
and analyst prompts for text-file inspection.

However, it is not currently included in the runtime-callable command catalog
returned by `list_runtime_callable()`. That means the generated tool catalog and
the prompt guidance are not perfectly aligned. Treat `read_file` as a registered
workspace inspection command whose model-facing exposure should be clarified
before relying on it as a first-class runtime tool.

## Naming Guidance

Use these terms consistently:

- **Command**: user-facing app action, usually slash-command or command-palette accessible.
- **Harness command**: command registered in `HarnessCommandRegistry`.
- **Runtime-callable tool**: model-facing subset advertised to prompt packages and called through `<tool_call>`.
- **Intent**: model-facing control signal consumed by the agent loop rather than normal command dispatch.
- **Knowledge intent**: model-facing proposal operation routed through `KnowledgeManager`.
- **Worker step**: approved Python execution unit, never a direct model tool.

Avoid calling every app action a tool. In DataHarness, **tools are model-facing
capabilities**, while **commands are user-facing controls**.

## Implementation Pointers

- Command descriptors and runtime-callable filtering live in `src/harness/command_registry.py`.
- Command registration and command handlers live in `src/harness/orchestrator.py`.
- Runtime tool-call parsing lives in `src/runtime/tool_calls.py`.
- Prompt tool catalog construction lives in `src/app/agents/prompt_packages.py`.
- Knowledge intent dispatch lives in `src/harness/knowledge_intents.py`.
- TUI command palette integration lives in `src/app/tui/commands.py`.
