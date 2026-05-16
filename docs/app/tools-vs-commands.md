# Tools vs Commands

## Definitions

- **Tool**: model-callable surface emitted as a `<tool_call>` through Layer 1 parsing, then validated and dispatched by Layer 3.
- **Command**: user/app-callable harness surface invoked from Layer 4 TUI, slash commands, command palette, or app controls, then validated and dispatched by Layer 3.
- **Service**: internal implementation unit, usually Layer 3, that owns domain logic used by tools and/or commands. Services are not directly exposed to the model or TUI.

## No-Orphan Invariant

No exposed harness operation may be surface-less.

If the model can call it, it is a Tool and must be listed in the tool registry and prompt catalog.
If the user or app can call it, it is a Command and must be listed in the command registry and reachable from Layer 4.
If neither is true, it is an internal Service/helper and must not be documented as a tool or command.

Model-emitted control intents that use `<tool_call>` are Tools in the `control` family even when their handler only updates the agentic control loop.

Tool argument descriptors must support deterministic validation before handler execution: required fields, type coercion, allowed values, and regex checks for bounded string/path formats.

## Tool Families

### Core Tools
- `file_read`: read-only workspace file discovery and inspection with `operation=list|inspect|content`.
- `file_write`: target definition for workspace-bound writes; do not register it in this pass.
- `shell_command`: target definition for tightly allowlisted read-only shell execution; do not register it in this pass.

### Control Tools
- `answer_directly`: model control signal consumed by the agentic loop.
- `handoff_to_analyst`: model control signal consumed by the agentic loop.
- `handoff_to_knowledge`: model control signal consumed by the agentic loop.
- `request_clarification`: model control signal consumed by the agentic loop.
- `respond_to_user`: model control signal consumed by the agentic loop.

### Analysis Tools
- `analysis_plan`: the model emits a CODE-FREE plan
  (`{goal, steps:[{purpose, declared_inputs, expected_outputs}]}`). The
  harness then runs a two-step flow: gen-1 is the model's code-free plan;
  gen-2 is an internal, non-persisted generation that synthesizes each step's
  Python as a fenced ```` ```python ```` block (no JSON escaping). The harness
  validates each step's generated code (allowed imports, every expected output
  referenced) with one bounded gen-2 retry per step, then emits a SINGLE
  `ApprovalRequired` over the assembled plan+code. Structurally invalid gen-1
  plans get one code-free shape-repair retry; exhausted repairs yield a
  plain-language `FinalMessage` (never a silent dead turn).
  The command path (`plan_analysis`) is unchanged: code is supplied directly
  and gen-2 is NOT invoked.
- `analysis_request_execution`: re-emit approval for an existing pending plan step.
- `analysis_inspect_artifact`: inspect analysis artifacts.
- `analysis_inspect_provenance`: inspect lineage for analysis outputs.
- `analysis_inspect_validity`: inspect trust/validity state for results.

### Knowledge Tools
- `knowledge_recall`: retrieve saved workspace knowledge.
- `knowledge_propose_update`: propose notes, preferences, gaps, or function candidates without bypassing review.

## Command Families

### App Commands
- `help`
- `exit` / `quit` handled locally by Layer 4 when appropriate.

### Chat Commands
- `create_chat`
- `list_chats`
- `view_chat`
- `resume_chat`
- `delete_chat`
- `compact`

### Workspace Commands
- `list_workspaces`
- `create_workspace`
- `rename_workspace`
- `delete_workspace`
- `switch_workspace`
- `workspace_status`
- `workspace_inventory`

### Doctor Commands
- `doctor`
- doctor action review/application paths surfaced by Layer 4 approval UI.

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

## Migration Notes

The command split is source-level as well as registry-level: `doctor` and
`compact` have dedicated command modules, while shared implementation lives
under `src/harness/services/`.

The following old command names remain as compatibility commands during migration but are not model-callable tools:

- `list_files` (superseded by `file_read` with `operation=list`)
- `inspect_file` (superseded by `file_read` with `operation=inspect`)
- `read_file` (superseded by `file_read` with `operation=content`)
- `plan_analysis` (superseded by `analysis_plan`)
- `request_execution` (superseded by `analysis_request_execution`)
- `recall_knowledge` (superseded by `knowledge_recall`)
