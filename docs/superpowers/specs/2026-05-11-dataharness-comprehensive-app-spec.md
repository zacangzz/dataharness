# DataHarness Canonical System Specification

Status: canonical source of truth for product, architecture, layer contracts, user experience, data flow, persistence, testing, packaging, and acceptance requirements.

Purpose: define the complete DataHarness application as a local-first, evidence-grounded data analysis, data science, and reporting workbench. This document is the single reference for the full application specification.

## 1. Product Purpose

DataHarness is a local-first data analysis, data science, and reporting application. It is not a generic chatbot shell. It is a stateful, evidence-grounded workbench that lets a user ask questions about local files, approve controlled Python work, inspect artifacts, retain reusable knowledge, and understand whether prior conclusions remain valid after data changes.

The system is single-user and local-first. It uses one local LLM runtime, one controlled Python execution worker, one harness (a separable Harness Core plus harness services that own intent routing and built-in prompt profiles), and one application layer that is the Textual TUI plus the `AppSession` facade.

The product goal is to make local data work reliable enough that important claims can be traced back to inspected source files, executed code, artifacts, fingerprints, validity state, and prompt-profile context.

## 2. Scope

### 2.1 In Scope

- Local single-user operation.
- Local LLM runtime integration through llama.cpp-backed runtime adapters.
- Async streaming runtime contract.
- Controlled Python execution for analytical steps.
- Workspace-first storage and operation.
- Chat lifecycle and chat history persistence scoped by workspace.
- Durable workspace state, memory, dataset knowledge, validity, doctor reports, and provenance.
- Explicit user approval before code execution.
- Harness-owned command surface for platform operations.
- Harness-owned prompt profiles for interaction, analysis, clarification, and knowledge capture.
- Textual TUI with live streaming events, status snapshots, workspace controls, chat controls, file ingest, file mentions, Markdown conversation rendering, and sidebar navigation.
- Artifact-backed analytical answers with provenance.
- Local telemetry and human-readable logs.

### 2.2 Out Of Scope

- Multi-user collaboration.
- Cloud execution.
- Parallel prompt-profile runtimes.
- Concurrent analysis runs in one app process.
- Autonomous harness self-modification.
- Unconstrained plugin execution.
- Hidden background maintenance that acts without user-visible status or reviewable records.
- Broad shell integration, third-party agent app store behavior, ACP provider integration, multi-agent concurrent execution, and full settings systems.
- HTTP-client domain behavior, request collections, environment management, and copying unrelated application source.

## 3. Core Principles

### 3.1 Evidence Over Prose

The model may plan, suggest, summarize, and explain. Analytical truth comes from inspected inputs, controlled execution, persisted artifacts, fingerprints, and provenance records. Important claims must either cite evidence or be marked unsupported.

### 3.2 Harness As Platform Core

The harness is the operational center of the product. It owns orchestration, run state, workspace truth, chat persistence, context policy, approvals, validity, doctor, review, memory update proposals, provenance, retry, repair, command semantics, intent routing, and prompt-profile selection. It is built as a separable Harness Core (kernel) plus harness services and shared contracts.

The TUI makes the harness usable and inspectable, but it does not replace harness authority.

### 3.3 Strict Layer Ownership

DataHarness has four major layers:

```text
Layer 4 Application/TUI -> Layer 3 Harness -> Layer 2 Worker
                                           \-> Layer 1 Runtime
```

Layer responsibilities:

- Layer 1 Runtime owns model interaction, streaming, token pressure, tool-call parsing, and runtime status.
- Layer 2 Worker owns subprocess execution, sandbox mechanics, task status, stdout/stderr capture, and execution envelopes.
- Layer 3 Harness owns orchestration, state, chat history, context assembly, command semantics, approval, validity, doctor, memory, provenance, persistence, intent routing, and prompt-profile selection. It is organized as a separable Harness Core (kernel) plus harness services and shared contracts.
- Layer 4 Application owns user interaction, Textual rendering, prompt UX, event mapping, and app-layer telemetry. Layer 4 is the TUI plus the `AppSession` facade; it does not own routing or prompt selection.

Dependency rules:

- Layer 4 calls Layer 3 through `AppSession`.
- Layer 4 must not import `runtime.*` directly.
- Layer 4 must not bypass `AppSession` to manipulate `Orchestrator`.
- Layer 3 may call Layer 1 and Layer 2.
- Layer 3 must not import Layer 4.
- Layer 2 must not import harness or application modules.
- Layer 1 must not import worker, harness, or application modules.

### 3.4 Async-Only Public Contracts

DataHarness public runtime, worker, harness, and application turn contracts are async-only. The production architecture does not expose sync turn, runtime, worker, or final-result object rendering APIs.

Required public contract shape:

- Runtime inference is exposed through async streaming events.
- Worker execution is exposed through async submit, wait, cancel, list, and get-task methods.
- Harness turns are exposed through async event iterators.
- Application turns are exposed through `AppSession` async event iterators.
- The TUI renders live events and status snapshots rather than waiting for a final result object.
- Prompt history and transcript compaction belong to Layer 3 chat services.
- Run concurrency is fixed at one active run per app process.
- Chat compaction is exposed as `/compact` and affects chat storage only.
- Workspace memory management is exposed through doctor and review workflows.
- Workspace activation state is reflected through status snapshots and workspace/chat events.

### 3.5 Hard-Serial Concurrency

DataHarness is hard-serial by design:

- One active workspace per app process.
- One active chat per app process.
- One active run per app process.
- One outstanding runtime stream per app process.
- One outstanding worker execution task per active run.

Overlap attempts raise `RunAlreadyActive(run_id)`. Workspace switching during an active run is blocked unless the user explicitly confirms a forced switch, which cancels the active run before switching.

## 4. Runtime Topology

Implementation dependencies flow downward, but the running application centers on the harness:

```text
TUI input
  -> AppSession
    -> Orchestrator
      -> intent routing and prompt-profile selection (Layer 3)
      -> RuntimeRequestBuilder
      -> LlamaCppRuntime.stream(...)
      -> PythonStepExecutor.submit/wait/cancel(...)
      -> persistence, doctor, provenance, events
  -> AppEvent mapping
  -> TUI widgets
```

The runtime remains stateless across requests. Active chat history and durable workspace context are Layer 3 state because Layer 3 builds runtime requests and owns compaction policy.

## 5. Layer 1: Runtime

### 5.1 Purpose

Layer 1 makes model interaction predictable. It adapts the local llama.cpp backend into an async, streaming, typed contract for the harness.

### 5.2 Required Capabilities

- Local model backend integration.
- Async token streaming.
- Reasoning delta separation.
- Tool-call extraction and repair.
- Runtime request validation.
- Token pressure reporting.
- Context-window reporting.
- Runtime status reporting.
- Structured finish and error events.

### 5.3 Public Interface

```python
class Runtime(Protocol):
    async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]: ...
    async def context_window(self) -> int: ...
    async def token_pressure(self, request: RuntimeRequest) -> TokenPressure: ...
    async def validate_request(self, request: RuntimeRequest) -> None: ...
    async def status(self) -> RuntimeStatus: ...
```

### 5.4 Runtime Models

`RuntimeMessage` fields:

- `role`: `system`, `user`, `assistant`, or `tool`
- `content`
- optional `name`
- optional `tool_call_id`

`RuntimeRequest` fields:

- `messages`
- `max_completion_tokens`
- `temperature`
- `top_p`
- `stop`
- `tools`
- `request_id`
- optional `correlation_id`

`RuntimeEvent` types:

- `text_delta`
- `reasoning_delta`
- `tool_call`
- `finish`
- `error`

`TokenPressure` reports:

- `context_window`
- `prompt_tokens`
- `reserved_completion_tokens`
- `total_tokens`
- `pressure_ratio`
- `over_threshold`

Runtime status values:

- `not_loaded`
- `loading`
- `ready`
- `streaming`
- `error`

### 5.5 Llama.cpp Bridge

The installed llama.cpp Python high-level streaming API is sync iterator based. `LlamaCppRuntime` provides async semantics through a private producer bridge:

- The producer runs the sync iterator on a background thread.
- It pushes `RuntimeEvent` values into a bounded `asyncio.Queue`.
- Default queue size is 64.
- Queue size is configurable via runtime config.
- The producer blocks when the queue is full, giving natural backpressure.
- The queue and thread are private implementation details and are never exposed outside Layer 1.

Cancellation is observed between deltas. The producer checks a cancel flag after each token, drains queued work on cancellation, emits a terminal cancelled/error event, and exits cleanly. Expected cancellation latency is one token.

### 5.6 Runtime Boundaries

Layer 1 may own:

- inference behavior
- streaming behavior
- token accounting
- request validation
- model-facing message packaging
- tool-call parsing
- runtime status

Layer 1 may not own:

- workspace state
- chat history
- memory
- context policy
- application prompt identity
- execution policy
- provenance
- UI state
- routing policy
- tool registry ownership or tool dispatch

## 6. Layer 2: Worker

### 6.1 Purpose

Layer 2 makes controlled computation possible. It executes approved Python steps inside workspace and policy boundaries, then returns canonical evidence envelopes.

### 6.2 Required Capabilities

- Async subprocess lifecycle.
- Task registry.
- Workspace-relative permission validation.
- Step temp directory creation.
- stdout/stderr capture.
- Timeout and resource enforcement.
- Cancellation.
- Artifact discovery.
- Execution envelope creation.
- Failure diagnostics.

### 6.3 Public Interface

```python
class StepExecutor(Protocol):
    async def submit(self, request: StepExecutionRequest) -> StepTaskHandle: ...
    async def wait(self, task_id: str) -> StepExecutionEnvelope: ...
    async def cancel(self, task_id: str, reason: str) -> StepExecutionEnvelope: ...
    async def list_tasks(self) -> list[StepTaskStatus]: ...
    async def get_task(self, task_id: str) -> StepTaskStatus | None: ...
```

### 6.4 Execution Request And Envelope

The worker receives:

- workspace id and workspace directory
- run id, plan id, step id
- executable Python code
- timeout
- permitted workspace-relative paths
- environment overrides

The worker returns:

- task id
- task status
- stdout
- stderr
- artifact paths
- diagnostics

The execution envelope must exist on success, failure, timeout, and cancellation. Cancelled work must never be reported as successful.

Step temp files live under:

```text
<workspace>/artifacts/tmp/<run_id>/<step_id>/
```

### 6.5 Sandbox Rules

Worker policy:

- read access limited to approved source data and registered artifacts in the active workspace
- write access limited to worker scratch paths during execution
- no writes to `data/`, `memory/`, or `state/`
- no outbound network
- no arbitrary shell escape unless harness policy explicitly allows it
- resource ceilings for time, memory, and artifact size

### 6.6 Failure Kinds

The worker distinguishes:

- Python exception
- timeout
- resource exhaustion
- permission violation
- missing expected output
- malformed result JSON
- partial artifact generation
- cancellation

Layer 2 reports these facts. Layer 3 decides how they affect the run.

## 7. Layer 3: Harness

### 7.1 Purpose

Layer 3 turns runtime plus execution into a real analysis system. It is the source of operational truth and the first fully meaningful product layer.

Layer 3 also owns intent routing and prompt-profile selection. The interaction, analyst, clarification, and knowledge behaviors are prompt profiles resolved inside the harness, not an app sublayer: a deterministic intent router (`ModeRouter`) picks the profile and a prompt-profile registry (`PromptProfileRegistry`) assembles the prompt package. Layer 4 is the TUI plus the `AppSession` facade.

Layer 3 is structured as:

- a separable **Harness Core (kernel)** under `src/harness/core/` — the state machine, command registry, approval gate, plan validity, analysis flow, persistence/db, app store, paths, fingerprints, kernel workspace store, and prompt registry. The kernel is the layer-pure heart that does not depend on harness services.
- **harness services** under `src/harness/services/` — mode routing, prompt profiles, chat, context, knowledge, knowledge intents, analysis, doctor, repair, provenance, workspace, and workspace files.
- model-callable **tools** under `src/harness/tools/` — the only operations the model may emit through parsed `<tool_call>` blocks.
- user/app-callable **commands** under `src/harness/commands/` — the operations Layer 4 may expose through slash commands, command palette results, dedicated controls, or contextual actions.
- **shared contracts** at `src/harness/` root — `control`, `events`, `exceptions`, `status`, and the `orchestrator` that composes the kernel and services.

The harness exposes three surface categories:

- **Tools** are model-callable operations emitted through Layer 1 parsing and validated/dispatched by Layer 3.
- **Commands** are user/app-callable operations invoked from Layer 4 and validated/dispatched by Layer 3.
- **Services** are internal domain logic used by tools, commands, and orchestrator workflows.

No exposed harness operation may be surface-less. If the model can call it, it must be a registered tool and appear in the prompt tool catalog. If the user or app can call it, it must be a registered command and have at least one Layer 4 reachability path. If neither is true, it is an internal service/helper and must not be documented as a tool or command.

Prompt profiles and the intent router are services. They are never directly model- or UI-callable.

### 7.2 Required Capabilities

- Orchestrator and control loop.
- Intent routing and prompt-profile selection.
- Active workspace, chat, run, and prompt-profile state.
- Chat lifecycle and persistence.
- Workspace lifecycle and ingest coordination.
- Context rebuild and compaction policy.
- Runtime request assembly.
- Plan and step management.
- Explicit approval gates.
- Worker dispatch and cancellation.
- Model-callable tool registry and dispatch enforcement.
- Direct command registry and command-family dispatch.
- Status snapshots and status watcher.
- Typed harness events.
- Durable state and memory indexing.
- Dataset knowledge and validity.
- Doctor and review workflows.
- Deterministic repair, retry, replan, and finish logic.
- Artifact inspection and provenance.
- Telemetry and logging.

### 7.3 Orchestrator Public Surface

The orchestrator exposes async methods for:

- running a user turn
- resuming approved steps
- resuming clarifications
- listing commands
- returning help
- handling direct commands
- cancelling runs
- listing execution tasks
- compacting chat history
- listing, creating, viewing, resuming, and deleting chats
- listing, creating, renaming, deleting, activating, and ingesting into workspaces
- producing status snapshots
- watching status changes

Layer 4 mirrors this through `AppSession` so the TUI never imports the orchestrator directly.

### 7.4 Run State Machine

The harness owns run transitions. Typical states:

- `idle`
- `routing`
- `clarifying`
- `planning`
- `awaiting_approval`
- `executing`
- `inspecting`
- `updating_memory`
- `reviewing_doctor`
- `responding`
- `finished`
- `failed`
- `cancelled`

Higher layers may request work or decisions, but the harness validates and records transitions.

### 7.5 Turn Control Loop

A user turn follows this logic:

1. Layer 4 opens a turn and sends user text through `AppSession`.
2. The harness routes the text to a prompt profile (`ModeRouter`) and loads the prompt package (`PromptProfileRegistry`), preserving the prior non-interaction profile on ambiguous input and persisting the chosen profile on the run state.
3. The harness appends the user message to the active chat.
4. The harness reloads fresh durable workspace context.
5. The harness validates or records the active prompt profile.
6. The harness assembles a runtime request from profile prompt, durable context, chat summary, recent turns, and current user text.
7. The harness asks Layer 1 for token pressure and compacts chat if required.
8. The harness streams runtime events and maps them to `HarnessEvent` values.
9. If execution is required, the harness creates or validates a plan and step contract, pauses for explicit approval, then dispatches Layer 2.
10. The harness inspects worker evidence, records envelopes, artifacts, provenance, and validity changes.
11. The harness decides whether to continue, retry, replan, ask for clarification, run doctor, update memory proposals, or finish.
12. The harness persists state and emits final events.
13. `AppSession` maps harness events to app events.
14. The TUI renders conversation, status, plan, artifacts, failures, approvals, clarifications, and sidebar updates.

### 7.6 Approval Rules

Code execution requires explicit user approval of the executable plan or specific executable step. Approval must not be inferred from timeout.

Non-execution maintenance decisions may use a 10-second timeout path only when:

- the action is not code execution
- the action is not destructive without review
- the user has not cancelled
- the user has not chosen to stop after the current step
- current run, provenance, and pending-review references do not block the action

### 7.7 Chat Management

Chats are Layer 3 records. Every chat belongs to exactly one workspace and is stored under:

```text
<app_root>/workspaces/<workspace_id>/chats/<chat_id>/
```

Chat directory layout:

```text
metadata.json
messages.jsonl
compactions.jsonl
```

Chat creation is lazy. App startup does not write an empty chat directory. The chat directory, metadata, and first message line are written on the first user message.

Chat messages include:

- message id
- role: `user`, `assistant`, or `compacted_summary`
- text
- timestamp
- turn id
- active prompt profile
- token estimate

The harness appends the current user message before prompt assembly and appends the assistant final message after successful completion. Failed or cancelled turns may record a terminal marker but must not invent an assistant answer.

Resuming a chat loads persisted messages into Layer 3 prompt history. Deleting a workspace cascades deletion to that workspace's chats.

### 7.8 Runtime Request Assembly

Layer 3 assembles runtime messages in this order:

1. active prompt profile's system prompt
2. fresh durable workspace context
3. active chat summary, if present
4. recent active chat turns for the active workspace
5. current user message

Budget policy:

- Recent turns retained after compaction: 8 turns.
- Completion reservation: 25% of context window.
- Durable context cap: 30% of the remaining prompt budget.
- Chat summary cap: 15% of the remaining prompt budget.
- Recent turns cap: 25% of the remaining prompt budget.
- System prompt and current user message use the remainder.
- Compaction trigger: token pressure over 80% of context window.

Layer 3 calls `runtime.token_pressure(request)` for authoritative pressure and decides whether to compact.

### 7.9 Chat Compaction

`/compact` and `compact_chat_history(...)` compact chat history only. Compaction writes to workspace-scoped chat storage, not workspace `memory/`.

Compaction emits:

```text
ChatHistoryCompacted(status="queued")
ChatHistoryCompacted(status="running")
ChatHistoryCompacted(status="completed" | "failed")
```

Because the runtime is hard-serial, runtime-backed compaction queues behind an in-flight stream. If a turn is cancelled while compaction is queued, compaction proceeds after the turn ends unless policy blocks it.

Workspace memory management belongs to `/doctor`, not `/compact`.

### 7.10 Workspace Model

One workspace is active at a time. The workspace folder is the portable durable unit of work.

Recommended app root shape:

```text
<app_root>/
+-- <app>/
|   +-- app.json
+-- harness/
|   +-- telemetry/
|   +-- logs/
+-- workspaces/
    +-- <workspace_id>/
        +-- chats/
        +-- data/
        +-- artifacts/
        |   +-- tmp/
        +-- memory/
        |   +-- preferences.json
        |   +-- notes/
        |   |   +-- gaps/
        |   +-- functions/
        +-- state/
            +-- workspace.db
```

Workspace ownership:

- `data/` holds copied source input and is read-only after ingest.
- `artifacts/tmp/` holds worker scratch evidence.
- durable `artifacts/` paths outside `tmp/` hold promoted outputs worth keeping.
- `memory/` holds harness-managed durable workspace memory that the user may inspect or edit.
- `state/` holds harness-only operational state.

The global app store tracks known workspace ids, recent workspaces, last opened workspace, and basic UI preferences. It is not analytical truth.

### 7.11 Workspace Activation

`activate_workspace(workspace_id, force=False)`:

- switches immediately when no run is active
- raises `WorkspaceSwitchBlocked(active_run_id)` when a run is active and `force=False`
- cancels the active run, waits for `TurnCancelled`, then switches when `force=True`

Layer 4 must show a confirmation before retrying with `force=True`.

### 7.12 File Ingest

Host files enter a workspace through `AppSession.ingest_files(...)` and Layer 3 ingest logic. Layer 4 may provide file picker UI and staged selection, but copying and source registration belong to Layer 3.

`WorkspaceIngestResult` reports:

- accepted destination paths inside workspace
- rejected source paths with reasons
- number of source records added

### 7.13 Control Objects

Harness-owned control objects are JSON-compatible, versioned, persisted, and validated. Important objects include:

- `RunStateRecord`
- `ModeSwitchEvent`
- `ApprovalRecord`
- `Plan`
- `PlanStep`
- `StepContract`
- `ExecutionEnvelope`
- `StepResult`
- `PromptPackage`
- `DoctorReport`
- `TmpAction`
- `ReviewProposal`
- `MemoryUpdateProposal`
- provenance records

All persisted path references are workspace-relative unless explicitly representing external pre-ingest sources.

Validation failures must preserve the invalid payload and explain the reason so deterministic repair, retry, or review can act on a concrete record.

### 7.14 Deterministic Repair, Retry, And Replan

The harness applies safe deterministic repair before spending another model call on mechanical problems:

- type normalization
- wrapper repair
- metadata insertion
- path normalization

If repair is insufficient, the harness chooses a targeted recovery:

- output repair for malformed structured output
- schema retry for validation mismatch
- code repair and rerun for computation failure
- replan when the existing plan is no longer appropriate

Retry loops are explicit, budgeted, visible, and persisted.

### 7.15 Validity And Fingerprints

Reusable conclusions are tied to source files, fingerprints, schema fingerprints, optional profile fingerprints, lineage, and current validity.

Validity states:

- `ok`
- `changed`
- `stale`
- `needs_review`
- `revalidated`
- `broken_lineage`

Fingerprinting is lazy after first ingest:

- first ingest computes full fingerprint
- subsequent checks compare stored file size and modified timestamp
- unchanged metadata reuses stored fingerprint
- changed metadata triggers full rehash

No prior conclusion is silently overwritten.

### 7.16 Doctor And Review

Doctor is a Layer 3 platform function, callable directly from the TUI, harness control logic, or prompt-profile workflows.

Doctor responsibilities:

- rescan tracked sources
- detect source drift, missing files, schema changes, broken lineage, stale saved functions, orphaned records, and tmp artifacts
- update validity findings
- review workspace memory indexes
- propose tmp cleanup or promotion
- emit structured events and persist a report

Doctor emits:

- `CommandStarted(command="doctor")`
- `DoctorStarted`
- phase-level `CommandProgress`
- `DoctorFinding`
- `DoctorActionProposed`
- `DoctorReportReady`
- `DoctorNarrationReady`, when LLM narration is available or a deterministic fallback is produced
- `DoctorApprovalRequested`, when user review is required for tmp actions
- `DoctorActionsApplied`, after approved doctor actions are applied
- `CommandCompleted(command="doctor")`

Doctor narration is owned by Layer 3. The doctor service may use the runtime to produce human-readable narration over a structured report, but Layer 4 only maps and renders the resulting events. `AppSession` must not import `runtime.*` or synthesize doctor narration locally.

Tmp review precedes cleanup. Tmp actions may be:

- delete
- promote
- keep temporarily
- review

Promotion mapping:

- reusable code -> `memory/functions/`
- durable semantic note -> `memory/notes/`
- unresolved semantic issue -> `memory/notes/gaps/`
- user-facing chart, table, report, or output -> durable `artifacts/`

Tmp items referenced by active runs, pending reviews, failure envelopes, provenance, or artifact registry records cannot be deleted.

Review is the lighter path for durable learning updates. Memory updates must identify source evidence, conflicts, target, proposed content, and status before being applied.

### 7.17 Knowledge And Function Management

The harness provides:

- user preference retrieval and update
- dataset metadata retrieval and update
- knowledge notes
- saved reusable analysis functions
- freshness checks before saved-function reuse
- bounded synthesis and reconciliation when deterministic storage rules are insufficient

Only `KnowledgeManager` may write under `memory/`. App code, tools, commands, prompt profiles, and services must use harness-owned knowledge APIs rather than writing memory files directly.

### 7.18 Provenance

Every important claim must be traceable to:

- source files
- fingerprints
- executed code identity
- artifacts
- plan and step lineage
- validity state
- active prompt profile
- prompt template identity and version where relevant

The harness owns provenance rules. Layer 4 renders provenance; it does not decide it.

### 7.19 Command Surface

Layer 3 exposes user-callable harness functions through a typed command registry. Layer 4 discovers command names, descriptions, arguments, availability, disabled reasons, affected resources, expected events, and examples from Layer 3.

Command coverage is grouped by family:

- app commands: `help`; local Layer 4 `exit` / `quit` handling where appropriate
- chat commands: `create_chat`, `list_chats`, `view_chat`, `resume_chat`, `delete_chat`, `compact`
- workspace commands: `list_workspaces`, `create_workspace`, `rename_workspace`, `delete_workspace`, `switch_workspace`, `workspace_status`, `workspace_inventory`
- doctor commands: `doctor` plus doctor action review/application paths surfaced through Layer 4 approval UI
- run and review commands: `cancel_run`, `stop_after_current_step`, `retry_step`, `rerun_step`, `revise_goal`, `mark_result_trusted`, `mark_result_invalidated`, `challenge_conclusion`
- memory commands: `memory_review` plus memory proposal approval/rejection/application commands when present
- provenance and validity commands: `provenance_inspect`, `validity_inspect`, and artifact inspection commands when available

If a command is listed as available, invoking it must perform real harness behavior and emit typed events. If behavior is incomplete, the command must be unavailable with a clear `disabled_reason`.

Commands are never model-callable by implication. Compatibility command names such as `list_files`, `inspect_file`, `read_file`, `plan_analysis`, `request_execution`, and `recall_knowledge` may remain user/app-facing during migration, but command compatibility does not make those names valid tool calls.

Slash command grammar is positional only:

```text
/<command_name> [<positional_arg_1> [<positional_arg_2> ...]]
```

Tokens containing spaces must be double-quoted. Named flags are out of scope.

### 7.20 Tool Surface

Layer 3 exposes model-callable operations through a typed tool registry. Layer 1 only streams model output and parses `<tool_call>` blocks. Layer 3 validates tool names and arguments, dispatches only registered tools, and never falls back to command dispatch for model-emitted names.

Tool descriptors must support deterministic validation before handler execution:

- required-argument checks
- type coercion
- `allowed_values` checks for enum-like arguments
- regex checks for bounded string and path formats
- neutral tool-call context containing only workspace id, chat id, run id, and pending approval/clarification flags

Tool handlers must not depend on command-specific context types. Handlers and services still own semantic checks such as workspace existence, file availability, artifact existence, and approval state.

The core model-facing tool families are:

- file tools
- control tools
- analysis tools
- knowledge tools

`file_read` is the canonical read-only file tool. It replaces model-facing use of `list_files`, `inspect_file`, and `read_file`:

```json
{"name":"file_read","arguments":{"operation":"list","path":"data/"}}
{"name":"file_read","arguments":{"operation":"inspect","path":"data/sales.csv"}}
{"name":"file_read","arguments":{"operation":"content","path":"data/notes.md","max_bytes":8192}}
```

`file_write` is separate from `file_read` because writes have a different risk level and approval model. `shell_command` is separate from both file tools and must remain tightly allowlisted and read-only unless a future spec broadens it. `file_write` and `shell_command` are target tool definitions and must not be registered until their approval and allowlist behavior are implemented and tested.

Control tools represent model-emitted flow-control choices:

- `answer_directly`
- `handoff_to_analyst`
- `handoff_to_knowledge`
- `request_clarification`
- `respond_to_user`

Control tools are registered model-callable tools because they use the `<tool_call>` path. They are not commands because the user does not invoke them through Layer 4 command surfaces.

Analysis tools include:

- `analysis_plan`
- `analysis_request_execution`
- `analysis_inspect_artifact`
- `analysis_inspect_provenance`
- `analysis_inspect_validity`

`analysis_plan` is the model-facing successor to `plan_analysis`. It creates a validated analysis plan and emits `ApprovalRequired`. `analysis_request_execution` is the model-facing successor to `request_execution`. Layer 2 execution remains approval-gated: the model can propose analysis work, but it cannot directly execute arbitrary code.

Knowledge tools include:

- `knowledge_recall`
- `knowledge_propose_update`

Knowledge tools expose model-facing recall or proposal operations. They may propose notes, preferences, gaps, or reusable function candidates. Durable memory writes still go through `KnowledgeManager` and any required review path.

Prompt packages must advertise tool names from the tool registry, not command descriptors. A prompt catalog entry is invalid if the named tool is not registered.

### 7.21 Service Surface

Services are internal implementation units. They are not directly exposed to the model or TUI and must not appear directly in prompt catalogs, slash command catalogs, command palette results, or TUI controls unless wrapped by a tool or command descriptor.

Target service areas:

- chat service: chat records, compaction, runtime request building
- workspace service: workspace listing, activation, ingest, inventory
- doctor service: diagnostics, tmp review, source checks, proposed actions, narration, and approval emission
- knowledge service: preferences, notes, gaps, function candidates, memory proposals
- analysis service: plan validation, step contracts, approval state, artifact/provenance access
- context service: durable workspace context, file schema snapshots, token-budgeted context assembly
- status service: authoritative workspace/run/chat status snapshots
- mode-router service: prompt-profile selection from user text and turn state
- prompt-profile service: persona package assembly and allowed-tool catalog construction

A service method can be called by a tool, command, or orchestrator workflow. Service code owns reusable domain behavior; exposed surfaces own validation and reachability.

## 8. Harness Events And Status

### 8.1 Event Rules

Harness events live in Layer 3, inherit a common base, contain no Textual formatting, and are mapped to App events by Layer 4.

Base fields:

- event id
- event name
- timestamp
- workspace id
- chat id
- run id

Required event families:

- turn lifecycle: `TurnStarted`, `FinalMessage`, `TurnFailed`, `TurnCancelled`
- status: `StatusChanged`, `WorkspaceHealthChanged`, `RuntimeStatusChanged`
- chat: `ChatCreated`, `ChatSelected`, `ChatDeleted`, `ChatHistoryLoaded`, `ChatHistoryCompacted`
- commands: `CommandStarted`, `CommandProgress`, `CommandCompleted`
- mode/context/prompt: `ModeActivated`, `ContextReloaded`, `PromptBuilt`
- runtime stream: `RuntimeDelta`
- plan/approval: `PlanReady`, `ApprovalRequired`, `ApprovalResolved`
- worker: `StepTaskSubmitted`, `StepTaskStatusChanged`, `StepCompleted`, `ArtifactsReady`
- doctor: `DoctorStarted`, `DoctorFinding`, `DoctorActionProposed`, `DoctorReportReady`, `DoctorNarrationReady`, `DoctorApprovalRequested`, `DoctorActionsApplied`

### 8.2 Status Snapshot

`HarnessStatusSnapshot` includes:

- workspace id
- chat id and title
- workspace health
- active prompt profile
- run id and run state
- runtime status
- execution task counts
- approval state
- clarification state
- chat turn count
- chat token estimate
- last compacted timestamp
- compaction count
- doctor warning count
- last event reference

Layer 3 computes snapshots from authoritative state. Layer 4 renders them.

### 8.3 Status Watcher

`watch_status` yields:

- immediately on subscribe
- when a snapshot field changes and at least 50 ms have passed since the last yield
- every 2 seconds as heartbeat, even if unchanged

Subscribers must tolerate duplicate snapshots.

## 9. Layer 4: Application And TUI

### 9.1 Purpose

Layer 4 turns the harness into the product the user experiences. It is the application layer built on top of Layer 3. Layer 4 is the Textual TUI plus the `AppSession` facade that connects it to the harness. Prompt-profile identity, intent routing, and prompt selection are Layer 3 concerns (see §7.1).

Layer 4 owns:

- product presentation
- user interaction
- app-layer turn correlation
- event mapping for UI consumption
- keyboard, command, help, prompt, and navigation behavior

Layer 4 does not own operational truth. Routing, prompt-profile selection, plans, approvals, execution, workspace state, chat state, memory writes, doctor decisions, validity, provenance, and command semantics are all Layer 3 responsibilities.

The application layer does not replace the harness. Its purpose is to make the harness operable, inspectable, and purpose-built for data analysis work.

### 9.2 Layer 4 Internal Topology

Layer 4 is organized as:

```text
Layer 4a TUI --> AppSession --> Layer 3 Orchestrator
```

`AppSession` is the boundary object. It is Layer 4 code, but it is not the TUI and it is not a routing layer. It is a thin application facade that forwards TUI input to the harness, applies app telemetry and concurrency checks, and maps harness events to app events. It does not route intents or select prompts; those are Layer 3 concerns.

This distinction keeps responsibilities clear:

- Layer 4a TUI collects user input and renders app events.
- `AppSession` forwards those calls to Layer 3 and maps events back.
- Layer 3 routes intent, selects the prompt profile, validates, persists, executes, and emits authoritative events.

### 9.3 AppSession Responsibilities

`AppSession` is the Layer 4 facade over `Orchestrator`.

It owns:

- app-layer telemetry and turn correlation
- single-active-run fast-fail gate
- mapping `HarnessEvent` to `AppEvent`
- pure passthrough of direct commands and doctor-approval decisions to the orchestrator

It mirrors the orchestrator's async method surface so TUI modules do not import harness internals directly. It does not import `app.agents` (no such package exists) or `runtime.*`.

`AppSession` may hold active workspace and chat references for UI convenience, but it must not become a second source of chat content, workspace truth, command semantics, run state, routing, or prompt selection. Its state is process-local coordination state; durable state and routing belong to Layer 3.

### 9.4 Prompt Profiles (Layer 3)

DataHarness gets its data-analysis behavior from Layer 3 prompt profiles, not an app sublayer. A deterministic intent router and a prompt-profile registry inside the harness answer:

- what kind of turn is this?
- which prompt profile should handle it?
- what role prompt and response style should shape the runtime request?
- when should a profile ask for clarification or hand off?

Prompt profiles:

- `interaction`
- `data analyst` (`analyst`)
- `clarification`
- `knowledge`

Profiles are prompt packages, not concurrent runtimes. The interaction profile handles front-door conversation and can hand off analytical or knowledge intents through registered control tools. The data-analyst profile turns analytical intent into plans, execution requests, artifact-backed answers, and gap records. The clarification profile handles missing intent or missing execution details. The knowledge profile turns user teaching and reusable logic into harness-owned memory proposals.

`ModeRouter` selects the profile per turn from the user text; on ambiguous input the harness preserves the prior non-interaction profile (continuity for follow-ups and clarification resume). The chosen profile is written back onto the live run state. `PromptProfileRegistry` assembles the prompt package (system + persona + tool catalog + response format) on demand.

### 9.5 Prompt Ownership

Layer 3 owns all app-defining prompts. Persona templates and prompt-assembly rules live under `src/harness/prompts/` (system, interaction, analyst, knowledge, clarification, response_format, doctor_narrator) alongside the pre-existing narrow operational prompts (compaction, doctor tmp review, knowledge reconciliation). Operational-prompt outputs are advisory until harness validation records and applies the action.

Layers 1, 2, and TUI widgets do not contain app-defining prompts.

### 9.6 Layer 4a: TUI Operating Model

Layer 4a is the operability and inspection sublayer. It makes the harness usable by a human operator and keeps the system state visible without forcing the user to infer everything from a transcript.

Layer 4a answers questions such as:

- what is the active workspace?
- what chat is active?
- is the runtime ready, loading, streaming, or failed?
- what is the current run state?
- what phase is the harness in?
- what plan, approval, artifact, failure, or doctor finding needs attention?
- what commands and file mentions are available now?
- what did the system just do, and what evidence supports the answer?

Layer 4a owns presentation and input mechanics. It does not own prompt profiles, routing policy, durable chat history, workspace state, command truth, execution decisions, or analytical validity.

The Textual UI is chat-first but not chat-only. It must expose distinct surfaces for:

- active workspace
- active chat
- runtime status
- run state
- current plan
- step execution status
- artifacts
- failures
- provenance
- context and memory summary
- doctor findings
- command progress

The UI renders Layer 3 events and status snapshots. It does not compute operational truth.

### 9.7 TUI Main Surfaces

Required structure:

- top status bar
- scrollable conversation/message log
- chat manager modal or panel
- Textual command provider and command palette
- plan panel
- process/run trace
- artifact panel
- context/status bar
- bottom prompt editor
- workspace manager
- file uploader/ingest screen
- workspace file browser
- inline approval banner
- clarification modal
- focused help and jump navigation

`DataHarnessApp` owns global bindings, command providers, theme/style setup, status watcher workers, and app lifecycle telemetry. If root composition becomes too broad, a main workflow screen may own selected workspace/chat, focus rules, expanded panes, and workflow-local navigation state. Domain widgets stay small and message-oriented.

### 9.8 Prompt Editor

The prompt editor is a Textual `TextArea` or focused subclass.

Required behavior:

- multiline editing
- normal message submission through `DataHarnessApp.submit_user_text`
- slash command hints and argument candidates
- `@` file mention detection at cursor
- completions without shifting main conversation layout
- mouse cursor placement, paste, selection, and common editor keys
- prompt focus retention after errors and completed turns
- concise status for active prompt profile, run state, runtime status, and hint state
- context-sensitive argument candidates when data exists: workspace ids, chat ids, run ids, step ids, and artifact paths
- selected commands with required arguments prefill the prompt with slash command text and argument placeholders instead of executing prematurely

Keyboard behavior:

- `enter` submits when no completion overlay is active and submit mode is active
- `shift+enter` inserts newline
- `ctrl+j` inserts newline
- `escape` closes active overlay first and otherwise preserves prompt text
- `up` and `down` navigate overlays
- `tab` switches file picker modes when the picker is visible

### 9.9 Inline Approval Banner

Code execution approval is shown through an inline approval banner docked near the prompt rather than a full-screen modal. The banner keeps the conversation, plan, and code context visible while the user decides.

Required behavior:

- appears when Layer 3 emits `ApprovalRequired`
- remains visible until the user approves, rejects, revises, cancels, or the pending approval is otherwise resolved
- displays the goal, plan id, step id, declared inputs, expected outputs, and a readable code preview when code is present
- supports keyboard decisions: approve, reject, revise, and escape-to-defocus without dismissing the pending approval
- posts a Layer 4 approval-decision message that routes through `AppSession.resume_approved_step(...)` or the appropriate rejection/revision path
- hides only after the decision has been handed to `AppSession`
- uses markup-safe rendering for plan, code, validation, and error text
- keeps prompt and surrounding TUI state recoverable after approval failures
- never dispatches code execution directly from the widget

Layer 4 owns the banner widget and key handling. Layer 3 remains the source of approval state, plan/step truth, execution gating, and resume behavior.

Clarification remains modal because it requires focused text entry and does not need simultaneous code review in the same way execution approval does.

### 9.10 File Mention Picker

Typing `@` opens a workspace file picker overlay.

Required behavior:

- fuzzy filtering as the user types
- tree mode toggled by `tab`
- `enter` inserts selected path
- `escape` dismisses
- workspace-relative paths
- hidden/generated/runtime directories excluded
- stable mention format: `@path/to/file.csv`
- quoted mention format for spaces: `@"path with spaces.csv"`
- file contents are not inserted into the prompt

Performance rules:

- scanning must not block normal typing
- paths are cached per workspace
- cache invalidates on workspace switch
- result lists are bounded
- several thousand files should remain usable

### 9.11 File Ingest Screen

The file ingest screen copies host files into active workspace `data/` through `AppSession.ingest_files`.

Required behavior:

- opens via `f3`, `/upload`, command palette, and workspace manager button
- initial root is user's home directory
- `ctrl+r` changes root
- `space` toggles multi-select
- `enter` confirms selection
- staged list shown before commit
- `escape` from staged list returns to picker
- excludes hidden files and symlink loops by default
- default per-file size cap is 200 MB, with explicit prompt for larger files
- success refreshes sidebar files and workspace manager file panel
- rejection shows per-file reasons

Layer 4 owns selection UI. Layer 3 owns copy, registration, and status truth.

### 9.12 Conversation Rendering

Conversation rendering uses structured blocks:

- user blocks for user messages
- assistant Markdown blocks for assistant output
- compact failure blocks
- compact cancellation blocks
- compaction summary markers

Markdown support:

- headings
- lists
- block quotes
- tables
- links rendered as text
- fenced code blocks
- syntax highlighting when supported

Streaming assistant output updates one active assistant block progressively. `AppFinalMessage` finalizes it and prevents duplicate final text. Plain text remains safe from Rich markup injection. Resumed chats rebuild the same structure from Layer 3 `ChatRecord`.

### 9.13 Sidebar And Workspace Navigation

The sidebar is a navigation and status surface with stable sections:

- workspace summary
- active chat
- files
- recent run trace
- commands
- doctor findings
- failures

It updates from status snapshots, workspace actions, chat actions, command events, doctor events, failures, and turn lifecycle events.

Run trace and status surfaces must expose async phases, not only final outcomes. Phase markers should cover routing, context reload, prompt build, model stream, tool or command execution, artifact write, validation, doctor review, and final response when those events exist. If a needed phase event is missing, the TUI work should document the missing event and add it through Layer 3 rather than importing deeper internals.

Workspace manager requirements:

- navigable workspace list
- selected workspace file panel using reusable file picker/list model
- selected workspace chat count and source count
- create, switch, delete, and close actions
- active-run switch error with confirmation flow

Navigation keys:

- `f1` focused help
- `ctrl+?` focused help when terminal support allows it
- `f2` workspace manager
- `f3` file ingest
- `ctrl+p` command palette
- `ctrl+o` jump navigation
- `j`/`k` move in navigable lists
- `l` activates or expands list items where that matches the widget model
- `enter` activates selected items
- `escape` closes overlays/modals first

Jump mode uses stable DataHarness widget ids and ignores hidden targets. Initial targets:

- `1`: prompt bar or input
- `2`: conversation
- `3`: status or sidebar
- `w`: workspace manager
- `c`: chat manager when available
- `p`: plan or process surface when available

Focused help uses lightweight widget help metadata. The help screen renders the focused widget name, purpose, and current bindings, is dismissible with `escape`, and restores prior focus. Permanent instructional text in the main UI should stay minimal once focused help exists.

### 9.14 Command Palette And Slash Commands

The command palette is backed by a Textual command provider populated from `AppSession.list_commands(...)`. Unavailable commands appear disabled with Layer 3's `disabled_reason`.

The provider builds searchable results from `HarnessCommandDescriptor`, including command name, slash alias, description, availability, affected resource, expected events, and examples. Availability is context-aware: workspace, chat, active run, pending approval, pending clarification, and selected artifact can change whether a command is enabled.

Selecting a command executes immediately only when no arguments are required. Commands with required arguments focus the prompt editor with a prefilled slash command and argument placeholders. Candidate loading goes through `AppSession` or Layer 4 facade methods, never direct Layer 3 imports.

Slash commands are parsed by Layer 4 using the positional grammar. Layer 3 validates argument count, types, semantics, availability, execution, and results.

`/help` and `/help <command>` render `HelpResult` from Layer 3. Unknown slash commands show concise UI errors and may suggest matching descriptors.

Every available Layer 3 command must be reachable through at least one UI path: palette, slash command, dedicated control, or contextual action.

### 9.14.1 TCSS And Interaction States

TCSS carries interaction details rather than scattering inline styles through widgets. Dedicated styles are required for:

- focused pane states
- compact mode
- disabled and unavailable states
- success, warning, error, running, and idle status severity
- command palette
- autocomplete and argument dropdowns
- modal screens
- inline approval banner
- jump labels
- help screen
- prompt/file picker overlays
- Markdown conversation blocks

The app must start with minimal fallback styling if TCSS loading fails, and packaging must include the TCSS file.

### 9.15 Required TUI Controls

The TUI must support:

- switch workspace
- inspect workspace status
- command palette
- slash commands including `/doctor`, `/compact`, and `/help`
- chat create, list, view, resume, delete, and compact
- approve a plan through the inline approval banner
- revise a goal
- clarify missing intent
- stop after current step
- cancel a run
- rerun a step
- inspect artifact
- run doctor
- review memory updates
- challenge a conclusion
- mark result trusted
- mark result invalidated
- inspect provenance
- inspect validity
- upload files into workspace
- mention files in prompt
- search command provider results
- jump to stable visible widgets
- open focused-widget help

Controls without complete Layer 3 behavior must be visibly unavailable. Layer 4 must not fake success locally.

## 10. End-To-End Flows

### 10.1 First Dataset Added

The user uploads or ingests files. Layer 4 collects file choices and calls `AppSession.ingest_files`. Layer 3 copies/registers files into `data/`, computes initial fingerprints, adds source records, emits status changes, and returns `WorkspaceIngestResult`. The sidebar and workspace manager refresh from Layer 3 status.

### 10.2 First Analysis

The user asks an analytical question. The harness routes the turn to the analyst profile. It builds context, creates a plan if needed, pauses for execution approval, runs approved code in the worker, inspects results, records provenance and validity, and returns an evidence-backed answer.

### 10.3 Follow-Up Analysis

The harness includes active chat history, chat summary, durable workspace context, preferences, dataset knowledge, saved functions, and validity state. The analyst reuses valid knowledge and blocks stale function reuse when freshness checks fail.

### 10.4 Clarification

When intent or semantics are insufficient, the harness requests clarification and records clarification state. The TUI renders a clarification modal or prompt. The user's answer resumes the harness flow from that decision point, preserving the active prompt profile when the answer is ambiguous.

### 10.5 Drift And Doctor

Doctor checks source metadata and fingerprints, detects drift or broken lineage, updates validity findings, reviews tmp artifacts, and proposes actions. The TUI renders findings and recommendations. No doctor outcome silently overwrites prior state.

### 10.6 Chat Resume

The user selects a saved chat. Layer 4 calls `AppSession.resume_chat`. Layer 3 validates workspace ownership, loads persisted messages, emits chat history events, and uses that chat for subsequent prompt assembly.

### 10.7 Workspace Switch During Active Run

The user requests a workspace switch. Layer 4 calls `activate_workspace(force=False)`. Layer 3 raises `WorkspaceSwitchBlocked`. Layer 4 asks for confirmation. If confirmed, Layer 4 retries with `force=True`; Layer 3 cancels the active run, emits cancellation status, then switches workspace.

## 11. Error Handling

Layer 1 emits or raises typed runtime errors. Layer 2 returns execution task statuses and envelopes. Layer 3 maps failures into harness events and persisted state. Layer 4 renders failures and offers controls.

Non-streaming async methods raise typed exceptions:

- `ChatNotFound`
- `ChatWorkspaceMismatch`
- `ChatActiveDeletionBlocked`
- `WorkspaceNotFound`
- `RunAlreadyActive`
- `WorkspaceSwitchBlocked`

Streaming methods surface terminal events:

- `TurnFailed`
- `TurnCancelled`
- `ChatHistoryCompacted(status="failed")`

TUI-specific fallback behavior:

- prompt editor construction failure falls back to minimal input
- slash descriptor load failure keeps normal prompt submission available
- file scan failure shows empty picker with error summary
- missing file at selection time dismisses picker and shows prompt-local warning
- Markdown render failure renders plain text
- finalization mismatch treats final message as authoritative
- sidebar section update failure preserves previous state and reports low-severity warning

## 12. Telemetry And Logs

Every layer emits:

- structured append-only JSONL events for machine audit
- human-readable rotated logs

App-global layout:

```text
<app_root>/harness/
+-- telemetry/
|   +-- runtime.events.jsonl
|   +-- worker.events.jsonl
|   +-- harness.events.jsonl
|   +-- app.events.jsonl
+-- logs/
    +-- runtime.log
    +-- worker.log
    +-- harness.log
    +-- app.log
```

Workspace-scoped events are mirrored into `<workspace>/state/telemetry/`.

Every event includes:

- schema version
- timestamp
- layer
- component
- event name
- severity
- correlation ids
- payload
- duration for finished/failed events
- redaction metadata field

Telemetry references persistence rather than duplicating analytical records. Telemetry write failures do not crash the harness; they surface as degraded observability warnings.

## 13. Packaging

Packaging must include:

- Textual TCSS files
- prompt files
- Layer 4 TUI modules
- runtime modules dynamically imported by CLI/runtime factory
- app, harness, runtime, worker, and observability submodules needed by PyInstaller

Packaging scripts and spec files must include every Textual asset, prompt resource, and dynamically imported module required at runtime.

## 14. Testing Requirements

Layer 1 tests verify:

- async streaming deltas and finish metadata
- reasoning delta separation
- tool-call parsing
- malformed stream errors
- cancellation at inter-token boundary
- bounded queue backpressure
- absence of Layer 3/4 concepts in runtime models

Layer 2 tests verify:

- submit returns quickly with task handle
- list/get task states
- wait returns envelope
- cancel terminates work
- timeout status
- permission enforcement
- failed/cancelled tasks produce diagnostics

Layer 3 tests verify:

- tool registry lists only model-callable tools
- command registry lists only user/app-callable commands
- model tool calls cannot dispatch command-only names such as `doctor`, `compact`, or `delete_workspace`
- every model-emitted control intent using `<tool_call>` is registered as a tool or explicitly documented outside harness dispatch
- tool descriptor validation covers required fields, type coercion, allowed values, and regex constraints
- `file_read` covers list, inspect, and content operations
- prompt packages advertise tool names from the tool registry, not command descriptors
- old command compatibility remains only where intentionally preserved
- event order for non-execution turns
- runtime deltas stream as harness events
- active chat history included in subsequent prompts
- lazy chat creation
- resume chat reloads persisted history
- chat isolation by workspace and chat id
- compaction queuing and status events
- token-pressure compaction at 80%
- runtime request budget policy
- workspace deletion cascades chats
- workspace switch blocking and force behavior
- command descriptors and disabled reasons
- command-family reachability through Layer 4 command catalog behavior
- `/doctor` verbose event flow
- doctor narration and approval events originate from Layer 3 and preserve Layer 4 payload shapes
- `/help` behavior
- approval resume emits worker task events
- cancellation calls worker cancel
- status snapshots and watch heartbeat
- typed exceptions
- single-active-run enforcement
- no Layer 3 imports from Layer 4

Layer 4 tests verify:

- status bar renders Layer 3 snapshots
- event stream updates process log, conversation, plan, artifacts, sidebar, and prompt state
- conversation rehydrates from `view_chat`
- chat manager calls Layer 3
- `/compact` calls Layer 3 and renders summary marker
- command palette uses descriptors
- command provider search filters descriptors and preserves metadata
- unavailable commands show `disabled_reason`
- selected commands with required args prefill the prompt instead of executing
- slash parser supports quoted positional args
- prompt hints suggest command arguments from Layer 4 facade data where available
- `/help` and `/doctor` render Layer 3 content
- inline approval banner and clarification modal resume through `AppSession`
- cancellation renders `TurnCancelled`
- workspace switch confirmation retries with `force=True`
- file ingest calls `AppSession.ingest_files`
- prompt editor multiline behavior
- `@` file picker insertion and quoting
- Markdown rendering avoids markup injection
- jump overlay focuses visible targets and ignores hidden targets
- focused help renders widget metadata and current bindings
- TCSS resources are included in packaging and fallback styling lets the app start if loading fails
- no sync app/session methods are used
- no direct TUI imports of `runtime.*`
- no `src/app` imports of `app.agents` or `runtime.*`, and no Layer 4 routing or prompt-selection logic

Minimum verification commands for TUI-focused work:

```bash
uv run pytest tests/app/tui -q
uv run pytest -q
```

## 15. Acceptance Criteria

DataHarness is not correct unless all of these are true:

- no analytical claim is accepted without inspected evidence
- no artifact-backed conclusion lacks provenance
- no saved knowledge is reused after material source change without validity handling
- no doctor outcome silently overwrites prior state
- intent routing and prompt-profile selection are Layer 3; no app code routes or selects prompts, and no prompt profile bypasses harness ownership boundaries
- no `src/app/agents/` package exists; prompt profiles are Layer 3 services
- model-callable operations are registered tools, user/app-callable operations are registered commands, and internal domain logic remains services
- model tool dispatch never falls back to command dispatch
- prompt tool catalogs are generated from the tool registry
- no UI hides critical failures or uncertainty
- no retry loop runs invisibly without bounded control
- no durable memory update occurs without a reviewable path
- no code execution occurs without explicit executable plan or step approval
- no tmp cleanup or promotion occurs before recorded tmp review
- no persisted control object lacks a matching telemetry event with resolving correlation IDs
- all touched public runtime, worker, harness, and app contracts are async-only
- one active run, chat, workspace, runtime stream, and worker task invariant is enforced
- runtime cancellation is visible within one token boundary
- worker cancellation returns a cancelled envelope
- chat history is workspace-scoped and persisted under `<app_root>/workspaces/<workspace_id>/chats`
- compaction writes only to chat storage, not workspace memory
- status bar uses Layer 3 snapshots only
- every available command is callable through Layer 4
- `/doctor` is a real Layer 3 flow
- doctor narration and doctor approval events originate in Layer 3 and are only mapped/rendered by Layer 4
- TUI controls either call real Layer 3 behavior or show unavailable state
- packaging includes required assets and dynamic modules
- CODEMAP is updated whenever code relationship structure changes

## 16. Implementation Guidance

Implement in layer order when changing behavior:

1. Layer 1 runtime contract and bridge.
2. Layer 2 async worker task management.
3. Layer 3 async orchestration, chat, commands, doctor, status, and persistence.
4. Layer 4 AppSession event mapping.
5. Layer 4 TUI surfaces.
6. Prompt-profile refinements.
7. Packaging and end-to-end verification.

For TUI work, prefer staged vertical slices:

1. reusable file picker model and overlay
2. file ingest screen
3. prompt editor
4. `@` file mention integration
5. structured Markdown conversation blocks
6. sidebar section widgets
7. workspace manager file panel reuse
8. TCSS and packaging updates

The implementation must preserve layer boundaries even when a shortcut appears easier. If a UI feature needs semantic data, add a Layer 3 service or `AppSession` facade rather than reading harness internals directly.
