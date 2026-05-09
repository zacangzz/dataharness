# Spec 6 — Pipeline orchestrator

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3, 4, 5
**Blocks:** specs 7, 8

## 1. Purpose

Replace the current smolagents-era `Pipeline` with a thin orchestrator that owns turn lifecycle: session, workspace manifest, sandbox client, `Runner.run` invocation, RunItem streaming, workspace-switch invalidation. No route logic lives here anymore — triage owns that (spec 5).

## 2. Scope

### In scope

- `Pipeline` class with a single `run(message, on_event, active_workspace)` entry point.
- Per-turn construction of `Manifest`, `UnixLocalSandboxClient`, `RunConfig`.
- Per-workspace `SQLiteSession` management (create, reuse, invalidate on switch).
- `Runner.run` invocation with streaming; RunItem stream forwarded to `on_event` callback.
- Turn cancellation on workspace switch (`CancelledError` propagation, sandbox cleanup).
- Turn-level telemetry span wrapping the entire `Runner.run`.
- Error handling: any `AgentsException`, `CancelledError`, or underlying `ModelBehaviorError` caught and converted into a user-facing error payload on `on_event`; no fallback agents per decision A.

### Out of scope

- Route selection (spec 5).
- UI rendering (spec 7).
- Packaging (spec 8).

## 3. Public surface

```python
class Pipeline:
    def __init__(
        self,
        triage_agent: Agent,
        session_root: Path,
    ): ...

    async def run(
        self,
        message: str,
        on_event: Callable[[PipelineEvent], Awaitable[None]],
        active_workspace: WorkspaceEntry,
    ) -> PipelineResult: ...

    async def invalidate_workspace(self, name: str) -> None: ...
```

`PipelineEvent` is a tagged union: `AgentStarted`, `ReasoningSummary`, `TokenDelta`, `ToolCallStart`, `ToolCallComplete`, `ToolOutput`, `Handoff`, `AgentFinished`, `FinalMessage`, `StatusUpdate`, `Error`.

`PipelineResult` carries final text, token counts, wall time, agent trail.

### 3.1 `StatusUpdate` — pipeline-originated status bar messages

The Pipeline is the single source of truth for status-bar text. Specialist agents do not write directly to the UI's status widget; the Pipeline reflects turn lifecycle into `StatusUpdate` events and the UI (spec 7 §4) renders them.

```python
@dataclass
class StatusUpdate:
    text: str           # short, user-facing, < 80 chars
    level: Literal["idle", "working", "tool", "handoff", "warn", "error"]
    agent: str | None   # active agent name at emission time, if any
```

Lifecycle emission points (§4): `turn_start`, `handoff`, `tool_call_start`, `tool_call_complete`, `tool_output`, `turn_end`, `cancelled`, `error`.

Rationale for Pipeline-origin (vs UI polling SDK events): Pipeline already sees every RunItem before the UI does, already owns the turn lifecycle, and can emit a single coherent event stream. Keeps `src/cli/app.py` a pure renderer.

### 3.2 Activity vocabulary

Pipeline, UI, and telemetry share one activity vocabulary for streamed turn state:

- `agent_started`
- `reasoning_summary`
- `tool_call_start`
- `tool_call_complete`
- `tool_output`
- `handoff`
- `status_update`
- `agent_finished`
- `final_message`
- `error`

The UI renders from live `PipelineEvent`s, not by tailing telemetry, but every user-visible process entry should be correlatable by `turn_id`, `run_id`, `agent`, and `tool_call_id` where applicable.

## 4. Per-turn lifecycle

1. Read `active_workspace.name` and `active_workspace.dir`. Emit `AgentStarted(agent="triage")`, then `StatusUpdate("Thinking…", level="working", agent="triage")`.
2. Retrieve or create `SQLiteSession` at `<workspace.dir>/memory/session.db` (spec 9 §3; replaces the prior `local/workspaces/<name>/.hragent/session.db` path).
3. Build `Manifest` with the two-volume mount from spec 9 §9:
   ```python
   Manifest(entries={
       "data":   LocalDir(src=active_workspace.dir / "data",   mode="ro"),
       "memory": LocalDir(src=active_workspace.dir / "memory", mode="rw"),
   })
   ```
   Both surface at `/workspace/data` and `/workspace/memory` inside the sandbox.
4. Instantiate `UnixLocalSandboxClient()` (optionally wrapped by `sandbox_guard` — spec 8 §5 fallback).
5. Compute the **tiny triage signal block** from non-LLM helpers: `has_data`, `new_files_present`, `gaps_open_present`, `drift_present` (spec 5 §4). Prepend only that signal block to the triage turn. Do **not** inject the knowledge manifest, note summaries, saved-function listings, or preferences into triage.
6. Build `RunConfig(sandbox=SandboxRunConfig(client=sandbox_client, manifest=manifest))`.
7. Call `Runner.run` with streaming enabled (exact method name — `run`, `run_streamed`, or equivalent — pinned at spec-1 SDK probe): `Runner.run_streamed(triage_agent, message, session=session, run_config=run_config)`.
8. Iterate the stream; dispatch each `RunItem` to `on_event` as the appropriate `PipelineEvent`. Inline activity/status emissions:
   - On raw reasoning deltas, coalesce into short `ReasoningSummary(text, agent=current)` updates. The summary is user-visible; raw chain-of-thought is not surfaced directly in the UI.
   - On `Handoff(from, to)` → emit `AgentFinished(agent=from, outcome="handoff")`, `Handoff(from, to)`, `AgentStarted(agent=to)`, then `StatusUpdate(f"Handed off to {to}", level="handoff", agent=to)`.
   - On `ToolCallStart(name)` → emit `StatusUpdate(f"Calling {name}…", level="tool", agent=current)`.
   - On `ToolOutput` → emit `StatusUpdate("Reading tool output", level="tool", agent=current)`.
   - On first `TokenDelta(output_type="message")` after a handoff → emit `StatusUpdate("Streaming answer", level="working", agent=current)`.
9. Specialists retrieve knowledge lazily after handoff via tools (`get_file_metadata`, `inspect_file_schema`, `list_saved_functions`, `get_user_preferences`, `list_knowledge` when explicitly needed). Migration scope does **not** rely on a post-handoff Pipeline injection step.
10. Assemble `PipelineResult` from the final assistant message and metadata. Emit `AgentFinished(agent=current, outcome="completed")`, then `StatusUpdate("Ready", level="idle", agent=None)` on success.
11. On any exception: emit `AgentFinished(agent=current, outcome="error")` when an active agent exists, then `PipelineEvent.Error` with the raw exception text, followed by `StatusUpdate("Error — see conversation", level="error", agent=None)`; do not suppress.
12. On `CancelledError` (workspace switch): emit `AgentFinished(agent=current, outcome="cancelled")` when an active agent exists, then `StatusUpdate("Cancelled", level="idle", agent=None)`.
13. `finally`: close `sandbox_client`; do not discard the session (session persists across turns within the same workspace).

## 5. Workspace-switch invalidation

When the UI switches workspaces:

- Pipeline cancels any in-flight `Runner.run` via `task.cancel()`.
- Awaits cancellation; closes sandbox client in the `finally` block of the in-flight turn.
- Drops the `SQLiteSession` handle for the old workspace (closes connection; file is not deleted unless the workspace itself is deleted).
- Clears internal per-workspace state.

The UI clears chat history independently.

## 6. Session file placement

- Path: `<workspace.dir>/memory/session.db`. Lives alongside the other agent-written state (`files/`, `functions/`, `notes/` — spec 9 §3). Transparent layout so the user can back up or diff a workspace as a single folder.
- Created on first turn in a workspace. Parent dir created if missing.
- Cleaned up automatically when `WorkspaceManager.delete(name)` removes the workspace folder (current implementation calls `shutil.rmtree`; `memory/` is wiped alongside `data/`).
- Existing workspaces without a `memory/` subfolder are lazy-migrated on first open (spec 9 §3).

## 7. Error handling

Per decision A (no fallbacks), these surface directly:

| Exception | Event emitted | User sees |
|---|---|---|
| `AgentsException` (max turns, tool failure) | `Error{kind="agent_exception", message=...}` | "Agent error: ..." in conversation pane |
| `ModelBehaviorError` (bad tool_call JSON after retry) | `Error{kind="model_behavior"}` | "Model output error" |
| `ContextLengthExceeded` | `Error{kind="context_exceeded"}` | "Context exceeded, clear chat to continue" |
| `SandboxInitError` | `Error{kind="sandbox_unavailable"}` | "Sandbox unavailable, analyst disabled this turn" |
| `CancelledError` (workspace switch) | `AgentFinished{outcome="cancelled"}` + `StatusUpdate("Cancelled")`; no `Error` event | New workspace UI; cancelled turn does not render a final assistant answer |
| `TimeoutError` (clarification or shell) | `Error{kind="timeout"}` | "Operation timed out" |

## 8. Budgets

- Max turns (Agents SDK `RunConfig`): 8 (matches current step cap).
- Turn wall-clock: 300s, enforced via `asyncio.wait_for`.
- Sandbox shell exec: 60s per command (enforced inside sandbox capability config).

## 9. Telemetry

- Turn-level span `pipeline.run` with: `turn_id`, `run_id`, `workspace.name`, `workspace.has_data`, `agent_trail=[triage, <specialist>]`, `final_status=ok|error|cancelled`, `wall_time_ms`, `max_turns_hit=<bool>`, `status_updates_emitted=<int>`.
- All nested SDK spans remain intact (agent / tool / generation), attached to this turn via context vars.

## 10. Testing

**Integration (stub `LlamaCppAgentsModel`, real sandbox, temp workspace):**
- Turn completes end-to-end on a fixture workspace; final answer delivered.
- SQLiteSession persists across turns in the same workspace.
- Workspace switch cancels in-flight turn cleanly; sandbox closed.
- Stub LLM raising `AgentsException` surfaces as `PipelineEvent.Error`.
- Turn wall-clock budget of 300s enforced; exceeding triggers timeout error.
- Socket-patched test confirms no network egress during a turn.
- Stub emits streaming events (text deltas, ToolCallStart, ToolCallComplete, ToolOutput, FinalMessage); `on_event` receives them in order without buffering.
- Stub emits `AgentStarted` / `AgentFinished` around triage and specialist activity; per-agent process grouping is possible without inspecting transcript text.
- Raw reasoning is converted into `ReasoningSummary` events before UI delivery; UI never depends on raw chain-of-thought text.
- `StatusUpdate` events fire at each lifecycle point listed in §4; `turn_start` fires before the first model call; `Ready` fires last on success; `Error`/`Cancelled` fire last on failure.
- Triage input contains only the tiny routing signal block, not the knowledge manifest.
- New-file analytical ask completes in one turn via analyst route; no forced intake-first handoff.

**End-to-end real-model (pytest marker `@pytest.mark.integration`, real GGUF via `HRAGENT_TEST_MODEL_PATH`):**

These tests actually load llama_cpp with the production model and run canonical conversations through the full Pipeline (triage → specialist handoff → tools → final). Gated on CI `integration` job, not pre-commit. Budgets recorded in `tests/integration/budgets.json` by machine tier.

| Fixture | Input | Expected route | Quality assertion | Latency budget (first-token / total) |
|---|---|---|---|---|
| greet | "hello" | conversational | response is non-empty, < 200 chars, no tool calls | 3s / 10s |
| list-files | "what files do I have?" (workspace with `employees.csv`) | data_analyst | response mentions `employees.csv`; ≥ 1 ToolCall to `list_files` | 5s / 60s |
| column-stats | "what's the average salary?" (on `employees.csv` with numeric `salary`) | data_analyst | response includes a numeric mean matching fixture; ≥ 1 ToolCall to `column_stats` | 5s / 120s |
| clarification | "summarize the data" (ambiguous) | clarification or data_analyst | either `user_input` tool invoked, or analyst proceeds with a specific assumption stated in final text | 5s / 60s |
| no-data | "hello" (empty workspace) | conversational | response does not claim data exists; no `column_stats` / `preview_file` calls | 3s / 15s |

Each fixture asserts: (a) `FinalMessage` delivered; (b) stream contains ≥ 1 text delta before `FinalMessage`; (c) no `api.openai.com` connection attempt under socket patch; (d) latency budgets logged (hard-fail only when > 1.5× budget).

Multi-turn session test: run `greet` then `list-files` in the same `SQLiteSession`; assert analyst sees prior context.

## 11. Files

**New:**
- `src/core/pipeline.py` — new thin orchestrator at `src/core/pipeline.py` (top-level under `core/`, per Option B layout). Old `src/core/agents/pipeline.py` is deleted.
- `tests/core/test_pipeline.py` — replaces the retired `tests/core/agents/test_pipeline.py`.

Imports used by this orchestrator (post-refactor paths):
- `from src.core.engine.agents_model import LlamaCppAgentsModel` (spec 1)
- `from src.core.engine.llm import LlmModel` (spec 2)
- `from src.core.engine.compaction import Compaction` (spec 1 move + rename)
- `from src.core.agents.triage import build_triage_agent` (spec 5)
- `from src.core.agents.conversational import build_conversational_agent` (spec 4)
- `from src.core.agents.data_analyst import build_data_analyst_agent` (spec 4)
- `from src.core.agents.clarification import build_clarification_agent` (spec 4)
- `from src.core.clarification_bus import clarification_bus` (spec 3)

**Retired:**
- `src/core/agents/pipeline.py` — deleted.
- `src/core/pipeline_factory.py` — deleted; its role (wiring agents + tools + session root) moves into a small `build_pipeline()` helper at the top of `src/main.py` (or `src/core/pipeline.py`).

**Tests retired:**
- `tests/core/agents/test_pipeline.py` — covered the retired route-selection pipeline. Replaced by `tests/core/test_pipeline.py`, which tests the new orchestrator end-to-end.

## 12. Acceptance

- `Pipeline.run` is the single callable used by the UI.
- Sessions persist per workspace; dropped on switch.
- Sandbox closed in `finally`.
- Errors surface directly per decision A; no fallback agent path remains.
- Integration tests green; offline assertion passes.
