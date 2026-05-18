# Tools, Commands, And Services Split Design

## Purpose

DataHarness needs a strict exposed-surface taxonomy so model-callable behavior, TUI/user-callable behavior, and internal domain logic do not blur together.

This design updates the app vocabulary and source organization around three concepts:

- **Tool**: model-callable surface emitted as a `<tool_call>` through Layer 1 parsing, then validated and dispatched by Layer 3.
- **Command**: user/app-callable harness surface invoked from Layer 4 TUI, slash commands, command palette, or app controls, then validated and dispatched by Layer 3.
- **Service**: internal implementation unit, usually Layer 3, that owns domain logic used by tools and/or commands. Services are not directly exposed to the model or TUI.

The split must prevent orphaned exposed operations and keep Layer 4 command reachability explicit.

## Current Problem

`docs/app/tools-vs-commands.md` is directionally correct, but current code and docs still mix concepts:

- Runtime-callable tool exposure is currently derived from a command registry whitelist.
- `read_file` is registered and prompt-documented but not included in `list_runtime_callable()`.
- `_dispatch_tool_call()` can dispatch any registered command if the model emits its name.
- Knowledge intent names are model-facing, but their relationship to doctor and memory workflows is unclear.
- Workspace and chat commands are registered in one broad orchestrator registration block rather than clear command families.

The result is an exposed-surface model that is easy to drift: a command can become model-callable accidentally, and a model-facing operation can appear in prompts without a real registry boundary.

## Boundary Rules

No exposed harness operation may be surface-less.

If the model can call it, it is a Tool and must be listed in the tool registry and prompt catalog.

If the user or app can call it, it is a Command and must be listed in the command registry and reachable from Layer 4 through at least one path: slash command, command palette, dedicated TUI control, or documented contextual action.

If neither is true, it is an internal Service/helper and must not be documented as a tool or command.

Layer 1 remains parse-only for tool calls. Layer 1 streams model output and parses `<tool_call>` blocks; Layer 3 validates and dispatches tools.

Layer 4 remains the command integration layer. Commands are invoked from Layer 4 TUI/app surfaces and dispatched by Layer 3.

Model-emitted control intents are part of the model-callable surface. They should be represented as registered tools in a `control` tool family when they are dispatched through the same `<tool_call>` path as harness tools. They may have handlers that only update the agentic control loop rather than calling a service, but they must still be visible in the tool registry and prompt catalog.

## Tool Design

Tools are model-facing and should be grouped by purpose and risk. The public model-facing API should be smaller than the internal service API.

Use operation-based umbrella tools when operations share the same intent and risk level. Use separate tools when risk, approval, or lifecycle differs.

Tool arguments must be deterministically validated before handler execution. Tool descriptors should support type coercion, required-argument checks, `allowed_values` checks for enum-like arguments, and `regex` checks for bounded string/path formats. Regex validation is appropriate for simple deterministic constraints such as identifier syntax, operation names, and relative path shape; handlers and services still own semantic checks such as workspace existence or file availability.

Tool handlers must not depend on command-specific context types. They should receive a `ToolContext`, or a neutral shared call context, that contains only the state needed by model-callable operations: workspace id, chat id, run id, and pending approval/clarification flags.

### Core Tools

`file_read` is the canonical read-only file tool.

Examples:

```json
{"name":"file_read","arguments":{"operation":"list","path":"data/"}}
{"name":"file_read","arguments":{"operation":"inspect","path":"data/sales.csv"}}
{"name":"file_read","arguments":{"operation":"content","path":"data/notes.md","max_bytes":8192}}
```

`file_read` replaces the model-facing use of `list_files`, `inspect_file`, and `read_file`. Existing commands may remain for user compatibility during migration.

`file_write` is separate from `file_read` because writes have a different risk level and approval model.

`shell_command` is separate from both file tools. It must remain tightly allowlisted and read-only unless a future spec explicitly broadens it. It must not support pipes, redirects, environment mutation, network, or destructive commands.

`file_write` and `shell_command` are target tool definitions for the taxonomy. They should not be registered until their approval and allowlist behavior are implemented and tested.

### Control Tools

Control tools represent model-emitted flow-control choices:

- `answer_directly`
- `handoff_to_analyst`
- `handoff_to_knowledge`
- `request_clarification`
- `respond_to_user`

Control tools are model-callable tools because they are emitted through `<tool_call>`. They are not commands because the user does not invoke them through Layer 4 command surfaces. Additional mode-specific control tools may be added, but they must follow the same registry and prompt-catalog rules.

### Analysis Tools

Analysis is a first-class tool family because DataHarness is a data-analysis app.

`analysis_plan` creates a validated analysis plan from model-proposed steps and emits `ApprovalRequired`. It is the model-facing successor to `plan_analysis`.

`analysis_request_execution` re-emits approval for an existing pending step. It is the model-facing successor to `request_execution`.

Artifact, provenance, and validity inspection can also belong to the analysis tool family when model-facing access is useful:

- `analysis_inspect_artifact`
- `analysis_inspect_provenance`
- `analysis_inspect_validity`

Layer 2 execution remains approval-gated. The model can propose analysis work; it cannot directly execute arbitrary code.

### Knowledge Tools

Knowledge overlaps with doctor, but it should not simply become doctor.

Knowledge tools are model-facing recall or proposal operations:

- `knowledge_recall`
- `knowledge_propose_update`

They may propose notes, preferences, gaps, or reusable function candidates, but durable memory writes still go through `KnowledgeManager` and any required review path.

Doctor can use knowledge services internally during diagnostics and memory mining.

## Command Design

Commands are user/app-facing and must be reachable from Layer 4.

### App Commands

- `help`
- `exit` / `quit` where handled locally by Layer 4.

### Chat Commands

- `create_chat`
- `list_chats`
- `view_chat`
- `resume_chat`
- `delete_chat`
- `compact`

`compact` is a command, not a tool. Automatic token-pressure compaction is an internal harness workflow, not a user command and not a model tool.

### Workspace Commands

- `list_workspaces`
- `create_workspace`
- `rename_workspace`
- `delete_workspace`
- `switch_workspace`
- `workspace_status`
- `workspace_inventory`

Workspace commands should be organized as a command family and remain visible through Layer 4 where appropriate.

### Doctor Commands

- `doctor`
- doctor action review/application paths surfaced through Layer 4 approval UI.

Doctor is a command/workflow family. It owns diagnostics, cleanup review, source checks, tmp review, and memory mining workflows. It may call knowledge services, but it is not itself a knowledge tool.

### Run And Review Commands

- `cancel_run`
- `stop_after_current_step`
- `retry_step`
- `rerun_step`
- `revise_goal`
- `mark_result_trusted`
- `mark_result_invalidated`
- `challenge_conclusion`

### Memory Commands

- `memory_review`
- memory proposal approval/rejection/application commands when added.

Memory commands expose user review and control. Knowledge tools expose model recall/proposal. Both share knowledge services.

## Service Design

Services are internal implementation units. They are not directly exposed to the model or TUI.

Target service areas:

- Chat service: chat records, compaction, runtime request building.
- Workspace service: workspace listing, activation, ingest, inventory.
- Doctor service: diagnostics, tmp review, source checks, proposed actions.
- Knowledge service: preferences, notes, gaps, function candidates, memory proposals.
- Analysis service: plan validation, step contracts, approval state, artifact/provenance access.
- Context service: durable workspace context, file schema snapshots, token-budgeted context assembly.
- Status service: authoritative workspace/run/chat status snapshots.

A service method can be called by a tool, command, or orchestrator workflow. It must not appear directly in the prompt catalog, slash command catalog, command palette, or TUI controls unless wrapped by a Tool or Command descriptor.

## Source Organization

Target organization:

```text
src/harness/
  tools/
    __init__.py
    registry.py
    file.py
    control.py
    analysis.py
    knowledge.py
    shell.py
  commands/
    __init__.py
    registry.py
    chat.py
    workspace.py
    doctor.py
    compact.py
    run.py
    memory.py
    provenance.py
  services/
    __init__.py
    chat.py
    workspace.py
    doctor.py
    knowledge.py
    analysis.py
    context.py
    status.py
```

This structure is the required end state for the implementation. The tools registry, prompt-catalog migration, dispatch enforcement, command-family extraction, and Layer 4 command reachability checks should land together as one coherent change set, not as separate phases.

## Migration Strategy

1. Update docs first:
   - Rewrite `docs/app/tools-vs-commands.md`.
   - Add `docs/app/services.md`.
2. Introduce `src/harness/tools/registry.py`.
3. Add `file_read(operation=list|inspect|content)`.
4. Change model tool dispatch to use only the tool registry.
5. Build prompt catalogs from the tool registry.
6. Add analysis and knowledge tool families while preserving old command compatibility.
7. Extract command families into `src/harness/commands/`.
8. Update `CODEMAP.md` whenever source import, call, inheritance, or definition structure changes.

The migration is complete only when model tool dispatch no longer falls back to command dispatch, prompt catalogs are tool-registry backed at every constructor/call site, command families live under `src/harness/commands/`, and command reachability from Layer 4 is tested.

## Compatibility

Existing command names such as `list_files`, `inspect_file`, `read_file`, `plan_analysis`, `request_execution`, and `recall_knowledge` may remain as commands during migration.

Prompts and model-facing docs should move to:

- `file_read`
- `analysis_plan`
- `analysis_request_execution`
- `knowledge_recall`
- `knowledge_propose_update`

Command compatibility should not imply model-callability.

## Testing Requirements

Tests must prove:

- The tool registry lists only model-callable tools.
- The command registry lists user/app-callable commands.
- Model tool calls cannot dispatch command-only names such as `doctor`, `compact`, or `delete_workspace`.
- Every command remains reachable through Layer 4 command catalog behavior.
- Every model-emitted control intent that uses `<tool_call>` is present in the tool registry or explicitly documented as outside harness dispatch.
- Tool arguments are deterministically validated by descriptor metadata, including required fields, allowed values, type coercion, and regex checks where appropriate.
- `file_read` covers list, inspect, and content operations.
- Prompt packages advertise tool names from the tool registry, not command descriptors.
- Old command compatibility remains where intentionally preserved.

## Documentation Requirements

`docs/app/tools-vs-commands.md` must become the public taxonomy for exposed surfaces.

`docs/app/services.md` must document internal services and the service exposure rule.

`docs/app/compaction-behaviour.md` and `docs/app/doctor-behaviour.md` remain command workflow docs. They should not describe compact or doctor as model tools.

## Out Of Scope

This design does not implement broad shell access.

This design does not remove existing command compatibility names in the first pass.

This design does not change the Layer 2 worker approval boundary.

This design does not require a full services refactor before tool/command dispatch is enforced.
