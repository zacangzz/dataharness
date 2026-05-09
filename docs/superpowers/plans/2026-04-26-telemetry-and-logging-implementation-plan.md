# Telemetry and Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec anchor:** This plan implements `docs/superpowers/specs/2026-04-23-custom-data-analysis-llm-v1-main-spec.md` §6.15 (Telemetry And Logging) and §10 acceptance invariant: *no persisted control object lacks a matching telemetry event whose correlation IDs resolve to it*. Every event schema field, sink path, layer obligation, correlation ID, retention rule, redaction rule, and persistence-linkage rule below is dictated by §6.15.1–§6.15.9.

**Goal:** Implement spec-compliant per-layer observability so that (a) every persisted control object (`StepResult`, `ApprovalRecord`, `LineageRecord`, applied `MemoryUpdateProposal`, `DoctorReport`) is reachable from at least one telemetry event by correlation IDs, and (b) a blank-screen failure, startup crash, stalled model call, harness state bug, worker sandbox failure, or persistence write problem is diagnosable from files on disk without attaching a debugger.

**Architecture:** Add `src/observability/` with a typed JSONL telemetry writer, per-layer rotating logs, early bootstrap logging, and `contextvars`-based correlation propagation. Sinks live under `<app_root>/harness/telemetry/` and `<app_root>/harness/logs/` (canonical, app-global) and are mirrored to `<workspace>/state/telemetry/` for any event carrying a `workspace_id`. `src/cli.py` configures logging before importing any app/harness/runtime/worker module. Every layer emits both a structured event stream (`<layer>.events.jsonl`) and a human-readable log (`<layer>.log`); both are rendered from the same in-process event object so they cannot drift.

**Tech Stack:** Python 3.12, `pydantic` v2, stdlib `logging`, `logging.handlers.RotatingFileHandler`, `contextvars`, `pytest`, existing app/runtime/harness/worker packages.

---

## Required Outcome

After this plan is implemented, the following must hold:

1. **Spec §10 telemetry invariant.** A test loads every persisted `StepResult`, `ApprovalRecord`, `LineageRecord`, applied `MemoryUpdateProposal`, and `DoctorReport` from a workspace, and proves each one is reachable from at least one telemetry event whose `correlation` IDs resolve to that record.
2. **Blank-app diagnosability.** With no debugger and only files on disk, an operator can localize a failure to one of: bootstrap, import, app construction, compose, mount, render, screen, session, controller, harness, runtime, worker, persistence.
3. **Triage commands work.**

```bash
# blank-app triage
grep -E "bootstrap|app\.(lifecycle|compose|mount|render|screen|widget|error)" \
  <app_root>/harness/logs/bootstrap.log <app_root>/harness/logs/app.log

# correlated turn trace across layers
grep "turn=<turn_id>" <app_root>/harness/logs/*.log

# spec §10 reverse lookup: persisted record -> telemetry event
jq --arg sid "<step_id>" 'select(.correlation.step_id==$sid)' \
  <app_root>/harness/telemetry/*.events.jsonl

# error sweep
jq 'select(.severity=="error")' <app_root>/harness/telemetry/*.events.jsonl
```

## File Structure

**Create:**

- `src/observability/__init__.py` — re-export `Telemetry`, `TelemetryEvent`, `Layer`, `Severity`, `Correlation`, `configure_logging`, `bind_boot`, `bind_session`, `bind_workspace`, `bind_turn`, `bind_run`, `bind_step`, `bind_approval`, `bind_proposal`, current-id helpers.
- `src/observability/events.py` — `TelemetryEvent`, `Layer`, `Severity`, `Correlation`, `EventName` (string-validated against allowlist), and validation rules.
- `src/observability/telemetry.py` — JSONL writer, log mirror, correlation context managers, `emit_error` helper, atomic-line file appends, fallback-stderr-on-write-failure, app-global+workspace-mirror dual sinks.
- `src/observability/logging_setup.py` — early logging bootstrap, per-layer `RotatingFileHandler`, correlation-aware filter, `sys.excepthook` and `threading.excepthook` hooks, optional `DATAHARNESS_LOG_STDERR=1` mirror.
- `src/observability/runtime_paths.py` — resolve `<app_root>/harness/{telemetry,logs}/` from source runs and PyInstaller bundles; resolve `<workspace>/state/telemetry/` from a workspace path.
- `src/observability/redaction.py` — identity redactor for v1; reserves `redactions` field on every event so policy can be added without breaking consumers (§6.15.7).
- `src/observability/correlation.py` — `Correlation` pydantic model + `ContextVar` set + `bind_*` context managers.
- `tests/observability/test_events.py`
- `tests/observability/test_telemetry.py`
- `tests/observability/test_logging_setup.py`
- `tests/observability/test_bootstrap.py`
- `tests/observability/test_app_blank_diagnostics.py`
- `tests/observability/test_app_instrumentation.py`
- `tests/observability/test_harness_instrumentation.py`
- `tests/observability/test_runtime_instrumentation.py`
- `tests/observability/test_worker_instrumentation.py`
- `tests/observability/test_workspace_mirror.py`
- `tests/observability/test_persistence_linkage.py` — implements §10 telemetry invariant.
- `tests/observability/test_end_to_end_trace.py`

**Modify:**

- `src/cli.py` — remove top-level `from app.tui.app import DataHarnessApp`; configure logging first; emit bootstrap events around path resolution, import, app construction, run start, run end, and any error.
- `src/app/tui/app.py` — emit lifecycle, compose, mount, render/screen snapshot, widget-health, and Textual error events.
- `src/app/tui/controller.py` — emit controller input, command, approval, workspace-switch, and exception events.
- `src/app/session.py` — open `session_id` and `turn_id`; emit session/turn start/end/error; inject shared `Telemetry` into router and orchestrator.
- `src/app/agents/router.py` — emit `app.mode.proposed` / `app.mode.switched` / `app.mode.rejected` with reason and prompt template id.
- `src/harness/orchestrator.py` — emit turn, mode-activation, context rebuild, prompt build, runtime dispatch, plan built, approval lifecycle, dispatch, resume, completion, repair/replan, and error events.
- `src/harness/persistence.py` — stamp `telemetry_event_id` inside saved JSON records for every persisted control object listed in §6.15.8; emit `persistence.write.{started,finished,failed}`.
- `src/harness/db.py` — no physical schema change; add JSON-querying helpers used by tests.
- `src/harness/validity.py` — emit `harness.validity.{ok,changed,stale,needs_review,revalidated,broken_lineage}`.
- `src/harness/doctor.py` — emit `harness.doctor.{opened,tmp_action,closed}`.
- `src/harness/knowledge.py` — emit `harness.memory.proposal.{created,approved,applied,rejected}`.
- `src/harness/approval.py` — emit `harness.approval.{requested,granted,rejected,auto_proceeded,timed_out}`.
- `src/harness/repair.py` — emit `harness.repair.{attempted,succeeded,failed}` and `harness.replan.triggered`.
- `src/harness/context_manager.py` — emit `harness.context.{compaction_started,compaction_finished,token_pressure_gate}`.
- `src/runtime/llama_cpp_runtime.py` — emit `runtime.dispatch.{started,token,finish,error}` per §6.15.5.
- `src/runtime/protocol.py` — document telemetry contract; no signature change.
- `src/worker/executor.py` — emit `worker.step.{started,finished,failed,timeout}`.
- `src/worker/sandbox_bootstrap.py` — write inherited correlation IDs into envelope metadata; emit subprocess bootstrap event via stderr capture for the parent to ingest.
- `scripts/build_app.sh` — add `--collect-submodules observability` to the PyInstaller command.
- `.gitignore` — ignore `logs/` and any source-run telemetry directories.
- `docs/observability.md` — operator triage recipes including spec §10 reverse-lookup.

## Sink Layout (spec §6.15.2)

Canonical app-global sinks:

```text
<app_root>/harness/
├── telemetry/
│   ├── runtime.events.jsonl
│   ├── worker.events.jsonl
│   ├── harness.events.jsonl
│   ├── app.events.jsonl
│   ├── persistence.events.jsonl   # extension; spec lists 4 layers, persistence is harness-internal
│   └── bootstrap.events.jsonl     # extension; bootstrap covers pre-app-construction
└── logs/
    ├── runtime.log
    ├── worker.log
    ├── harness.log
    ├── app.log
    ├── persistence.log
    └── bootstrap.log
```

Workspace mirror (any event whose `correlation.workspace_id` is set):

```text
<workspace>/state/telemetry/
├── runtime.events.jsonl
├── worker.events.jsonl
├── harness.events.jsonl
└── app.events.jsonl
```

Mirroring is **additive** — the app-global stream is never truncated to satisfy a workspace. Workspace mirror rotation matches app-global rotation (10 MB × 5 backups).

## Event Contract (spec §6.15.3)

```python
class Severity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"

class Layer(StrEnum):
    BOOTSTRAP = "bootstrap"
    APP = "app"
    HARNESS = "harness"
    RUNTIME = "runtime"
    WORKER = "worker"
    PERSISTENCE = "persistence"

class Correlation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID | None = None
    workspace_id: str | None = None
    turn_id: UUID | None = None
    run_id: str | None = None
    step_id: str | None = None
    approval_id: str | None = None
    proposal_id: str | None = None
    boot_id: UUID | None = None  # extension for pre-session bootstrap

class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    event_id: UUID = Field(default_factory=uuid4)
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    layer: Layer
    component: str          # e.g. "tui.session", "orchestrator", "validity_manager"
    event: str              # dotted name from allowlist, e.g. "harness.approval.granted"
    severity: Severity = Severity.INFO
    correlation: Correlation = Field(default_factory=Correlation)
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float | None = None
    redactions: list[str] = Field(default_factory=list)  # reserved per §6.15.7
```

Validation rules:

- `event` must match the allowlist defined in `events.py` (one constant per layer).
- `duration_ms` is **required** when `event` ends in `.finished`, `.failed`, or `.end`.
- `payload` must be JSON-serializable. Free-text fields exceeding 4 KB are replaced by `{ "digest": sha256, "ref": "<persisted-artifact-path-or-id>" }` per §6.15.3.
- `correlation.workspace_id` triggers workspace mirroring.
- Any field marked sensitive by `redaction.py` is replaced; secret-named env values (`*_KEY`, `*_TOKEN`, `*_SECRET`) are dropped unconditionally per §6.15.7.

## Event Allowlist (spec §6.15.5)

Bootstrap (extension): `bootstrap.start`, `bootstrap.path.resolved`, `bootstrap.import.start`, `bootstrap.import.end`, `bootstrap.import.error`, `bootstrap.app.construct.start`, `bootstrap.app.construct.end`, `bootstrap.run.start`, `bootstrap.run.end`, `bootstrap.error`.

App (§6.15.5 + blank-screen extensions): `app.session.opened`, `app.session.closed`, `app.command.invoked`, `app.command.completed`, `app.workspace.switched`, `app.mode.switched`, `app.mode.rejected`, `app.user.prompt_submitted`, `app.user.approval_decision`, `app.user.clarification_submitted`, `app.lifecycle.constructed`, `app.compose.started`, `app.compose.widget`, `app.compose.finished`, `app.mount.started`, `app.mount.finished`, `app.ready`, `app.screen.snapshot`, `app.widget.health`, `app.render.started`, `app.render.finished`, `app.error`, `app.turn.started`, `app.turn.finished`, `app.turn.failed`, `app.mode.proposed`.

Harness (§6.15.5): `harness.run.started`, `harness.run.completed`, `harness.run.failed`, `harness.approval.requested`, `harness.approval.granted`, `harness.approval.rejected`, `harness.approval.auto_proceeded`, `harness.approval.timed_out`, `harness.repair.attempted`, `harness.repair.succeeded`, `harness.repair.failed`, `harness.replan.triggered`, `harness.validity.ok`, `harness.validity.changed`, `harness.validity.stale`, `harness.validity.needs_review`, `harness.validity.revalidated`, `harness.validity.broken_lineage`, `harness.doctor.opened`, `harness.doctor.tmp_action`, `harness.doctor.closed`, `harness.memory.proposal.created`, `harness.memory.proposal.approved`, `harness.memory.proposal.applied`, `harness.memory.proposal.rejected`, `harness.context.compaction_started`, `harness.context.compaction_finished`, `harness.context.token_pressure_gate`, `harness.turn.received`, `harness.mode.activated`, `harness.prompt.built`, `harness.plan.built`, `harness.step.dispatch`, `harness.step.resume`, `harness.error`.

Runtime (§6.15.5): `runtime.dispatch.started`, `runtime.dispatch.token`, `runtime.dispatch.finish`, `runtime.dispatch.error`, `runtime.init.started`, `runtime.init.finished`, `runtime.model.load.started`, `runtime.model.load.finished`, `runtime.prompt.built`, `runtime.tool_call.parsed`, `runtime.token_pressure`.

Worker (§6.15.5): `worker.step.started`, `worker.step.finished`, `worker.step.failed`, `worker.step.timeout`, `worker.sandbox.config`, `worker.sandbox.violation`, `worker.subprocess.started`, `worker.subprocess.finished`, `worker.artifact.emitted`.

Persistence (extension): `persistence.write.started`, `persistence.write.finished`, `persistence.write.failed`.

Required event payloads (selected; full list in `events.py` docstrings):

- `runtime.dispatch.finish` — `model_id`, `prompt_token_count`, `completion_token_count`, `finish_reason`. (§6.15.5)
- `runtime.dispatch.error` — `malformed_buffer_ref` when applicable. (§6.15.5)
- `worker.step.finished` — `step_contract_digest`, `sandbox_limits`, `exit_code`, `started_at`, `finished_at`, `duration_ms`, `step_result_id`. (§6.15.5 + §6.15.8)
- `harness.approval.granted` — `approval_id` (not the approval payload). (§6.15.8)

## Correlation Rules (spec §6.15.4)

- Application opens `turn_id`. Lower layers must not invent it.
- Plan execution opens `run_id`. Steps open `step_id` scoped to that run.
- Approvals/clarifications/memory proposals carry their own IDs and the enclosing `turn_id`.
- All IDs propagate via `ContextVar`. Worker subprocesses receive them via env vars (`DATAHARNESS_TURN_ID`, `DATAHARNESS_RUN_ID`, `DATAHARNESS_STEP_ID`, `DATAHARNESS_WORKSPACE_ID`) and echo them in `ExecutionEnvelope.metadata` so the parent re-stamps events on receipt.

## Persistence Linkage (spec §6.15.8 + §10 invariant)

For every persisted control object the harness writes — `StepResult`, `ApprovalRecord`, `LineageRecord`, applied `MemoryUpdateProposal`, `DoctorReport` — the persisting code must:

1. Emit a telemetry event whose `correlation` resolves the record's IDs (`step_id` for `StepResult`, `approval_id` for `ApprovalRecord`, `proposal_id` for applied `MemoryUpdateProposal`, etc.).
2. Stamp the record's JSON with the emitted event's `event_id` under the key `telemetry_event_id`.

The `tests/observability/test_persistence_linkage.py` test enumerates every persisted record after a representative session and asserts both directions resolve.

## Failure Mode (spec §6.15.9)

- Telemetry write failures must not crash the harness.
- On `OSError`/`PermissionError` while writing to a sink, log to a fallback `stderr` channel formatted as `TELEMETRY_WRITE_FAILED layer=<l> event=<e> err=<msg>` and increment a per-layer failure counter.
- Sustained failure (counter ≥ configurable threshold, default 10 within 60 s) raises a single `app.error` with `phase="telemetry_degraded"` so the application layer can surface a degraded-observability warning to the user.

## Design Notes

- **Early bootstrap is mandatory.** `src/cli.py` does not import `DataHarnessApp` at module load. Logging and exception hooks install first, then app import / construction / run are logged as separate phases.
- **Two streams, same IDs.** Every mirrored log line includes `boot=<id> session=<id> workspace=<id> turn=<id> run=<id> step=<id> event=<event_id> name=<event> severity=<severity>`.
- **Contextvars + subprocess handoff.** All correlation IDs live in `ContextVar`. Worker subprocesses inherit via env vars and echo into envelope metadata.
- **No schema-column migration.** `WorkspaceDb` uses generic JSON tables. Persistence stamps `telemetry_event_id` inside `record_json`.
- **Failure events are required at every instrumented boundary.** The boundary catches, emits an error event with `phase`, exception type, message, traceback, and re-raises unless existing behavior already returns a failure envelope.
- **Bounded streams.** `RotatingFileHandler(maxBytes=10_000_000, backupCount=5)` per `.log`. The JSONL writer rotates on the same threshold and writes whole lines atomically (one `write()` per line, append mode, file-locked).
- **No raw token trace in v1.** `runtime.dispatch.token` events are only emitted when `DATAHARNESS_RUNTIME_TOKEN_TRACE=1`.
- **Identity redactor in v1.** `redaction.py` is a no-op pass-through but every event's `redactions` field is populated (empty list) so future policy can apply without consumer breakage.

---

### Task 1: Event Model, Correlation, and Path Resolution

**Files:**
- Create: `src/observability/events.py`
- Create: `src/observability/correlation.py`
- Create: `src/observability/runtime_paths.py`
- Create: `src/observability/redaction.py`
- Test: `tests/observability/test_events.py`

- [ ] **Step 1: Write failing tests**
  - Assert every value in `Layer`, `Severity`, and the event-name allowlist (per §6.15.5 list above) exists.
  - Assert `TelemetryEvent` round-trips through JSON with UUID/datetime/StrEnum values.
  - Assert `TelemetryEvent` rejects an event name not in the allowlist.
  - Assert `TelemetryEvent` requires `duration_ms` when name ends in `.finished`/`.failed`/`.end`.
  - Assert payload values exceeding 4 KB are replaced by `{digest, ref}` automatically.
  - Assert `Correlation` rejects unknown fields (`extra="forbid"`).
  - Assert `bind_session(...)`, `bind_workspace(...)`, `bind_turn(...)`, `bind_run(...)`, `bind_step(...)`, `bind_approval(...)`, `bind_proposal(...)` populate the corresponding fields on a freshly constructed `Correlation.current()`.
  - Assert nested `bind_*` blocks restore the prior value on exit.
  - Assert `resolve_app_telemetry_dir()` returns `<app_root>/harness/telemetry` for source and PyInstaller runs and creates no directory itself.
  - Assert `resolve_workspace_telemetry_dir(workspace_path)` returns `<workspace>/state/telemetry`.
  - Assert `redact(event)` returns the event unchanged but populates `event.redactions = []`.

- [ ] **Step 2: Implement**
  - `BaseModel` with `ConfigDict(extra="forbid")` for all schema types.
  - `events.py` exports `EVENT_ALLOWLIST: frozenset[str]` matching the allowlist above.
  - `correlation.py` uses one `ContextVar` per ID and a `Correlation.current()` helper that reads them.
  - Path resolution detects PyInstaller via `sys._MEIPASS` and walks to the bundle parent for `<app_root>`; source runs use the repo root.
  - `redaction.py` is a no-op pass-through that always sets `event.redactions = []`.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_events.py -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/observability tests/observability/test_events.py`
  - `git commit -m "feat(observability): add event model, correlation, and path resolution"`

### Task 2: Telemetry Writer with Workspace Mirror and Failure Mode

**Files:**
- Create: `src/observability/telemetry.py`
- Test: `tests/observability/test_telemetry.py`
- Test: `tests/observability/test_workspace_mirror.py`

- [ ] **Step 1: Write failing tests**
  - `Telemetry(app_dir).emit(event)` writes one valid JSONL line to `<app_dir>/harness/telemetry/<layer>.events.jsonl`.
  - When `event.correlation.workspace_id` is set and `Telemetry.bind_workspace_root(ws_path)` was called, the same event is **also** written to `<ws_path>/state/telemetry/<layer>.events.jsonl`.
  - When workspace mirror write fails, the app-global write still succeeds (additive guarantee, §6.15.2).
  - Concurrent emits from two threads produce one complete JSON object per line on both sinks.
  - Patching the file handle to raise `OSError` does not raise out of `emit()`; instead `TELEMETRY_WRITE_FAILED ...` appears on captured stderr and the per-layer failure counter increments.
  - After 10 failures in 60 s, a single `app.error` event with `phase="telemetry_degraded"` is emitted to a still-working sink (or to stderr if all sinks fail).
  - `emit_error(layer, component, event, phase, exc)` includes exception type, message, and full traceback in `payload`.
  - Files rotate at ≥ 10 MB with 5 backups.

- [ ] **Step 2: Implement**
  - One file lock per (sink path) combination; open/append/close per emit for correctness first.
  - Mirror each event to `logging.getLogger(layer.value)` with `extra={"telemetry_event": event}`.
  - Failure counter is per-layer in-memory with monotonic-time window.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_telemetry.py tests/observability/test_workspace_mirror.py -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/observability/telemetry.py tests/observability/test_telemetry.py tests/observability/test_workspace_mirror.py`
  - `git commit -m "feat(observability): telemetry writer with workspace mirror and failure mode"`

### Task 3: Per-Layer Logging and Exception Hooks

**Files:**
- Create: `src/observability/logging_setup.py`
- Test: `tests/observability/test_logging_setup.py`

- [ ] **Step 1: Write failing tests**
  - `configure_logging(app_dir)` creates `bootstrap.log`, `app.log`, `harness.log`, `runtime.log`, `worker.log`, and `persistence.log` under `<app_dir>/harness/logs/`.
  - `logging.getLogger("app.session").info("x")` writes only to `app.log`.
  - Unknown logger names route to `bootstrap.log`.
  - Log format contains `boot=`, `session=`, `workspace=`, `turn=`, `run=`, `step=`, `event=`, `name=`, and `severity=`.
  - Calling `configure_logging(...)` twice does not duplicate handlers.
  - `sys.excepthook` and `threading.excepthook` write tracebacks to `bootstrap.log`.
  - `DATAHARNESS_LOG_STDERR=1` adds a stderr handler without disabling file logs.

- [ ] **Step 2: Implement**
  - Install `RotatingFileHandler(maxBytes=10_000_000, backupCount=5)` for layer loggers `bootstrap`, `app`, `harness`, `runtime`, `worker`, `persistence`.
  - Route module loggers by prefix: `app.*`, `harness.*`, `runtime.*`, `worker.*`, `persistence.*`; everything else propagates to `bootstrap`.
  - Add a filter that reads observability `Correlation.current()` and any telemetry `extra` and stamps fields on the record.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_logging_setup.py -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/observability/logging_setup.py tests/observability/test_logging_setup.py`
  - `git commit -m "feat(observability): per-layer logs with correlation filter"`

### Task 4: Bootstrap Wiring Before App Import

**Files:**
- Modify: `src/cli.py`
- Test: `tests/observability/test_bootstrap.py`

- [ ] **Step 1: Write failing tests**
  - Importing `cli` must not import `app.tui.app`; assert `"app.tui.app" not in sys.modules` immediately after `import cli`.
  - Patch `importlib.import_module("app.tui.app")` to raise `RuntimeError("import boom")`; `cli.main()` emits `bootstrap.import.error` to both `bootstrap.log` and `bootstrap.events.jsonl`.
  - Patch `DataHarnessApp.__init__` to raise; `cli.main()` emits `bootstrap.app.construct.start` then `bootstrap.error`.
  - Patch `DataHarnessApp.run` to raise; `cli.main()` emits `bootstrap.run.start` then `bootstrap.error`.
  - Assert `<app_root>/harness/{telemetry,logs}/` is auto-created when `main()` runs.

- [ ] **Step 2: Implement**
  - In `main()`: resolve `<app_root>`, call `configure_logging(app_root)`, install exception hooks, then defer import of `DataHarnessApp` to a `build_app()` helper.
  - Emit bootstrap events around path resolution, import, app construction, and run.
  - Re-raise exceptions after logging so process exit behavior remains honest.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_bootstrap.py tests/app/tui/test_textual_app.py -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/cli.py tests/observability/test_bootstrap.py`
  - `git commit -m "feat(cli): bootstrap logging before app import"`

### Task 5: Textual Blank-Screen Diagnostics

**Files:**
- Modify: `src/app/tui/app.py`
- Test: `tests/observability/test_app_blank_diagnostics.py`
- Test: `tests/app/tui/test_textual_app.py`

- [ ] **Step 1: Write failing tests**
  - Constructing `DataHarnessApp(telemetry=Telemetry(tmp_path))` emits `app.lifecycle.constructed` with `title`.
  - Running `list(app.compose())` emits `app.compose.started`, one `app.compose.widget` per yielded widget, and `app.compose.finished` with `widget_count` and `compose_ids`.
  - If `compose()` raises after yielding `Header`, telemetry emits `app.error` with `phase="compose"` and traceback.
  - `on_mount()` emits `app.mount.started`, `app.mount.finished`, and `app.screen.snapshot` containing expected widget IDs and a missing-IDs list.
  - Snapshot assertion fails when no content widgets are discoverable, so a blank app produces an explicit diagnostic.

- [ ] **Step 2: Implement**
  - Accept optional `telemetry: Telemetry | None`, `session_id: UUID | None` on `DataHarnessApp.__init__`.
  - Wrap `compose()` in a generator that logs every yielded widget id/class.
  - `on_mount()` logs active screen, expected IDs from `compose_ids()`, found IDs, and missing IDs.
  - Add `on_error()` or the nearest Textual-supported error hook for render/message errors; if Textual lacks one, wrap local action handlers and document the limitation.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_app_blank_diagnostics.py tests/app/tui/test_textual_app.py -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/app/tui/app.py tests/observability/test_app_blank_diagnostics.py tests/app/tui/test_textual_app.py`
  - `git commit -m "feat(app): textual lifecycle and blank-screen diagnostics"`

### Task 6: App Controller, Session, and Router Instrumentation

**Files:**
- Modify: `src/app/tui/controller.py`
- Modify: `src/app/session.py`
- Modify: `src/app/agents/router.py`
- Test: `tests/observability/test_app_instrumentation.py`

- [ ] **Step 1: Write failing tests**
  - `HarnessViewController.initial_view()` emits `app.screen.snapshot` (or `app.lifecycle.initial_view`) with workspace id, mode, command count, process events count.
  - `session.submit_user_text("hi")` opens a fresh `turn_id`, emits `app.user.prompt_submitted`, `app.turn.started`, `app.mode.proposed`, and `app.turn.finished` with the same `turn_id`.
  - `controller.invoke_command(..., "workspace_status")` emits `app.command.invoked` and `app.command.completed` with command name and argument keys.
  - Workspace switch emits `app.workspace.switched` with old/new workspace ids.
  - Mode switch from router emits `app.mode.switched` or `app.mode.rejected` with reason and `prompt_template_id`.
  - Exception from `handle_user_turn` emits `app.turn.failed` and `app.error` before re-raise.

- [ ] **Step 2: Implement**
  - Inject one shared `Telemetry` into controller, session, router, orchestrator.
  - Open `session_id` at session construction; open `turn_id` at session boundary and bind for the entire turn.
  - Payload includes input length, command name, mode, reason, prompt template id, prompt template version, result flags, duration.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_app_instrumentation.py tests/app -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/app/tui/controller.py src/app/session.py src/app/agents/router.py tests/observability/test_app_instrumentation.py`
  - `git commit -m "feat(app): instrument controller session and router"`

### Task 7: Harness Instrumentation (orchestrator, validity, doctor, knowledge, approval, repair, context)

**Files:**
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/validity.py`
- Modify: `src/harness/doctor.py`
- Modify: `src/harness/knowledge.py`
- Modify: `src/harness/approval.py`
- Modify: `src/harness/repair.py`
- Modify: `src/harness/context_manager.py`
- Test: `tests/observability/test_harness_instrumentation.py`

- [ ] **Step 1: Write failing tests**
  - `Orchestrator.handle_turn(...)` emits `harness.turn.received`, `harness.context.compaction_started/finished` when rebuild runs, `harness.mode.activated`, `harness.prompt.built`, `harness.run.started`, and `harness.run.completed`.
  - Analyst approval path emits `harness.plan.built`, `harness.approval.requested`, then one of `harness.approval.granted`/`harness.approval.rejected`/`harness.approval.auto_proceeded`/`harness.approval.timed_out`.
  - `resume_approved_step(...)` emits `harness.step.resume`, `harness.step.dispatch`, and `harness.run.completed`.
  - Validity transitions emit `harness.validity.{state}` for each of the six states.
  - Doctor flow emits `harness.doctor.opened`, one or more `harness.doctor.tmp_action`, then `harness.doctor.closed`.
  - Knowledge proposal flow emits `harness.memory.proposal.{created,approved,applied}` (or `rejected`).
  - Repair flow emits `harness.repair.attempted` and one of `harness.repair.{succeeded,failed}`; replan emits `harness.replan.triggered`.
  - Context-pressure gate emits `harness.context.token_pressure_gate` with token count.
  - Any orchestrator exception emits `harness.error` with `phase` and traceback.

- [ ] **Step 2: Implement**
  - Add optional `telemetry` to each harness component constructor.
  - Each emit binds the relevant correlation IDs (`run_id`, `step_id`, `approval_id`, `proposal_id`) for the duration of the operation.
  - Keep public return shapes unchanged.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_harness_instrumentation.py tests/harness -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/harness tests/observability/test_harness_instrumentation.py`
  - `git commit -m "feat(harness): instrument orchestration, validity, doctor, knowledge, approval, repair, context"`

### Task 8: Persistence Linkage and Spec §10 Telemetry Invariant

**Files:**
- Modify: `src/harness/persistence.py`
- Modify: `src/harness/db.py`
- Test: `tests/observability/test_persistence_linkage.py`

- [ ] **Step 1: Write failing tests**
  - `HarnessPersistence.save_step_result(...)` emits `persistence.write.started` and `persistence.write.finished`; the saved JSON record contains a `telemetry_event_id` matching the `harness.run.completed` (or relevant) event's `event_id`.
  - Same for `save_approval_record`, `save_lineage_record`, `save_applied_memory_proposal`, `save_doctor_report`.
  - **Spec §10 invariant test:** drive a representative session through the orchestrator using fakes (analyst plan + approval + execution + memory proposal + doctor cycle + lineage). Then enumerate every persisted control object across the workspace DB and `memory/`. For each, assert there exists at least one telemetry event whose `correlation` resolves the record (`step_id`/`approval_id`/`proposal_id`/etc.), and conversely that every recorded `telemetry_event_id` resolves to an event in the JSONL.
  - `HarnessPersistence.save_*(...)` failure emits `persistence.write.failed` and re-raises.

- [ ] **Step 2: Implement**
  - Persistence accepts a shared `Telemetry`. Before writing, it captures the current `Correlation`, allocates the telemetry event, writes to JSONL, then writes the record with `telemetry_event_id` set.
  - Records are copied before stamping so callers are not mutated.
  - No physical SQLite columns added; only JSON-querying helpers.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_persistence_linkage.py tests/harness -q`
  - Expected: all tests pass; spec §10 invariant holds.

- [ ] **Step 4: Commit**
  - `git add src/harness/persistence.py src/harness/db.py tests/observability/test_persistence_linkage.py`
  - `git commit -m "feat(persistence): stamp telemetry_event_id and enforce spec §10 linkage"`

### Task 9: Runtime Instrumentation

**Files:**
- Modify: `src/runtime/llama_cpp_runtime.py`
- Modify: `src/runtime/protocol.py`
- Test: `tests/observability/test_runtime_instrumentation.py`

- [ ] **Step 1: Write failing tests**
  - Construction emits `runtime.init.started` and `runtime.init.finished` without requiring a real model in unit tests.
  - Model load emits `runtime.model.load.started` / `runtime.model.load.finished`.
  - `complete(request)` emits `runtime.prompt.built`, `runtime.dispatch.started`, and `runtime.dispatch.finish` with `model_id`, `prompt_token_count`, `completion_token_count`, `finish_reason`, `duration_ms`.
  - Parsed tool calls emit `runtime.tool_call.parsed` with call count and tool names.
  - `stream(request)` emits `runtime.dispatch.started` at iterator open and `runtime.dispatch.finish` at iterator close.
  - `DATAHARNESS_RUNTIME_TOKEN_TRACE=1` enables per-token `runtime.dispatch.token` events; default disables them.
  - Model exceptions emit `runtime.dispatch.error` with `phase="model_call"` or `phase="stream"` and a `malformed_buffer_ref` when a buffer was captured.

- [ ] **Step 2: Implement**
  - Optional `telemetry` in `LlamaCppRuntime.__init__`.
  - `time.perf_counter()` for latency.
  - Mirror diagnostic lines via `logging.getLogger("runtime.llama_cpp")`.
  - Document telemetry contract in `runtime/protocol.py` without changing signatures.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_runtime_instrumentation.py tests/runtime -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/runtime tests/observability/test_runtime_instrumentation.py`
  - `git commit -m "feat(runtime): instrument llama runtime calls"`

### Task 10: Worker and Sandbox Instrumentation with Subprocess Handoff

**Files:**
- Modify: `src/worker/executor.py`
- Modify: `src/worker/sandbox_bootstrap.py`
- Test: `tests/observability/test_worker_instrumentation.py`

- [ ] **Step 1: Write failing tests**
  - `PythonStepExecutor.execute(request)` emits `worker.step.started`, `worker.sandbox.config`, `worker.subprocess.started`, `worker.subprocess.finished`, and `worker.step.finished`.
  - `worker.step.finished` payload includes `step_contract_digest`, `sandbox_limits`, `exit_code`, `started_at`, `finished_at`, `duration_ms`, `step_result_id`, `stdout_bytes`, `stderr_bytes`, `artifact_count`.
  - Timeout emits `worker.step.timeout` and a terminal `worker.step.failed`.
  - Sandbox violation emits `worker.sandbox.violation` and preserves existing `ExecutionEnvelope` behavior.
  - Subprocess receives correlation IDs via env vars (`DATAHARNESS_TURN_ID`, `DATAHARNESS_RUN_ID`, `DATAHARNESS_STEP_ID`, `DATAHARNESS_WORKSPACE_ID`) and echoes them in `ExecutionEnvelope.metadata`. Parent re-stamps subprocess-origin events with these IDs.
  - Subprocess `sandbox_bootstrap.py` writes a single `worker.subprocess.started`-equivalent line to its stderr containing python version, cwd, config path, inherited correlation IDs; parent ingests and emits a real telemetry event.

- [ ] **Step 2: Implement**
  - Optional `telemetry` in `PythonStepExecutor.__init__`.
  - Pass correlation IDs to subprocess via env vars.
  - Subprocess does not write directly to JSONL files (race risk); it surfaces metadata for the parent to log.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_worker_instrumentation.py tests/worker -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add src/worker tests/observability/test_worker_instrumentation.py`
  - `git commit -m "feat(worker): instrument execution and sandbox with subprocess id handoff"`

### Task 11: End-to-End Correlated Trace and Blank-App Smoke

**Files:**
- Test: `tests/observability/test_end_to_end_trace.py`

- [ ] **Step 1: Write failing tests**
  - Build `DataHarnessApp` with tmp telemetry and run under Textual test pilot long enough to compose/mount.
  - Assert `app.lifecycle.constructed`, `app.compose.finished`, `app.mount.finished`, and `app.screen.snapshot` exist before any user turn.
  - Submit one analyst turn through session/harness with fake runtime and fake worker.
  - Read all `*.events.jsonl`, sort by `ts`, and assert the expected flow (names match the allowlist):
    `app.user.prompt_submitted` → `app.turn.started` → `app.mode.proposed` → `harness.turn.received` → `harness.mode.activated` → `harness.prompt.built` → `runtime.dispatch.started` → `runtime.dispatch.finish` → `harness.plan.built` → `harness.approval.requested` → `harness.approval.granted` → `harness.step.resume` → `harness.step.dispatch` → `worker.step.started` → `worker.subprocess.started` → `worker.subprocess.finished` → `worker.step.finished` → `harness.run.completed` → `app.turn.finished`.
  - Assert every turn-scoped event shares the same `correlation.turn_id`; every step-scoped event shares the same `correlation.step_id`.
  - Assert `app.log`, `harness.log`, `runtime.log`, `worker.log` each contain `turn=<turn_id>`.
  - Assert workspace-mirrored streams under `<workspace>/state/telemetry/` contain the same workspace-scoped events.

- [ ] **Step 2: Fix wiring gaps surfaced by the test**
  - Preserve existing tests and public return shapes while passing telemetry through constructors.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/observability/test_end_to_end_trace.py -q`
  - Expected: all tests pass.

- [ ] **Step 4: Commit**
  - `git add tests/observability/test_end_to_end_trace.py src`
  - `git commit -m "test(observability): correlated end-to-end diagnostics"`

### Task 12: Packaging, Docs, and Operator Recipes

**Files:**
- Modify: `scripts/build_app.sh`
- Modify: `.gitignore`
- Create: `docs/observability.md`

- [ ] **Step 1: Write/extend checks**
  - Add `--collect-submodules observability` to the PyInstaller command and verify the built binary starts far enough to create `<app_root>/harness/logs/bootstrap.log`.
  - Confirm `.gitignore` ignores `logs/` and any source-run telemetry directories.

- [ ] **Step 2: Implement docs**
  - Document streams, sinks, mirroring, rotation, correlation IDs, redaction policy, failure mode.
  - Include triage recipes:

```bash
# blank-app
grep -E "bootstrap|app\.(lifecycle|compose|mount|screen|error)" \
  <app_root>/harness/logs/bootstrap.log <app_root>/harness/logs/app.log

# correlated turn trace
grep "turn=<turn_id>" <app_root>/harness/logs/*.log

# spec §10 reverse lookup
jq --arg sid "<step_id>" 'select(.correlation.step_id==$sid)' \
  <app_root>/harness/telemetry/*.events.jsonl

# error sweep
jq 'select(.severity=="error")' <app_root>/harness/telemetry/*.events.jsonl

# runtime latency
jq 'select(.event=="runtime.dispatch.finish") | .duration_ms' \
  <app_root>/harness/telemetry/runtime.events.jsonl

# worker step outcome
jq 'select(.event=="worker.step.finished") | .payload' \
  <app_root>/harness/telemetry/worker.events.jsonl
```

- [ ] **Step 3: Verify**
  - Run: `uv run pytest -q`
  - Run: `bash scripts/build_app.sh`
  - Manual: delete `<app_root>/harness/logs/`, run built app, confirm bootstrap/app logs appear with compose/mount/snapshot events.
  - Manual: temporarily make `src/app/tui/app.py` raise in `compose()`, run app, confirm `app.error phase=compose` with traceback. Revert.
  - Manual: run an end-to-end analyst turn against a real workspace, confirm `<workspace>/state/telemetry/` mirror exists and contains workspace-scoped events.

- [ ] **Step 4: Commit**
  - `git add scripts/build_app.sh .gitignore docs/observability.md`
  - `git commit -m "docs(observability): triage recipes and packaging"`

---

## Verification Checklist

- [ ] `uv run pytest -q` passes.
- [ ] `bash scripts/build_app.sh` passes.
- [ ] Spec §6.15.1 — every layer emits both `.events.jsonl` and `.log`, rendered from the same event object.
- [ ] Spec §6.15.2 — sinks live under `<app_root>/harness/{telemetry,logs}/`; workspace events mirror to `<workspace>/state/telemetry/`; mirroring is additive.
- [ ] Spec §6.15.3 — every event carries `schema_version`, `ts`, `layer`, `component`, `event`, `severity`, `correlation`, `payload`; `duration_ms` present on `*.finished`/`*.failed`/`*.end`; `redactions` field always present.
- [ ] Spec §6.15.4 — `turn_id` opens at the application layer; `run_id`/`step_id` at the harness; lower layers never invent correlation IDs.
- [ ] Spec §6.15.5 — every required event in the per-layer obligations list is exercised by tests.
- [ ] Spec §6.15.6 — both streams rotate at 10 MB × 5 backups; structured stream rotates atomically (no partial JSON).
- [ ] Spec §6.15.7 — `redactions` field reserved on every event; secrets never written.
- [ ] Spec §6.15.8 — every persisted `StepResult`, `ApprovalRecord`, `LineageRecord`, applied `MemoryUpdateProposal`, `DoctorReport` reachable from a telemetry event by correlation IDs and stamped with `telemetry_event_id`.
- [ ] Spec §6.15.9 — telemetry write failures do not crash the harness; sustained failure surfaces via single `app.error phase=telemetry_degraded`.
- [ ] Spec §10 invariant test (`test_persistence_linkage.py`) green.
- [ ] Bootstrap-ordering test proves `src/cli.py` logs before importing `app.tui.app`.
- [ ] Textual smoke proves compose/mount/screen events emitted before any user turn.
- [ ] Manual blank-app drill writes enough evidence to localize failure to one of: bootstrap, import, app construction, compose, mount, render, screen, session, controller, harness, runtime, worker, persistence.
- [ ] Persistence test proves `telemetry_event_id` is inside JSON records (not a physical SQLite column).
