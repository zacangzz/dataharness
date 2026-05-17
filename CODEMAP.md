# CODEMAP — `src/` Reference

Single-source reference tracking four relationship types across the codebase:

1. **Imports** — which files pull from which other files (`src/` only)
2. **Call sites** — which functions/classes call into others
3. **Inheritance** — class `extends` graph
4. **Definitions** — where every symbol is declared

Skim the **Top-level Indices** for navigation, then drop into **Per-file Inventory** for full details.

---

# AGENTS: edit from below only:

## Layered Architecture (top → bottom)

| Layer | Path | Role |
|------|------|------|
| 4 — App | `src/app/`, `src/cli.py` | TUI + `AppSession` facade, event mapping (no routing/prompt selection) |
| 3 — Harness | `src/harness/` | Harness Core kernel (`core/`) + services (`services/`) + shared contracts (root); orchestrator, state machine, intent routing, prompt profiles, persistence, doctor, knowledge, chat |
| 2 — Worker | `src/worker/` | Sandboxed Python step execution |
| 2 — Runtime | `src/runtime/` | LLM streaming (llama.cpp), tool-call parsing |
| 0 — Observability | `src/observability/` | Telemetry events, structured logging, path resolution |

**Hard rule (per `factory.py`):** Layer 4 must NOT import `runtime.*` directly. Layer 4 obtains a wired `Orchestrator` via `harness.factory.build_orchestrator`.

**Memory write rule (per `harness/services/knowledge.py`):** only `KnowledgeManager` may write under `memory/`. `guarded_external_memory_write` always raises.

**Layer 3 structure:** Harness Core kernel = `src/harness/core/*`; harness services = `src/harness/services/*`; shared contracts at `src/harness/` root = `control.py`, `events.py`, `exceptions.py`, `status.py`, `orchestrator.py` (+ `__init__.py`). `core/*` must not import `services/*`.

---

## Top-level Indices

### Index A — Import Graph (file → internal `src/` imports)

```
src/cli.py
  → harness, observability, worker.sandbox_bootstrap (private `-m` dispatch; no app.* imports; constructs DataHarnessApp via harness.factory)

src/app/__init__.py                     → (none)
src/app/events.py                       → (none)
src/app/event_mapping.py                → app.events
src/app/session.py                      → app.event_mapping, app.events,
                                           harness.core.command_registry, harness.control,
                                           harness.exceptions, harness.orchestrator,
                                           harness.status, observability, observability.events
(no app.agents package — routing/prompt profiles are Layer 3 services; src/app/session.py imports neither app.agents nor runtime.*)
(agentic loop + intent routing + prompt-profile selection relocated to harness layer; see src/harness/orchestrator.py:run_agentic_turn / _select_profile)
src/app/tui/__init__.py                 → (none)
src/app/tui/app.py                      → app.session, app.tui.clipboard, app.tui.commands,
                                           app.tui.event_consumer,
                                           app.tui.file_picker, app.tui.help, app.tui.jump,
                                           app.tui.prompt_bar, app.tui.prompt_editor,
                                           app.tui.run_trace, app.tui.screens, app.tui.widgets,
                                           app.tui.screens.workspace_manager,
                                           app.tui.screens.file_ingest, app.tui.sidebar_sections,
                                           harness.command_registry, harness.control,
                                           observability, observability.events
src/app/tui/clipboard.py                → (none; stdlib subprocess/shutil/sys only)
src/app/tui/models.py                   → (none)
src/app/tui/commands.py                 → (none)
src/app/tui/event_consumer.py           → app.events
src/app/tui/help.py                     → (none)
src/app/tui/jump.py                     → (none)
src/app/tui/screens.py                  → (none)
src/app/tui/conversation.py             → (none)
src/app/tui/file_picker.py              → (none)
src/app/tui/prompt_editor.py            → (none)
src/app/tui/sidebar.py                  → (none)
src/app/tui/widgets.py                  → app.tui.conversation, app.tui.help, app.tui.sidebar,
                                           app.tui.sidebar_sections
src/app/tui/sidebar_sections.py         → (none)
src/app/tui/run_trace.py                → (none)
src/app/tui/prompt_bar.py               → app.tui.file_picker, app.tui.help, app.tui.prompt_editor
src/app/tui/screens/__init__.py         → (none; re-export)
src/app/tui/screens/chat_manager.py     → (none)
src/app/tui/screens/command_palette.py  → (none)
src/app/tui/screens/workspace_manager.py→ app.tui.file_picker, app.tui.screens.file_ingest
src/app/tui/screens/file_ingest.py      → app.tui.file_picker
src/app/tui/screens/workspace_modal.py  → (none)

# --- Shared contracts (src/harness/ root) ---
src/harness/__init__.py                 → harness.core.app_store, harness.core.paths,
                                           harness.core.workspace
src/harness/control.py                  → (none)
src/harness/events.py                   → harness.status, runtime.types, worker.models
src/harness/exceptions.py               → (none)
src/harness/status.py                   → runtime.types
src/harness/orchestrator.py             → harness.control, harness.events, harness.exceptions,
                                           harness.status,
                                           harness.core.analysis_flow, harness.core.command_registry,
                                           harness.core.persistence, harness.core.state_machine,
                                           harness.services.analysis, harness.services.chat,
                                           harness.services.context, harness.services.doctor,
                                           harness.services.knowledge, harness.services.mode_router,
                                           harness.services.prompt_profiles, harness.services.workspace,
                                           harness.services.workspace_files,
                                           harness.commands.* (chat, compact, diagnostics, doctor,
                                            memory, provenance, run, workspace; imported lazily inside
                                            _register_commands),
                                           harness.tools.analysis, harness.tools.control,
                                           harness.tools.file, harness.tools.knowledge,
                                           harness.tools.registry,
                                           observability, runtime.protocol, runtime.types,
                                           worker.executor, worker.models, worker.policy
                                           (knowledge_intents imported only by harness.tools.knowledge)

# --- Harness Core kernel (src/harness/core/) — must NOT import harness.services.* ---
src/harness/core/__init__.py            → (none; empty marker)
src/harness/core/analysis_flow.py       → (none)
src/harness/core/app_store.py           → (none)
src/harness/core/approval.py            → (none)
src/harness/core/command_registry.py    → harness.events
src/harness/core/db.py                  → (none)
src/harness/core/factory.py             → harness.core.db, harness.core.persistence,
                                           harness.orchestrator, harness.services.context,
                                           harness.services.doctor, harness.services.knowledge,
                                           observability, runtime.protocol, worker.executor
src/harness/core/fingerprints.py        → (none)
src/harness/core/paths.py               → (none)
src/harness/core/persistence.py         → harness.control, harness.core.db, observability,
                                           observability.events
src/harness/core/prompt_registry.py     → (none)
src/harness/core/state_machine.py       → harness.control
src/harness/core/validity.py            → (none)
src/harness/core/workspace.py           → harness.core.app_store, harness.core.paths

# --- Harness services (src/harness/services/) ---
src/harness/services/__init__.py        → harness.services.analysis, harness.services.doctor,
                                           harness.services.mode_router,
                                           harness.services.prompt_profiles,
                                           harness.services.workspace_files
src/harness/services/analysis.py        → harness.control, harness.events, worker.models,
                                           worker.policy
src/harness/services/chat.py            → harness.exceptions, runtime.protocol, runtime.types
src/harness/services/context.py         → (none)
src/harness/services/doctor.py          → harness.control, harness.events,
                                           harness.core.fingerprints, harness.core.persistence,
                                           harness.core.validity, harness.services.chat,
                                           harness.services.knowledge, runtime.protocol, runtime.types
src/harness/services/knowledge.py       → harness.control, harness.core.persistence
src/harness/services/knowledge_intents.py → (none)
src/harness/services/mode_router.py     → observability, observability.events
src/harness/services/prompt_profiles.py → harness.tools.registry
src/harness/services/provenance.py      → harness.core.db
src/harness/services/repair.py          → (none)
src/harness/services/workspace.py       → harness.core.app_store, harness.core.workspace,
                                           harness.exceptions, harness.services.chat
src/harness/services/workspace_files.py → harness.services.context

# --- Harness commands package (src/harness/commands/) ---
src/harness/commands/__init__.py        → harness.commands.chat, harness.commands.compact,
                                           harness.commands.diagnostics, harness.commands.doctor,
                                           harness.commands.memory, harness.commands.provenance,
                                           harness.commands.run, harness.commands.workspace
src/harness/commands/chat.py            → harness.core.command_registry, harness.orchestrator
src/harness/commands/compact.py         → harness.core.command_registry, harness.orchestrator
src/harness/commands/diagnostics.py     → harness.core.command_registry, harness.orchestrator
src/harness/commands/doctor.py          → harness.core.command_registry, harness.orchestrator
src/harness/commands/memory.py          → harness.core.command_registry, harness.orchestrator
src/harness/commands/provenance.py      → harness.core.command_registry, harness.orchestrator
src/harness/commands/run.py             → harness.core.command_registry, harness.orchestrator
src/harness/commands/workspace.py       → harness.core.command_registry, harness.orchestrator

# --- Harness tools package (src/harness/tools/) ---
src/harness/tools/__init__.py           → harness.tools.registry
src/harness/tools/analysis.py           → harness.events, harness.tools.registry
src/harness/tools/control.py            → harness.events, harness.tools.registry
src/harness/tools/file.py               → harness.events, harness.tools.registry
src/harness/tools/knowledge.py          → harness.events, harness.services.knowledge_intents,
                                           harness.tools.registry
src/harness/tools/registry.py           → re, harness.events

src/runtime/__init__.py                 → runtime.config
src/runtime/bridge.py                   → runtime.types
src/runtime/config.py                   → (none)
src/runtime/llama_cpp_runtime.py        → observability, observability.events, runtime.bridge,
                                           runtime.config, runtime.tool_calls, runtime.types
src/runtime/protocol.py                 → runtime.types
src/runtime/tool_calls.py               → (none)
src/runtime/types.py                    → (none)

src/observability/__init__.py           → observability.events, observability.logging_setup,
                                           observability.runtime_paths, observability.telemetry
src/observability/events.py             → (none)
src/observability/logging_setup.py      → observability.events, observability.telemetry
src/observability/redaction.py          → (none)
src/observability/runtime_paths.py      → (none)
src/observability/telemetry.py          → observability.events

src/worker/__init__.py                  → worker.executor, worker.models
src/worker/executor.py                  → observability, observability.events, worker.models,
                                           worker.paths, worker.policy
src/worker/models.py                    → (none)
src/worker/paths.py                     → (none)
src/worker/policy.py                    → worker.models
src/worker/sandbox_bootstrap.py         → (subprocess; no static src.* imports)
```

### Index B — Inheritance Graph (class extends)

**Pydantic `BaseModel` subclasses** (ubiquitous data contracts):
- runtime/types: `RuntimeMessage`, `RuntimeRequest`, `RuntimeEvent`, `TokenPressure`
- runtime/config: `RuntimeConfig`
- runtime/tool_calls: `ParsedToolCall`; `extract_fenced_code` (gen-2 fenced ```` ```python ```` → code lines)
- observability/events: `TelemetryEvent`
- worker/models: `ResourceLimits`, `PermissionEnvelope`, `StepExecutionRequest`, `ExecutionEnvelope`, `StepTaskHandle`, `StepTaskStatus`, `StepExecutionEnvelope`
- harness/core/app_store: `AppStore`
- harness/services/chat: `ChatMessage`, `ChatRecord`, `ChatSummary`, `ChatDeleteResult`
- harness/core/command_registry: `ArgSpec`, `CommandContext`, `HarnessCommandDescriptor`, `HelpResult`
- harness/tools/registry: `ToolContext`, `ToolArgSpec`, `ToolDescriptor`
- harness/control: `HarnessRecord`, `ValidationFailure`, `SessionConfig`
- harness/events: `HarnessEvent`, `HarnessEventRef`, + all `*Event` subclasses
- harness/core/paths: `AppPaths`, `WorkspacePaths`
- harness/services/provenance: `ProvenanceRecord`
- harness/status: `HarnessEventRefPayload`, `HarnessStatusSnapshot`
- harness/services/workspace: `WorkspaceSummary`, `WorkspaceIngestResult`
- harness/services/mode_router: `ProfileDecision`
- harness/services/prompt_profiles: `PromptPackage` (mode/template_version/prompt_text/package_hash)
- app/events: `AppEvent`
- app/tui/models: `WorkspaceView`, `AppView`

**`HarnessRecord(BaseModel)` chain** (harness/control.py):
`HarnessRecord` ← `RunStateRecord`, `ModeSwitchEvent`, `ApprovalRecord`, `PlanStep`, `Plan`, `StepContract`, `ExecutionEnvelope`, `StepResult`, `PromptPackage`, `DoctorReport`, `TmpAction`, `ReviewProposal`, `MemoryUpdateProposal`

**`HarnessEvent(BaseModel)` chain** (harness/events.py):
`HarnessEvent` ← `TurnStarted`, `FinalMessage`, `TurnFailed`, `TurnCancelled`, `TurnPaused`, `ModeHandoffAccepted`, `ToolCallExecuted`, `StatusChanged`, `WorkspaceHealthChanged`, `RuntimeStatusChanged`, `ModeActivated`, `ContextReloaded`, `PromptBuilt`, `ChatCreated`, `ChatSelected`, `ChatDeleted`, `ChatHistoryLoaded`, `ChatHistoryCompacted`, `DoctorNarrationReady`, `DoctorApprovalRequested`, `DoctorActionsApplied`, `CommandStarted`, `CommandProgress`, `CommandCompleted`, `RuntimeDelta`, `PlanReady`, `ApprovalRequired`, `ApprovalResolved`, `StepTaskSubmitted`, `StepTaskStatusChanged`, `StepCompleted`, `ArtifactsReady`, `DoctorStarted`, `DoctorFinding`, `DoctorActionProposed`, `DoctorReportReady`

**`AppEvent(BaseModel)` chain** (app/events.py):
`AppEvent` ← `AppTurnStarted`, `AppRuntimeDelta`, `AppFinalMessage`, `AppTurnFailed`, `AppTurnCancelled`, `AppTurnPaused`, `AppModeHandoff`, `AppToolCallExecuted`, `AppStatusChanged`, `AppChatHistoryLoaded`, `AppApprovalRequired`, `AppCommandStarted`, `AppCommandProgress`, `AppCommandCompleted`, `AppDoctorFinding`, `AppDoctorReportReady`, `AppChatHistoryCompacted`, `AppDoctorNarrationReady`, `AppDoctorApprovalRequested`, `AppDoctorActionsApplied`, `AppRaw`

**Exception hierarchies:**
- `HarnessError(Exception)` (harness/exceptions.py) ← `ChatNotFound`, `ChatWorkspaceMismatch`, `ChatActiveDeletionBlocked`, `WorkspaceNotFound`, `RunAlreadyActive`, `WorkspaceSwitchBlocked`
- `ValueError` ← `ToolCallParseError` (runtime/tool_calls), `RuntimeInputError`/`ModelBehaviorError` (runtime/types), `WorkerPolicyError` (worker/policy), `InvalidTransition` (harness/core/state_machine)
- `RuntimeError` ← `TmpCleanupBlocked` (harness/services/doctor)
- `PermissionError` ← `MemoryWriteForbidden` (harness/services/knowledge)

**StrEnum subclasses:**
- `RunState`, `ValidationFailureKind` (harness/control)
- `ValidityState` (harness/core/validity)
- `ExecutionStatus`, `FailureKind` (worker/models)
- `RunState`, `ActiveMode`, `WorkspaceStatus`, `ResultState` (app/tui/models — note: distinct from harness `RunState`)

**`str, Enum`:** `Layer`, `Outcome`, `EventKind` (observability/events)

**Textual `App`/`Screen`/`Widget` subclasses (app/tui):**
- `App[None]` ← `DataHarnessApp` (app/tui/app.py)
- `Screen` ← `ChatManagerScreen`, `CommandPaletteScreen`, `WorkspaceManagerScreen`, `WorkspaceModal` (screens/*) — `ClarificationScreen` removed (now inline `ClarificationBar`)
- `ModalScreen` ← `HelpScreen` (help.py), `JumpOverlay` (jump.py)
- `Static` ← `WorkspaceBar`, `PlanPane`, `StepStatusPane`, `ArtifactsPane`, `ContextMemoryPane`, `DoctorPane`, `FailurePane`, `ProvenancePane`, `StatusPane` (widgets.py — all default to `markup=False`); `UserMessageBlock`, `SystemMessageBlock` (conversation.py — markup=False)
- `VerticalScroll` ← `ConversationPane`, `SidebarPane` (widgets.py)
- `Vertical` ← `PromptBar` (prompt_bar.py); `AssistantMessageBlock` (conversation.py); `WorkspaceSection`, `ChatsSection`, `FilesSection`, `TraceSection`, `CommandsSection`, `DoctorSection`, `FailuresSection` (sidebar_sections.py); `ApprovalBanner`, `ClarificationBar` (widgets.py — inline; replace ApprovalScreen and ClarificationScreen)
- `ModalScreen` ← `FileIngestScreen` (screens/file_ingest.py)
- `Message` ← `ResumeChatRequested`, `InsertMentionRequested` (sidebar_sections.py); `FilePicker.Selected`, `FilePicker.Confirmed`, `FilePicker.Dismissed` (file_picker.py)
- `TextArea` ← `PromptEditor` (prompt_editor.py)
- `Widget` ← `FilePicker` (file_picker.py)
- `Provider` ← `DataHarnessCommandProvider` (commands.py)

**Other:**
- `logging.Filter` ← `TelemetryContextFilter` (observability/logging_setup)
- `Protocol` ← `Runtime` (runtime/protocol), `Helpable` (app/tui/help), `KnowledgeManagerProtocol` (harness/services/knowledge_intents)
- `NamedTuple` ← `FingerprintResult` (harness/core/fingerprints), `JumpInfo` (app/tui/jump)
- frozen `dataclass` ← `RepairResult` (harness/services/repair), `ActiveWorkspace` (harness/core/workspace), `_TaskRecord` (worker/executor)

### Index C — Cross-file Call/Usage Map (selected hot paths)

**`Orchestrator` (harness/orchestrator.py) is the hub:**
- Builds: `ModeRouter` (services/mode_router.py) and `PromptProfileRegistry` (services/prompt_profiles.py) in `__init__` (`self.mode_router`/`self.prompt_profiles`); `ChatStore`, `ChatCompactor`, `RuntimeRequestBuilder` (services/chat.py); `Doctor`, `DoctorRunner` (services/doctor.py); `AnalysisService` (services/analysis.py); `WorkspaceFileService` (services/workspace_files.py); `ContextManager` (services/context.py); `HarnessStateMachine` (core/state_machine.py); `StatusBroker` (status.py); `AsyncWorkspaceManager` (services/workspace.py); `HarnessCommandRegistry` (core/command_registry.py); `HarnessToolRegistry` (tools/registry.py); `HarnessPersistence` (core/persistence.py); optional `KnowledgeManager` (services/knowledge.py)
- Routes internally: `_select_profile(state, *, chat_id, user_input) -> str` calls `mode_router.route()`, keeps the prior non-interaction profile on ambiguous (`interaction`) routing, writes `state.active_agent_mode` IN PLACE on the live `RunStateRecord`, returns the mode; `run_agentic_turn` calls it and loads the package via `prompt_profiles.load(mode)`. `run_agentic_turn` has NO `requested_mode`/`prompt_provider` params; `run_turn` keeps an internal optional `requested_mode: str | None = None` (and `prompt_text`); `resume_with_clarification` carries `active_agent_mode` forward
- Has `tool_registry: HarnessToolRegistry` (initialized in `__init__`); `_register_tools()` wires `file_read` via `make_file_read_handler` (delegating to `WorkspaceFileService`), the `CONTROL_TOOL_NAMES` (`family="control"`) via `make_control_handler`, the model-facing analysis family (`analysis_plan`, `analysis_request_execution`) via `make_analysis_plan_handler` / `make_analysis_request_execution_handler` (delegating to `AnalysisService`), and the model-facing knowledge family (`knowledge_recall`, `knowledge_propose_update`) via `make_knowledge_recall_handler`/`make_knowledge_propose_update_handler`. `_dispatch_tool_call()` resolves handler/validate via `tool_registry` only (no `command_registry` fallback, no legacy `plan_analysis` alias, no special-cased `KNOWLEDGE_INTENTS` bypass), builds `ToolContext(chat_id=<active chat_id>)`, and re-yields handler events
- Has `registry: HarnessCommandRegistry`; `_register_commands()` no longer holds inline descriptors — it lazily imports and delegates to family registrars in `harness.commands.*`: `register_doctor_commands` (doctor), `register_compact_commands` (compact), `register_diagnostics_commands` (help), `register_chat_commands` (create/list/view/resume/delete_chat), `register_workspace_commands` (workspace + list_files/inspect_file/read_file), `register_run_commands` (plan_analysis, request_execution, cancel_run, stop_after_current_step, revise_goal, retry_step, rerun_step, mark_result_trusted/invalidated, challenge_conclusion), `register_memory_commands` (memory_review, recall_knowledge), `register_provenance_commands` (inspect_artifact, provenance_inspect, validity_inspect). Legacy names such as `plan_analysis`, `request_execution`, `workspace_status`, and `workspace_inventory` remain Layer-4/user commands only and are not model-callable tools
- Yields: every `HarnessEvent` subclass from harness/events.py
- Consumed by: `app.session.AppSession` (Layer 4 facade)

**`AppSession` (app/session.py):**
- Thin Layer 4 facade over `Orchestrator` (no `app.agents` import, no `runtime.*` import)
- Calls: `to_app_event()`; forwards `run_agentic_turn`, `handle_direct_command` (pure passthrough), `handle_doctor_approval`, and the other orchestrator methods, mapping `HarnessEvent` → `AppEvent`
- Does NOT route intents or select prompts (Layer 3 owns that); doctor narration/approval events now originate in Layer 3 `DoctorRunner`, not `AppSession`
- Used by: `DataHarnessApp` (app/tui/app.py) — instantiated in `cli.build_app`

**`build_orchestrator` (harness/core/factory.py)** is the only entry point that wires Layer 3 dependencies; called by `cli.build_app`.

**`LlamaCppRuntime.stream` (runtime/llama_cpp_runtime.py)** uses:
- `SyncToAsyncBridge` (runtime/bridge.py) to wrap blocking llama iterator
- `parse_tool_call_block` / `repair_tool_call_block` / `extract_fenced_code` (runtime/tool_calls.py) for tool extraction
- Telemetry emit via `observability.Telemetry`
- Implements `runtime.protocol.Runtime` (structural protocol)

**`PythonStepExecutor.submit` (worker/executor.py):**
- Calls `WorkerPolicyValidator` (worker/policy.py) before subprocess spawn
- Spawns `python -m worker.sandbox_bootstrap` subprocess
- Path utilities: `build_step_tmp_dir`, `as_posix_workspace_relative` (worker/paths.py)
- Used by `Orchestrator.resume_approved_step` (when wired) — currently invoked indirectly through code execution flow

**`Doctor.run` / `DoctorRunner.run` (harness/services/doctor.py):**
- Uses `lazy_fingerprint` (harness/core/fingerprints.py) → returns `FingerprintResult`
- Uses `classify` + `ValidityState` (harness/core/validity.py)
- Persists via `HarnessPersistence` (harness/core/persistence.py)
- `DoctorRunner` emits deterministic source/tmp/pending-plan checks in `light/full` modes and runtime-backed semantic memory/script checks in `semantic/full` modes.
- Workspace activation runs a light doctor pass; successful worker completion schedules a semantic doctor pass.

**`KnowledgeManager.propose_update` (harness/services/knowledge.py):**
- Returns `MemoryUpdateProposal` (harness/control.py)
- `guarded_external_memory_write` enforces single-writer rule (always raises elsewhere)
- Called from `harness.services.knowledge_intents.handle_knowledge_intent`
- Also owns direct memory writes for doctor/knowledge workflows: notes, gaps, functions, preferences, and turn-id dedup metadata.

**`ChatStore` (harness/services/chat.py):**
- `cascade_delete_for_workspace` invoked by `AsyncWorkspaceManager.delete_workspace`
- `RuntimeRequestBuilder.build_messages` consumes `ChatRecord` → emits `RuntimeMessage` list (runtime/types) for `Runtime.stream`
- `ChatCompactor.compact` driven by `Orchestrator.compact_chat_history` and token-pressure auto-compaction inside `run_turn`

**`Telemetry.emit` (observability/telemetry.py)** is called from: `LlamaCppRuntime`, `PythonStepExecutor`, `HarnessPersistence` (save_dict), `ModeRouter` (route decision telemetry at `Layer.HARNESS`), `DataHarnessApp._emit`, and CLI bootstrap.

**Event flow user → screen:**
```
user keystroke
  → PromptBar.on_input_submitted
  → DataHarnessApp.submit_user_text
  → DataHarnessApp._stream_turn
  → AppSession.run_user_turn
  → Orchestrator.run_agentic_turn
  → Orchestrator._select_profile (ModeRouter.route + continuity + write-back) + prompt_profiles.load
  → Orchestrator.run_turn
  → RuntimeRequestBuilder.build_messages
  → LlamaCppRuntime.stream (yields RuntimeEvent)
  → Orchestrator yields HarnessEvent (TurnStarted, RuntimeDelta, FinalMessage, ...)
  → to_app_event → AppEvent
  → EventConsumer.dispatch → DataHarnessApp._handle_*
  → ConversationPane / SidebarPane / WorkspaceBar updates
```

**Event flow slash command → harness:**
```
slash text or palette selection
  → DataHarnessApp.submit_user_text / handle_command_palette_selection
  → DataHarnessApp._stream_command
  → DataHarnessApp._resolve_active_chat_id (for /compact when active chat was not hydrated)
  → AppSession.handle_direct_command
  → Orchestrator.handle_direct_command
  → EventConsumer.dispatch → DataHarnessApp._handle_command_* / command-specific handlers
  → `/create_chat` success calls DataHarnessApp.activate_chat to select the new empty chat and refresh chat resources
```

### Index D — Symbol Definition Index (where to find a name)

| Symbol | Defined in |
|--------|-----------|
| `Orchestrator` | `src/harness/orchestrator.py` |
| `AppSession` | `src/app/session.py` |
| `DataHarnessApp` | `src/app/tui/app.py` |
| `LlamaCppRuntime` | `src/runtime/llama_cpp_runtime.py` |
| `PythonStepExecutor` | `src/worker/executor.py` |
| `WorkerPolicyValidator` | `src/worker/policy.py` |
| `Doctor` / `DoctorRunner` | `src/harness/services/doctor.py` |
| `AnalysisService` | `src/harness/services/analysis.py` |
| `WorkspaceFileService` | `src/harness/services/workspace_files.py` |
| `ChatStore` / `ChatCompactor` / `RuntimeRequestBuilder` | `src/harness/services/chat.py` |
| `KnowledgeManager` | `src/harness/services/knowledge.py` |
| `WorkspaceManager` (sync) / `bootstrap_workspace` | `src/harness/core/workspace.py` |
| `AsyncWorkspaceManager` | `src/harness/services/workspace.py` (ex-`workspace_async`, renamed) |
| `WorkspaceFileService` | `src/harness/services/workspace_files.py` |
| `ModeRouter` / `ProfileDecision` | `src/harness/services/mode_router.py` |
| `PromptProfileRegistry` / `PromptPackage` / `MODE_TOOL_NAMES` / `_tool_catalog` | `src/harness/services/prompt_profiles.py` |
| `AppStore` | `src/harness/core/app_store.py` |
| `HarnessStateMachine` | `src/harness/core/state_machine.py` |
| `HarnessCommandRegistry` | `src/harness/core/command_registry.py` |
| `HarnessToolRegistry` | `src/harness/tools/registry.py` |
| `ToolContext` | `src/harness/tools/registry.py` |
| `ToolArgSpec` | `src/harness/tools/registry.py` |
| `ToolDescriptor` | `src/harness/tools/registry.py` |
| `make_file_read_handler` | `src/harness/tools/file.py` |
| `make_control_handler` | `src/harness/tools/control.py` |
| `CONTROL_TOOL_NAMES` | `src/harness/tools/control.py` |
| `make_analysis_plan_handler` | `src/harness/tools/analysis.py` |
| `make_analysis_request_execution_handler` | `src/harness/tools/analysis.py` |
| `make_knowledge_recall_handler` | `src/harness/tools/knowledge.py` |
| `make_knowledge_propose_update_handler` | `src/harness/tools/knowledge.py` |
| `register_chat_commands` | `src/harness/commands/chat.py` |
| `register_compact_commands` | `src/harness/commands/compact.py` |
| `register_diagnostics_commands` | `src/harness/commands/diagnostics.py` |
| `register_doctor_commands` | `src/harness/commands/doctor.py` |
| `register_memory_commands` | `src/harness/commands/memory.py` |
| `register_provenance_commands` | `src/harness/commands/provenance.py` |
| `register_run_commands` | `src/harness/commands/run.py` |
| `register_workspace_commands` | `src/harness/commands/workspace.py` |
| `HarnessPersistence` | `src/harness/core/persistence.py` |
| `WorkspaceDb` | `src/harness/core/db.py` |
| `StatusBroker` / `HarnessStatusSnapshot` | `src/harness/status.py` |
| `Telemetry` | `src/observability/telemetry.py` |
| `TelemetryEvent` / `Layer` / `Outcome` / `EventKind` | `src/observability/events.py` |
| `RuntimeRequest` / `RuntimeEvent` / `RuntimeMessage` / `TokenPressure` | `src/runtime/types.py` |
| `RuntimeConfig` | `src/runtime/config.py` |
| `Runtime` (protocol) | `src/runtime/protocol.py` |
| `SyncToAsyncBridge` | `src/runtime/bridge.py` |
| `parse_tool_call_block` / `repair_tool_call_block` | `src/runtime/tool_calls.py` |
| `StepExecutionRequest` / `StepExecutionEnvelope` / `ExecutionEnvelope` | `src/worker/models.py` |
| `PermissionEnvelope` / `ResourceLimits` | `src/worker/models.py` |
| `handle_knowledge_intent` / `KnowledgeManagerProtocol` | `src/harness/services/knowledge_intents.py` |
| `to_app_event` | `src/app/event_mapping.py` |
| `EventConsumer` | `src/app/tui/event_consumer.py` |
| `ClipboardProvider` / `NativeClipboard` | `src/app/tui/clipboard.py` |
| `ConversationPane` / `SidebarPane` / `WorkspaceBar` (+ panes) | `src/app/tui/widgets.py` |
| `PromptBar` | `src/app/tui/prompt_bar.py` |
| `PromptEditor` | `src/app/tui/prompt_editor.py` |
| `FilePicker` (with multiselect/Confirmed/Dismissed/update_root/focus_picker/dismiss_picker) / `WorkspaceFileIndex` / `WorkspaceFileEntry` | `src/app/tui/file_picker.py` |
| `format_file_mention` / `filter_file_entries` | `src/app/tui/file_picker.py` |
| `FileIngestScreen` | `src/app/tui/screens/file_ingest.py` |
| `WorkspaceSection` / `ChatsSection` / `FilesSection` / `TraceSection` / `CommandsSection` / `DoctorSection` / `FailuresSection` / `ResumeChatRequested` / `InsertMentionRequested` | `src/app/tui/sidebar_sections.py` |
| `SidebarState` | `src/app/tui/sidebar.py` |
| `UserMessageBlock` / `AssistantMessageBlock` / `SystemMessageBlock` | `src/app/tui/conversation.py` |
| `ApprovalBanner` | `src/app/tui/widgets.py` (replaces former `ApprovalScreen`) |
| `ClarificationBar` | `src/app/tui/widgets.py` (replaces former `ClarificationScreen`) |
| `WorkspaceManagerScreen` | `src/app/tui/screens/workspace_manager.py` |
| `HelpScreen` | `src/app/tui/help.py` |
| `Jumper` / `JumpOverlay` | `src/app/tui/jump.py` |
| `RunTrace` | `src/app/tui/run_trace.py` |
| `DataHarnessCommandProvider` / `build_command_prefill` | `src/app/tui/commands.py` |
| `build_orchestrator` | `src/harness/core/factory.py` |
| `_dispatch_private_module` / `build_app` / `main` | `src/cli.py` |
| `lazy_fingerprint` / `sha256_file` | `src/harness/core/fingerprints.py` |
| `classify` / `ValidityState` | `src/harness/core/validity.py` |
| `ContextManager` | `src/harness/services/context.py` |
| `try_deterministic_repair` / `RepairResult` | `src/harness/services/repair.py` |
| `ProvenanceRecord` / `ClaimChecker` / `reuse_allowed_for_source` | `src/harness/services/provenance.py` |
| `TimedDecisionGate` | `src/harness/core/approval.py` |
| `HarnessPromptRegistry` | `src/harness/core/prompt_registry.py` |
| `parse_slash` | `src/harness/core/command_registry.py` |
| `AppPaths` / `WorkspacePaths` | `src/harness/core/paths.py` |
| `AnalysisFlow` / `AnalysisPhase` | `src/harness/core/analysis_flow.py` |
| `redact_payload` | `src/observability/redaction.py` |
| `configure_logging` / `TelemetryContextFilter` | `src/observability/logging_setup.py` |
| `resolve_app_root` / `resolve_log_dir` / `resolve_telemetry_dir` | `src/observability/runtime_paths.py` |
| `current_boot_id` / `current_session_id` / `current_turn_id` / `current_step_id` | `src/observability/telemetry.py` |
| `bind_boot` / `bind_session` / `bind_turn` / `bind_step` | `src/observability/telemetry.py` |
| `build_step_tmp_dir` / `to_workspace_relative` / `as_posix_workspace_relative` | `src/worker/paths.py` |
| sandbox subprocess entry `main` | `src/worker/sandbox_bootstrap.py` |

---

## Per-file Inventory

> Format: each file lists internal `src/` imports, defined symbols (class/func/var with one-line description and inheritance), internal calls, and usage notes. Stdlib/third-party imports are omitted intentionally. Inheritance shown as `Name(Base)`.

---

## `src/cli.py`

### `src/cli.py`
**Imports (internal only — from same repo `src/`):**
- (re-exports/uses harness, observability; no `app.*` imports)
**Defines:**
- **var** `_PRIVATE_MODULE_TARGETS` — private module targets accepted by the packaged CLI dispatch path
- **func** `_default_runtime_factory(config, telemetry) -> LlamaCppRuntime` — creates LlamaCppRuntime
- **func** `build_app(telemetry, *, workspace_id, app_root, runtime_factory, runtime) -> DataHarnessApp` — constructs app: session + state + telemetry + optional runtime
- **func** `_parse_argv(argv) -> argparse.Namespace` — CLI parser (workspace, app-root flags)
- **func** `_dispatch_private_module(argv) -> int | None` — handles packaged private `-m worker.sandbox_bootstrap <config>` before TUI startup
- **func** `main() -> None` — entry: private worker dispatch if requested, else parse → configure logging+telemetry → build → run app
**Internal calls:**
- `harness.factory.build_orchestrator` (wires Layer 3)
- `runtime.llama_cpp_runtime.LlamaCppRuntime(config, telemetry)`
- `worker.sandbox_bootstrap.main()` (private packaged worker subprocess path)
- `app.tui.app.DataHarnessApp(...)`
- `observability.configure_logging`, `Telemetry`, `bind_boot`, `bind_session`
**Notes:**
- Sole place where `runtime_factory` is constructed; passed into `build_orchestrator`
- Bootstrap telemetry events emitted before app is built
- Packaged worker subprocesses call `dataharness -m worker.sandbox_bootstrap <config>`; `_dispatch_private_module` must handle this before argparse/TUI construction

---

## `src/app/`

### `src/app/__init__.py`
Module marker only.

### `src/app/events.py`
**Imports:** none
**Defines:**
- **class** `AppEvent(BaseModel)` — base; `app_event_id`, `event_name`, `ts`, `workspace_id`, `chat_id`, `run_id`
- **class** `AppTurnStarted(AppEvent)` — turn start with `turn_id`, `user_message_id`, `active_mode`
- **class** `AppRuntimeDelta(AppEvent)` — streaming delta (text/reasoning/tool_call)
- **class** `AppFinalMessage(AppEvent)` — final assistant message + usage
- **class** `AppTurnFailed(AppEvent)` — turn failure (summary, error_code)
- **class** `AppTurnCancelled(AppEvent)` — turn cancellation w/ reason
- **class** `AppTurnPaused(AppEvent)` — turn paused for tool dispatch or clarification
- **class** `AppModeHandoff(AppEvent)` — agentic mode handoff notification
- **class** `AppToolCallExecuted(AppEvent)` — harness tool-call result summary
- **class** `AppStatusChanged(AppEvent)` — workspace status snapshot
- **class** `AppChatHistoryLoaded(AppEvent)` — chat load (`message_count`, `token_estimate`)
- **class** `AppApprovalRequired(AppEvent)` — approval request payload
- **class** `AppCommandStarted/Progress/Completed(AppEvent)` — command lifecycle
- **class** `AppDoctorFinding/ReportReady(AppEvent)` — doctor results; report carries `summary_counts`, `recommendations`, and `action_records`
- **class** `AppChatHistoryCompacted(AppEvent)` — compaction result
- **class** `AppDoctorNarrationReady/AppDoctorApprovalRequested/AppDoctorActionsApplied(AppEvent)` — interactive doctor cleanup flow
- **class** `AppRaw(AppEvent)` — fallback for unmapped harness events
**Notes:**
- All Pydantic; `event_name` discriminator for routing in `EventConsumer`

### `src/app/event_mapping.py`
**Imports:** `app.events.*`
**Defines:**
- **func** `to_app_event(ev: HarnessEvent) -> AppEvent` — isinstance-dispatch mapping; preserves `ts`/`workspace_id`/`chat_id`/`run_id`
**Internal calls:** instantiates every `App*` class in `app.events`, including doctor `action_records`
**Notes:**
- Single boundary converting harness → app events; called inside `AppSession.run_user_turn`

### `src/app/session.py`
**Imports:**
- `app.event_mapping.to_app_event`, `app.events.AppEvent`
- `harness.core.command_registry.{CommandContext, HarnessCommandDescriptor, HelpResult}`
- `harness.control.RunStateRecord`, `harness.exceptions.RunAlreadyActive`
- `harness.orchestrator.Orchestrator`, `harness.status.HarnessStatusSnapshot`
- `observability.{Telemetry, bind_turn, resolve_telemetry_dir}`, `observability.events.{EventKind, Layer}`
- (no `app.agents` import — package deleted; no `runtime.*` import)
**Defines:**
- **class** `AppSession` — thin Layer 4 async-only facade over `Orchestrator`
  - `__init__(*, orchestrator=None, telemetry=None, app_root=None)` — no `mode_router`/`prompt_registry` params (routing/prompts are Layer 3)
  - `run_user_turn(*, state, workspace_dir, chat_id, user_text)` — async iter `AppEvent`; sets `_active` gate, calls `orchestrator.run_agentic_turn(state, workspace_dir=, chat_id=, user_input=)` (no requested_mode/prompt_provider), maps events
  - `resume_approved_step(...)`, `resume_with_clarification(...)` — forward to orchestrator
  - `handle_direct_command(state, *, command, arguments)` — PURE passthrough to `orchestrator.handle_direct_command` + event map (no doctor narration wrapping)
  - `handle_doctor_approval(*, state, workspace_dir, report_id, decision, action_ids=None)` — forwards to `orchestrator.apply_doctor_actions`
  - `cancel_run` / `compact_chat_history`
  - `list_commands` / `help` / `list_chats` / `create_chat` / `view_chat` / `resume_chat` / `delete_chat`
  - `list_workspaces` / `create_workspace` / `rename_workspace` / `delete_workspace` / `activate_workspace` / `ingest_files`
  - `status_snapshot` / `watch_status`
- **var** `DataAnalysisAppSession = AppSession` — back-compat alias
**Internal calls:**
- `to_app_event`; `Orchestrator.*` (delegates all ops); `Orchestrator.run_agentic_turn`, `Orchestrator.apply_doctor_actions`
**Notes:**
- `_active` flag prevents concurrent runs at the session level (orchestrator also enforces). No routing, no prompt selection, no doctor narration here — all moved to Layer 3.

(There is no `src/app/agents/` package. Routing is `harness.services.mode_router.ModeRouter`; prompt assembly is `harness.services.prompt_profiles.PromptProfileRegistry`. The former `AgentModeRouter`/`PromptPackageRegistry`/`AnalystMode`/`KnowledgeMode`/`InteractionMode` and `app.agents.types.PromptPackage` no longer exist.)

### `src/harness/services/knowledge_intents.py`
**Defines:**
- **class** `KnowledgeManagerProtocol(Protocol)` — `propose_update(...)`
- **func** `_slug(text) -> str` — kebab-case slug
- **func** `handle_knowledge_intent(manager, tool_call) -> Any` — dispatch by intent → `manager.propose_update(...)` with target `memory/notes/{slug}.md`, `memory/preferences.json`, or `memory/functions/{slug}.py`
**Notes:** imported only by `harness.tools.knowledge` (knowledge writes flow through the `knowledge_propose_update` tool handler)

### `src/harness/services/mode_router.py`
**Imports:** `observability.{Telemetry, ...}`, `observability.events.{EventKind, Layer}`
**Defines:**
- **class** `ProfileDecision(BaseModel)` — `mode: str`, `reason: str`
- **class** `ModeRouter` — keyword/LLM-fallback intent classifier
  - `request_mode(user_text) -> ProfileDecision` — stable alias delegating to `route()`
  - `route(user_text) -> ProfileDecision` — normalize/tokenize, match knowledge/analysis terms, optional cached LLM classifier, default `interaction`/`front_door_default`; emits telemetry at `Layer.HARNESS`
**Notes:** Layer 3 service; built by `Orchestrator.__init__` as `self.mode_router`. Re-exported from `harness.services`.

### `src/harness/services/prompt_profiles.py`
**Imports:** `harness.tools.registry.HarnessToolRegistry`
**Defines:**
- **class** `PromptPackage(BaseModel)` — `mode`, `template_version`, `prompt_text`, `package_hash` (inline model; distinct from `harness/control.py` `PromptPackage(HarnessRecord)`)
- **var** `MODE_TOOL_NAMES` — dict `mode → model-facing tool names`
- **func** `_tool_catalog(mode, tool_registry) -> str` — markdown tool catalog for the mode
- **class** `PromptProfileRegistry`
  - `load(mode) -> PromptPackage` — assembles `system.md` + persona + tool catalog + `response_format.md` from `src/harness/prompts/`, `template_version="v1"`, sha256 `package_hash`
**Notes:** Layer 3 service; built by `Orchestrator.__init__` as `self.prompt_profiles`. Re-exported from `harness.services`. Persona/operational prompts: `src/harness/prompts/{system,interaction,analyst,knowledge,clarification,response_format,doctor_narrator,compaction,doctor,knowledge_reconcile}.md`.

### `src/app/tui/__init__.py`
Marker.

### `src/app/tui/app.py`
**Imports:**
- `app.session.AppSession`
- `app.tui.clipboard.ClipboardProvider, NativeClipboard`
- `app.tui.commands.DataHarnessCommandProvider, build_command_prefill`
- `app.tui.event_consumer.EventConsumer`
- `app.tui.file_picker.FilePicker, WorkspaceFileIndex, format_file_mention`
- `app.tui.help.HelpScreen`
- `app.tui.jump.Jumper, JumpOverlay`
- `app.tui.prompt_bar.PromptBar`
- `app.tui.prompt_editor.PromptEditor`
- `app.tui.run_trace.RunTrace`
- `app.tui.screens.file_ingest.FileIngestScreen`
- `app.tui.screens.workspace_manager.WorkspaceManagerScreen`
- `app.tui.sidebar_sections.ResumeChatRequested, InsertMentionRequested`
- `app.tui.widgets.ApprovalBanner, ClarificationBar, ConversationPane, SidebarPane, WorkspaceBar`
**Defines:**
- **func** `_parse_yes(value) -> bool` — helper for doctor confirmation text
- **var** `DataAnalysisAppSession = AppSession` (alias)
- **class** `DataHarnessApp(App[None])` — main Textual app; layout, event dispatch, input
  - properties: `session`, `state`, `_approval_banner`, `active_chat_id`, `workspace_dir`
  - `_emit`, `_emit_error` — telemetry helpers
  - `compose_ids`, `compose`, `on_mount`, `_subscribe_status`
  - `_ensure_chat`, `_resolve_active_chat_id`, `submit_user_text`
  - `_stream_turn(text)` — calls `session.run_user_turn`
  - `_stream_command(command, arguments)` — resolves `/compact` active chat when needed, then calls `session.handle_direct_command`
  - `_build_consumer() -> EventConsumer`
  - `_handle_*` — turn_started/runtime_delta/final_message/turn_failed/turn_cancelled/command_*/doctor_*/status_changed
  - `_handle_doctor_report_ready`, `_handle_doctor_narration_ready`, `_handle_doctor_approval_requested`, `_handle_doctor_actions_applied`
  - `_on_doctor_accept_all`, `_on_doctor_apply_selected`, `_on_doctor_reject_all` — schedule doctor action application through Textual workers
  - `_refresh_trace_widgets`
  - `activate_chat(chat_id)` — sets active chat, rehydrates/clears transcript for that record, refreshes trace and sidebar resources
  - `apply_workspace_snapshot(snapshot)`
  - `_args_to_dict(spec, positional)`
  - `handle_command_palette_selection(descriptor)`
  - `on_input_submitted(event)` — preserved for non-prompt `Input` widgets
  - `on_prompt_editor_submitted(PromptEditor.Submitted)` — primary prompt submit handler
  - `_refresh_sidebar_resources()` — async; refreshes sidebar files/chats from `WorkspaceFileIndex` + chat store
  - `action_resume_chat`, `action_open_workspaces`, `action_open_files`, `action_upload_files`, `action_toggle_jump_mode`, `action_help`
  - `action_copy_text`, `action_paste_text`, `_copyable_text` — copy selected/focused conversation text via native clipboard + Textual fallback; paste native/Textual clipboard into prompt
  - `_insert_mention_into_editor(path)` — inserts formatted `@file` mention and restores editor focus
  - `handle_approval_decision(plan, step_contract, decision)` → `_stream_resume_approved`
  - `_stream_doctor_approval(report_id, decision, action_ids=None)` → `session.handle_doctor_approval`
  - `handle_clarification_response(text)` → `_stream_clarification`
**Internal calls:** `AppSession`, all imports above
**Notes:**
- `_subscribe_status` runs as background worker (Textual) — subscribes to orchestrator status broker
- `_trace: RunTrace` ring-buffers phase lines for `WorkspaceBar` + `SidebarPane`
- Approval/clarification/doctor action review are inline banner flows, not full-screen modals

### `src/app/tui/clipboard.py`
**Defines:**
- **protocol** `ClipboardProvider` — Layer 4 copy/paste interface used by TUI app actions
- **class** `NativeClipboard` — best-effort terminal OS clipboard provider:
  - macOS: `pbcopy` / `pbpaste`
  - Windows: PowerShell `Set-Clipboard` / `Get-Clipboard -Raw`, with `clip` copy fallback
  - Linux/Unix: `wl-copy` / `wl-paste`, then `xclip`, then `xsel`
  - `copy(text) -> bool`, `paste() -> str | None`; returns fallback signals on missing commands/timeouts/errors
**Notes:** Layer 4 only; app code still keeps Textual local clipboard/OSC52 fallback for unsupported terminals.

### `src/app/tui/models.py`
**Defines:**
- **class** `RunState(StrEnum)` — idle, running, stopping, error
- **class** `ActiveMode(StrEnum)` — interaction, analyst, knowledge
- **class** `WorkspaceStatus(StrEnum)` — ready, busy, degraded
- **class** `ResultState(StrEnum)` — trusted, invalidated, challenged, pending
- **class** `WorkspaceView(BaseModel)` — `workspace_id`, `run_state`, `active_mode`
- **class** `AppView(BaseModel)` — full snapshot incl. `available_workspaces/commands`, `doctor_warning_count`
**Notes:** distinct `RunState` from `harness.control.RunState`; mostly view models, currently lightly wired

### `src/app/tui/commands.py`
**Defines:**
- **func** `build_command_context(app) -> CommandContext` — extracts ws/chat/run + flags
- **func** `command_title(descriptor) -> str` — formats title incl. availability
- **func** `build_command_prefill(descriptor) -> str` — slash syntax + arg placeholders
- **const** `EXIT_DESCRIPTOR: HarnessCommandDescriptor` — synthetic Layer-4 `/exit` palette entry
- **class** `DataHarnessCommandProvider(Provider)` — Textual command palette
  - `_descriptors()`, `_callback_for(descriptor)`, `discover() -> Hits`, `search(query) -> Hits`
**Internal calls:** routes to `app.handle_command_palette_selection`

### `src/app/tui/conversation.py`
**Imports:** `textual.app.ComposeResult`, `textual.containers.Vertical`, `textual.widgets.{Markdown, Static}`
**Defines:**
- **func** `_clean(text)` — strips tool/draft follow-up noise and applies Layer-4 presentation formatting
- **func** `_format_tabular_fences(text)` / `_markdown_table_from_delimited(...)` — render CSV/TSV code fences as markdown tables for display only
- **class** `UserMessageBlock(Static)` — single-message block; CSS class `message-user`
  - `__init__(text)`, `text_buffer()`
- **class** `AssistantMessageBlock(Vertical)` — Markdown-rendered assistant block; CSS class `message-assistant`
  - `__init__(text="")`, `compose()`, `update_text(text)`, `append_delta(text)`, `text_buffer()`
- **class** `SystemMessageBlock(Static)` — system/notice block; CSS class `message-system`
  - `__init__(text)`, `text_buffer()`
**Notes:** consumed by `widgets.ConversationPane` for transcript rendering

### `src/app/tui/event_consumer.py`
**Imports:** `app.events.AppEvent`
**Defines:**
- **type** `Handler = Callable[[AppEvent], None]`
- **class** `EventConsumer`
  - `__init__(handlers: dict[str, Handler])`
  - `dispatch(event)` — lookup by `event.event_name`
**Notes:** thin router; handler map built in `DataHarnessApp._build_consumer`

### `src/app/tui/file_picker.py`
**Imports:** `textual.{events, on}`, `textual.app.ComposeResult`, `textual.containers.Vertical`, `textual.message.Message`, `textual.widget.Widget`, `textual.widgets.{OptionList, Static, Tree}`, `textual.widgets.option_list.Option`
**Defines:**
- **const** `SKIPPED_DIRS: set[str]` — `.git`, `.venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `logs`, `tmp`
- **class** `WorkspaceFileEntry` (frozen dataclass) — `path`, `is_dir`
- **func** `format_file_mention(path) -> str` — escapes whitespace into `@"..."` form
- **func** `filter_file_entries(entries, query, *, limit=30) -> list[WorkspaceFileEntry]` — fuzzy subsequence rank
- **class** `WorkspaceFileIndex` — cached recursive scan (default `max_entries=5000`)
  - `__init__(workspace_dir, *, max_entries=5000)`, `invalidate()`, `scan()`
- **class** `FilePicker(Widget)` — fuzzy + tree dual-mode picker; emits `Selected(path)`, `Confirmed(paths)`, `Dismissed`
  - inner **class** `Selected(Message)` — `path`
  - inner **class** `Confirmed(Message)` — `paths: list[str]`
  - inner **class** `Dismissed(Message)`
  - `__init__(workspace_dir=None, *, root=None, allow_multiselect=False, mode_default="fuzzy")`
  - `compose()`, `on_mount()`, `refresh_query(query)`, `toggle_mode()`, `focus_picker()`, `dismiss_picker()`, `update_root(new_root)`
  - `_render_modes`, `_label_for`, `_build_tree(entries)`, `_highlighted_path`, `_toggle_selected`, `_select_current`
  - `on_key(event)`, `on_option_selected(event)`
**Notes:** Tab toggles fuzzy/tree; Enter posts `Selected` (or `Confirmed` if multiselect with staged items); Space toggles selection in multiselect; Escape dismisses; tree mode builds a true hierarchy via `_build_tree`

### `src/app/tui/help.py`
**Defines:**
- **class** `HelpData` (frozen dataclass) — `title`, `description`
- **class** `Helpable(Protocol)` — `help: HelpData`
- **class** `HelpScreen(ModalScreen[None])`
  - `__init__(widget)`, `compose`, `action_close`
  - `text_buffer` (test hook), `_build_text(widget)`, `_find_help_source(widget)`, `_format_bindings(widget)`

### `src/app/tui/jump.py`
**Defines:**
- **class** `JumpInfo(NamedTuple)` — `key`, `widget`
- **class** `Jumper`
  - `__init__(ids_to_keys, screen)`
  - `get_overlays() -> dict[Offset, JumpInfo]`
- **class** `JumpOverlay(ModalScreen[str | Widget | None])`
  - `compose`, `on_key`, `action_dismiss_overlay`

### `src/app/tui/screens.py` and `src/app/tui/screens/__init__.py`
**Defines:** (empty — placeholder for backward import compatibility)
**Notes:** `ApprovalScreen` and `ClarificationScreen` removed; both are now inline widgets (`ApprovalBanner`, `ClarificationBar`) in `widgets.py`. Approval decision strings unchanged: approve→approved, reject→rejected, revise→revise_requested.

### `src/app/tui/widgets.py`
**Imports:** `app.tui.help.HelpData`, `app.tui.conversation.{AssistantMessageBlock, SystemMessageBlock, UserMessageBlock}`, `app.tui.sidebar.SidebarState`, `app.tui.sidebar_sections.*`
**Defines:**
- **class** `WorkspaceBar(Static)` — header strip; `update_from(...)`
- **class** `ConversationPane(VerticalScroll)` — transcript + streaming buffer
  - `append_user/append_assistant/append_assistant_delta/finalize_assistant/discard_streaming/text_buffer/rehydrate_from_record/_refresh_text`; `append_assistant_delta` appends text deltas only and drops reasoning/tool-call deltas from the transcript
- **class** `SidebarPane(VerticalScroll)` — composes per-section widgets (Workspace/Chats/Files/Trace/Commands/Doctor/Failures); routes update calls to children + `SidebarState`; aggregates `text_buffer` from `SidebarState`
  - `compose`, `update_status`, `update_files(files)`, `update_chats(chats)` (accepts `list[str]` or `list[ChatSummary]`), `command_started/progress/completed`, `append_doctor_finding`, `doctor_report`, `failure`, `update_trace`, `text_buffer`, `_brief_result`
- **class** `PlanPane(Static)` — `render_plan(plan)`
- **class** `StepStatusPane(Static)` — `render_contract(contract, requires_approval)`
- **class** `ArtifactsPane(Static)` — `render_refs(refs)`
- **class** `ContextMemoryPane(Static)` — `render_summary(prefs, notes_count, doctor_warnings)`
- **class** `DoctorPane(Static)` — `render_doctor`, `append_finding`, `render_report`
- **class** `FailurePane(Static)` — `render_failure(failure)`
- **class** `ProvenancePane(Static)` — `render_lineage(refs)`
- **class** `StatusPane(Static)` — `append_events(events)`
- **class** `ApprovalBanner(Vertical)` — inline approval banner; `show(plan, step_contract)`/`hide()`; keys `a`/`r`/`v` and buttons emit `ApprovalBanner.ApprovalDecisionMade(plan, step_contract, decision)`; also renders doctor action review via `show_doctor_review(report_id, actions, findings)` and `get_doctor_decisions()` inside a dedicated doctor container; normal approval keybindings are ignored in doctor mode; replaces the removed `ApprovalScreen`
- **class** `ClarificationBar(Vertical)` — inline clarification bar; `show(question)`/`hide()`; Input + Submit/Dismiss buttons; emits `ClarificationBar.ClarificationSubmitted(text)` on Enter or Submit; `ClarificationBar.ClarificationDismissed` on escape or Dismiss; replaces the removed `ClarificationScreen`
**Notes:** active widgets: `ConversationPane`, `SidebarPane`, `WorkspaceBar`. Other panes available for alternate layouts.

### `src/app/tui/run_trace.py`
**Defines:**
- **class** `RunTrace` — ring buffer (default 20)
  - `lines`, `current_phase`
  - `command_started/progress/completed`, `turn_started`, `runtime_delta`, `final_message`, `cancelled`, `failed`
**Notes:** used by `DataHarnessApp` to drive `WorkspaceBar` + `SidebarPane`

### `src/app/tui/sidebar.py`
**Defines:**
- **class** `SidebarState` — sidebar model: workspace/run/runtime + files, chats (str + summaries), trace, commands, doctor, failure
  - `__init__()` — defaults; ring buffers (`trace` 20, `commands` 12, `doctor` 8); `chat_summaries: list`
  - `update_status(*, workspace_id, run_state, active_mode, runtime_status, chat_id=None)`
  - `set_files(files)` (capped 12), `set_chats(chats)` (capped 8), `set_chat_summaries(summaries)` (derives `chats` strings)
  - `update_trace(lines)`, `command_started(command)`, `command_progress(...)`, `command_completed(text)`
  - `append_doctor(text)`, `set_failure(summary, error_code)`
  - `text_buffer()` — multi-section snapshot (WORKSPACE/CHAT/FILES/TRACE/COMMANDS/DOCTOR/FAILURES)
**Notes:** consumed by `widgets.SidebarPane` for aggregated `text_buffer()`

### `src/app/tui/sidebar_sections.py`
**Imports:** `textual.on`, `textual.app.ComposeResult`, `textual.containers.Vertical`, `textual.message.Message`, `textual.widgets.{OptionList, Static}`, `textual.widgets.option_list.Option`
**Defines:**
- **class** `ResumeChatRequested(Message)` — `chat_id`
- **class** `InsertMentionRequested(Message)` — `path`
- **class** `WorkspaceSection(Vertical)` — heading + `update_status(...)`, `text_buffer()`
- **class** `ChatsSection(Vertical)` — heading + `OptionList`; `update_chats(summaries)`, `set_active_chat(id)`; selecting an option posts `ResumeChatRequested`
- **class** `FilesSection(Vertical)` — heading + `OptionList`; `update_files(files)`; selecting an option posts `InsertMentionRequested`
- **class** `_DequeSection(Vertical)` — bounded ring buffer body
- **class** `TraceSection(_DequeSection)`, `CommandsSection(_DequeSection)`, `DoctorSection(_DequeSection)`
- **class** `FailuresSection(Vertical)` — `set_failure(summary, error_code)`, `text_buffer()`
**Notes:** All sections expose `text_buffer()` for diagnostics; SidebarPane keeps `SidebarState` updated and aggregates via `state.text_buffer()`.

### `src/app/tui/screens/file_ingest.py`
**Imports:** `textual.on`, `textual.binding.Binding`, `textual.containers.Vertical`, `textual.screen.ModalScreen`, `textual.widgets.{Footer, Static}`, `app.tui.file_picker.FilePicker`
**Defines:**
- **class** `FileIngestScreen(ModalScreen)`
  - `__init__(*, session, workspace_id, initial_root=None)`
  - `compose()` — yields header / `FilePicker(root=..., allow_multiselect=True)` / staged Static / `Footer`
  - `action_dismiss_screen`, `action_change_root` (toggles between cwd/home for V1)
  - `_on_single_selected(FilePicker.Selected)` — updates staged display
  - `_on_confirmed(FilePicker.Confirmed)` — calls `session.ingest_files` and dismisses with result
**Notes:** Layer 4-only; Layer 3 owns copy + registration via `AppSession.ingest_files`.

### `src/app/tui/prompt_bar.py`
**Imports:** `app.tui.file_picker.{FilePicker, format_file_mention}`, `app.tui.help.HelpData`, `app.tui.prompt_editor.PromptEditor`, `harness.command_registry.{HarnessCommandDescriptor, parse_slash}`
**Defines:**
- **type** `HintTarget = tuple[str, str]`
- **class** `PromptBar(Vertical)` — multiline editor + hints + option list + file picker
  - `compose`, `editor` (prop → `PromptEditor`), `input` (prop alias for `editor`), `on_mount`
  - `update_status`, `update_state`, `prefill`
  - `_workspace_dir`, `_file_query(text)`, `_show_file_picker(query)`
  - `refresh_hints(text)` — async; calls `session.list_commands`, `list_chats`, `list_workspaces`
  - `_build_hint_text`, `_format_descriptors`, `_build_hint_options`, `_set_hint_options`, `_has_hint_options`
  - `_restore_editor_focus`, `_accept_highlighted_hint`, `_prefill_command`, `_prefill_argument`, `_argument_candidates(arg_type)`
  - `on_editor_changed(TextArea.Changed)` — listener for `#user_input`
  - `on_prompt_editor_submitted(PromptEditor.Submitted)`
  - `on_hint_option_selected`, `on_file_picker_selected(FilePicker.Selected)`, `on_file_picker_dismissed(FilePicker.Dismissed)`, `_picker_visible`, `on_key`, `text_buffer`
**Notes:** completes on `/`-prefix; argument candidates fetched from session for `workspace_id`/`chat_id`; `@` triggers `FilePicker` overlay using cached `WorkspaceFileIndex`; `update_state` invalidates picker cache on workspace_id change; `escape` while picker visible dismisses it; `enter`/`up`/`down`/`tab` are forwarded to the picker while it is visible

### `src/app/tui/prompt_editor.py`
**Imports:** `textual.events`, `textual.message.Message`, `textual.widgets.TextArea`
**Defines:**
- **class** `PromptEditor(TextArea)` — multiline markdown editor; Enter submits, Ctrl+J / Shift+Enter insert newline
  - inner **class** `Submitted(Message)` — `text`
  - `__init__()` — TextArea with `language="markdown"`, no line numbers
  - `text` (prop), `set_text(text)`, `insert_text(text)`, `clear_text()`
  - `submit()` — posts `Submitted(stripped)` if non-empty; does NOT auto-clear
  - `on_key(event)` — Ctrl+J / Shift+Enter newline, Enter submit
**Notes:** receivers must call `clear_text()` after consuming `Submitted`

### `src/app/tui/screens/__init__.py`
Re-exports `ApprovalScreen`, `ClarificationScreen` from `screens.py`.

### `src/app/tui/screens/chat_manager.py`
**Defines:**
- **class** `ChatManagerScreen(Screen)` — list/create chats; `compose`, `on_mount`, `refresh_list`, `on_button_pressed`, `text_buffer`
**Internal calls:** `session.list_chats`, `session.create_chat`, `DataHarnessApp.activate_chat`
**Notes:** unused in main app

### `src/app/tui/screens/command_palette.py`
**Defines:**
- **class** `CommandPaletteScreen(Screen)` — list available commands; `compose`, `on_mount`, `text_buffer`
**Notes:** superseded by Textual `DataHarnessCommandProvider`

### `src/app/tui/screens/workspace_manager.py`
**Defines:**
- **class** `WorkspaceManagerScreen(Screen)` — list/create/switch/delete workspaces; right pane embeds a navigable `FilePicker` for the selected workspace; "Upload files…" button opens `FileIngestScreen`
  - `compose`, `on_mount`, `refresh_list`, `_workspace_dir_for(workspace_id)`
  - `on_list_view_highlighted/selected`, `on_button_pressed`
  - `action_create_workspace`, `action_switch_selected`, `action_cursor_down/up`, `action_delete_workspace`, `action_upload_files`
  - `on_file_picker_selected(FilePicker.Selected)` — dismisses screen with `{"insert_mention": path}`; app inserts mention into prompt editor
  - `switch_to(workspace_id)` — calls `session.activate_workspace` → `app.apply_workspace_snapshot`
  - `action_close`, `_refresh_files`, `_list_files`, `_input_value`
  - `_show_error`, `_clear_error`, `_highlight_selected_workspace`, `_update_selected_from_item`, `text_buffer`
**Notes:** opened via F2 / `/workspaces`; uses `app.tui.file_picker.WorkspaceFileIndex` for cached workspace file listings

### `src/app/tui/screens/workspace_modal.py`
**Defines:**
- **class** `WorkspaceModal(Screen)` — confirm switch (force when run active)
**Notes:** triggers on `WorkspaceSwitchBlocked`; currently unused (manager handles directly)

---

## `src/harness/`

### `src/harness/__init__.py`
Re-exports `AppStore`, `AppPaths`, `WorkspacePaths`, `ActiveWorkspace`, `WorkspaceManager`, `bootstrap_workspace` (now sourced from `harness.core.{app_store,paths,workspace}`).

### `src/harness/core/__init__.py`
Empty package marker (no re-exports). Import kernel modules by full path, e.g. `harness.core.persistence`.

### `src/harness/services/__init__.py`
Re-exports `AnalysisService`, `Doctor`, `DoctorRunner`, `TmpCleanupBlocked`, `ModeRouter`, `ProfileDecision`, `PromptPackage`, `PromptProfileRegistry`, `WorkspaceFileService`.

### `src/harness/core/app_store.py`
**Defines:**
- **class** `AppStore(BaseModel)` — known workspaces, recents, prefs
  - `load(cls, path)` (classmethod), `register_workspace`, `save`
**Notes:** persisted at `app.json`; recency-ordered list

### `src/harness/core/approval.py`
**Defines:**
- **class** `TimedDecisionGate` — 10s auto-proceed gate; code-execution NEVER auto-proceeds
  - `submit_user_decision(decision)`, `cancel`, `wait(*, eligible_for_auto_proceed, timeout_seconds)`

### `src/harness/services/chat.py`
**Imports:** `harness.exceptions.ChatNotFound`, `ChatWorkspaceMismatch`; `runtime.protocol`; `runtime.types.RuntimeMessage`, `RuntimeRequest`
**Defines:**
- **class** `ChatMessage(BaseModel)`
- **class** `ChatRecord(BaseModel)` — messages + metadata + compaction history
- **class** `ChatSummary(BaseModel)`
- **class** `ChatDeleteResult(BaseModel)`
- **const** `_COMPACTION_PROMPT_PATH` — canonical Layer 3 prompt file at `src/harness/prompts/compaction.md`
- **func** `_new_chat_id()` / `_estimate_tokens(text)`
- **class** `ChatStore` — workspace-scoped persistence under `<app_root>/chats/<workspace_id>/<chat_id>/`
  - `create_chat`, `append_message`, `append_compaction`, `register_chat`, `view_chat`, `list_chats`, `delete_chat`, `cascade_delete_for_workspace`
- **func** `_format_drops_system_role(chat_format)` — true for `gemma*` formats whose chat templates have no `system` slot
- **class** `RuntimeRequestBuilder`
  - `__init__(context_window, *, completion_reserve_pct=0.25, durable_pct=0.30, summary_pct=0.15, recent_pct=0.25, recent_turns_kept=8, chat_format=None)`
  - `build_messages(*, active_mode_prompt, durable_context, chat_record, current_user_text) -> list[RuntimeMessage]` — when `chat_format` indicates `system` role is unsupported, folds persona+durable+summaries into `[SYSTEM]...[/SYSTEM]` prefix on first user turn; deduplicates current user text against the trailing entry of `chat_record.messages`
- **class** `ChatCompactor`
  - `compact(chat_id, *, reason, recent_turns_kept=None) -> AsyncIterator[Literal[...]]`
  - `_fallback_summary(messages)`, `_looks_like_transcript_echo(summary_text)`, `_summarize_via_runtime(older)`, `_load_compaction_prompt()`
**Notes:**
- Storage: `messages.jsonl` + `metadata.json`
- Token budget split: 30% durable / 15% summary / 25% recent / 25% completion reserve
- Compaction summaries use a DataHarness handoff shape. Runtime prompting is loaded from `src/harness/prompts/compaction.md`, and deterministic fallback preserves the same current user goal, durable progress/facts, workspace file references, constraints/preferences, and next steps while filtering role-prefixed transcript echoes and trivial greetings/test messages.

### `src/harness/core/command_registry.py`
**Imports:** `harness.events.HarnessEvent`
**Defines:**
- **type** `ArgType` (literal enum)
- **class** `ArgSpec(BaseModel)`, `CommandContext(BaseModel)`, `HarnessCommandDescriptor(BaseModel)`, `HelpResult(BaseModel)`
- **type** `CommandHandler` — `Callable[[CommandContext, dict], AsyncIterator[HarnessEvent]]`
- **class** `HarnessCommandRegistry`
  - `register(descriptor, handler, *, availability)`
  - `list_descriptors(ctx)`, `help(command)`, `validate(command, args)`, `get_handler(command)`
- **func** `parse_slash(text) -> tuple[str, list[str]]` — positional-only per spec §8

### `src/harness/services/context.py`
**Defines:**
- **class** `ContextManager`
  - `rebuild(*, workspace_dir, session_ledger, validity_states, chat_history) -> dict`
  - `compact(entries, *, active_plan_id, current_step_id, unresolved_failures) -> dict`
- **func** `list_workspace_files`, `read_file_schema`
**Notes:** loads `preferences.json` + all `memory/notes/*.md`. (`src/harness/context.py` shim deleted — import from `harness.services.context`.)

### `src/harness/core/analysis_flow.py`
**Defines (no internal imports; pydantic + stdlib only):**
- **enum** `AnalysisPhase(StrEnum)` — inspecting/plan_pending/approval_pending/executing/done/failed
- **class** `AnalysisFlow(BaseModel)` — Layer-3 per-chat analysis state (chat_id, run_id, workspace_id, phase, goal, plan_id, original_request, inspection_summary, force_attempts, timestamps); `is_terminal()`
- Owned/persisted by `Orchestrator` (`_analysis_flows` dict + `state/analysis_flows.jsonl`, mirror of `_pending_plans`). Drives sticky-analyst override, prose-only→forced-plan emission (Gap A fix), hybrid APPROVAL_PENDING handling, and EXECUTING/DONE/FAILED wiring in `resume_approved_step`.

### `src/harness/control.py`
**Defines (no internal imports):**
- **func** `utc_now()`
- **enum** `RunState(StrEnum)` — idle/routing/clarifying/planning/awaiting_approval/executing/inspecting/updating_memory/reviewing_doctor/responding/finished/failed/cancelled
- **enum** `ValidationFailureKind(StrEnum)` — parse_failure/schema_mismatch/deterministic_repair_candidate/execution_failure/semantic_failure
- **class** `HarnessRecord(BaseModel)` — base: schema_version, id, workspace_id, ts, status
- **class** `RunStateRecord(HarnessRecord)`
- **class** `ModeSwitchEvent(HarnessRecord)`
- **class** `ApprovalRecord(HarnessRecord)` — validator: timeout cannot approve code execution
- **class** `PlanStep(HarnessRecord)` / `Plan(HarnessRecord)` — code plans must start `pending`
- **class** `StepContract(HarnessRecord)` — input paths must be workspace-relative
- **class** `ExecutionEnvelope(HarnessRecord)` — note: distinct from `worker.models.ExecutionEnvelope`
- **class** `StepResult(HarnessRecord)`
- **class** `PromptPackage(HarnessRecord)` — distinct from `harness.services.prompt_profiles.PromptPackage`
- **class** `DoctorReport(HarnessRecord)`
- **class** `TmpAction(HarnessRecord)` — delete/promote/keep
- **class** `ReviewProposal(HarnessRecord)`, `MemoryUpdateProposal(HarnessRecord)`
- **class** `ValidationFailure(BaseModel)`
- **func** `classify_validation_error(*, payload, error, default_kind) -> ValidationFailure`
- **class** `SessionConfig(BaseModel)`

### `src/harness/core/db.py`
**Defines:**
- **var** `AUTHORITATIVE_TABLES` — list[str] (18 tables)
- **func** `_validate_key_name(key_name)` / `create_schema() -> str`
- **class** `WorkspaceDb` — SQLite (WAL)
  - `connect`, `conn` (lazy prop), `list_tables`
  - `append_record(table, record_id, record)`
  - `save_record(table, key_name, key_value, record)` — upsert via `json_extract`
  - `load_record(...)`
  - `list_records(table) -> list[dict]` — full table scan

(Deleted shims: `src/harness/doctor.py`, `src/harness/doctor_runner.py`, and `src/harness/commands.py` no longer exist. Canonical: `harness.services.doctor` for `Doctor`/`DoctorRunner`/`PHASES`/`PROMOTION_TARGETS`/`TmpCleanupBlocked`; `harness.core.command_registry` for `HarnessCommandRegistry`. The `src/harness/commands/` PACKAGE of real command modules is unrelated and still exists.)

### `src/harness/services/analysis.py`
**Imports:** `harness.control.{Plan, PlanStep, RunStateRecord, StepContract}`; `harness.events.{ApprovalRequired, CommandCompleted, CommandProgress, CommandStarted, HarnessEvent, PlanReady}`; `worker.models.PermissionEnvelope`; `worker.policy.WorkerPolicyValidator`
**Defines:**
- **var** `PLAN_ALLOWED_PACKAGES`
- **func** `normalize_plan_step_code(idx, raw)` — normalizes legacy `code` or safer `code_lines`
- **class** `AnalysisService`
  - `build_plan_from_arguments(state, *, goal, steps)` — validates command-supplied analysis code and builds `Plan` + `StepContract` records
  - `analysis_plan_events(...)` — command-path plan handling; code supplied directly, no gen-2
  - `assemble_plan_events(...)` — model two-step path; code-free plan → gen-2 code synthesis via owner → validation/retry → final plan
  - `analysis_request_execution_events(...)` — re-emits approval for an existing pending step
  - `validate_generated_step(...)`, `finalize_plan(...)`
**Notes:** transitional service receives the owning `Orchestrator` for stateful registries and generation helpers.

### `src/harness/services/doctor.py`
**Imports:** `harness.control`; `harness.events.*`; `harness.core.fingerprints.lazy_fingerprint`; `harness.core.persistence`; `harness.core.validity.{ValidityState, classify}`; `harness.services.chat`; `harness.services.knowledge.KnowledgeManager`; `runtime.protocol`; `runtime.types.{RuntimeMessage, RuntimeRequest}`
**Defines:**
- **var** `PROMOTION_TARGETS` — kind→workspace-relative path
- **class** `TmpCleanupBlocked(RuntimeError)`
- **class** `Doctor`
  - `check_source_file(path, *, stored_size, stored_mtime_ns, stored_fingerprint)`
  - `check_all_sources(workspace_dir, persistence, workspace_id)` — async source rescan with drift/missing findings
  - `inventory_tmp_artifacts(workspace_dir, persistence)` — async tmp inventory with keep/cleanup classifications
  - `prune_pending_plans(workspace_dir)` — async pending plan tombstone/stuck-plan scan
  - `review_tmp_items(items, *, trigger_context, live_refs, promote_map)`
  - `run(workspace_dir, *, trigger_context, tmp_items, persistence, workspace_id, live_refs, promote_map)`
  - `apply_tmp_action(action_record, *, workspace_dir)` — unlink/rename + mark applied
  - `_discover_tmp_items`, `_persist`
- **var** `PHASES` — scan_sources/review_validity/review_lineage/review_tmp/review_memory/assemble_recommendations
- **class** `DoctorRunner`
  - `__init__(doctor, persistence, runtime, knowledge_manager, chat_store)`
  - `run(*, workspace_id, workspace_dir, trigger, chat_id, run_id, mode="full") -> AsyncIterator[HarnessEvent]` — deterministic phases for `light/full`; LLM semantic phases for `semantic/full`
  - `_run_phase(...)` — `review_tmp` discovers tmp files and emits promotion/keep actions; others stub
  - `_classify_tmp_items(items)` — successful `step.py` → function promotion; failed step evidence → keep
  - `_read_step_result(path)`, `_event_action(action)`, `_category(phase)`
  - `_run_chat_knowledge_mining(...)`, `_run_script_assessment(...)`, `_run_consistency_check(...)` — runtime-backed semantic doctor phases
  - `_collect_tmp_actions(report_id)`, `_fallback_narration(findings_payload, action_summaries)`, `_render_narration(findings_payload, action_summaries)` (LLM via `doctor_narrator.md`, deterministic fallback), `_narrate_and_request_approval(report_id, chat_id, workspace_id, summary_counts, findings)` → yields `DoctorNarrationReady` + `DoctorApprovalRequested` (findings passed as a parameter, not instance state) — these moved here from Layer 4 `AppSession`; off-canonical, see `docs/app/doctor-behaviour.md`
**Notes:** spec §6.12 — cleanup follows persisted `TmpAction`. LLM narration / approval-request emission is a Layer 3 off-canonical addition over the spec's required tmp-review approval gate.

### `src/harness/services/workspace_files.py`
**Imports:** `harness.services.context.{list_workspace_files, read_file_schema}`
**Defines:**
- **var** `READ_FILE_CHAR_CAP`
- **class** `WorkspaceFileService`
  - `list_files(workspace_dir)` — shared inventory wrapper
  - `inspect_file(workspace_dir, rel_path)` — shared schema inspection with missing workspace/path errors
  - `read_content(workspace_dir, rel_path, *, max_bytes, encoding)` — bounded workspace-relative text read with escape and binary guards
**Notes:** shared by model-facing `file_read` and legacy file commands.

### `src/harness/events.py`
**Imports:** `harness.status.HarnessStatusSnapshot`; `runtime.types.RuntimeStatus`; `worker.models.StepExecutionEnvelope, StepTaskStatus`
**Defines:**
- **func** `_new_event_id()`
- **class** `HarnessEvent(BaseModel)` (base) and full event hierarchy (see Index B)
- **class** `HarnessEventRef(BaseModel)`
**Notes:** immutable audit trail; `RuntimeDelta` carries text/reasoning OR tool_call

### `src/harness/exceptions.py`
**Defines:** `HarnessError(Exception)` ← `ChatNotFound`, `ChatWorkspaceMismatch`, `ChatActiveDeletionBlocked`, `WorkspaceNotFound`, `RunAlreadyActive`, `WorkspaceSwitchBlocked`

### `src/harness/core/factory.py`
**Imports:** `harness.core.db`, `harness.core.persistence`, `harness.orchestrator`, `harness.services.context`, `harness.services.doctor`, `harness.services.knowledge`; `observability`; `runtime.protocol.Runtime`; `worker.executor.PythonStepExecutor`
**Defines:**
- **func** `build_orchestrator(*, workspace_dir, runtime, telemetry) -> Orchestrator` — sole wiring point
**Notes:** Layer 4 must call this — never construct `Orchestrator` directly. Factory wires `KnowledgeManager` with the workspace dir/persistence so memory writes stay inside Layer 3. Kernel module that may import services (the wiring exception).

### `src/harness/core/fingerprints.py`
**Defines:**
- **class** `FingerprintResult(NamedTuple)` — action/fingerprint/size/mtime
- **func** `sha256_file(path) -> str`
- **func** `lazy_fingerprint(path, *, stored_size, stored_mtime_ns, stored_fingerprint) -> FingerprintResult` — fast path: reuse if metadata unchanged
**Notes:** actions: `fingerprinted`, `reused_fingerprint`, `changed`, `missing`

### `src/harness/services/knowledge.py`
**Imports:** `harness.control.{MemoryUpdateProposal, utc_now}`; `harness.core.persistence.HarnessPersistence`
**Defines:**
- **class** `MemoryWriteForbidden(PermissionError)`
- **func** `guarded_external_memory_write(workspace_dir, relative_path, content)` — always raises (boundary enforcement)
- **class** `KnowledgeManager` — single writer for `memory/`
  - `load_preferences`, `update_preferences`, `rescan_workspace_memory`
  - `synthesize_from_user_teaching`, `check_function_freshness`
  - `propose_update(*, run_id, memory_target, source_refs, proposed_content) -> MemoryUpdateProposal`
  - `apply(proposal_id, *, decision)`
  - `write_note/delete_note`, `write_gap/delete_gap`, `write_function/delete_function`
  - `set_preference/remove_preference`
  - `has_note_for_turns(workspace_dir, turn_ids)` — echo-dedup helper for doctor knowledge mining
  - `_detect_conflicts`, `_resolve_memory_target`, `_slug`
**Notes:** spec §6.13 + §10.8; reuse blocked unless source validity is `ok`/`revalidated`

### `src/harness/orchestrator.py`
**Imports:** `harness.{control, events, exceptions, status}` (shared contracts); `harness.core.{analysis_flow, command_registry, persistence, state_machine}`; `harness.services.{analysis, chat, context, doctor, knowledge, mode_router, prompt_profiles, workspace, workspace_files}`; `harness.tools.*`; `harness.commands.*` (lazy, in `_register_commands`); `worker.{executor,models,policy}`; `observability`; `runtime.{protocol,types}`
**Defines:**
- **func** `_sanitize_assistant_text(text)` — strips leaked assistant draft and Gemma turn markers before chat persistence
- **func** `_summarize_step_execution(workspace_dir, envelope)` — status-aware final message for worker results/failures
- **func** `_is_repairable_plan_analysis_error(message)` — classifies plan schema/field validation errors that merit one internal repair retry
- **func** `_workspace_schema_snapshot(workspace_dir)` — compact JSON-lines schema context for plan repair prompts
- **func** `_build_plan_analysis_repair_prompt(...)` — strict retry prompt for invalid `analysis_plan` tool calls
- **func** `_plan_analysis_no_code_message(validation_error)` — final no-code-ran user message after repeated invalid plans
- **func** `_apply_safe_action(km, workspace_dir, action)` — auto-apply safe doctor cleanup/promotion actions
- **func** `_read_workspace_file(...)` — compatibility wrapper delegating to `WorkspaceFileService.read_content`
- **class** `Orchestrator`
  - `_register_commands` (built-ins: doctor, compact, help, cancel_run, memory_review, inspect_artifact, provenance_inspect, validity_inspect, mark_result_trusted, mark_result_invalidated, challenge_conclusion, stop_after_current_step, revise_goal, retry_step, rerun_step, chat ops, workspace ops). All Layer 3 commands now available; no stubs remain.
  - `_handle_doctor`, `_handle_compact`, `_handle_help`, `_handle_cancel_run`, `_handle_memory_review`, `_handle_recall_knowledge`, `_handle_inspect_artifact`, `_handle_provenance_inspect`, `_handle_validity_inspect`, `_handle_mark_result_trusted`, `_handle_mark_result_invalidated`, `_handle_challenge_conclusion`, `_handle_stop_after_current_step`, `_handle_revise_goal`, `_handle_retry_step`, `_handle_rerun_step`, `_handle_unavailable` (fallback)
  - `_mark_step_validity(...)` (verifies step_records membership before write), `_request_step_action(...)` — shared helpers for trusted/invalidated and retry/rerun
  - `_handle_revise_goal` appends `run_state_history` audit record with previous/new goal
  - `_stop_after_step_run_ids: set[str]` — run ids flagged for graceful stop after current step
  - `_step_action_requests: dict[str, str]` — step_id → "retry" | "rerun" pending action
  - `_mark_step_validity(ctx, args, command, status)` — shared helper for trusted/invalidated
  - `_make_chat_handler(name)` / `_make_workspace_handler(name)` — factories
  - `list_commands(context)`, `help(command)`
  - `handle_direct_command(state, *, command, arguments)`
  - **workspace ops:** `list_workspaces`, `create_workspace`, `rename_workspace`, `delete_workspace`, `activate_workspace(force)`, `ingest_files`; activation runs a light doctor pass
  - **run lock:** `_acquire_run(run_id)` raises `RunAlreadyActive`; `_release_run`
  - **chat ops:** `create_chat`, `list_chats`, `view_chat`, `delete_chat`, `resume_chat`, `compact_chat_history`
  - **profile routing:** `_select_profile(state, *, chat_id, user_input) -> str` — calls `self.mode_router.route(user_input).mode`; if routed `interaction` and a prior non-interaction profile exists, keep the prior (continuity); writes `state.active_agent_mode` IN PLACE on the live `RunStateRecord` (not a model_copy); returns the chosen mode. Built deps: `self.mode_router` (`ModeRouter`), `self.prompt_profiles` (`PromptProfileRegistry`) in `__init__`.
  - **turn:** `run_turn(state, *, workspace_dir, chat_id, user_input, requested_mode=None, prompt_text=None, durable_context="", persist_user_message=True) -> AsyncIterator[HarnessEvent]` — single-stream; `requested_mode`/`prompt_text` are internal optionals for self-reuse, not app injection; emits `TurnPaused`/`TurnFailed(empty_output)` instead of hollow asg_ rows
  - **agentic turn:** `run_agentic_turn(state, *, workspace_dir, chat_id, user_input, max_iterations=4) -> AsyncIterator[HarnessEvent]` — NO `requested_mode`/`prompt_provider` params; calls `_select_profile` then `self.prompt_profiles.load(mode).prompt_text`. Bounded multi-iteration loop: sticky-analyst override (in-flight `AnalysisFlow` forces analyst mode, emits `ModeHandoffAccepted(reason="analysis_flow_sticky")`) → ensure INSPECTING flow on analyst entry → APPROVAL_PENDING hybrid branch (deterministic approve/reject/show, free-form grounds the analyst turn) → build durable context → run_turn → dispatch tool_calls → handle handoffs/empty-output/malformed-tool/plan-repair retry → prose-only-in-analyst drives forced plan emission (Gap A) → ApprovalRequired termination. `resume_with_clarification` sets `cleared.active_agent_mode = state.active_agent_mode` for profile continuity. Layer-3 owned per spec §6.3 / §8.1.
  - **analysis flow registry:** `_append_analysis_flow`/`_replay_analysis_flows` (prunes terminal/dropped), `_get_flow`/`_set_phase`/`_drop_flow`/`_ensure_inspecting_flow`/`_find_flow_by_plan`; `_force_plan_tool_call(state, *, flow, workspace_dir, chat_id, run_id, correction=None) -> dict|None` — dedicated non-persisted gen (`stop=["</tool_call>"]`) parsed via `runtime.tool_calls.parse_tool_call_block`, validates code-free `analysis_plan` args; `_classify_approval_intent`/`_looks_like_plan_intent`/`_summarize_inspection`/`_plan_brief` helpers
  - **tool dispatch:** `_dispatch_tool_call(state, name, args, *, chat_id=None) -> AsyncIterator[HarnessEvent]` — routes every name via `tool_registry.get_handler(name)`/`tool_registry.validate(name, args)` (tool-only; no `command_registry` fallback, no `KNOWLEDGE_INTENTS` bypass — knowledge writes now flow through the `knowledge_propose_update` tool handler which calls `knowledge_intents.handle_knowledge_intent(run_id=ctx.run_id, ...)`), builds a `ToolContext`; re-yields handler events
  - **context block:** `_build_durable_context_block(workspace_id, workspace_dir, user_query="") -> str` — adds query-relevant memory notes
  - `close`, `cancel_run(run_id, reason) -> TurnCancelled`
  - **status:** `status_snapshot(workspace_id)`, `watch_status() -> AsyncIterator`
  - **doctor actions:** `apply_doctor_actions(report_id, decision, workspace_id, workspace_dir, chat_id, action_ids=None)` — optional selected action ids apply only checked doctor actions; explicit empty list applies none
  - **execution resumption:** `resume_approved_step(...)`, `resume_with_clarification(...)`; successful worker completion starts a semantic doctor background pass
  - **artifact promotion:** `_promote_step_artifacts(workspace_dir, step_result_path, run_id) -> list[Path]` — copies successful step outputs from tmp/ to artifacts/ and memory/functions/
  - `prepare_worker_dispatch(plan, *, approval) -> dict` — validates code-exec approval
  - `_build_plan_from_arguments(state, *, goal, steps) -> tuple[Plan, list[StepContract]]` — compatibility delegate to `AnalysisService.build_plan_from_arguments`
  - `_generate_step_code(state, *, step, workspace_dir, correction=None) -> list[str]` — gen-2: internal, non-persisted runtime generation (`stop=["```"]`), parses fenced ```` ```python ```` via `runtime.tool_calls.extract_fenced_code`; schema-aware prompt (`_GEN2_SYSTEM_PROMPT`)
  - `_assemble_plan_events(...)`, `_validate_generated_step(...)`, `_finalize_plan(...)`, `_analysis_plan_events(...)`, `_analysis_request_execution_events(...)` — compatibility delegates to `AnalysisService`
  - `_handle_plan_analysis(ctx, args)` / `_handle_request_execution(ctx, args)` — command-only wrappers around `AnalysisService`; emit PlanReady + ApprovalRequired
  - `switch_workspace(state, *, new_workspace_id) -> RunStateRecord`
**Notes:**
- Single-active-run via `_acquire_run`/`_release_run`
- `RuntimeRequestBuilder` handles token-pressure auto-compaction inside `run_turn`
- Yields `TurnStarted`, `ModeActivated`, `ChatHistoryLoaded`, `PromptBuilt`, `RuntimeDelta`s, `FinalMessage`
- Runtime-callable command catalog now includes `recall_knowledge` for workspace memory search

### `src/harness/core/paths.py`
**Defines:**
- **class** `AppPaths(BaseModel)` — `from_root(root)` → app/harness/workspaces dirs
- **class** `WorkspacePaths(BaseModel)` — `from_workspace_dir(root)` → data/artifacts/tmp/memory{notes,gaps,functions}/state
  - `relative(path)`

### `src/harness/core/persistence.py`
**Imports:** `harness.control.ApprovalRecord`; `harness.core.db.WorkspaceDb`; `observability`, `observability.events`
**Defines:**
- **class** `HarnessPersistence`
  - `save_model(table, key_name, key_value, record: BaseModel)`
  - `save_dict(...)` — emits `PERSISTENCE_WRITE_*` telemetry
  - `save_plan_with_steps(plan_payload)` — upsert plan + steps
  - `save_approval(approval)`
  - `save_execution_envelope(envelope, workspace_dir)` — cascades to artifact_registry + lineage_records
  - `_fingerprint_artifact(workspace_dir, artifact_path)`

### `src/harness/core/prompt_registry.py`
**Defines:**
- **var** `ALLOWED_LAYER3_PROMPTS = ["compaction", "doctor", "knowledge_reconcile"]`
- **class** `HarnessPromptRegistry`
  - `allowed_prompts`, `load(name) -> str`
**Notes:** narrow operational-prompt registry; distinct from `harness.services.prompt_profiles.PromptProfileRegistry` (persona prompt assembly).

### `src/harness/services/provenance.py`
**Imports:** TYPE_CHECKING `harness.core.db.WorkspaceDb`
**Defines:**
- **class** `ProvenanceRecord(BaseModel)` — sources, fingerprints, code hash, artifacts, plan/step, validity, prompt info
- **class** `ClaimChecker`
  - `check_claims(claims) -> dict[str, list[str]]` — supported vs unsupported
  - `_refs_have_lineage(refs)`
- **func** `reuse_allowed_for_source(*, validity_state) -> bool` — `ok` or `revalidated` only

### `src/harness/services/repair.py`
**Defines:**
- **class** `RepairResult` (frozen dataclass) — `kind`, `payload`, `recipe`
- **func** `_wrapper_repair`, `_type_normalization`, `_path_normalization`, `_metadata_insertion`
- **var** `REPAIR_RECIPES` — tuple of recipes
- **func** `try_deterministic_repair(payload, *, failure_kind, record_kind) -> RepairResult`
**Notes:** only for parse_failure/schema_mismatch/deterministic_repair_candidate

### `src/harness/core/state_machine.py`
**Imports:** `harness.control.{ApprovalRecord, Plan, RunState, RunStateRecord}`
**Defines:**
- **var** `ALLOWED_TRANSITIONS` — dict per spec §4.2
- **class** `InvalidTransition(ValueError)`
- **class** `HarnessStateMachine`
  - `transition(state, next_state) -> RunStateRecord`
  - `can_dispatch_execution(plan, approval) -> bool` — code requires approved + decided_by != "timeout"
  - `decide_after_failure(state, *, failure_kind) -> dict` — retry vs replan

### `src/harness/status.py`
**Imports:** `runtime.types.RuntimeStatus`
**Defines:**
- **class** `HarnessEventRefPayload(BaseModel)`
- **class** `HarnessStatusSnapshot(BaseModel)` — workspace/chat/run + health/mode/tasks/approvals; includes `doctor_findings`
- **class** `StatusBroker`
  - `publish(snapshot)`, `append_doctor_finding(finding)`, `close`, `watch() -> AsyncIterator[HarnessStatusSnapshot]`
**Notes:** heartbeat 2.0s default; coalesce 0.05s default

### `src/harness/core/validity.py`
**Defines:**
- **enum** `ValidityState(StrEnum)` — ok/changed/stale/needs_review/revalidated/broken_lineage
- **func** `classify(*, fingerprint_action, stored_fingerprint, new_fingerprint, has_dependents_with_stale_inputs, needs_user_review, user_revalidated) -> ValidityState`

### `src/harness/core/workspace.py`
**Imports:** `harness.core.app_store.AppStore`; `harness.core.paths.WorkspacePaths`
**Defines:**
- **var** `DEFAULT_WORKSPACE_ID = "w_0001"`
- **class** `ActiveWorkspace` (frozen dataclass) — `workspace_id`, `workspace_dir`
- **func** `bootstrap_workspace(workspace_dir) -> Path` — create dir tree + `preferences.json`
- **class** `WorkspaceManager`
  - `open_default_workspace`, `open_workspace(workspace_id)`
**Notes:** kernel workspace store. Distinct from `harness.services.workspace` (async manager) and `harness.services.workspace_files` (file inventory/schema reads).

### `src/harness/services/workspace.py`
**Imports:** `harness.core.app_store.AppStore`; `harness.core.workspace.bootstrap_workspace`; `harness.exceptions.WorkspaceNotFound`; `harness.services.chat.ChatStore`
**Notes:** renamed from `harness.workspace_async` (the old name no longer exists).
**Defines:**
- **class** `WorkspaceSummary(BaseModel)` — id/dir/created_at/last_activated_at/chat_count/source_count/health
- **class** `WorkspaceIngestResult(BaseModel)`
- **class** `AsyncWorkspaceManager`
  - `list_workspaces`, `create_workspace`, `rename_workspace` (cascades dirs + AppStore), `delete_workspace` (calls `ChatStore.cascade_delete_for_workspace`)
  - `activate_workspace(*, force)`, `ingest_files(workspace_id, paths)` — dedup via `_stem_N.suffix`
  - `_register`, `_summary`, `_deduplicate_dest`

---

## `src/runtime/`

### `src/runtime/__init__.py`
Re-exports `RuntimeConfig`, `auto_ctx_from_ram_gb` from `runtime.config`.

### `src/runtime/bridge.py`
**Imports:** `runtime.types.RuntimeEvent`
**Defines:**
- **class** `SyncToAsyncBridge` — bridges blocking sync iterator to async
  - `__init__(iterator_factory, queue_size=64)`, `cancel`, `stream()` (async gen), `_put`, `_produce`
- **var** `_SENTINEL` — end-of-stream marker
**Notes:** daemon producer thread; cancel emits "cancelled" error event; used by `LlamaCppRuntime.stream`

### `src/runtime/config.py`
**Defines:**
- **func** `auto_ctx_from_ram_gb(total_gb)` — heuristic: ≤8→4096, ≤16→8192, ≤32→16384, else 32768
- **class** `RuntimeConfig(BaseModel, frozen)` — model_path, chat_format="gemma", n_ctx=32768, n_batch=512, n_threads, type_k=2, type_v=2, n_gpu_layers=-1, offload_kqv=True, flash_attn=True, verbose=False, enable_reasoning_stream=True, bridge_queue_size=64

### `src/runtime/llama_cpp_runtime.py`
**Imports:** `observability.{Telemetry, resolve_telemetry_dir}`; `observability.events.{EventKind, Layer}`; `runtime.bridge.SyncToAsyncBridge`; `runtime.config.RuntimeConfig`; `runtime.tool_calls.{ToolCallParseError, parse_tool_call_block, repair_tool_call_block}`; `runtime.types.{ModelBehaviorError, RuntimeEvent, RuntimeInputError, RuntimeMessage, RuntimeRequest, RuntimeStatus, TokenPressure}`
**Defines:**
- **vars** `TOOL_START`, `TOOL_END`, `TOOL_START_MARKERS`, `THINK_START`, `THINK_END`, `LEGACY_THINK_START`, `LEGACY_THINK_END`, `THINK_START_MARKERS`, `THINK_END_MARKERS`, `STREAM_MARKERS`, `EOS_TOKENS`
- **func** `strip_eos(text)`, `strip_full_eos(text)`, `eos_prefix_suffix(text)`, `build_llama_kwargs(config)`, `marker_prefix_suffix(text)`, `_prefix_suffix_for(text, markers)`, `_find_earliest_marker(text, markers)`
- **class** `_SeqGen` — `next()` increment counter
- **func** `event_from_tool_call_text(text, request_id, seq)` — text → `RuntimeEvent` (try parse, fallback to repair)
- **func** `emit_content_events(content, stream_buffer, request_id, seq, in_reasoning=False, enable_reasoning_stream=True)` — stateful typed event extraction with partial-marker buffering; streams Gemma channel/legacy reasoning progressively; loops through multiple tool calls in one chunk/tail
- **class** `LlamaCppRuntime` (implements `runtime.protocol.Runtime`)
  - `__init__(config, telemetry=None)` — load model
  - `_set_status`, `status`, `chat_format` (property, exposes `_config.chat_format`), `context_window`
  - `_count_tokens(request)` — tokenize w/ heuristic fallback
  - `token_pressure(request)`, `validate_request(request)`
  - `_completion_kwargs(request)`, `_sync_event_iterator(request)` — yields RuntimeEvents; keeps parse-error diagnostics local to each stream
  - `stream(request) -> AsyncIterator[RuntimeEvent]` — wraps sync iter via `SyncToAsyncBridge`
**Notes:** state machine loading→ready→streaming→ready (status lock-protected); all post-init `_llama` access is serialized through `_llama_lock`

### `src/runtime/protocol.py`
**Imports:** `runtime.types.{RuntimeEvent, RuntimeRequest, RuntimeStatus, TokenPressure}`
**Defines:**
- **class** `Runtime(Protocol)` — attr `chat_format: str`; methods `stream`, `context_window`, `token_pressure`, `validate_request`, `status`

### `src/runtime/tool_calls.py`
**Defines:**
- **var** `TOOL_CALL_RE` — `<tool_call>...</tool_call>` regex
- **class** `ToolCallParseError(ValueError)`
- **class** `ParsedToolCall(BaseModel)` — `name`, `arguments`
- **func** `_match_and_parse(text)`, `parse_tool_call_block(text)`, `repair_tool_call_block(text)` — wraps scalar args as `{"value": scalar}`

### `src/runtime/types.py`
**Defines:**
- **class** `RuntimeMessage(BaseModel)` — role/content/name/tool_call_id
- **class** `RuntimeRequest(BaseModel)` — messages/max_completion_tokens/temperature=1.0/top_k=64/top_p=0.95/stop/tools/request_id/correlation_id
- **class** `RuntimeEvent(BaseModel)` — type/request_id/seq/text/tool_call/finish_reason/usage/error_code/error_message
- **class** `TokenPressure(BaseModel)` — context_window/prompt_tokens/reserved_completion_tokens/total/pressure_ratio/over_threshold (>0.80)
- **var** `RuntimeStatus = Literal["not_loaded","loading","ready","streaming","error"]`
- **class** `RuntimeInputError(ValueError)`, `ModelBehaviorError(ValueError)`

---

## `src/observability/`

### `src/observability/__init__.py`
Re-exports `EventKind`, `Layer`, `Outcome`, `TelemetryEvent` (from events); `configure_logging`; `resolve_app_root/log_dir/telemetry_dir`; `Telemetry`, `bind_*`, `current_*`.

### `src/observability/events.py`
**Defines:**
- **enum** `Layer(str, Enum)` — BOOTSTRAP/APP/HARNESS/RUNTIME/WORKER/PERSISTENCE
- **enum** `Outcome(str, Enum)` — OK/ERROR
- **enum** `EventKind(str, Enum)` — 100+ identifiers spanning bootstrap/app/harness/runtime/worker/persistence phases
- **class** `TelemetryEvent(BaseModel)` — event_id (UUID), ts, layer, kind, outcome, boot_id/session_id/turn_id/step_id, duration_ms, payload

### `src/observability/logging_setup.py`
**Imports:** `observability.events.{Layer, Outcome}`; `observability.telemetry.current_*`
**Defines:**
- **class** `TelemetryContextFilter(logging.Filter)` — injects `boot_id/session_id/turn_id/step_id/event_id/kind/outcome` into LogRecords
- **func** `_handler(path) -> RotatingFileHandler`, `_clear_handlers(logger)`, `_install_exception_hooks()`
- **func** `configure_logging(log_dir) -> Path` — root + per-layer rotating file handlers; optional stderr if `DATAHARNESS_LOG_STDERR=1`

### `src/observability/redaction.py`
**Defines:**
- **func** `redact_payload(payload) -> dict` — currently no-op copy

### `src/observability/runtime_paths.py`
**Defines:**
- **func** `repo_root() -> Path` — handles dev + frozen
- **func** `resolve_app_root() -> Path` — `repo_root()`
- **func** `resolve_log_dir() -> Path` — `{root}/harness/logs`
- **func** `resolve_telemetry_dir() -> Path` — `{root}/harness/telemetry`

### `src/observability/telemetry.py`
**Imports:** `observability.events.{EventKind, Layer, Outcome, TelemetryEvent}`
**Defines:**
- **vars** `_boot_id`, `_session_id`, `_turn_id`, `_step_id` — `ContextVar`s
- **func** `current_boot_id`, `current_session_id`, `current_turn_id`, `current_step_id`
- **func** `bind_boot`, `bind_session`, `bind_turn`, `bind_step` — context managers
- **class** `Telemetry`
  - `__init__(log_dir)`
  - `emit(layer, kind, *, payload, outcome, duration_ms) -> TelemetryEvent` — JSONL append `{layer}.events.jsonl` + logger
  - `emit_error(layer, kind, *, phase, exc) -> TelemetryEvent` — exception type/message/traceback
**Notes:** thread-locked file writes; ContextVars propagate trace IDs

---

## `src/worker/`

### `src/worker/__init__.py`
Re-exports `PythonStepExecutor` (executor); `ExecutionEnvelope`, `ExecutionStatus`, `FailureKind`, `PermissionEnvelope`, `ResourceLimits`, `StepExecutionRequest` (models).

### `src/worker/executor.py`
**Imports:** `observability.{Telemetry, current_boot_id, current_session_id, current_step_id, current_turn_id, resolve_telemetry_dir}`; `observability.events.{EventKind, Layer}`; `worker.models.{ExecutionEnvelope, ExecutionStatus, FailureKind, StepExecutionRequest, StepExecutionEnvelope, StepTaskHandle, StepTaskStatus}`; `worker.paths.{as_posix_workspace_relative, build_step_tmp_dir}`; `worker.policy.{WorkerPolicyError, WorkerPolicyValidator}`
**Defines:**
- **vars** `INTERNAL_FILES`, `SANDBOX_VIOLATION_MARKERS`
- **func** `allowed_code_roots() -> list[str]`
- **func** `_stage_declared_inputs(*, workspace_dir, tmp_dir, declared_inputs) -> set[Path]` — symlinks declared inputs under tmp_dir preserving subpath; returns top-level staged dirs for `_write_envelope` filtering
- **func** `_subprocess_env() -> dict[str,str]` — adds `src/` to PYTHONPATH; propagates `DATAHARNESS_BOOT_ID/SESSION_ID/TURN_ID/STEP_ID`
- **func** `_decode`, `_to_step_task_status`
- **class** `_TaskRecord` (dataclass) — `task_id`, `request`, `status`, `process`, `cancel_event`, `done_event`, `envelope`, `runner_task`
- **class** `PythonStepExecutor`
  - `submit(request) -> StepTaskHandle` — registers + spawns runner
  - `wait(task_id) -> StepExecutionEnvelope`
  - `cancel(task_id, reason) -> StepExecutionEnvelope`
  - `list_tasks`, `get_task`
  - `_run(rec)`, `_execute_async(rec)` — script write → policy validate → sandbox config → subprocess (`python -m worker.sandbox_bootstrap`) → wait w/ timeout → classify → envelope
  - `_wrap_envelope`, `_classify_success_contract`, `_preserve_malformed_user_result`, `_is_sandbox_violation`
  - `_package_versions(packages)`, `_write_envelope(...)` — `step_result.json` + `step_report.md`

### `src/worker/models.py`
**Defines:**
- **func** `utc_now()`
- **enum** `ExecutionStatus(StrEnum)` — OK/EXECUTION_ERROR/TIMEOUT/RESOURCE_EXHAUSTED/CONTRACT_ERROR/SANDBOX_ERROR
- **enum** `FailureKind(StrEnum)` — OK/PYTHON_EXCEPTION/TIMEOUT_OR_RESOURCE_EXHAUSTION/MISSING_OUTPUT_FILES/MALFORMED_RESULT_JSON/PARTIAL_ARTIFACT_GENERATION/SANDBOX_VIOLATION
- **class** `ResourceLimits(BaseModel)` — timeout=120s, memory=1024MB, artifact=100M, stdout/stderr=5M
- **class** `PermissionEnvelope(BaseModel)` — allowed_read_paths, registered_artifact_paths, allowed_write_roots (default `artifacts/tmp`), allowed_packages, allow_network=False, allow_shell=False
- **class** `StepExecutionRequest(BaseModel)` — full request payload + `effective_timeout()`
- **class** `ExecutionEnvelope(BaseModel)` — status/paths/artifact_refs/execution_metadata/failure_kind (note: distinct from `harness.control.ExecutionEnvelope`)
- **class** `StepTaskHandle(BaseModel)` / `StepTaskStatus(BaseModel)` / `StepExecutionEnvelope(BaseModel)` — three-tier async response

### `src/worker/paths.py`
**Defines:**
- **func** `build_step_tmp_dir(workspace_dir, *, run_id, step_id) -> Path` — `{ws}/artifacts/tmp/{run_id}/{step_id}`
- **func** `to_workspace_relative(workspace_dir, path) -> Path` — boundary-checked
- **func** `as_posix_workspace_relative(workspace_dir, path) -> str`

### `src/worker/policy.py`
**Imports:** `worker.models.{PermissionEnvelope, ResourceLimits}`
**Defines:**
- **class** `WorkerPolicyError(ValueError)`
- **vars** `NETWORK_MODULES`, `SHELL_MODULES`, `STDLIB_ALLOWLIST`
- **class** `WorkerPolicyValidator`
  - `__init__(workspace_dir, permission_envelope)`
  - `_resolve_relative(path_text)` — rejects absolute + `..` escape
  - `validate_read(path_text)`, `validate_write(path_text)`
  - `_import_names(node)` — rejects relative imports
  - `validate_code_imports(code)` — AST walk vs allowlists
  - `validate_resource_limits(limits)` — all > 0

### `src/worker/sandbox_bootstrap.py`
(No static `src.*` imports — runs as subprocess via `python -m worker.sandbox_bootstrap`)
**Defines:**
- **vars** `NETWORK_MODULES`, `SHELL_MODULES`, `STDLIB_ALLOWLIST`, `CODE_SUFFIXES`, `BLOCKED_AUDIT_EVENTS`, `WRITE_OPEN_FLAGS`, `WRITE_MODE_CHARS`
- **func** `_is_relative_to(path, root)`, `_is_write_mode(mode_raw)`
- **func** `main() -> int` — entry: load JSON config → set RLIMIT_AS → preload importlib/pkgutil → install `guarded_import` + audit hook (with nested package-frame helpers) → `runpy.run_path(script_path, "__main__")`
**Notes:**
- Import hook: blocks user network/shell unless allowed; whitelists preloaded modules; allows dependency imports issued from already-allowed package frames while audit-blocking dangerous operations
- Audit hook: enforces open() read/write boundaries via allowed_reads + allowed_write_roots; blocks `socket.__new__`/`subprocess.Popen`/`os.system`
- Python install roots exempted (stdlib data files)

---

## Cross-cutting Notes

### Layer boundaries enforced in code
- `harness/core/factory.py` — sole place Layer 4 obtains an `Orchestrator` (with runtime injected)
- `harness/services/knowledge.py::guarded_external_memory_write` — raises if any non-`KnowledgeManager` code touches `memory/`
- `harness/core/*` must not import `harness/services/*` (kernel/services boundary; `core/factory.py` is the wiring exception)
- `worker/policy.py` + `worker/sandbox_bootstrap.py` — defense in depth: static AST validation pre-spawn + runtime import/audit hooks in subprocess

### Name collisions to watch
| Name | Two locations |
|------|---------------|
| `RunState` | `harness/control.py` (StrEnum, full lifecycle) vs `app/tui/models.py` (StrEnum, idle/running/stopping/error) |
| `ExecutionEnvelope` | `harness/control.py` (Pydantic record) vs `worker/models.py` (worker result) |
| `PromptPackage` | `harness/control.py` (HarnessRecord) vs `harness/services/prompt_profiles.py` (BaseModel for prompt assembly) |
| `PromptProfileRegistry` vs `HarnessPromptRegistry` | `harness/services/prompt_profiles.py` (persona prompt assembly) vs `harness/core/prompt_registry.py` (narrow operational prompts) |
| `workspace` | `harness/core/workspace.py` (kernel store) vs `harness/services/workspace.py` (async manager, ex-`workspace_async`) vs `harness/services/workspace_files.py` (file inventory/schema) |

### Telemetry is the one global side effect
`Telemetry.emit` invoked from runtime, worker, harness persistence, app session, `ModeRouter` (Layer 3 route decisions), TUI app. Context vars (`current_boot_id` etc.) propagate through async/threads via `ContextVar`.

### Hot path summary
1. Keystroke → `PromptBar.on_input_submitted` → `DataHarnessApp._stream_turn`
2. `AppSession.run_user_turn` → `Orchestrator.run_agentic_turn`
3. `Orchestrator._select_profile` (`ModeRouter.route` + continuity + write-back) → `prompt_profiles.load` → `Orchestrator.run_turn` → `RuntimeRequestBuilder.build_messages` → `LlamaCppRuntime.stream`
4. `RuntimeEvent`s flow back through `SyncToAsyncBridge` → wrapped as `HarnessEvent`s → `to_app_event` → `AppEvent`
5. `EventConsumer.dispatch` → `DataHarnessApp._handle_*` → widget updates

### Compact + Doctor (interactive cleanup flow)
- New events (harness): `DoctorNarrationReady`, `DoctorApprovalRequested`, `DoctorActionsApplied` (`src/harness/events.py`).
- New events (app): `AppChatHistoryCompacted`, `AppDoctorNarrationReady`, `AppDoctorApprovalRequested`, `AppDoctorActionsApplied` (`src/app/events.py`); all mapped in `src/app/event_mapping.py`.
- `Orchestrator.apply_doctor_actions(report_id, decision, workspace_id, workspace_dir, chat_id, action_ids=None)` reads `tmp_actions` rows, calls `Doctor.apply_tmp_action`, yields `DoctorActionsApplied`; selected `action_ids` limit application to checked doctor actions.
- `DoctorRunner.__init__(doctor, persistence, runtime, knowledge_manager, chat_store)` now persists `DoctorReport` + `TmpAction` rows during `run` (was previously sidebar-only), and full/semantic modes can mine chat memory or assess saved scripts through the runtime.
- `Orchestrator.compact_chat_history` now populates `replaced_turn_count` and `summary_token_estimate` on completed `ChatHistoryCompacted`; manual `user_requested` compaction passes `recent_turns_kept=0`, while token-pressure compaction keeps the compactor default recent window.
- LLM doctor narration + `DoctorNarrationReady`/`DoctorApprovalRequested` now emit from Layer 3 `DoctorRunner._narrate_and_request_approval` (`src/harness/services/doctor.py`), rendering via `src/harness/prompts/doctor_narrator.md` with a deterministic fallback. `AppSession.handle_direct_command` is a pure passthrough — it no longer wraps the doctor flow. (Off-canonical addition, see `docs/app/doctor-behaviour.md`.)
- `AppSession.handle_doctor_approval(*, state, workspace_dir, report_id, decision, action_ids=None)` calls `Orchestrator.apply_doctor_actions`.
- TUI: `ConversationPane.append_compaction`, `append_doctor_line`, `append_doctor_block` (`src/app/tui/widgets.py`); blocks `CompactionSummaryBlock`, `DoctorMessageBlock` (`src/app/tui/conversation.py`). Rehydrate renders `compacted_summary` role as `CompactionSummaryBlock`. New handlers in `DataHarnessApp`: `_handle_chat_history_compacted`, `_handle_doctor_narration_ready`, `_handle_doctor_approval_requested`, `_handle_doctor_actions_applied`; completed compaction rehydrates the active transcript and refreshes sidebar resources so chat counts update. Doctor action records render in `ApprovalBanner.show_doctor_review`, suppress stale clarification prompts, and dispatch selected ids through `_stream_doctor_approval`.
