# Custom Data Analysis LLM V1: Canonical System Specification

Date: 2026-04-23
Status: Canonical main specification
Purpose: unify the local harness specs and the multi-agent app spec into one layered v1 design
Supersedes:
- `2026-04-22-local-data-analysis-harness-overview.md`
- `2026-04-22-local-data-analysis-harness-orchestrator-and-control-loop.md`
- `2026-04-22-local-data-analysis-harness-worker-and-execution.md`
- `2026-04-22-local-data-analysis-harness-state-memory-and-doctor.md`
- `2026-04-22-local-data-analysis-harness-tui-and-verification.md`
- `2026-04-23-data-analysis-app-logic.md`

## 1. Purpose

This document defines the full v1 system for a custom data analysis LLM application.

The system is built in strict layers:

`LLM runtime -> execution worker -> harness core -> application layer`

The harness is the product core. The application layer is built on top of it. Without the harness, the TUI and agent modes do not have a reliable execution, memory, state, doctor, or provenance foundation.

This is not a generic chatbot shell. It is a stateful, evidence-grounded, local-first data analysis system whose final form includes a specialized application layer made up of a TUI plus agent modes.

The layer order is the implementation view. The runtime topology is different: the harness is the platform center, with runtime and worker below it and TUI plus agent modes as sibling consumers above it inside the application layer.

## 2. V1 Scope

### 2.1 In Scope

- fully local single-user operation
- custom LLM runtime for the chosen local model backend
- controlled Python execution for data analysis
- workspace-first operation with portable workspace folders
- durable state, memory, dataset knowledge, and validity tracking
- doctor and review capabilities as harness-owned platform functions
- direct user-invoked harness commands
- a chat-first but inspectable terminal UI
- an application layer made up of a TUI plus built-in agent modes for specialization and routing
- artifact-backed analytical answers with provenance

### 2.2 Out of Scope

- multi-user collaboration
- cloud execution
- autonomous self-modification of the harness
- unconstrained plugin execution
- hidden background maintenance loops that act without user visibility

## 3. System Principles And Dependency Model

### 3.1 Evidence Over Prose

The model may plan, suggest, and explain, but analytical truth comes from inspected inputs, executed code, and recorded artifacts.

### 3.2 Harness Is The Platform Core

The harness is the first layer that constitutes the real application. It owns orchestration, state, memory, context loading, doctoring, validation, retries, and provenance.

### 3.3 Layers Only Depend Downward

Dependencies are one-way across the major layers:

`LLM runtime -> execution worker -> harness core -> application layer`

Higher layers consume lower-layer services. They do not bypass them or take over their responsibilities.

Within the application layer, TUI and agent modes are sibling consumers of the harness rather than a strict runtime nesting where the TUI owns the agents.

### 3.4 Ownership Is Exclusive

Each major layer owns a distinct part of the system:

- runtime owns inference behavior
- worker owns execution behavior
- harness owns operational truth
- application layer owns the product surface built on top of the harness

Within the application layer:

- TUI owns presentation and operator controls
- agent modes own prompt identity and specialization policy

### 3.5 The App Becomes Usable In Stages

- after the runtime layer, the system can generate model output
- after the execution layer, the system can compute through controlled code execution
- after the harness layer, the system becomes a barebones but real analysis harness
- after the TUI sublayer, it becomes an operable product
- after the agent-modes sublayer, it becomes the full specialized data analysis app

## 4. Layer 1: LLM Runtime

### 4.1 Purpose

This layer makes model interaction possible and predictable.

It provides one managed model runtime for the application, not a fleet of parallel agent runtimes.

### 4.2 Core Capabilities

- local model backend integration
- inference adapter for the application
- token streaming
- reasoning capture policy
- context-window accounting
- tool-call decoding and retry behavior
- structured finish events and usage reporting

### 4.3 Runtime Contract

The runtime must expose a stable application-facing interface that supports:

- user and system message input
- streamed text deltas
- streamed reasoning deltas that can be separately handled
- structured tool-call events
- finish metadata
- deterministic error reporting when model output is malformed

### 4.4 Context-Window Handling

This layer is responsible for model-facing token accounting, not application-level context policy.

This layer should:

- report usable context-window limits
- expose token usage and pressure signals to the harness
- preserve message ordering and structured event boundaries passed into the model
- fail clearly when the harness submits malformed or over-budget input

Compaction policy belongs to the harness, which decides what context is loaded, trimmed, summarized, or persisted.

### 4.5 Tool-Call Protocol

The runtime must support structured tool calls as first-class outputs.

Malformed tool-call payloads should trigger a narrow correction path. If correction fails, the runtime must surface a model-behavior error rather than silently guessing.

### 4.6 Boundaries

This layer may own:

- inference behavior
- streaming behavior
- token accounting and model-facing message packaging
- tool-call parsing

This layer may not own:

- session state
- memory
- context policy
- application prompt identity
- execution policy
- provenance
- UI state
- routing policy

## 5. Layer 2: Execution Worker

### 5.1 Purpose

This layer makes controlled computation possible.

### 5.2 Core Capabilities

- sandboxed Python execution
- allowed package and runtime policy
- filesystem boundaries
- execution envelopes
- artifact generation and registration
- runtime metadata capture
- failure reporting for code execution

### 5.3 Execution Contract

The worker receives:

- executable step code
- declared inputs
- workspace paths
- package and permission envelope
- expected output contract
- run metadata

The worker returns a canonical execution envelope containing:

- `step_result.json`
- `step_report.md`
- stdout
- stderr
- artifact references
- execution metadata

This envelope must exist even on failure.

Step-scoped temporary execution files should be written under the active workspace at:

- `artifacts/tmp/<run_id>/<step_id>/`

### 5.4 Sandbox Rules

The initial v1 worker should enforce:

- read access limited to approved source data and registered artifacts in the active workspace
- write access limited to `artifacts/tmp/` in the active workspace
- no outbound network
- no arbitrary shell escape in the first version unless explicitly allowed by harness policy
- resource ceilings for time, memory, and artifact size

The worker may not mutate:

- `data/` after ingest
- `memory/`
- `state/`

### 5.5 Provenance Responsibilities

The worker must record enough raw execution evidence for later audit:

- code hash
- environment summary
- package versions where relevant
- input references
- produced artifact paths
- run id and step id
- timestamps

### 5.6 Failure Semantics

The worker must clearly distinguish:

- Python exception
- timeout or resource exhaustion
- missing output files
- malformed result JSON
- partial artifact generation

These are execution facts. The worker reports them but does not decide what they mean for the user.

### 5.7 Boundaries

This layer may own:

- code execution
- sandbox behavior
- artifact production
- raw runtime metadata

This layer may not own:

- planning
- memory updates
- semantic conclusions
- doctor decisions
- final answer authority

## 6. Layer 3: Harness Core

### 6.1 Purpose

This layer turns runtime plus execution into an actual analysis system.

It is the system's operational core and the first fully meaningful product layer.

### 6.2 Core Capabilities

- orchestrator and control loop
- single-runtime run state machine
- plan and step management
- workspace and app-state management
- direct harness command surface
- minimal harness-operational prompt assistance where deterministic rules are insufficient
- contract validation
- context loading and freshness rules
- durable state and memory
- dataset knowledge and validity tracking
- doctor and review workflows
- deterministic repair, retry, replan, and finish logic
- provenance and evidence checking

### 6.3 Orchestration And Control Loop

Every turn flows through the harness.

The harness runs the application as a single sequential control loop on top of one LLM runtime instance.

The harness must:

1. reload fresh durable context
2. resolve the active run state and active agent mode
3. construct or update a structured plan when needed
4. select the next executable step
5. generate the step contract
6. verify explicit plan or step approval when execution is required
7. dispatch the step to the execution worker when execution is required
8. inspect returned files and artifacts
9. decide whether to continue, retry, replan, ask for clarification, switch modes, or finish
10. persist the resulting state transitions

The harness is the only control-plane authority.

### 6.4 Run State Machine And Prompt Routing

The harness should own the application's explicit run state machine.

This state machine exists to keep the system local, sequential, and cheap enough to run on smaller machines.

The v1 system should not spawn parallel agent runtimes. It should reuse one managed runtime and switch prompt identity by state.

The harness may also own a minimal set of harness-operational prompts. These prompts are not app-defining prompts. They exist to give the runtime bounded context for harness decisions when deterministic logic is insufficient.

In v1 this prompt-assisted harness set should remain narrow:

- context compaction
- doctor tmp review and promotion decisions
- knowledge synthesis and reconciliation

Operational prompt outputs are advisory until the harness validates, records, and applies the resulting action.

The harness should track at least:

- active run state
- active agent mode
- current plan id
- current step id
- pending clarification
- pending review
- retry budget and attempt count
- latest doctor status
- active workspace id

Typical run states should include:

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

The harness decides transitions between these states. Higher layers may request a transition, but they do not own the transition rules.

Code execution approval is explicit in v1.

Before the harness dispatches a plan step to the execution worker, the user must have approved the executable plan or the specific executable step. This approval must not be inferred from timeout. If the user does not approve, the harness remains paused, asks for revision, or cancels according to the user's chosen control action.

For non-execution pauses, approval remains optional in v1. When the harness pauses for a non-execution decision, the user should have a 10-second decision window. If no action is taken in that window, the harness may proceed automatically unless the user has already cancelled, chosen to stop after the current step, or the pending action would run code.

### 6.5 Workspace And App-State Model

The application should be workspace-first.

One workspace is active at a time. The user may switch workspaces through the TUI, but the system should never operate on multiple workspaces concurrently in v1.

The durable unit of work is the workspace folder. It should be portable as a self-contained project directory.

The app should also maintain a small separate app store for global app concerns. This app store is not authoritative for work truth.

The workspace should own:

- copied source data
- generated artifacts
- durable user-facing memory files
- harness operational state for that work
- file registry, fingerprints, validity, and doctor history

The app store should own only:

- known workspace ids and paths
- recent workspaces
- last opened workspace
- basic app or UI preferences

Deleting the app store should not invalidate a workspace.

Recommended top-level app shape:

```text
<app_root>/
├── <app>/
│   └── app.json
├── harness/
│   ├── telemetry/
│   └── logs/
└── workspaces/
    └── w_0001/
        ├── data/
        ├── artifacts/
        ├── memory/
        │   ├── preferences.json
        │   ├── notes/
        │   │   └── gaps/
        │   └── functions/
        └── state/
            └── workspace.db
```

`<app_root>/harness/` should hold app-global harness telemetry, logs, and non-workspace operational files. It is not the source of truth for any workspace's analytical state.

Recommended workspace shape:

```text
<workspace>/
├── data/
├── artifacts/
│   └── tmp/
├── memory/
│   ├── preferences.json
│   ├── notes/
│   │   └── gaps/
│   └── functions/
└── state/
    └── workspace.db
```

### 6.6 Control Objects And Validation

The harness owns and validates the canonical control objects:

- run-state records
- mode-switch events
- approval records
- plan objects
- step contracts
- execution envelopes
- step result envelopes
- prompt-package records
- doctor reports
- review proposals
- memory update proposals

Validation must distinguish:

- parse failure
- schema mismatch
- deterministic repair candidate
- execution failure
- semantic failure

The harness must know what failed before deciding what to do next.

The canonical control objects should be JSON-compatible, versioned, and typed enough to support validation, durable storage, and later JSON Schema generation. The main specification defines the required behavioral fields and invariants. The implementation plan may choose the concrete schema library.

All canonical objects should include:

| Field | Requirement |
| --- | --- |
| `schema_version` | Stable version string for migration and validation. |
| `id` | Stable object id unique within its object type and workspace. |
| `workspace_id` | Active workspace id when the object belongs to workspace truth. |
| `created_at` | ISO 8601 timestamp. |
| `updated_at` | ISO 8601 timestamp when the object can change after creation. |
| `status` | Object-specific status enum when the object has a lifecycle. |

Path-bearing fields should store workspace-relative paths unless the object explicitly represents an external source before ingest. Persisted artifact and memory references should not depend on absolute machine-local paths.

The required v1 contract shape is:

| Object | Required fields | Key invariants |
| --- | --- | --- |
| `RunStateRecord` | `run_id`, `state`, `active_agent_mode`, `plan_id`, `step_id`, `retry_budget`, `attempt_count`, `pending_clarification_id`, `pending_review_id`, `latest_doctor_report_id` | `state` must be one of the declared run states. `step_id` must belong to `plan_id` when both are present. |
| `ModeSwitchEvent` | `run_id`, `from_mode`, `to_mode`, `reason`, `requested_by`, `accepted` | Mode switches are append-only events. Rejected switches must record a reason. |
| `ApprovalRecord` | `run_id`, `target_type`, `target_id`, `approval_kind`, `decision`, `decided_by`, `decided_at`, `expires_at` | Code execution approval must have `decision` set to `approved` before dispatch and must not be created by timeout. Timeout-based approval may apply only to eligible non-execution decisions. |
| `Plan` | `run_id`, `goal`, `status`, `steps`, `requires_code_execution`, `approval_status`, `approval_record_id` | Plans that require worker execution must have explicit approval before any executable step runs. |
| `PlanStep` | `plan_id`, `step_order`, `purpose`, `kind`, `status`, `declared_inputs`, `expected_outputs`, `depends_on` | `step_order` is stable inside a plan. Executable steps must produce a `StepContract` before dispatch. |
| `StepContract` | `run_id`, `plan_id`, `step_id`, `code`, `declared_inputs`, `workspace_paths`, `permission_envelope`, `expected_output_contract`, `run_metadata` | Code execution must use an approved plan or step. Inputs and writable paths must satisfy worker sandbox policy. |
| `ExecutionEnvelope` | `run_id`, `step_id`, `status`, `step_result_path`, `step_report_path`, `stdout_path`, `stderr_path`, `artifact_refs`, `execution_metadata`, `failure_kind` | The envelope exists even on failure. Referenced files must be under the step tmp directory or promoted artifact paths. |
| `StepResult` | `run_id`, `step_id`, `status`, `observations`, `claims`, `artifact_refs`, `metrics`, `failure_summary` | Claims must reference evidence or be marked as unsupported. Failures must not be converted into analytical claims. |
| `PromptPackage` | `run_id`, `agent_mode`, `prompt_template_id`, `prompt_template_version`, `context_refs`, `token_budget`, `reasoning_capture_policy` | Prompt packages are records of what was sent, not durable analytical truth. |
| `DoctorReport` | `workspace_id`, `trigger`, `status`, `source_findings`, `validity_changes`, `lineage_findings`, `tmp_review`, `tmp_actions`, `recommendations` | Reports must record findings before cleanup actions are applied. No doctor outcome silently overwrites prior state. |
| `TmpAction` | `doctor_report_id`, `item_path`, `action`, `destination_path`, `reason`, `decision_source`, `applied` | Cleanup actions are reviewable before application. Referenced or failed-run evidence cannot be deleted until no active run, provenance record, or pending review depends on it. |
| `ReviewProposal` | `run_id`, `proposal_type`, `source_refs`, `proposed_changes`, `rationale`, `status` | Durable learning and destructive maintenance decisions must pass through a reviewable proposal path. |
| `MemoryUpdateProposal` | `run_id`, `memory_target`, `source_refs`, `proposed_content`, `conflicts`, `status` | Memory updates must identify source evidence and conflicts before being committed. |

Object statuses should be narrow enums rather than free text. Validation failures should preserve the invalid payload and the reason it failed, so deterministic repair, retry, or user review can operate on a concrete record.

### 6.7 Deterministic Repair, Retry, And Replan

The harness should apply safe deterministic repair before spending another model call on purely mechanical failures.

Examples include:

- type normalization
- wrapper repair
- metadata insertion
- path normalization

If repair is insufficient, the harness chooses a targeted retry path:

- output repair for malformed structured output
- field or schema retry for validation mismatch
- code repair and rerun for computation failure
- replan when the existing plan is no longer appropriate

Retry loops must be explicit, budgeted, and visible.

The harness should also own deterministic maintenance work that does not require agent-style specialization.

Examples include:

- source rescans
- fingerprint recomputation
- stale-state detection
- lineage break detection
- doctor report generation

### 6.8 Context Management And Compaction

The harness rebuilds working context every turn from durable sources rather than trusting chat history.

Fresh context may include:

- session ledger
- user preferences
- dataset knowledge
- dataset fingerprints
- prior analyses
- unresolved doctor findings
- current validity states

Conversation is the interface. Durable state is the source of truth.

The harness also owns context compaction as part of context management.

Compaction should:

- reduce context pressure without treating summaries as durable truth
- preserve operationally atomic units such as tool calls and tool outputs
- keep the active plan, current step, recent execution evidence, and unresolved failures available
- prefer reconstructing context from ledger and memory state over blindly retaining long chat transcripts

The runtime reports token limits and pressure. The harness decides what to keep, summarize, drop, or reload.

Compaction may use a narrow harness-operational prompt when deterministic trimming is insufficient. The goal is to preserve operational meaning, not to create new durable truth.

### 6.9 Storage Model

The storage model should balance reliability with local inspectability.

The recommended v1 approach is hybrid:

- SQLite for structured operational truth
- plain files for user-facing and editable content

`state/workspace.db` should be authoritative for:

- workspace metadata
- file inventory and fingerprints
- run ledger
- plan and step records
- validity state
- doctor history
- artifact registry
- note and function indexing
- mode-switch and run-state history
- step logs and step-level action history

`memory/` files should be primary for:

- user preferences
- reusable notes in markdown
- reusable analysis functions as `.py` files

The workspace should keep raw inputs in `data/` and generated outputs in `artifacts/`.

Workspace path ownership should be strict:

- `data/` is copied source input and becomes read-only after ingest
- `artifacts/tmp/` is worker scratch space for step-scoped execution evidence
- durable `artifacts/` paths outside `tmp/` are harness-promoted outputs worth keeping
- `memory/` is harness-managed durable workspace memory that the user may inspect or edit
- `state/` is harness-only operational state

The app store under `<app_root>/<app>/app.json` should remain intentionally small and should not duplicate workspace truth.

### 6.10 Direct Harness Command Surface

The harness should expose a direct command surface that the user can invoke through the TUI without going through agent mode first.

This direct surface should include:

- `doctor`
- `compact_context`
- workspace status and inventory inspection
- artifact inspection
- memory review
- validity and provenance inspection
- rerun, retry, and cancellation controls

These are harness-owned platform functions. Agent modes may also use them, but they do not own them.

### 6.11 Validity And Fingerprinting

Every reusable conclusion must be tied to the data that produced it.

The harness should track:

- file fingerprints
- file size and modified timestamp metadata for lazy fingerprint checks
- schema fingerprints
- optional lightweight profile fingerprints
- lineage from source data to plan to step to artifact to conclusion

Fingerprinting policy in v1 should be lazy after first ingest:

- on first ingest of a new workspace file, the harness computes and stores the full file fingerprint
- on later workspace-open or doctor-triggered rescans, the harness first checks the stored file size and modified timestamp
- if both file size and modified timestamp are unchanged, the harness reuses the stored fingerprint without re-hashing the full file
- if either file size or modified timestamp changed, the harness recomputes the full fingerprint and updates the stored metadata

This lazy check is deterministic and should be the default path on lower-spec local machines. Full re-hashing remains the fallback when file metadata indicates possible change.

Validity states should include:

- `ok`
- `changed`
- `stale`
- `needs_review`
- `revalidated`
- `broken_lineage`

No prior conclusion should be silently overwritten.

### 6.12 Doctor And Review

Doctor is a harness-owned platform function. It is not fundamentally an agent-owned subsystem.

Doctor should:

- rescan tracked sources
- recompute fingerprints only when lazy fingerprint checks detect file change
- detect drift, missing files, schema changes, broken lineage, stale saved functions, and orphans
- determine what remains valid and what requires rerun or review
- emit a structured doctor report

Doctor should be callable directly by the TUI, by harness control logic, or by higher-level agent flows when they need maintenance diagnostics.

For source files, doctor should use lazy fingerprinting by default:

- read stored file size and modified timestamp metadata
- compare current file size and modified timestamp against the stored values
- skip full file hashing when neither value changed
- recompute and store a new full fingerprint only when file metadata changed or no stored fingerprint exists yet

This is a deterministic Python path and should prevent doctor from feeling frozen on slower local disks when large files have not actually changed.

Doctor also owns temporary artifact cleanup inside `artifacts/tmp/`.

Tmp review should run before any cleanup action is applied.

That review should run:

- on workspace open
- after the data analyst mode completes a task
- on explicit manual doctor invocation

Tmp review is primarily deterministic, but doctor may use a narrow harness-operational prompt when it needs workspace-aware judgment about whether a tmp item should be deleted, promoted, or kept temporarily.

That judgment may inspect:

- workspace memory
- saved functions
- notes and gaps
- recorded user preferences

The result of tmp review is a set of proposed `TmpAction` records in the doctor report. Cleanup may be applied only after the report records the review findings and the action remains valid against current run state, provenance references, and pending reviews. Tmp cleanup and promotion are non-execution decisions, so they may use the 10-second timeout path after review unless the user cancels, chooses to stop, or the action is blocked by a live reference.

When a tmp item is promoted, the mapping should be explicit:

- reusable code -> `memory/functions/`
- durable semantic note -> `memory/notes/`
- unresolved semantic issue -> `memory/notes/gaps/`
- user-facing output, chart, table, or report -> durable `artifacts/`

Otherwise the tmp item may be deleted only if it is not referenced by an active run, pending review, failure envelope, provenance record, or saved artifact registry entry.

Doctor reports must log every tmp action, including:

- item identity and path
- trigger context
- action taken: `deleted`, `promoted`, or `kept_temporarily`
- destination if promoted
- reason for the decision
- whether the action was deterministic or LLM-assisted

Review is the lighter workflow for proposing durable learning updates after a session or on demand.

### 6.13 Knowledge And Function Management

The harness should provide stable capabilities for:

- user preference retrieval and update
- dataset metadata retrieval and update
- knowledge notes
- saved reusable analysis functions
- freshness checks before saved-function reuse

Knowledge and function management is not just CRUD over existing memory. It also includes bounded synthesis and reconciliation of durable workspace knowledge when deterministic storage rules are insufficient.

Examples include:

- turning direct user teaching into reusable notes or function candidates
- reconciling overlapping or conflicting notes
- deciding whether a learned item should become a preference, note, gap, or saved function candidate

The harness should rescan workspace-backed memory files on workspace open and whenever doctor runs, then reconcile those files against `workspace.db` indexes and state.

These are harness capabilities even when agents invoke them.

### 6.14 Provenance

Every important claim must be traceable to:

- source files
- fingerprints
- executed code identity
- artifacts
- plan and step lineage
- current validity state
- active prompt mode
- prompt template identity or version where relevant

The harness is the owner of provenance rules.

### 6.15 Telemetry And Logging

Telemetry and logging are first-class harness concerns. They are operational observability, distinct from the analytical persistence records defined in §6.6 (`StepResult`, `ApprovalRecord`, `LineageRecord`, `DoctorReport`, `MemoryUpdateProposal`). Persistence is the source of truth for analytical state; telemetry is the source of truth for *what the system did and when*.

#### 6.15.1 Streams

Every layer (runtime, worker, harness, application) must emit two parallel streams:

- a **structured event stream** (`.events.jsonl`, append-only, one JSON object per line) intended for machine consumption, audit, replay, and debug tooling
- a **human-readable log** (`.log`, line-oriented, rotated by size) intended for operator inspection

Both streams describe the same events. The structured stream is canonical; the human log is a rendering.

#### 6.15.2 Sinks And Layout

Application-global telemetry lives under `<app_root>/harness/`:

```text
<app_root>/harness/
├── telemetry/
│   ├── runtime.events.jsonl
│   ├── worker.events.jsonl
│   ├── harness.events.jsonl
│   └── app.events.jsonl
└── logs/
    ├── runtime.log
    ├── worker.log
    ├── harness.log
    └── app.log
```

Workspace-scoped events (anything carrying a `workspace_id`) must be **mirrored** into `<workspace>/state/telemetry/` so a workspace can be inspected, archived, or moved without losing its operational history. Mirroring is additive; the app-global stream is never truncated to satisfy a workspace.

#### 6.15.3 Event Schema

Every structured event must include:

- `schema_version` — string, telemetry schema version
- `ts` — ISO-8601 UTC timestamp
- `layer` — one of `runtime | worker | harness | app`
- `component` — sublayer identifier (e.g. `orchestrator`, `validity_manager`, `tui.session`)
- `event` — dotted event name (e.g. `runtime.dispatch.started`, `worker.step.finished`, `harness.approval.granted`)
- `severity` — `debug | info | warn | error`
- `correlation` — object containing all applicable IDs: `session_id`, `workspace_id`, `turn_id`, `run_id`, `step_id`, `approval_id`, `proposal_id`
- `payload` — event-specific structured fields
- `duration_ms` — required on any `*.finished` or `*.failed` event

Unknown or unbounded user content (free text prompts, raw tool-call arguments) must not be embedded in `payload` verbatim if it exceeds a configured size; instead emit a digest plus a reference to the persisted artifact.

#### 6.15.4 Correlation Rules

- A user turn opens a `turn_id`. Every event produced while handling that turn carries the same `turn_id`.
- A plan execution opens a `run_id`. Every step opens a `step_id` scoped to that run. Worker, runtime, and harness events emitted on behalf of a step must carry both.
- Approvals, clarifications, and memory proposals carry their own IDs and the enclosing `turn_id`.
- The application layer is responsible for opening `turn_id`. Lower layers must not invent correlation IDs the harness has not assigned.

#### 6.15.5 Layer Obligations

Each layer must, at minimum, emit:

- **Runtime (L1):** `runtime.dispatch.{started,token,finish,error}`, including model id, prompt token count, completion token count, finish reason, and (on error) the malformed buffer reference.
- **Worker (L2):** `worker.step.{started,finished,failed,timeout}`, including `StepContract` digest, sandbox limits applied, exit code, `started_at`, `finished_at`, `duration_ms`, and `StepResult` reference.
- **Harness (L3):** `harness.run.{started,completed,failed}`, `harness.approval.{requested,granted,rejected,auto_proceeded,timed_out}`, `harness.repair.{attempted,succeeded,failed}`, `harness.replan.triggered`, `harness.validity.{ok,changed,stale,needs_review,revalidated,broken_lineage}`, `harness.doctor.{opened,tmp_action,closed}`, `harness.memory.proposal.{created,approved,applied,rejected}`, `harness.context.{compaction_started,compaction_finished,token_pressure_gate}`.
- **Application (L4):** `app.session.{opened,closed}`, `app.command.{invoked,completed}`, `app.workspace.switched`, `app.mode.{switched,rejected}`, `app.user.{prompt_submitted,approval_decision,clarification_submitted}`.

#### 6.15.6 Retention And Rotation

Both streams rotate by size with bounded backups (default: 10 MB per file, 5 backups). The structured stream must rotate atomically — partial JSON lines are not permitted. Workspace-mirrored telemetry follows the same policy and is preserved with the workspace on archive.

#### 6.15.7 Redaction

V1 runs locally with no third-party sinks, so dataset cell values, model outputs, and prompt content may be recorded in full. The schema must nonetheless reserve a `redactions` field on every event so a future deployment can apply policy without breaking consumers. Secrets (API keys, OS credentials, environment variables marked sensitive) must never be written to either stream regardless of profile.

#### 6.15.8 Relationship To Persistence

Telemetry references persistence; it does not duplicate it. A `worker.step.finished` event carries `step_result_id`, not the full `StepResult`. A `harness.approval.granted` event carries `approval_id`, not the approval payload. Persistence remains the source of truth for analytical state; telemetry remains the source of truth for the operational timeline. The two must agree: every persisted `StepResult`, `ApprovalRecord`, `LineageRecord`, and applied `MemoryUpdateProposal` must be reachable from a telemetry event whose `correlation` matches the record's IDs.

#### 6.15.9 Failure Mode

Telemetry write failures must not crash the harness. They must be reported on a fallback stderr channel and counted; sustained failure must surface to the application layer as a degraded-observability warning rather than a silent loss.

### 6.16 End-Of-Layer Result

At the end of this layer, the application already works as a barebones but real analysis harness:

- it can converse through the runtime
- it can create and run structured analysis steps
- it can inspect artifacts
- it tracks and logs every worker step
- it can remember user and dataset knowledge
- it can detect stale prior conclusions
- it can return evidence-backed answers

## 7. Layer 4: Application Layer

### 7.1 Purpose

This layer turns the harness into the actual product the user experiences.

It has two sibling sublayers built on top of the harness:

- `4a. TUI`
- `4b. agent modes`

The application layer does not exist without the harness.

### 7.2 Layer 4a: TUI

This sublayer makes the harness operable and inspectable.

### 7.3 TUI Core Capabilities

- conversation pane
- process and status visibility
- plan visibility
- artifact inspection
- operator controls
- clarification flow
- failure visibility
- provenance visibility

### 7.4 TUI Operating Model

The UI is chat-first, but the user must not be forced to infer system state from one scrolling transcript.

The UI should provide distinct surfaces for:

- active workspace
- active conversation
- current plan
- step execution status
- artifacts and results
- active context and memory summary
- doctor and validity warnings

### 7.5 TUI Required Controls

The user must be able to:

- switch workspace
- inspect workspace status
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
- mark a result trusted or invalidated

### 7.6 TUI Process Visibility

The UI should expose the harness and agent activity stream in a structured way, including:

- active layer or agent
- tool activity
- handoffs
- status transitions
- errors
- final outcome

Reasoning should be summarized appropriately, not dumped as raw internal text.

### 7.7 TUI Clarification Flow

Clarification must be a first-class UI path, not a hacked conversational side effect.

When the harness or an agent needs specific user input to proceed safely, the UI should surface the question cleanly and allow the run to resume from that decision point.

The TUI renders the clarification interface, but the harness owns the underlying clarification state and resume rules.

### 7.8 TUI Failure And Provenance UX

The UI should make it easy to inspect:

- what failed
- why it failed
- what the system attempted in response
- what data and artifacts support a claim
- whether the claim is currently valid, stale, or in need of review

### 7.9 Layer 4b: Agent Modes

These prompt modes specialize the harness into a purpose-built data analysis app.

### 7.10 Agent Purpose

This sublayer gives the system its identity, voice, and domain behavior through prompts and prompt logic.

### 7.11 Built-In Agent Modes

The v1 agent set should include:

- interaction agent
- data analyst agent
- knowledge agent

### 7.12 Agent Role Model

Agents in v1 are not separate concurrent runtimes. They are harness-managed prompt modes that run sequentially on the single runtime.

Agents own prompt definitions, prompt logic, and specialization policy. They do not own control-plane state.

- `interaction`
Owns the front-door interaction policy. It handles non-analytical conversation, decides when a turn should route to analyst or knowledge behavior, and requests clarification when intent is too ambiguous to proceed safely.

- `data analyst`
Turns analysis intent into harness actions and evidence-backed responses.

- `knowledge`
Captures reusable semantic knowledge into harness-owned memory stores.

### 7.13 Prompt Ownership

Layers 1, 2, and 4a should not contain prompts.

Layer 3 may own a minimal set of harness-operational prompts for bounded control and maintenance work.

Layer 4b should own the app-defining prompts:

- role prompt templates
- prompt assembly rules for each agent mode
- response style and behavioral framing
- domain-specific instructions for analysis and knowledge capture
- prompt-level rules for when a mode should request a handoff

This is the application's soul. The lower layers provide the body and the control system. Layer 4b defines how the app behaves as a data analysis product rather than a generic LLM shell.

Layer 3 prompts are harness-specific rather than app-defining. They help the runtime decide bounded what, how, where, and why questions for harness-owned tasks.

### 7.14 Harness-Client Rule

Agents must use harness-owned services for:

- planning
- execution
- memory updates
- knowledge retrieval
- doctor invocation and doctor reports
- provenance checks
- validity status
- clarification handoffs

Agents do not create parallel versions of these capabilities.

The harness chooses when to activate a prompt mode and supplies the prompt package to the runtime.

### 7.15 No Shadow Ownership

Agents may not own:

- runtime process management
- run-state transitions
- durable persistence semantics
- execution policy
- provenance rules
- validity rules
- doctor policy and maintenance diagnostics
- artifact truth
- platform retry or repair logic

They may trigger these mechanisms, but the harness defines and enforces them.

### 7.16 Behavioral Flows On Top Of Harness Capabilities

The agent-modes sublayer should implement the following application behaviors:

1. `analysis loop`
The analyst agent uses harness planning, execution, artifact inspection, knowledge retrieval, and saved-function reuse to answer analytical questions.

2. `knowledge capture loop`
The knowledge agent turns user teaching, file semantics, metric definitions, and reusable logic into harness memory or saved-function updates.

3. `gap loop`
The analyst can record an unresolved semantic gap. The knowledge agent later resolves it through harness-owned memory updates.

4. `drift loop`
The harness detects drift, runs doctor as needed, and produces structured maintenance findings. The TUI exposes those findings and lets the user inspect what changed, what remains valid, and what should be rerun or reviewed.

5. `clarification loop`
When intent or semantics are insufficiently specified, the interaction agent requests clarification. The harness records the clarification state, and the TUI renders the prompt and resumes the harness flow once the user responds.

### 7.17 End-Of-Layer Result

At the end of this layer, the system becomes the full specialized data analysis application:

- specialized routing
- unified front-door interaction handling
- domain-aware analysis behavior
- app-specific identity through prompt modes
- structured knowledge capture
- harness-owned maintenance surfaced through the TUI
- explicit clarification handling

The harness remains the product core. The application layer makes it operable, expressive, and purpose-built.

## 8. Cross-Layer Linkage Contract

### 8.1 Runtime Topology

The implementation layers are ordered downward, but the running application is centered on the harness.

The v1 runtime topology should be:

```text
TUI ─┐
     ├─ application session ──> harness orchestrator ──> runtime
agent modes ────────────────┘              │
                                           └────────────> execution worker
```

The application session is a thin Layer 4 adapter. It may compose TUI input, agent-mode prompt packages, and harness calls, but it may not become a second orchestrator.

The harness remains the control-plane authority. It validates mode changes, owns run-state transitions, gates execution approval, dispatches worker steps, records provenance, and persists durable state.

### 8.2 Dependency Direction

Code dependencies must preserve layer ownership:

- Layer 4 may import and call Layer 3 harness services.
- Layer 3 may import and call Layer 2 worker services and Layer 1 runtime services.
- Layer 3 must not import Layer 4 application modules.
- Layer 2 must not import harness or application modules.
- Layer 1 must not import worker, harness, or application modules.

When the harness needs application-owned prompt material, Layer 4 should inject it through a narrow interface rather than requiring the harness to import application code. The harness may accept a prompt provider, prompt package record, requested mode, or mode-switch request, but the harness must validate and record the resulting action before it affects run state.

### 8.3 Turn Linkage

Every user turn should follow one visible control path:

1. The TUI receives user input and sends it to the application session with the active workspace and run state.
2. The application session asks the agent-mode layer for a requested prompt mode or prompt package.
3. The application session calls the harness orchestrator with the user input, active workspace, current run state, and requested prompt context.
4. The harness reloads fresh durable context from workspace state and memory.
5. The harness accepts, rejects, or records any requested mode switch.
6. The harness constructs the runtime request using the selected prompt package and fresh context.
7. The harness calls the single managed runtime.
8. If the next action requires code execution, the harness creates or validates the plan and step contract, verifies explicit approval, and dispatches the worker.
9. The worker returns an execution envelope and step files under the workspace.
10. The harness inspects the worker evidence, records state, provenance, prompt package records, execution envelopes, and validity changes, then decides the next state.
11. The application session converts the harness result into a TUI-ready view model without changing the decision.
12. The TUI renders the answer, status, plan, artifacts, failures, approval prompts, or clarification prompts.

No layer may skip the harness for planning, execution, memory update, doctor, provenance, validity, or retry decisions.

### 8.4 Prompt Package Linkage

Layer 4b owns application-defining prompt templates and prompt assembly rules.

The harness owns activation and recording:

- the active mode in run state
- mode-switch events
- prompt package records
- runtime request construction
- token budget checks using Layer 1 runtime signals
- validation of structured outputs and tool calls

The prompt package passed into the harness should be treated as an input record, not as durable analytical truth. The harness persists what was used so later provenance can explain which prompt mode shaped an answer.

### 8.5 Worker Linkage

Layer 2 execution is reachable only through harness dispatch.

The harness must translate an approved `StepContract` into the worker's execution request, enforce workspace-relative path rules, provide the permission envelope, and persist the returned `ExecutionEnvelope`.

The TUI and agent modes may request or describe execution, but they must not call the worker directly.

### 8.6 Persistence Linkage

The harness should persist cross-layer events as workspace truth:

- run-state records and transitions
- mode-switch events
- prompt package records
- plans, steps, and step contracts
- approval records
- execution envelopes and step results
- artifact registry and provenance records
- doctor reports, tmp actions, and review proposals

Layer 4 may keep transient UI state, but durable analytical state belongs in the workspace through harness-owned persistence.

## 9. Cross-Layer End-To-End Flows

### 9.1 First Dataset Added

The TUI ingests the file into the active workspace. The harness registers it as a new source. The agent-modes sublayer may route to knowledge or analyst behavior depending on user intent.

The user may also invoke harness commands directly at this point, for example to run doctor or inspect workspace status before entering an agent mode.

### 9.2 First Analysis On New Data

The user asks a question. The interaction agent handles the front-door turn and routes analytical work to the analyst. The harness assembles fresh context and creates a plan. If computation is needed, the harness pauses for explicit executable plan or step approval before dispatching the worker. It then inspects returned artifacts, records provenance, and returns an evidence-backed answer through the TUI.

### 9.3 Follow-Up Analysis With Reused Knowledge

The harness reloads user preferences, dataset knowledge, saved-function availability, and validity status. The analyst uses those harness services to avoid repeating avoidable work while still respecting freshness checks.

### 9.4 Drift Detection And Doctor Review

The harness detects data drift through fingerprint mismatch and marks affected knowledge or conclusions accordingly. It can run doctor directly and produce a structured report. The TUI lets the user review what changed and what should be rerun, refreshed, removed, or preserved.

### 9.5 Saved Function Reuse

The analyst attempts to reuse a saved function. The harness verifies source and schema freshness before execution. If valid and execution is needed, the harness pauses for explicit executable plan or step approval before dispatching the worker. If stale, the harness blocks unsafe reuse and directs the next recovery step.

## 10. V1 Acceptance Criteria

The system should not be considered correct unless all of the following are true:

- no analytical claim is accepted without inspected evidence
- no artifact-backed conclusion lacks provenance
- no saved knowledge is reused after material source change without validity handling
- no doctor outcome silently overwrites prior state
- no agent bypasses harness ownership boundaries
- no UI hides critical failures or uncertainty
- no retry loop runs invisibly without bounded control
- no durable memory update occurs without a defined reviewable path
- no code execution occurs without explicit executable plan or step approval
- no tmp cleanup or promotion occurs before recorded tmp review
- no persisted control object (`StepResult`, `ApprovalRecord`, `LineageRecord`, applied `MemoryUpdateProposal`, `DoctorReport`) lacks a matching telemetry event whose correlation IDs resolve to it

## 11. Why This Structure

This structure makes the system readable as both architecture and implementation guidance.

It preserves the dependency order of the system while keeping each layer capability-oriented:

- runtime explains how the model is integrated
- worker explains how computation is executed
- harness explains how truth, memory, and control are maintained
- application layer explains how the product is operated and specialized

That is the intended v1 shape of the custom data analysis LLM application.
