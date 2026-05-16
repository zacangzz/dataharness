# Plan: analysis tool set — structural analysis-flow state machine

Status: IMPLEMENTED & GREEN (depth=structural state machine; APPROVAL_PENDING
behaviour=hybrid by intent; forced-emission gated to "only after inspection"
per user). Tasks #13–#19 complete via TDD; 653 passed, sole failure is the
pre-existing isolated-pass worker-sandbox timeout flake (Lessons-documented,
not a regression). Phase 2 (S1 GBNF) DROPPED, not deferred. Remaining:
user-run manual verification gate (rebuild `dist`, replay
chat_49f36c9b3e4a). Supersedes the prior staged S3a/S3b + Phase-2-grammar
plan.

## Root cause (verified this session — chat_49f36c9b3e4a / boot=5e120375)

`grep -cE "analysis_plan|tool_call|_assemble_plan|parse_error|..." harness.log`
= 0 for the whole session. `analysis_plan` was NEVER dispatched; no
parse_error; Phase 1 code never reached. Two independent structural gaps:

- **Gap A — absent tool_call.** Decisive turn `turn_016ffa33a243`
  (mode=analyst, iteration=2, input_chars=2788 = file_read result fed back):
  runtime `finish_reason=stop`, then `run_agentic_turn end iterations_done=2`.
  Model emitted only prose ("I will use the `analysis_plan` tool to
  outline...") and NO `<tool_call>`. In `run_agentic_turn`
  (`orchestrator.py`): `effective` empty → not handoff, not dispatchable
  (1474), not `empty_failed`, not `malformed_failed` → falls through to the
  silent `return` at **1567-1568**. Prose becomes the final answer. There is
  NO nudge for "analyst was expected to produce a plan tool_call but emitted
  prose." The malformed-nudge (1540-1565) only fires when a tool_call WAS
  emitted but broke.
- **Gap B — mode not sticky.** L4 `AgentModeRouter.route` (`session.py:72`)
  picks mode per-message from text only. "ok proceed" → no analysis terms →
  `front_door_default` → interaction (`router.py:90`). `run_turn:1709`
  `active_mode = requested_mode or state.active_agent_mode` — the L4
  requested_mode is always truthy so it always wins. `state.model_copy(
  update={"active_agent_mode": handoff_target})` at `1469` is a LOCAL copy;
  the TUI holds ONE long-lived `RunStateRecord` (`tui/app.py:86`) passed by
  reference and never updated by the loop. So after the analyst turn ends
  without a plan, every follow-up ("ok proceed", "ok", "show me the plan")
  runs `mode=interaction`, where `analysis_plan` is not available, and the
  model hallucinates "I have generated the analysis plan" (msg 8/10/12).

Not in `Lessons.md`. Adjacent rules (L98-100 malformed-nudge, L304-315
classify-by-error_code / FinalMessage-not-silent, L126-134 plans originate
from the tool call) ALL assume a tool_call was emitted. The
absent-tool_call + prose-intent + silent-loop-end + interaction-mode-
hallucination chain is a new, distinct failure mode.

## Decision

- Depth: **structural analysis-flow state machine**, Layer 3 owned.
- APPROVAL_PENDING user input: **hybrid by intent** (deterministic for
  approve / reject / show-plan; context-injected analyst turn for free-form
  questions about the pending plan).
- **Phase 2 (S1 GBNF) DROPPED.** Forced tool-call emission with a stop-token
  + validate + bounded retry is strictly stronger and simpler than a GBNF
  grammar over a whole analyst turn, and the Phase-1 core insight (tiny
  code-free JSON → near-zero malform) means a grammar adds ~0 once emission
  is forced. Tasks #7/#8 closed as dropped.

## Layer ownership (AGENTS.md / Lessons L22-25)

L4 `AgentModeRouter` still PROPOSES the initial mode and provides
`prompt_provider`. L3 harness OWNS the agentic loop, tool dispatch, handoff,
and now the analysis flow. L3 OVERRIDES the proposed mode when a flow is
in-flight for the chat — exactly analogous to the existing model-handoff
override at `1459-1472`. No new write paths added at L4; the TUI's
long-lived `_state` problem is sidestepped by keeping flow state in L3
(registry persisted like `_pending_plans`), not by plumbing state back to L4.

## New domain types (Layer 3)

New module `src/harness/analysis_flow.py` (keep `control.py` focused; do NOT
overload `RunStateRecord.state`, which is shared by non-analysis runs):

- `class AnalysisPhase(StrEnum)`: `INSPECTING`, `PLAN_PENDING`,
  `APPROVAL_PENDING`, `EXECUTING`, `DONE`, `FAILED`.
- `class AnalysisFlow(BaseModel)`: `chat_id: str`, `run_id: str`,
  `workspace_id: str`, `phase: AnalysisPhase`, `goal: str | None`,
  `plan_id: str | None`, `original_request: str | None`,
  `inspection_summary: str | None`, `force_attempts: int = 0`,
  `created_at`, `updated_at`.

## Orchestrator state + persistence (mirror `_pending_plans`)

- `self._analysis_flows: dict[str, AnalysisFlow]` keyed by `chat_id`
  (init alongside `_pending_plans` at `orchestrator.py:301-302`).
- Append-log `analysis_flows.jsonl` with `_append_analysis_flow(...)`
  (mirror `_append_pending_plan`).
- `_replay_analysis_flows()` on init (mirror `_replay_pending_plans`,
  `507-523`); prune entries already `DONE`/`FAILED` on replay.
- Helpers: `_get_flow(chat_id)`, `_set_phase(chat_id, phase, **patch)`
  (updates dict + appends log + bumps `updated_at`), `_drop_flow(chat_id)`.

## State transitions

- **Create / INSPECTING:** entering analyst (router `analysis_intent` OR
  model `handoff_to_analyst`) for an analysis question with no existing
  flow → create `AnalysisFlow(phase=INSPECTING, original_request=user_input)`.
- **INSPECTING (stay):** `file_read` dispatched in analyst — data gathering;
  capture a short inspection summary into `flow.inspection_summary` from the
  tool result.
- **→ PLAN_PENDING:** analyst iteration in INSPECTING produces prose-only
  (no tool_call, no failure) — i.e. the model is "done inspecting / about to
  plan". (This is exactly the Gap-A trigger; instead of the silent return we
  move to PLAN_PENDING and force the plan call.) Also entered if the model
  itself starts emitting plan intent.
- **→ APPROVAL_PENDING:** `_assemble_plan_events` → `_finalize_plan`
  emits `ApprovalRequired`; set `flow.plan_id = plan.id`. (The existing
  `return` at `1452`/`1505` already suspends the loop for the approval gate.)
- **→ EXECUTING:** `resume_approved_step` starts the worker.
- **→ DONE:** approved step execution completes successfully
  (CommandCompleted with artifacts) → `_drop_flow(chat_id)`.
- **→ FAILED:** forced-emission exhausted, plan assembly unrecoverable, or
  execution hard-fail → emit `FinalMessage` (never silent; Lessons
  L313-315) → `_drop_flow(chat_id)`.

## Fix A — orchestrator-driven forced plan emission

Do NOT rely on the model volunteering `<tool_call>analysis_plan` in free
chat. New `async def _force_plan_tool_call(self, state, *, flow,
workspace_dir, chat_id, run_id, correction=None) -> dict | None`:

- Build a minimal `RuntimeRequest` (mirror `_generate_step_code` at the
  gen-2 region; reuse `self._runtime_lock`, `self.runtime.stream`, fresh
  `request_id`, NOT persisted as chat):
  - system: "Emit EXACTLY ONE `<tool_call>` for `analysis_plan` with
    code-free arguments `{goal, steps:[{purpose, declared_inputs,
    expected_outputs}]}`. No prose, no other tool."
  - user: `flow.original_request` + workspace schema snapshot
    (`_workspace_schema_snapshot`) + `flow.inspection_summary` + optional
    `correction`.
  - `stop=["</tool_call>"]`; re-append the literal `</tool_call>` to the
    collected buffer before parsing.
- Parse with the existing tool-call parser
  (`event_from_tool_call_text` / `tool_calls` module). Valid code-free
  `analysis_plan` args → return args. Absent/invalid → return None.
- Caller (in `run_agentic_turn`, replacing the silent `1567` return when
  `active_mode == "analyst"` and `flow.phase == PLAN_PENDING`):
  1. `args = _force_plan_tool_call(...)`.
  2. None/invalid and `flow.force_attempts == 0` → bump `force_attempts`,
     retry once with `correction` describing what was missing.
  3. Still None/invalid → `FinalMessage` (plain language) + phase FAILED +
     drop flow + return.
  4. Valid → dispatch through the EXISTING `_assemble_plan_events` (gen-2
     per step + validate + bounded retry unchanged) → `_finalize_plan` →
     `ApprovalRequired` → phase APPROVAL_PENDING → return (approval gate).
- The passive path still works: if the model DOES emit a valid
  `analysis_plan` tool_call on its own, the existing dispatch (1474-1528)
  handles it and we just advance the phase — forcing only triggers on the
  prose-only-at-PLAN_PENDING gap.

This obsoletes Phase 2: tiny code-free JSON + `stop` + parse + validate +
one retry ≈ near-zero malform; a GBNF grammar would add complexity for ~0.

## Fix B — sticky analyst while flow in-flight

- **Entry guard** at the top of `run_agentic_turn` (before
  `active_mode = requested_mode`): if `flow = self._analysis_flows.get(
  chat_id)` exists and `flow.phase in {INSPECTING, PLAN_PENDING,
  APPROVAL_PENDING, EXECUTING}` → set `active_mode = "analyst"` (log an
  override line analogous to `ModeHandoffAccepted`; reason
  `"analysis_flow_sticky"`). L4 router untouched.
- **APPROVAL_PENDING — hybrid by intent** (new branch evaluated when a flow
  for the chat is APPROVAL_PENDING, BEFORE the normal runtime stream):
  - Deterministic, NO model turn:
    - approve intent (`approve`, `ok proceed`, `proceed`, `yes run it`,
      `run it`, bare `ok`/`go` while APPROVAL_PENDING) → drive the existing
      approval/resume affordance for `flow.plan_id` (emit the
      `ApprovalRequired`/plan so L4's existing approval UI handles it; do
      NOT fabricate a model answer).
    - reject intent (`reject`, `cancel`, `no`) → cancel plan, phase FAILED/
      DONE, drop flow, `FinalMessage`.
    - show-plan intent (`show me the plan`, `show plan`, `what's the plan`,
      `display the plan`) → deterministically render the stashed
      `_pending_plans[flow.plan_id]` (PlanReady-style render), no model.
  - Free-form question about the pending plan (anything else) → run a
    normal analyst turn but inject the stashed plan + approval state into
    the durable/context block so the answer is grounded (context-injected
    analyst turn). Intent match is keyword/heuristic; ambiguous → treat as
    free-form (safer: grounded answer, not an accidental approve).
- **Disarm:** phase → DONE/FAILED drops the flow; mode routing returns to
  normal automatically (no flow → no override).

## Anticipated changes (NO CODE YET)

1. `src/harness/analysis_flow.py` (new) — `AnalysisPhase`, `AnalysisFlow`.
2. `src/harness/orchestrator.py` — flow registry + `_append_analysis_flow` +
   `_replay_analysis_flows` + `_get_flow`/`_set_phase`/`_drop_flow`; entry
   sticky-override guard; APPROVAL_PENDING hybrid branch; replace silent
   `1567` return with PLAN_PENDING forced-emission path;
   `_force_plan_tool_call`; phase sets in `_dispatch_tool_call` /
   `_finalize_plan` / `resume_approved_step`; FinalMessage on exhaustion.
3. `src/app/agents/prompts/analyst.md` — tighten: after inspection, emit the
   `analysis_plan` tool_call directly (no narration). (Forcing no longer
   DEPENDS on prompt compliance; this just reduces unnecessary forced gens.)
   Content-only; no `.spec` change (no new packaged resource).
4. `docs/app/tools-vs-commands.md`, `docs/app/services.md` — document the
   analysis-flow state machine, sticky override, forced emission, hybrid
   approval handling, Phase 2 dropped.
5. `CODEMAP.md` — new module `harness/analysis_flow.py`; edges:
   `Orchestrator._force_plan_tool_call`, flow registry persistence/replay,
   `run_agentic_turn` → flow guard/transitions.
6. `Lessons.md` — APPEND after code verified: absent-tool_call prose
   failure & detection at PLAN_PENDING; L3-owned sticky analysis flow vs
   per-message L4 routing; forced emission obsoletes the GBNF grammar.

## TDD order (red→green isolated)

1. `AnalysisFlow`/`AnalysisPhase` create + `analysis_flows.jsonl`
   append + `_replay_analysis_flows` (prune DONE/FAILED).
2. Sticky entry guard: flow INSPECTING/PLAN_PENDING/APPROVAL_PENDING/
   EXECUTING + L4 requested_mode=interaction → loop runs mode=analyst.
3. Prose-only at INSPECTING → phase PLAN_PENDING (no silent return).
4. `_force_plan_tool_call` happy: FakeRuntime emits one code-free
   `<tool_call>analysis_plan</tool_call>`; assert NOT persisted; assert
   `stop=["</tool_call>"]`; returns parsed args.
5. PLAN_PENDING → forced emission → `_assemble_plan_events` → single
   `ApprovalRequired`; phase APPROVAL_PENDING.
6. Forced emission invalid once → one retry w/ correction → recover;
   exhausted → `FinalMessage` + phase FAILED + flow dropped (no silent).
7. APPROVAL_PENDING deterministic: "ok proceed" → approval affordance for
   flow.plan_id (NO model turn, no hallucination); "show me the plan" →
   stashed plan rendered (NO model turn); "reject" → cancel + drop.
8. APPROVAL_PENDING free-form ("why two steps?") → analyst turn with plan
   context injected (model turn, grounded).
9. resume_approved_step → phase EXECUTING; success → DONE + flow dropped →
   next message routes normally (no override).
10. Command path `_analysis_plan_events` / `/plan_analysis` unaffected
    (no flow created, no forcing, no sticky).
11. Full `pytest`; fix regressions (expect prior 620 baseline green).

## Verification gate (manual, user-run; Lessons habit)

Rebuild `dist` (`bash scripts/build_app.sh`), run `dist/dataharness`,
replay chat_49f36c9b3e4a exactly: "help me determine new hire rates over
last 2 months using @data/employment_history.csv + @data/employees.csv" →
let it inspect → "ok proceed" → "show me the plan". PASS = analyst stays
sticky, plan tool_call forced & emitted, single `ApprovalRequired`, "show
me the plan" renders the real stashed plan (no hallucination), approve →
execution → artifacts; inspect `dist/harness/logs/harness.log` for the
flow transitions and absence of interaction-mode plan hallucination.

## Open risks

- Forced gen is still a weak model writing the tiny code-free plan —
  mitigated by tiny JSON + `stop` + parse + validate + one retry +
  FinalMessage floor (Phase-1 core insight; why grammar is unnecessary).
- Flow staleness across crashes — `_replay_analysis_flows` prunes
  DONE/FAILED; consider a max-age prune.
- Over-sticky trap — phase must reach DONE/FAILED and drop; verify the
  EXECUTING→DONE transition fires on real CommandCompleted, not only tests.
- Approval-intent keyword matching — ambiguous input falls back to grounded
  free-form analyst turn, never an accidental approve.

## Guardrails (AGENTS.md)

CODEMAP read before edits (done). Update CODEMAP after if the 4 relationship
types change. `uv` only; never edit `.venv`. Probes
`UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src`. No `git commit` without
permission. Specs light on code. Layer discipline: flow state + forcing +
sticky override = Layer 3; router unchanged at Layer 4; tool-call parsing
reused from Layer 1. Append `Lessons.md` at END, only after code verified.
TDD: no production code without a failing test first.
