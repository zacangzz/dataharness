# Async Layered Architecture Design

Date: 2026-05-01 (revised 2026-05-03)
Status: approved design for implementation planning, revised after gap review
Scope: replace the current sync turn path with async-only contracts across the four DataHarness layers

## 1. Purpose

DataHarness must move to a fully async end-to-end architecture. This is a breaking migration: sync public APIs, final-result-only turn handling, and sync TUI rendering paths must be removed rather than kept as compatibility paths.

Each layer remains standalone and owns only its own functionality:

- Layer 1 runtime owns model interaction.
- Layer 2 worker owns Python execution mechanics.
- Layer 3 harness owns orchestration, operational truth, status aggregation, and chat session lifecycle.
- Layer 4 application/TUI owns the front-facing UI for Layer 3.

The implementation may be coordinated in one migration branch, but the plans and responsibilities must remain layer-isolated.

## 2. Current Context

The current TUI under `src/app/tui/` renders from `AppTurnResult` after `DataAnalysisAppSession.handle_user_turn(...)` completes. It has basic panes, approval and clarification screens, and a final `process_events` list, but it is not a live async event consumer.

The reference code in `docs/superpowers/specs/sample_code/` shows the intended product feel: a top status bar, scrollable conversation, process log, plan/artifact/context panels, workspace manager, file browser, and file drop support.

The current turn path does not feed prior chat messages back into the runtime. `Orchestrator.handle_turn(...)` rebuilds durable workspace context and passes `chat_history=[]`, while `ContextManager.rebuild(...)` returns `chat_history_loaded=False`. The async migration must change this: the harness must remember the active chat history and include it in subsequent runtime requests.

Chats are workspace-scoped Layer 3 records. They belong to a workspace, but they are stored under `<app_root>/chats` rather than inside the workspace directory. A new app process starts a new active chat lazily on the first user message. Resuming a saved chat reloads that chat's prior messages into Layer 3 prompt history. Durable workspace memory remains separate from chat history.

The earlier V1 spec in `docs/superpowers/specs/2026-04-23-custom-data-analysis-llm-v1-main-spec.md` required many TUI controls. The current code has partial plumbing: panes exist for conversation, plan, step status, artifacts, memory, doctor, failure, provenance, workspace, and status; approval and clarification screens exist; `HarnessCommandRouter` lists the direct commands. Most controls are not yet complete product UI flows, and most direct commands currently route through generic validation or placeholder responses rather than full harness behavior. The async TUI migration must finish those control surfaces instead of assuming they are already integrated.

The installed `llama-cpp-python` high-level API is sync. In version `0.3.20`, `Llama.create_chat_completion(..., stream=True)` returns a regular iterator, not an async iterator. Official docs describe the same shape. Therefore Layer 1 must expose async semantics to DataHarness while privately bridging the blocking llama.cpp iterator.

References:

- https://llama-cpp-python.readthedocs.io/en/stable/api-reference/
- https://github.com/abetlen/llama-cpp-python

## 3. Terminology

Two distinct objects use the word "session" in this codebase. They are not the same thing and the spec keeps them strictly separate:

- **`ChatSession`** — Layer 3 owned. Workspace-scoped conversation record. Holds `chat_id`, message history, compaction state, last run, persistence under `<app_root>/chats/<workspace_id>/<chat_id>/`. This is what the user thinks of as "a chat".
- **`AppSession`** — Layer 4 owned. Process-level facade in front of the Layer 3 `Orchestrator`. Adds Layer 4 concerns (mode routing, prompt-package selection, app-layer telemetry, harness→app event mapping). Holds active `workspace_id` and `chat_id` references for TUI convenience. Does not hold conversation content.

The current `DataAnalysisAppSession` class fills the `AppSession` role. The implementation may keep that class name for migration continuity, but documentation and event payloads must use `AppSession` (Layer 4) and `ChatSession` (Layer 3) so the two never collide.

## 4. Architecture Rule

Layer communication is downward for execution and upward through typed results/events:

```text
Layer 4 TUI -> Layer 4 AppSession -> Layer 3 Orchestrator -> Layer 2 worker
                                                       \---> Layer 1 runtime
```

No layer may absorb another layer's responsibility. For example, Layer 3 may submit and cancel worker tasks, but Layer 2 owns subprocess mechanics. Layer 4 may show workspace controls, but Layer 3 owns the status facts rendered by the status bar. Layer 4 must call Layer 3 through `AppSession`; the TUI must not import `harness.orchestrator` directly.

The runtime remains stateless across requests. Active chat memory is Layer 3 state because Layer 3 builds runtime requests, owns context policy, decides compaction, and persists chat records. Layer 4 renders chat messages and exposes controls, but it must not be the source of prompt history for Layer 1.

## 5. Concurrency Model

DataHarness is hard-serial in V1. The async migration changes the API shape, not the concurrency model.

Invariants:

- One active run per app process.
- One active workspace per app process.
- One active chat per app process.
- One outstanding Layer 2 execution task per active run.
- One outstanding Layer 1 runtime stream per app process.

`SessionConfig.max_parallel_runs` is removed. Overlap attempts raise `RunAlreadyActive(run_id)` (see §10). Layer 2's `submit/wait` API stays async-shaped because `asyncio.create_subprocess_exec` is async, but Layer 3 only ever holds one outstanding task. Layer 1 may use a private background producer thread to bridge the sync llama.cpp iterator (see §6); that internal thread does not constitute concurrent runtime requests.

## 6. Plan 1: Layer 1 Runtime Async Contract

### Goal

Layer 1 exposes async-only runtime behavior to the rest of DataHarness.

### Public Interface

```python
class Runtime(Protocol):
    async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]: ...
    async def context_window(self) -> int: ...
    async def token_pressure(self, request: RuntimeRequest) -> TokenPressure: ...
    async def validate_request(self, request: RuntimeRequest) -> None: ...
    async def status(self) -> RuntimeStatus: ...
```

### Schemas

```python
class RuntimeMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None

class RuntimeRequest(BaseModel):
    messages: list[RuntimeMessage]
    max_completion_tokens: int
    temperature: float = 0.2
    top_p: float = 0.95
    stop: list[str] = []
    tools: list[dict] = []
    request_id: str
    correlation_id: str | None = None  # Layer 3 turn/run identifier

class RuntimeEvent(BaseModel):
    type: Literal["text_delta", "reasoning_delta", "tool_call", "finish", "error"]
    request_id: str
    seq: int
    text: str | None = None                 # text_delta, reasoning_delta
    tool_call: dict | None = None           # tool_call
    finish_reason: Literal["stop", "length", "tool_call", "cancelled", "error"] | None = None
    usage: dict | None = None               # finish only
    error_code: str | None = None           # error only
    error_message: str | None = None        # error only

class TokenPressure(BaseModel):
    request_id: str
    context_window: int
    prompt_tokens: int
    reserved_completion_tokens: int
    total_tokens: int
    pressure_ratio: float                   # total_tokens / context_window
    over_threshold: bool                    # pressure_ratio > 0.80

RuntimeStatus = Literal["not_loaded", "loading", "ready", "streaming", "error"]
```

`RuntimeStatus.streaming` is per-request; because the app is hard-serial, an active stream is also runtime-global.

### Implementation Boundary

`LlamaCppRuntime` may use a private async bridge because llama.cpp streaming is sync iterator based. The bridge runs the sync iterator on a background thread and pushes `RuntimeEvent` items into a bounded `asyncio.Queue` consumed by the public `stream(...)` async iterator. Bridge configuration:

- Default queue size: **64** items.
- Configurable via `LlamaCppRuntimeConfig.bridge_queue_size`.
- Producer thread blocks on full queue (natural backpressure when consumer is slow).
- Queue is private; it must never be exposed to Layer 2, Layer 3, or Layer 4.

### Cancellation Granularity

The sync llama.cpp iterator cannot be interrupted mid-token. Layer 1 cancellation policy:

- Producer thread checks an internal cancel flag **between deltas** (after each token yielded).
- Maximum cancel latency = one token (~10–100 ms depending on model).
- llama.cpp iterator is allowed to finish the current token; the producer does not close it mid-call (avoids corrupt internal state).
- On cancel, the producer drains its queue, emits a final `RuntimeEvent(type="error", finish_reason="cancelled")`, then exits cleanly.

### Removals

- Remove `Runtime.complete(...)` from the protocol.
- Remove sync `Runtime.stream(...)`.
- Remove final-response-only runtime tests or convert them to async streaming tests.

### Tests

Layer 1 tests must verify:

- async streaming yields text deltas and finish metadata
- reasoning deltas remain separated
- tool-call parsing still works
- malformed stream content emits or raises typed runtime errors
- cancellation between deltas stops the private producer cleanly within one token
- bounded queue applies backpressure under slow consumer
- no Layer 3 or Layer 4 concepts appear in runtime models

## 7. Plan 2: Layer 2 Worker Async Task Management

### Goal

Layer 2 owns async Python execution and task lifecycle primitives. Layer 3 can start, observe, and cancel execution tasks through a narrow async interface. Layer 3 only ever holds one outstanding task in V1, but the API supports multiple registry entries for diagnostics.

### Public Interface

```python
class StepExecutor(Protocol):
    async def submit(self, request: StepExecutionRequest) -> StepTaskHandle: ...
    async def wait(self, task_id: str) -> StepExecutionEnvelope: ...
    async def cancel(self, task_id: str, reason: str) -> StepExecutionEnvelope: ...
    async def list_tasks(self) -> list[StepTaskStatus]: ...
    async def get_task(self, task_id: str) -> StepTaskStatus | None: ...
```

### Schemas

```python
class StepExecutionRequest(BaseModel):
    workspace_id: str
    workspace_dir: Path
    run_id: str
    plan_id: str
    step_id: str
    code: str
    timeout_seconds: int
    permitted_paths: list[Path]              # workspace-relative
    env_overrides: dict[str, str] = {}

class StepTaskHandle(BaseModel):
    task_id: str
    status: Literal["queued", "running"]
    submitted_at: datetime

class StepTaskStatus(BaseModel):
    task_id: str
    workspace_id: str
    run_id: str
    plan_id: str
    step_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "timeout"]
    started_at: datetime | None
    finished_at: datetime | None
    return_code: int | None

class StepExecutionEnvelope(BaseModel):
    task_id: str
    status: StepTaskStatus
    stdout: str
    stderr: str
    artifacts: list[Path]
    diagnostics: dict[str, object]
```

### Responsibilities

Layer 2 owns:

- subprocess lifecycle
- task IDs and task registry records
- stdout/stderr capture
- timeout and resource enforcement
- workspace-relative permission validation
- step temp directory creation
- execution envelope creation
- cancellation mechanics and cleanup

Layer 2 does not own:

- execution approval
- plan creation
- orchestration decisions
- artifact meaning or analytical validity
- TUI behavior
- agent modes

### Implementation Notes

`PythonStepExecutor` must use `asyncio.create_subprocess_exec` for subprocess lifecycle. Small local file writes can remain synchronous `pathlib` calls if they are bounded and not part of long-running execution. Subprocess execution must not block the event loop.

Cancellation must terminate the subprocess, update task status, and return a `StepExecutionEnvelope` with `status.status == "cancelled"`. Cancelled work must not produce a successful envelope.

### Removals

- Remove sync `PythonStepExecutor.execute(...)` as a public path.
- Convert worker tests to async.
- Remove tests that assume blocking execution semantics.

### Tests

Layer 2 tests must verify:

- submit returns a task handle without blocking for completion
- list/get show queued/running/completed states
- wait returns the execution envelope
- cancel terminates running work
- timeout produces timeout status
- permission violations remain enforced
- failed/cancelled tasks still produce diagnostic records where appropriate

## 8. Plan 3: Layer 3 Harness Async Orchestration And Status

### Goal

Layer 3 becomes the async orchestration and operational-status layer. It consumes Layer 1 runtime status and Layer 2 task status, then exposes authoritative harness events and status snapshots to Layer 4.

### Public Interface

```python
class Orchestrator:
    async def run_turn(..., chat_id: str) -> AsyncIterator[HarnessEvent]: ...
    async def resume_approved_step(...) -> AsyncIterator[HarnessEvent]: ...
    async def resume_with_clarification(...) -> AsyncIterator[HarnessEvent]: ...
    async def list_commands(context: CommandContext | None = None) -> list[HarnessCommandDescriptor]: ...
    async def help(command: str | None = None) -> HelpResult: ...
    async def handle_direct_command(...) -> AsyncIterator[HarnessEvent]: ...
    async def cancel_run(run_id: str, reason: str) -> TurnCancelled: ...
    async def list_execution_tasks(...) -> list[StepTaskStatus]: ...
    async def compact_chat_history(
        chat_id: str,
        reason: str = "user_requested",
    ) -> AsyncIterator[HarnessEvent]: ...
    async def list_chats(workspace_id: str) -> list[ChatSummary]: ...
    async def create_chat(workspace_id: str, title: str | None = None) -> ChatSummary: ...
    async def view_chat(chat_id: str) -> ChatRecord: ...
    async def resume_chat(chat_id: str) -> AsyncIterator[HarnessEvent]: ...
    async def delete_chat(chat_id: str) -> ChatDeleteResult: ...
    async def list_workspaces(...) -> list[WorkspaceSummary]: ...
    async def create_workspace(workspace_id: str) -> WorkspaceSummary: ...
    async def rename_workspace(old_id: str, new_id: str) -> WorkspaceSummary: ...
    async def delete_workspace(workspace_id: str) -> WorkspaceSummary: ...
    async def activate_workspace(workspace_id: str, force: bool = False) -> HarnessStatusSnapshot: ...
    async def ingest_files(workspace_id: str, paths: list[Path]) -> WorkspaceIngestResult: ...
    async def status_snapshot(workspace_id: str | None = None) -> HarnessStatusSnapshot: ...
    async def watch_status(...) -> AsyncIterator[HarnessStatusSnapshot]: ...
```

### `AppSession` (Layer 4)

`AppSession` is a Layer 4 facade over `Orchestrator`. It is async-only and event-based. Method surface mirrors `Orchestrator` because Layer 4 must not import `harness.orchestrator` directly. The four real responsibilities:

1. **Mode routing** — runs `AgentModeRouter.route(user_text)` to pick agent mode, loads `PromptPackageRegistry` package, injects `prompt_text`/`prompt_template_id`/`prompt_template_version` into the orchestrator call.
2. **App-layer telemetry** — wraps each turn in `bind_turn(turn_id)` and emits `APP` layer events distinct from harness events.
3. **Concurrency gate** — enforces the single-active-run invariant from Layer 4 side; raises `RunAlreadyActive` immediately on overlap (Layer 3 also enforces; the gate exists so the TUI fails fast without dispatching).
4. **Event mapping** — translates `HarnessEvent` → `AppEvent` with UI-shaped payloads (e.g. timestamp formatting, derived progress hints). `AppEvent` types mirror harness event names with `App` suffix (`AppTurnStarted`, `AppFinalMessage`, etc.).

```python
class AppSession:
    async def run_user_turn(...) -> AsyncIterator[AppEvent]: ...
    async def resume_approved_step(...) -> AsyncIterator[AppEvent]: ...
    async def resume_with_clarification(...) -> AsyncIterator[AppEvent]: ...
    async def list_commands(context: CommandContext | None = None) -> list[HarnessCommandDescriptor]: ...
    async def help(command: str | None = None) -> HelpResult: ...
    async def handle_direct_command(...) -> AsyncIterator[AppEvent]: ...
    async def cancel_run(...) -> TurnCancelled: ...
    async def compact_chat_history(...) -> AsyncIterator[AppEvent]: ...
    async def list_chats(workspace_id: str) -> list[ChatSummary]: ...
    async def create_chat(workspace_id: str, title: str | None = None) -> ChatSummary: ...
    async def view_chat(chat_id: str) -> ChatRecord: ...
    async def resume_chat(chat_id: str) -> AsyncIterator[AppEvent]: ...
    async def delete_chat(chat_id: str) -> ChatDeleteResult: ...
    async def list_workspaces(...) -> list[WorkspaceSummary]: ...
    async def create_workspace(workspace_id: str) -> WorkspaceSummary: ...
    async def rename_workspace(old_id: str, new_id: str) -> WorkspaceSummary: ...
    async def delete_workspace(workspace_id: str) -> WorkspaceSummary: ...
    async def activate_workspace(workspace_id: str, force: bool = False) -> HarnessStatusSnapshot: ...
    async def ingest_files(workspace_id: str, paths: list[Path]) -> WorkspaceIngestResult: ...
    async def status_snapshot(...) -> HarnessStatusSnapshot: ...
    async def watch_status(...) -> AsyncIterator[HarnessStatusSnapshot]: ...
```

### Harness Events

All harness events live in `src/harness/events.py` and inherit a common base. Events are not Textual widgets and must not contain UI formatting.

```python
class HarnessEvent(BaseModel):
    event_id: str            # uuid
    event_name: str          # discriminator
    ts: datetime
    workspace_id: str | None
    chat_id: str | None
    run_id: str | None

class HarnessEventRef(BaseModel):
    event_id: str
    event_name: str
    ts: datetime
    run_id: str | None
```

Required event types and payload shapes:

| Event | Additional fields |
|-------|-------------------|
| `TurnStarted` | `turn_id: str`, `user_message_id: str`, `active_mode: str` |
| `StatusChanged` | `snapshot: HarnessStatusSnapshot` |
| `WorkspaceHealthChanged` | `health: Literal["ready","busy","degraded","error"]`, `reason: str \| None` |
| `ChatCreated` | `chat: ChatSummary` |
| `ChatSelected` | `chat_id: str` |
| `ChatDeleted` | `chat_id: str` |
| `ChatHistoryLoaded` | `chat_id: str`, `message_count: int`, `token_estimate: int`, `source: Literal["new","resumed"]` |
| `CommandStarted` | `command: str`, `arguments: dict` |
| `CommandProgress` | `command: str`, `phase: str`, `phase_index: int`, `phase_total: int`, `message: str \| None` |
| `CommandCompleted` | `command: str`, `result: dict` |
| `RuntimeStatusChanged` | `runtime_status: RuntimeStatus`, `reason: str \| None` |
| `ModeActivated` | `mode: str`, `prior_mode: str \| None`, `decided_at: datetime` |
| `ContextReloaded` | `workspace_id: str`, `source_count: int`, `memory_token_estimate: int` |
| `PromptBuilt` | `request_id: str`, `prompt_token_estimate: int`, `breakdown: dict[str,int]` |
| `ChatHistoryCompacted` | `chat_id: str`, `status: Literal["queued","running","completed","failed"]`, `summary_token_estimate: int \| None`, `replaced_turn_count: int \| None`, `compaction_count: int` |
| `RuntimeDelta` | `request_id: str`, `seq: int`, `delta_type: Literal["text","reasoning","tool_call"]`, `text: str \| None`, `tool_call: dict \| None` |
| `PlanReady` | `plan_id: str`, `plan: dict` |
| `ApprovalRequired` | `plan_id: str`, `step_id: str`, `step: dict`, `prompt: str` |
| `ApprovalResolved` | `plan_id: str`, `step_id: str`, `decision: Literal["approved","rejected","clarified"]` |
| `StepTaskSubmitted` | `task_id: str`, `step_id: str`, `plan_id: str` |
| `StepTaskStatusChanged` | `task_id: str`, `status: StepTaskStatus` |
| `StepCompleted` | `task_id: str`, `envelope: StepExecutionEnvelope` |
| `ArtifactsReady` | `step_id: str`, `artifacts: list[Path]` |
| `DoctorStarted` | `trigger: str`, `report_id: str` |
| `DoctorFinding` | `report_id: str`, `category: Literal["source","validity","lineage","tmp","memory"]`, `severity: Literal["info","warn","error"]`, `summary: str`, `details: dict` |
| `DoctorActionProposed` | `report_id: str`, `action: Literal["cleanup","promote","keep","review"]`, `target: str`, `rationale: str` |
| `DoctorReportReady` | `report_id: str`, `summary_counts: dict[str,int]`, `recommendations: list[str]`, `action_records: list[dict]` |
| `FinalMessage` | `assistant_message_id: str`, `text: str`, `usage: dict` |
| `TurnFailed` | `failure_summary: str`, `error_code: str`, `details: dict` |
| `TurnCancelled` | `reason: str`, `cancelled_at: datetime` |

Event names removed compared to prior draft: `WorkspaceActivated` (subsumed by `StatusChanged` and `activate_workspace` return value).

### Status Snapshot

```python
class HarnessStatusSnapshot(BaseModel):
    workspace_id: str
    chat_id: str | None
    chat_title: str | None
    workspace_health: Literal["ready", "busy", "degraded", "error"]
    active_mode: str
    run_id: str | None
    run_state: str
    runtime_status: RuntimeStatus
    execution_tasks: dict[str, int]                 # status_name -> count
    approval_state: Literal["idle","awaiting_user","resolved"] | None
    clarification_state: Literal["idle","awaiting_user","resolved"] | None
    chat_turn_count: int
    chat_token_estimate: int
    last_compacted_at: datetime | None
    compaction_count: int
    doctor_warning_count: int
    last_event: HarnessEventRef | None
```

`execution_tasks` keys are the literal `StepTaskStatus.status` values: `"queued"`, `"running"`, `"completed"`, `"failed"`, `"cancelled"`, `"timeout"`. Missing keys mean count = 0.

Layer 3 gathers raw runtime status from Layer 1 and raw task status from Layer 2, then produces the app-operational snapshot. Layer 4 renders the snapshot but does not compute it.

### `watch_status` Semantics

`watch_status` yields a `HarnessStatusSnapshot` when:

1. Any field of the snapshot differs from the last-yielded snapshot, **and** at least 50 ms have passed since the last yield (50 ms coalescing window collapses bursts).
2. A heartbeat tick fires. Default heartbeat interval = **2 seconds**, configurable via `SessionConfig.status_heartbeat_seconds`. Heartbeat re-yields the current snapshot even if unchanged so subscribers know the stream is alive.

Subscribers must be tolerant of duplicate snapshots (heartbeat case). Layer 3 must not buffer history; new subscribers receive a snapshot immediately on subscribe, then change/heartbeat.

### Responsibilities

Layer 3 owns:

- active workspace/run/mode state
- workspace-scoped chat lifecycle and persistence
- workspace lifecycle and file ingest coordination
- run state transitions
- context rebuild, active chat history, and compaction policy
- operational status aggregation
- prompt package recording
- approval gates
- plan and step contract creation
- run/plan/step to Layer 2 task mapping
- decisions to submit, wait, list, and cancel execution tasks
- artifact inspection and evidence persistence
- doctor and review command orchestration
- harness event emission
- typed exception emission for invalid chat/workspace operations

### Chat Management

Layer 3 provides chat management as a first-class harness service, parallel in product shape to workspace management but scoped underneath workspaces. Every chat has exactly one `workspace_id`. Layer 3 must reject attempts to resume a chat against the wrong active workspace unless it first activates that chat's workspace through the workspace manager.

Chat records live under:

```text
<app_root>/chats/<workspace_id>/<chat_id>/
```

On-disk layout:

```text
metadata.json
messages.jsonl
compactions.jsonl
```

Schemas:

```python
class ChatMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "compacted_summary"]
    text: str
    ts: datetime
    turn_id: str | None
    active_mode: str | None
    token_estimate: int

class ChatRecord(BaseModel):
    chat_id: str
    workspace_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    last_active_mode: str | None
    last_run_id: str | None
    message_count: int
    token_estimate: int
    last_compacted_at: datetime | None
    compaction_count: int
    messages: list[ChatMessage]

class ChatSummary(BaseModel):
    chat_id: str
    workspace_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    token_estimate: int
    last_compacted_at: datetime | None

class ChatDeleteResult(BaseModel):
    chat_id: str
    workspace_id: str
    deleted: bool
    files_removed: int
```

Lazy creation: `create_chat(...)` allocates `chat_id` in memory but does not write to disk. The chat directory + `metadata.json` + first `messages.jsonl` line are written on the first user message of that chat. App start does not produce empty chat directories.

Chat records do not replace:

- durable workspace memory
- artifact truth
- worker execution envelopes
- raw internal reasoning

Layer 3 must append the current user message before prompt assembly, include prior active-chat history in the runtime request, and append the assistant final message after the turn finishes. Failed or cancelled turns may record a lightweight terminal marker, but they must not invent an assistant answer.

On app restart, the app starts a new chat lazily on the first user message. The user can use chat management to view saved chats, delete saved chats, or resume a saved chat. Resuming a chat loads its persisted messages into the active Layer 3 chat history and subsequent runtime requests include that restored history.

Layer 3 must provide:

- list chats for a workspace
- create a new chat under a workspace (lazy)
- view a chat transcript and metadata
- resume a chat as the active chat for its workspace
- delete a chat and remove its files from `<app_root>/chats`

Deleting a workspace cascades to its chats. The workspace manager removes `<app_root>/chats/<workspace_id>/` recursively when the workspace is deleted. The cascade is irreversible. Layer 3 emits `ChatDeleted` per removed chat, then a workspace deletion event.

### Runtime Request Assembly

Layer 3 assembles runtime requests in this order:

1. active mode/system prompt
2. fresh durable workspace context
3. active chat summary, if present
4. recent active chat turns for the active workspace
5. current user message

Numerics:

- **Recent turns kept after compaction**: last 8 turns (4 user + 4 assistant pairs). Older turns are eligible for compaction.
- **Completion reservation**: 25% of context window reserved for model output.
- **Prompt budget split** within the remaining 75%: durable context capped at 30%, chat summary 15%, recent turns 25%, system prompt + current user message take the remainder.
- **Compaction trigger**: assembled prompt token estimate > 80% of context window forces `compact_chat_history` before the request.

Layer 3 calls `runtime.token_pressure(request)` to get authoritative numbers and decides compaction based on `TokenPressure.over_threshold`.

The runtime never owns this history. It only receives the messages Layer 3 includes in the current request.

### Chat Compaction

Layer 3 provides explicit active-chat compaction via `compact_chat_history`. Compaction replaces older chat turns with a summary record while preserving recent turns and operational atoms needed to continue the active run.

Triggers:

- user action from the TUI (`/compact`)
- token pressure before a runtime request
- Layer 3 may also trigger on workspace switch or run cancellation if its policy decides preserving a summary is useful for the active chat

Compaction output belongs to the chat record under `<app_root>/chats`; it must not write to `memory/` or any durable workspace truth table. **Workspace memory management is exclusively the responsibility of `/doctor`, not `/compact`.** The `compact_context` command is not part of the API.

**Concurrency policy**: compaction may need Layer 1 to summarize. Because the runtime is hard-serial, compaction queues behind any in-flight stream. The streaming compaction method emits status events:

```text
ChatHistoryCompacted(status="queued") -> ChatHistoryCompacted(status="running") -> ChatHistoryCompacted(status="completed" | "failed")
```

If the user cancels the active turn while compaction is queued, compaction proceeds once the turn ends.

Compaction may use deterministic shaping for simple operational atoms; runtime summarization is used for natural-language conversation segments. `ChatHistoryCompacted` carries summary metadata only, not full hidden source transcript.

Layer 3 does not own:

- model implementation or llama.cpp bridging
- subprocess mechanics
- task registry implementation
- Textual rendering
- file upload UI
- raw TUI layout state

### Runtime Flow

Layer 3 builds a `RuntimeRequest`, calls `async for runtime_event in runtime.stream(request)`, and maps runtime deltas into harness `RuntimeDelta` events. Layer 3 records prompt metadata, usage, and final state at the appropriate event points.

### Worker Flow

Layer 3 submits only after approval:

```python
yield StepTaskSubmitted(...)
handle = await worker.submit(request)
yield StepTaskStatusChanged(...)
envelope = await worker.wait(handle.task_id)
yield StepCompleted(...)
```

Layer 3 may cancel via `await worker.cancel(task_id, reason)` when the user cancels a run, switches workspace with `force=True`, or requests stop behavior.

### Workspace Switching

`activate_workspace(workspace_id, force=False)` behavior:

- If no active run, switches workspace and returns the new `HarnessStatusSnapshot`.
- If a run is active and `force=False`, raises `WorkspaceSwitchBlocked(active_run_id)`. Snapshot unchanged.
- If a run is active and `force=True`, calls `cancel_run(active_run_id, reason="workspace_switch")`, awaits `TurnCancelled`, then activates the new workspace and returns the new snapshot.

The TUI handles `WorkspaceSwitchBlocked` by showing a confirmation modal and retrying with `force=True` if the user confirms.

### Command Surface

Layer 3 exposes the full set of user-callable harness functions through a typed command registry. Layer 4 must discover command names, descriptions, required arguments, optional arguments, availability, and disabled reasons from Layer 3 rather than hard-coding command truth.

```python
class ArgSpec(BaseModel):
    name: str
    type: Literal["str", "int", "float", "bool", "path", "chat_id", "workspace_id", "run_id", "step_id", "artifact_path"]
    required: bool
    description: str
    example: str | None = None

class CommandContext(BaseModel):
    workspace_id: str | None
    chat_id: str | None
    run_id: str | None
    has_pending_approval: bool
    has_pending_clarification: bool

class HarnessCommandDescriptor(BaseModel):
    name: str                                       # e.g. "doctor"
    slash_alias: str                                # e.g. "/doctor"
    short_description: str
    arguments: list[ArgSpec]
    available: bool
    disabled_reason: str | None
    affected_resource: Literal["workspace","chat","run","plan","step","artifact","memory","provenance","doctor"]
    expected_event_types: list[str]
    example_usage: str

class HelpResult(BaseModel):
    commands: list[HarnessCommandDescriptor]       # all if `command` is None, single-element if specified
    not_found: bool
```

Layer 3 direct commands must be real harness flows, not echo responses. If a command is listed as available, invoking it must perform the corresponding harness behavior and emit typed events. If the underlying behavior is not implemented, Layer 3 must mark the command unavailable with a clear `disabled_reason`.

Layer 3 command coverage must include at least:

- `doctor`
- `compact` (chat history compaction; replaces former `compact_chat_history` slash alias)
- `cancel_run`
- `retry_step`
- `revise_goal`
- `stop_after_current_step`
- `rerun_step`
- `challenge_conclusion`
- `mark_result_trusted`
- `mark_result_invalidated`
- `inspect_artifact`
- `memory_review`
- `provenance_inspect`
- `switch_workspace`
- `workspace_status`
- `workspace_inventory`
- `validity_inspect`
- `help`
- chat management commands for create, list, view, resume, delete

### Slash Command Grammar

Layer 4 parses slash commands; Layer 3 owns semantics. V1 grammar is **positional only**:

```text
/<command_name> [<positional_arg_1> [<positional_arg_2> ...]]
```

Rules:

- Tokens separated by whitespace.
- Tokens containing spaces must be double-quoted: `/inspect_artifact "Project Reports/q1.csv"`.
- No named flags in V1. May be added later without breaking.
- Argument count and types validated against `HarnessCommandDescriptor.arguments` by Layer 3.
- Unknown commands surface a Layer 4 error with `/help <prefix>` suggestions.

Examples:

```text
/help
/help inspect_artifact
/doctor
/workspace_status
/inspect_artifact artifacts/tmp/run_1/step_1/output.txt
/resume_chat chat_123
/cancel_run "stuck"
/compact
```

### `/help`

Layer 3 owns help content, generated from `HarnessCommandDescriptor` registry:

- `help()` (no arg) returns `HelpResult` with all descriptors. Layer 4 renders as a list with one-line `short_description`.
- `help(command="doctor")` returns single-element `HelpResult` with full `HarnessCommandDescriptor`. Layer 4 renders name, slash alias, description, args (name + type + required + description + example), example usage, expected events, availability + disabled reason if any.
- `help(command="unknown")` returns `HelpResult(commands=[], not_found=True)`.

Unavailable commands appear in `/help` listings with an "(unavailable: <reason>)" annotation.

### Doctor Command Flow

The doctor process must be fully operational as a Layer 3 command. `/doctor` and command-palette doctor invocation both call Layer 3; Layer 4 does not run doctor logic directly. Workspace memory management belongs here, not in `/compact`.

Doctor must emit verbose enough events for Layer 4 to render progress and results:

1. `CommandStarted(command="doctor")`
2. `DoctorStarted(trigger, report_id)`
3. `CommandProgress(command="doctor", phase, phase_index, phase_total, message)` for scan phases such as source check, tmp review, lineage/validity review, memory review, recommendation assembly
4. `DoctorFinding` events for source, validity, lineage, tmp, and memory findings
5. `DoctorActionProposed` events for cleanup, promotion, keep, or review actions
6. `DoctorReportReady` with report ID, summary counts, recommendations, and action records
7. `CommandCompleted(command="doctor", result={"report_id": ...})`

Doctor results must remain harness-owned. Layer 4 may show report details, filter findings, and offer action buttons, but Layer 3 owns whether actions are valid and how they are applied.

### Workspace Schemas

```python
class WorkspaceSummary(BaseModel):
    workspace_id: str
    workspace_dir: Path
    created_at: datetime
    last_activated_at: datetime | None
    chat_count: int
    source_count: int
    health: Literal["ready", "busy", "degraded", "error"]

class WorkspaceIngestResult(BaseModel):
    workspace_id: str
    accepted: list[Path]                            # destination paths inside workspace
    rejected: list[dict]                            # {source_path, reason}
    source_records_added: int
```

### Removals

- Remove `Orchestrator.handle_turn(...)` final dict contract.
- Remove sync `resume_approved_step(...)` and `resume_with_clarification(...)`.
- Remove `process_events` as the core orchestration API.
- Remove `SessionConfig.max_parallel_runs`; replace with single-active-run invariant + `RunAlreadyActive` error.
- Remove `compact_context` command.
- Remove `WorkspaceActivated` event.
- Convert harness and app session tests to async event consumption.

### Tests

Layer 3 tests must verify:

- event order for non-execution turns matches schema
- runtime deltas stream through as harness events
- active chat history is included in later runtime requests
- a new app process starts a new chat lazily on first user message
- resumed chats reload persisted history from `<app_root>/chats`
- chat history is isolated by workspace and chat ID
- user-triggered compaction queues behind in-flight runtime stream and emits queued/running/completed status events
- token-pressure compaction runs before overlong runtime requests at 80% threshold
- runtime request assembly respects 25% completion reserve and prompt split
- list/view/resume/delete chat operations are Layer 3-owned
- workspace deletion cascades to all `<app_root>/chats/<workspace_id>/` files
- `activate_workspace(force=False)` raises `WorkspaceSwitchBlocked` when run active
- `activate_workspace(force=True)` cancels active run then switches
- command descriptors reflect all available Layer 3 functions and disabled reasons
- direct command invocation emits `CommandStarted`, command-specific progress/results, and `CommandCompleted`
- `/doctor` execution emits verbose doctor progress and `DoctorReportReady`
- `/help` returns full descriptors; `/help <command>` returns single descriptor; unknown returns `not_found=True`
- plan/approval pauses emit `ApprovalRequired`
- approval resume submits Layer 2 task and emits task events
- cancellation calls Layer 2 cancel and returns `TurnCancelled` directly (not AsyncIterator)
- status snapshots reflect workspace, runtime, run, approval, and task state
- `watch_status` yields on change with 50 ms coalescing and 2 s heartbeat
- typed exceptions raised on invalid chat/workspace operations match §10
- second concurrent `run_turn` raises `RunAlreadyActive`
- persistence happens at semantic event points
- chat history and compaction summaries are persisted only under `<app_root>/chats`, not as durable workspace memory
- Layer 3 imports no Layer 4 TUI modules

## 9. Plan 4: Layer 4 Async TUI

### Goal

Layer 4 becomes the front-facing async UI for Layer 3. It renders Layer 3 events and status snapshots; it does not compute operational truth.

### TUI Structure

The Textual app must emulate the reference modules in `docs/superpowers/specs/sample_code/`:

- top `StatusBar`
- scrollable conversation/message log
- chat manager modal/panel
- command palette
- `PlanPanel`
- `ProcessLog`
- `ArtifactPanel`
- `ContextBar`
- bottom prompt input
- workspace modal
- file uploader/drop zone
- workspace file browser
- approval modal
- clarification modal

### Turn Flow

1. User submits text.
2. TUI disables prompt input.
3. If the text begins with `/`, TUI parses it as a slash command (positional grammar §8) and dispatches it through the async Layer 3 command surface via `AppSession.handle_direct_command(...)`.
4. Otherwise TUI starts a Textual worker for `app_session.run_user_turn(...)` using the active `chat_id`.
5. Each `AppEvent` updates only the relevant widget.
6. `ApprovalRequired` opens the approval modal.
7. User approval calls `app_session.resume_approved_step(...)`.
8. `FinalMessage`, `CommandCompleted`, `TurnFailed`, or `TurnCancelled` re-enables input.

### Status Bar

The status bar renders only the latest `HarnessStatusSnapshot` from Layer 3. Visual spinner behavior is allowed, but semantic facts such as workspace health, runtime state, run state, and task counts come from Layer 3. The status bar subscribes to `watch_status` and treats heartbeat ticks as liveness only.

### Conversation Log Rehydration

Conversation log uses an in-memory cache of rendered messages for the current process lifetime. Cheap re-renders (panel toggle, window resize, widget remount within session) read from cache. On app restart or `resume_chat`, Layer 4 calls `app_session.view_chat(chat_id)` and rebuilds the log from the returned `ChatRecord`. Layer 3 stays the source of truth; Layer 4 cache is only a render optimization.

### Workspace UI

Layer 4 owns the workspace modal UI, file drop target, and file browser. Workspace actions must go through `AppSession` so that Layer 3 remains the source of active workspace and status truth.

File upload sends source paths to `app_session.ingest_files(...)`. Layer 3 coordinates copying or registering those files into the active workspace `data/`, returns `WorkspaceIngestResult`, and emits status changes. Layer 4 must not mutate harness state behind Layer 3.

Workspace switch with active run: Layer 4 calls `activate_workspace(workspace_id, force=False)`. On `WorkspaceSwitchBlocked`, Layer 4 shows confirmation modal and retries with `force=True` on user confirm.

### Chat Management UI

Layer 4 includes chat management next to workspace management. Chats are workspace-scoped items, so the chat manager filters by the active workspace unless the user is intentionally browsing another workspace's chats.

Layer 4 controls:

- create a new chat
- list chats for the active workspace
- view a saved chat transcript
- resume a saved chat
- delete a chat
- compact the active chat (`/compact` or button)

Layer 4 displays the active chat and streams assistant deltas into the conversation/message log. The displayed log is UI cache; prompt history comes from Layer 3 events and Layer 3 chat state.

The compact-history control calls `app_session.compact_chat_history(...)`. It must not compact local widget text on its own. After compaction, Layer 4 shows the updated chat state returned by Layer 3: a compacted summary marker plus recent turns. The UI must make compaction visible enough that the user understands older chat turns were summarized, while avoiding raw hidden reasoning or excessive transcript dumps.

### Command Palette And Slash Commands

Layer 4 provides a command palette for all Layer 3 functions. The palette is populated from `app_session.list_commands(...)` and shows unavailable commands as disabled with the Layer 3 `disabled_reason`. Layer 4 must not maintain a separate command truth table.

Layer 4 also supports slash commands in the prompt input using the positional grammar (§8). Slash-command parsing belongs to Layer 4 only as user input parsing. Command validation, argument semantics, availability, execution, and results belong to Layer 3. Unknown slash commands show a concise UI error and may suggest matching descriptors via `help(command=<prefix>)`.

For `/doctor`, Layer 4 must:

- dispatch `doctor` through `app_session.handle_direct_command(...)`
- render `CommandStarted`, `CommandProgress`, `DoctorFinding`, `DoctorActionProposed`, `DoctorReportReady`, and `CommandCompleted`
- keep controls responsive enough to cancel or inspect related state according to Layer 3 status
- never synthesize doctor findings locally

For `/help`, Layer 4 calls `app_session.help(command=...)` and renders the returned `HelpResult` in a help panel or modal.

At the end of the async migration, every Layer 3 function marked available for the current context must be callable from Layer 4 through at least one appropriate UI path: command palette, slash command, dedicated control, or contextual action. Dedicated controls are still required for common workflows such as approval, cancellation, workspace switching, chat management, file upload, and artifact inspection.

### V1 TUI Control Coverage

The async TUI must cover the required controls from the V1 spec rather than only exposing the command names:

- switch workspace (with `force=False/True` confirmation)
- inspect workspace status
- command palette access to Layer 3 commands
- slash-command access to Layer 3 commands, including `/doctor`, `/compact`, `/help`
- create, view, resume, delete, and compact chats
- approve a plan
- revise a goal
- clarify missing intent
- stop after the current step
- cancel a run
- rerun a step
- inspect an artifact
- run doctor
- review memory updates
- challenge a conclusion
- mark a result trusted
- mark a result invalidated
- inspect provenance and validity state

Each control calls an `AppSession` async method and renders the returned Layer 3 events/status. Controls without complete Layer 3 behavior must be implemented in Layer 3 or disabled with a clear unavailable state; Layer 4 must not fake successful behavior locally.

### Responsibilities

Layer 4 owns:

- Textual layout and widgets
- user input collection
- approval and clarification modals
- workspace manager UI
- chat manager UI
- file uploader/drop zone and browser UI
- rendering app/harness events
- in-memory conversation log cache
- starting and cancelling Textual workers
- invoking chat management and compaction through Layer 3
- rendering command palette and slash-command entry points from Layer 3 command descriptors
- slash command parsing (positional grammar)

Layer 4 does not own:

- harness orchestration
- status facts
- runtime behavior
- worker execution
- plan creation
- artifact validity
- durable analytical state
- prompt history ownership
- command truth (lives in `HarnessCommandDescriptor` registry)

### Removals

- Remove `submit_user_text(...) -> AppTurnResult`.
- Remove final-result-only rendering.
- Remove UI state that computes workspace/runtime status independently.
- Convert TUI tests to async event scripts.

### Tests

Layer 4 tests must verify:

- status bar renders Layer 3 snapshots, including heartbeat ticks
- process log updates while events stream
- plan panel updates from `PlanReady` and task events
- chat history events update the message log
- conversation log rehydrates from `view_chat` after simulated app restart
- chat manager lists, views, resumes, deletes, and creates chats through Layer 3
- compact-history control calls Layer 3 and renders the compacted chat state with summary marker
- command palette is populated from Layer 3 descriptors with `disabled_reason` shown
- slash commands parse with positional grammar including quoted args
- `/help` and `/help <command>` render Layer 3 help content
- `/doctor` starts the Layer 3 doctor flow and renders verbose doctor events
- approval modal resumes through `AppSession`
- clarification modal resumes through `AppSession`
- cancel action calls async cancellation and renders `TurnCancelled`
- workspace switch with active run shows confirmation modal then retries with `force=True`
- file drop copies to active workspace through the workspace boundary
- V1 required controls are present and either wired to Layer 3 behavior or visibly unavailable
- no sync app/session methods are used

## 10. Error Handling

Layer 1 emits or raises typed runtime errors. Layer 2 produces execution failure/cancellation/timeout task states and envelopes. Layer 3 maps lower-layer failures into harness events and durable state. Layer 4 renders the failure and offers controls, but does not reinterpret failure semantics.

### Typed Exceptions (Non-Streaming)

Raised by non-streaming async methods on `Orchestrator` and `AppSession`:

```python
class ChatNotFound(Exception):
    chat_id: str

class ChatWorkspaceMismatch(Exception):
    chat_id: str
    expected_workspace: str
    actual_workspace: str

class ChatActiveDeletionBlocked(Exception):
    chat_id: str

class WorkspaceNotFound(Exception):
    workspace_id: str

class RunAlreadyActive(Exception):
    run_id: str

class WorkspaceSwitchBlocked(Exception):
    active_run_id: str
```

### Typed Error Events (Streaming)

Streaming methods (`run_turn`, `resume_chat`, `compact_chat_history`, `handle_direct_command`) surface errors as terminal events:

- `TurnFailed` — turn could not produce a final answer
- `TurnCancelled` — turn cancelled by user or workspace switch
- `ChatHistoryCompacted(status="failed")` — compaction failure terminal status

### Cancellation

Cancellation must be explicit:

- runtime cancellation stops stream production at the next inter-token boundary
- worker cancellation terminates subprocess work and returns a cancelled envelope
- harness cancellation updates run/task mapping and returns `TurnCancelled` directly from `cancel_run`
- TUI cancellation requests Layer 3 cancellation and waits for the resulting event/return value

## 11. Migration And Removal Policy

This is a breaking migration. Implementation must remove sync public APIs instead of keeping compatibility shims:

- no `Runtime.complete(...)`
- no sync `Runtime.stream(...)`
- no sync `PythonStepExecutor.execute(...)`
- no `Orchestrator.handle_turn(...)` final dict API
- no `DataAnalysisAppSession.handle_user_turn(...)` final `AppTurnResult` API
- no TUI final-result-only turn renderer
- no Layer 4-owned prompt history or local transcript compaction
- no `SessionConfig.max_parallel_runs`
- no `compact_context` command
- no `WorkspaceActivated` event

Tests must be migrated at the same time so the repository proves the new async contracts.

## 12. Packaging Notes

If new Textual modules, prompt files, or other runtime resources are added during implementation, packaging metadata and build scripts must include them. The existing project instruction to update `hragent.spec` for Textual or prompt resources still applies.

## 13. V1 Acceptance Criteria

Concrete invariants the migration must satisfy. Tests bind to these.

**Layer contracts**
- All four layers expose async-only public contracts for their touched behavior.
- No sync turn/execution/runtime APIs remain in production code.
- Each layer's tests pass independently.

**Concurrency**
- Single active run, chat, workspace per app process.
- Second concurrent `run_turn` raises `RunAlreadyActive`.
- `activate_workspace` with active run raises `WorkspaceSwitchBlocked` unless `force=True`.

**Runtime**
- Layer 1 internal bridge queue defaults to 64, configurable.
- Cancellation observed within one token at the next inter-token boundary.
- Layer 3 consumes Layer 1 streaming without knowledge of llama.cpp bridge internals.

**Worker**
- Layer 3 can list and cancel Layer 2 execution tasks.
- Cancelled work returns an envelope with `status.status == "cancelled"`.

**Chat**
- New app process produces no chat directory until first user message.
- `<app_root>/chats/<workspace_id>/<chat_id>/` contains `metadata.json`, `messages.jsonl`, optional `compactions.jsonl`.
- Active chat history included in subsequent prompts.
- `resume_chat` reloads persisted history.
- Workspace deletion cascades and removes all `<app_root>/chats/<workspace_id>/` files.
- Compaction output written only under `<app_root>/chats`, never under `memory/`.

**Runtime request assembly**
- Recent turns retained = 8.
- Completion reserve = 25% of context window.
- Prompt split: durable ≤ 30%, chat summary ≤ 15%, recent turns ≤ 25%.
- Compaction trigger at 80% context window pressure.

**Compaction**
- `/compact` queues behind in-flight runtime stream.
- Emits `ChatHistoryCompacted` queued → running → completed/failed.
- `/compact` does not modify durable workspace memory; workspace memory mgmt is `/doctor` only.

**Status**
- `HarnessStatusSnapshot` matches schema in §8.
- `watch_status` yields on change (50 ms coalescing) + 2 s heartbeat.
- Layer 4 status bar uses Layer 3 snapshots only.

**Commands**
- Every available command in the registry is invocable through palette or slash.
- Unavailable commands appear with `disabled_reason`.
- `/help` returns full descriptor list.
- `/help <command>` returns single descriptor; unknown returns `not_found=True`.
- Slash grammar = positional only; quoted args for spaces; no named flags.

**Doctor**
- `/doctor` runs the Layer 3 doctor process and emits `DoctorStarted`, `CommandProgress`, `DoctorFinding`, `DoctorActionProposed`, `DoctorReportReady`, `CommandCompleted`.

**TUI**
- Layer 4 calls Layer 3 only through `AppSession`.
- Conversation log rehydrates from `view_chat` after app restart.
- Workspace switch shows confirmation modal then retries with `force=True` on confirm.
- End-to-end TUI tests show live event rendering, status snapshots, approval resume, clarification resume, cancellation, workspace switching, and file upload.
