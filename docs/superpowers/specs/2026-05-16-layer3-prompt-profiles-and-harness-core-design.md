# Layer 3 Prompt Profiles And Harness Core Design

Status: design proposal. Supersedes the Layer 4b "agent modes" model in
`2026-05-11-dataharness-comprehensive-app-spec.md`. Implementation lands as one
coherent change set.

## Purpose

Two structural corrections to Layer 3:

1. **Collapse Layer 4b into Layer 3.** The "agent / soul of the app" concept in
   the canonical spec is a fallacy. An "agent" is not a runtime, a tool, or a
   command — it is a prompt persona plus an intent-routing decision. Routing and
   persona-prompt selection are operational truth (spec §3.2), not presentation.
   They belong in Layer 3. The `src/app/agents/` package is removed entirely.

2. **Name the missing Layer 3 kernel and finish the surface split.** The
   Tool / Command / Service taxonomy is a *surface* taxonomy; it never described
   the platform kernel. The kernel is the **Harness Core**. Loose
   `src/harness/*.py` files are sorted into Core, Service, or deleted shims so
   the layer is explainable.

Goal: streamline Layer 3 so its prompt, routing, surface, and kernel code each
have one obvious home, improving logic, explainability, and interpretability.

## Concept Change: Agents Become Prompt Profiles

The "agent" abstraction is **deleted**. There is no Layer 4b.

Layer 3 owns named **prompt profiles**: `interaction`, `analyst`, `knowledge`,
`clarification`. A profile is a persona prompt plus that profile's allowed-tool
set. A profile is selected per turn by an L3 **intent router** that classifies
the user's text. This is the same class of thing as the existing L3 operational
prompts (`compaction`, `doctor`, `knowledge_reconcile`) — a harness-owned prompt
resource, not an app identity.

Routing and profile behavior are **preserved exactly**. This is a relocation and
reframing, not a behavior redesign. The keyword/phrase router logic, the four
profile names, and each profile's allowed-tool list are carried over unchanged.

### Selection Ownership

- Layer 4 delivers only the user's text.
- `Orchestrator.run_agentic_turn(...)` calls the L3 router internally, picks the
  profile, loads the profile prompt, and runs the loop.
- The existing sticky `analysis_flow` override (already Layer 3) continues to
  override the routed profile while a plan is in flight.
- There is **no** `requested_mode` parameter and **no** `prompt_provider`
  callback crossing the Layer 4 ↔ Layer 3 boundary. No user-override seam; a
  future manual-mode control would be added later as a deliberate new data input.

## The Harness Core (Kernel)

Layer 3 is the Harness Core plus three exposed/shared surfaces that hang off it:

```
Harness Core (engine + shared contracts + infra)   ← the platform itself
  ├─ Tools     (model-callable surface)
  ├─ Commands  (user/app-callable surface)
  └─ Services  (shared domain logic behind surfaces & orchestrator workflows)
```

Tools, Commands, and Services hang off the Core. They do not replace it. A file
is **Core** when it is engine machinery, a shared contract/type, or
infrastructure with little or no domain behavior. A file is a **Service** when it
is behavioral domain logic invoked by a tool, command, or orchestrator workflow.

Core has two physical homes:

- `src/harness/core/` holds the **separable kernel** — engine machinery and
  infrastructure that is not imported across layers: `state_machine.py`,
  `factory.py`, `command_registry.py`, `validity.py`, `approval.py`,
  `analysis_flow.py`, `db.py`, `persistence.py`, `app_store.py`, `paths.py`,
  `fingerprints.py`, `workspace.py`, `prompt_registry.py`.
- `src/harness/` root holds the **shared contracts + engine entrypoint** —
  `orchestrator.py` and the high-fanout cross-layer contracts `control.py`,
  `events.py`, `exceptions.py`, `status.py`. These are imported by Layers 1/2/4
  and nearly every test; foldering them is pure churn with cosmetic gain and
  real regression risk. They are Harness Core by role, not by folder.

Tools live in `src/harness/tools/`, Commands in `src/harness/commands/`,
Services in `src/harness/services/`.

## Source Organization

### Removed: `src/app/agents/`

| File | Disposition |
|---|---|
| `prompts/{system,interaction,analyst,knowledge,clarification,response_format,doctor_narrator}.md` | move → `src/harness/prompts/` |
| `router.py` (`AgentModeRouter`) | move → `src/harness/services/mode_router.py`; concept→profile; telemetry `Layer.APP`→`Layer.HARNESS` |
| `prompt_packages.py` (`PromptPackageRegistry`, `_tool_catalog`, `MODE_TOOL_NAMES`) | move → `src/harness/services/prompt_profiles.py`; `MODE_TOOL_NAMES` → profile→allowed-tools table |
| `types.py` (`PromptPackage`) | move → `src/harness/services/prompt_profiles.py` (name kept) |
| `analyst.py` / `interaction.py` / `knowledge.py` (`*Mode`) | **delete** (dead `build_turn`, no callers) |
| `__init__.py` | delete; package removed |

`prompt_profiles.py` and the existing `HarnessPromptRegistry` stay **separate by
concern**, sharing only the prompt root `src/harness/prompts/`:

- `HarnessPromptRegistry` (Core, `prompt_registry.py`) remains the
  *operational*-prompt loader/allowlist (`compaction`, `doctor`,
  `knowledge_reconcile`) — unchanged. Persona names are **not** added to that
  allowlist; persona assembly is a different concern (multi-fragment package +
  tool catalog, not a single gated operational prompt).
- `prompt_profiles.py` (Service) owns persona assembly and reads the persona
  `.md` fragments (`system`, `<profile>`, `response_format`) from the shared
  `src/harness/prompts/` root directly, as `PromptPackageRegistry` does today.

The only reconciliation is the shared root directory, so there is one prompt
home, not two.

### Harness Core moves

The Core split (new `src/harness/core/` kernel; shared contracts +
`orchestrator.py` staying at `src/harness/` root) is defined in
*The Harness Core (Kernel)* above. Every file listed for `core/` is `git mv`'d
there and its importers repointed; the root-level contracts do not move.

### Latent Services → `src/harness/services/`

Behavioral domain logic that was never foldered:

| From | To |
|---|---|
| `knowledge.py` | `services/knowledge.py` |
| `knowledge_intents.py` | `services/knowledge_intents.py` |
| `chat.py` | `services/chat.py` |
| `context.py` | `services/context.py` |
| `workspace_async.py` | `services/workspace.py` |
| `repair.py` | `services/repair.py` |
| `provenance.py` | `services/provenance.py` |

There are intentionally three package-qualified `workspace` modules with
distinct roles: `core/workspace.py` (workspace handle/paths dataclass),
`services/workspace.py` (async workspace operations, ex-`workspace_async.py`),
and `commands/workspace.py` (workspace command family). This is allowed; the
plan must not collapse them.

`analysis_flow.py` is **Core** (state contracts + per-chat registry), not a
service module. `docs/app/services.md` currently lists "Analysis flow" as a
service area; that entry is corrected to reference the Core location, not a
`services/` source owner.

### Deleted shims (canonical owner elsewhere)

- `commands.py` — re-export of `command_registry.HarnessCommandRegistry`; 0 importers.
- `doctor.py` — re-export of `services.doctor`.
- `doctor_runner.py` — re-export of `services.doctor`.

Importers are repointed to the canonical module. These shims are pruned from
`docs/app/services.md`.

### Migration mechanic

**Hard move, repoint all.** `git mv` each file; update every importer in `src`,
`tests`, and `CODEMAP.md` in the same change set. **No compatibility shims** —
the existing `doctor.py`/`commands.py` shims are evidence that re-export cruft
accumulates. `tests/harness/test_service_ownership.py` is updated to assert the
new locations.

## Doctor Narration → Layer 3

LLM doctor narration is **off canonical spec** (the spec's §8.1 doctor event
family is `DoctorStarted`/`DoctorFinding`/`DoctorActionProposed`/
`DoctorReportReady`; it never defined `DoctorNarrationReady` or
`DoctorApprovalRequested`). It is a humanization layer on top of the
spec-required tmp-review approval gate, and it is what currently drags
`runtime.*` into Layer 4 (spec §3.3 violation in `AppSession`).

Decision: **move narration into Layer 3**, do not drop it. Verified: this is
lower-risk than it looks — `src/harness/services/doctor.py` already imports
`runtime.types`, holds `self.runtime`, and already streams the runtime
(narration-style streaming exists at lines ~723/777/840). The Layer 3 doctor
service is the natural and existing home; `AppSession`'s version is a duplicate.
`DoctorNarrationReady`/`DoctorApprovalRequested`/`DoctorActionsApplied` are
already `HarnessEvent` subclasses and already mapped in
`src/app/event_mapping.py`, so preserving event names/payloads is automatic when
Layer 3 emits the same types.

- `doctor_narrator.md` → `src/harness/prompts/`.
- The `AppSession` doctor-narration logic (`_render_doctor_narration`,
  `_stream_doctor_narration_and_approval`, `_fallback_doctor_narration`,
  `_collect_tmp_actions`) is **removed**; the equivalent narration + approval
  emission is consolidated into the Layer 3 doctor service / `doctor` command
  path, which already has the runtime and streams. The `/doctor` command event
  stream emits `DoctorNarrationReady` then `DoctorApprovalRequested` inline
  after `DoctorReportReady`.
- `AppSession.handle_direct_command` loses its `command == "doctor"`
  post-processing branch and becomes a pure passthrough; `AppSession` only maps
  events; its `runtime.*` import is removed, fixing §3.3.
- `docs/app/doctor-behaviour.md` gains an **anomaly note**: LLM narration and the
  `DoctorNarrationReady`/`DoctorApprovalRequested` event pair are off-canonical
  additions over the spec's required tmp-review approval gate, flagged for
  future review.

## AppSession After The Change

`AppSession` keeps: single-active-run gate, app telemetry / turn binding,
`HarnessEvent`→`AppEvent` mapping, and thin passthrough of orchestrator methods.

`AppSession` loses: `mode_router`, `prompt_registry`, the `prompt_provider`
callback, the `requested_mode` plumbing, doctor narration logic, and the
`runtime.types` import. `run_user_turn` becomes: gate + telemetry +
`orchestrator.run_agentic_turn(user_text)` + `to_app_event`.

## Layer 4 Wiring

The Layer 4 ↔ Layer 3 connection was verified against real code. The TUI's
**public surface does not change**; the change is internal to `session.py` and
the orchestrator. This must be explicit so the implementation does not chase
phantom TUI edits.

Verified touchpoints:

- `src/app/tui/app.py:82` — `AppSession(telemetry=..., app_root=...)`. The TUI
  already passes neither `mode_router` nor `prompt_registry`. Removing those
  constructor parameters needs **no TUI change**; this call site is already
  compatible.
- `src/app/tui/app.py:339` — `run_user_turn(state, workspace_dir, chat_id,
  user_text)`. This is *already* the post-refactor public signature.
  `run_user_turn` does **not** change shape; this call site is **unchanged**.
- `src/app/session.py` — the only `src/app` importer of `app.agents`; that
  import is deleted with the package. Internally, `run_user_turn` drops the
  `mode_router.route(...)` call and the `prompt_provider` closure and simply
  calls `orchestrator.run_agentic_turn(...)` without `requested_mode` /
  `prompt_provider`. The public method signature is preserved.
- Orchestrator-internal call sites that pass `requested_mode` / `prompt_provider`
  (`run_agentic_turn`, the handoff re-run, `run_turn`,
  `resume_with_clarification`) are rewired to the Layer 3 router + prompt-profile
  registry instead of injected parameters. Pure Layer 3 change; no Layer 4
  surface impact.

Net Layer 4 code change: delete the `app.agents` import in `session.py` and the
routing/prompt closure inside `run_user_turn`. The TUI (`tui/app.py`) is
untouched by the routing change (doctor wiring below is separate).

## Mode Continuity (active_agent_mode)

Deleting the `requested_mode` plumbing removes the only mechanism that currently
carries the profile across a clarification or follow-up. A bare clarification
reply ("the 2024 one") has no analysis keywords; naive re-routing would send it
to `interaction` and lose the analyst, recreating a known dead-turn failure.

`RunStateRecord.active_agent_mode` exists for this but is **broken**: every
Layer 3 write uses `state.model_copy(update={...})`, returning a discarded copy
while the TUI holds one long-lived `RunStateRecord` by reference. The field is
permanently stuck at its initial `"interaction"` (the "loop never writes back"
pathology already recorded in `Lessons.md`).

Decision — Layer 3 owns and persists the active profile on the run state:

- The orchestrator writes the chosen profile (routed, sticky-flow override, or
  handoff target) **into the passed `RunStateRecord` in place** each turn,
  instead of throwaway `model_copy`. The single long-lived TUI state object
  stays correct.
- `resume_with_clarification` (and any follow-up resume) reads
  `state.active_agent_mode` for continuity instead of receiving a
  `requested_mode` argument. The router still classifies fresh user turns;
  `active_agent_mode` is the continuity anchor for resume/ambiguous text, and
  the sticky `analysis_flow` override still wins while a plan is in flight.
- This fixes the long-standing Lessons-flagged write-back bug as part of this
  work. It is a behavior fix, so it gets its own failing-test-first coverage
  (clarification reply with no keywords resumes under the prior profile).

## Doctor Event Origin (Layer 4 impact)

Doctor narration/approval events now originate in Layer 3. To avoid a TUI
rewrite, the event **names and payload shapes** consumed by
`src/app/event_mapping.py`, `src/app/events.py`, and `src/app/tui/app.py`
(`DoctorNarrationReady`, `DoctorApprovalRequested`, and the doctor-approval
resume path) are **preserved**. Only their origin moves (Layer 3 emits them; the
event mapper maps them; the TUI renders them unchanged). `handle_doctor_approval`
on `AppSession` remains a thin passthrough to the Layer 3 doctor service.

## Layer 4 Connection Acceptance

- The TUI builds an `AppSession` with no agent/router arguments (call site
  unchanged).
- `run_user_turn` keeps its public signature; `tui/app.py` is untouched by the
  routing change.
- A normal user turn renders with Layer-3-selected profiles.
- A clarification reply with no analysis keywords resumes under the prior
  profile (mode continuity).
- The `/doctor` flow still renders narration + approval and applies actions.
- No `app.agents` import anywhere in `src/app`; no `runtime.*` import in
  `src/app`.

## Canonical Spec Amendments (`2026-05-11-...-app-spec.md`)

- §3.3 / §4 topology: remove Layer 4b; Layer 4 = TUI (4a) + `AppSession` facade.
- §7 (Layer 3): add ownership of prompt profiles and intent routing; describe
  the Harness Core (kernel) and the three surfaces on it (Core / Tools /
  Commands / Services).
- §9: delete the Layer-4b subsections (9.2 sibling topology, 9.4 agent modes,
  9.5 prompt ownership claiming personas are Layer 4b). Rewrite 9.1/9.3 so
  `AppSession` no longer owns routing or prompt selection.
- §15 acceptance: reword "no agent bypasses harness ownership" to the
  profile/Core model.

## Cross-Doc Updates

- `docs/app/tools-vs-commands.md`: add the Harness Core (kernel); note prompt
  profiles + mode router are Layer 3 services.
- `docs/app/services.md`: add the Harness Core (kernel) and its boundary; add
  source owners for the migrated services; prune the deleted shims; add
  mode-router / prompt-profile service entries; correct the "Analysis flow"
  entry to point at the Core location (`analysis_flow.py` is Core, not a
  `services/` module).
- `docs/app/doctor-behaviour.md`: anomaly note (above).
- `Lessons.md`: prune/rewrite the "Routing And Prompt Packages" section and the
  L4-`AgentModeRouter` lessons; routing is Layer 3. Add the Harness Core /
  services-location lessons.
- `CODEMAP.md`: update imports, definitions, and call sites for every moved
  module (the four tracked relationship types).

## Tests

- Relocate `tests/app/agents/test_prompt_packages.py` and router tests under
  `tests/harness/`; construct the profile registry from Layer 3 services.
- Update all `app.agents.*` imports to `harness.services.*`.
- Update `test_command_reachability` / `test_agentic_turn` for the dropped
  `requested_mode` / `prompt_provider` parameters.
- Update `tests/app/test_app_session_async.py` — its `FakeOrchestrator`
  `run_agentic_turn` signature still declares `requested_mode` /
  `prompt_provider`; align it with the reduced contract.
- Update `test_service_ownership.py` for new Core / Service locations and the
  deleted shims.
- **New failing-test-first coverage** for mode continuity: a clarification reply
  with no analysis keywords resumes under the prior profile (active_agent_mode
  written back to the live `RunStateRecord`). This is the one intentional
  behavior fix.
- Otherwise no behavior assertions change — routing and profile behavior are
  preserved.

## Out Of Scope

- Redesigning routing heuristics or profile prompt content.
- Moving the high-fanout shared contracts (`control`/`events`/`exceptions`/
  `status`) into a subfolder.
- The separate `2026-05-15` tools/commands/services dispatch-enforcement work,
  except where this refactor's file moves touch the same modules.
- Removing or re-spec'ing doctor LLM narration (only relocated; flagged for
  future review).

## Acceptance

- `src/app/agents/` does not exist.
- `src/app` imports no `runtime.*` and no `app.agents`. Layer 4 still uses
  `AppSession` plus the shared Layer 3 contracts it already depends on
  (`RunStateRecord`, harness events/exceptions); §3.3 only forbids `runtime.*`
  and bypassing `AppSession`, not contract types.
- The orchestrator selects the prompt profile from user text with no Layer 4
  parameter.
- The orchestrator writes the active profile into the live `RunStateRecord`;
  a clarification/follow-up with no keywords resumes under the prior profile.
- Persona prompts load through the Layer 3 prompt loader/allowlist.
- Every moved file has its importers repointed; no re-export shims remain.
- `src/harness/core/` contains the separable kernel; shared contracts remain at
  `src/harness/` root, documented as Harness Core.
- The canonical spec no longer describes Layer 4b or an "agent soul".
- `docs/app/services.md`, `tools-vs-commands.md`, `doctor-behaviour.md`,
  `Lessons.md`, and `CODEMAP.md` reflect the new structure.
- Full test suite green: no *unintended* behavior regressions; the single
  intentional change (mode continuity) is covered by its own tests.
