# Services

Services are internal implementation units. They are not Tools and they are not Commands.

## Boundary Rule

- Tools expose model-callable operations.
- Commands expose Layer 4 user/app-callable operations.
- Services hold shared domain logic used by tools, commands, or orchestrator workflows.

## Harness Core (Kernel)

Layer 3 is split into a separable **Harness Core (kernel)** and **harness services**.

The kernel lives under `src/harness/core/` and is the layer-pure heart of the harness: state machine, command registry, approval gate, plan validity, analysis flow, persistence/db, app store, paths, fingerprints, kernel workspace store, and prompt registry. Kernel modules do not depend on harness services.

Shared contracts stay at the `src/harness/` root: `control.py`, `events.py`, `exceptions.py`, `status.py`, and `orchestrator.py` (the composer that wires the kernel and services together).

Services live under `src/harness/services/`. A service may depend on the kernel and on shared contracts; the kernel must not depend on a service.

Boundary: nothing in `src/harness/core/` imports from `src/harness/services/`. There is no `app.agents` package — routing and prompt profiles are services, not Layer 4 code.

## Why Services Exist

Services prevent duplicated logic between model-callable tools and user-callable commands. A command and a tool may both inspect workspace facts, but the workspace inspection logic should live once in a service and be wrapped by separate exposed surfaces.

## Current Service Areas

- Mode router service: deterministic keyword/LLM-fallback intent routing returning a `ProfileDecision` (`.mode`/`.reason`); `request_mode()` is a stable alias of `route()`; telemetry emits at `Layer.HARNESS`.
- Prompt profiles service: `PromptProfileRegistry` assembles a `PromptPackage` (mode/template_version/prompt_text/package_hash) from persona prompts plus the mode tool catalog; `MODE_TOOL_NAMES`/`_tool_catalog` map modes to model-facing tools.
- Chat service: chat records, compaction, runtime request building.
- Knowledge service: dataset knowledge, notes, preferences, gap/function candidate proposals, and memory-update proposals (`knowledge`); knowledge-intent dispatch (`knowledge_intents`).
- Repair service: deterministic plan/code repair attempts.
- Provenance service: lineage records and reuse-allowed checks.
- Workspace service: workspace listing, activation, ingest, inventory.
- Doctor service: diagnostics, tmp review, source checks, proposed actions.
- Analysis service: plan validation, step contracts, approval state, artifact/provenance access. The model path is two-step — the model emits a code-free plan (gen-1); the harness synthesizes each step's Python via an internal fenced gen-2 (one bounded retry per step), validates it, then emits a single approval. The command path supplies code directly and skips gen-2.
- Analysis flow: a kernel module (`harness.core.analysis_flow`, NOT a service) — a Layer-3-owned per-chat state machine (`AnalysisPhase`: INSPECTING → PLAN_PENDING → APPROVAL_PENDING → EXECUTING → DONE/FAILED) persisted in `state/analysis_flows.jsonl` (mirror of pending plans, replayed on init, terminal/dropped pruned). While a flow is in-flight the orchestrator overrides the per-message routed mode to analyst (sticky); the Layer-3 `ModeRouter` can no longer lose it. When the analyst answers in prose without emitting the plan tool call — but only after it actually inspected data or signalled plan intent — the orchestrator FORCES one code-free `analysis_plan` tool call via a dedicated non-persisted generation with `stop=["</tool_call>"]`, one bounded retry, then a loud `FinalMessage` if still absent (never a silent dead turn). This obsoletes a GBNF grammar. While APPROVAL_PENDING, approve/reject/show-plan are handled deterministically with no model turn (cannot hallucinate "already ran it"); free-form questions run a normal analyst turn with the stashed plan injected for grounding. The command path (`/plan_analysis`) creates no flow and is unaffected.
- Context service: durable workspace context, file schema snapshots, token-budgeted context assembly.
- Status service: authoritative workspace/run/chat status snapshots.

## Current Source Owners

- `src/harness/services/mode_router.py`: `ModeRouter` + `ProfileDecision`; intent routing. Re-exported from `harness.services`.
- `src/harness/services/prompt_profiles.py`: `PromptProfileRegistry` + `PromptPackage`, `MODE_TOOL_NAMES`, `_tool_catalog`; persona prompts under `src/harness/prompts/`. Re-exported from `harness.services`.
- `src/harness/services/knowledge.py`: dataset knowledge, notes, preferences, gap/function proposals (`KnowledgeManager`).
- `src/harness/services/knowledge_intents.py`: knowledge-intent dispatch (`handle_knowledge_intent`).
- `src/harness/services/chat.py`: chat records, compaction, runtime request building.
- `src/harness/services/context.py`: durable workspace context, schema snapshots, token-budgeted context assembly.
- `src/harness/services/repair.py`: deterministic plan/code repair.
- `src/harness/services/provenance.py`: lineage records and reuse-allowed checks.
- `src/harness/services/workspace.py`: async workspace manager (formerly `workspace_async`, renamed). Distinct from `core/workspace.py` (the kernel workspace store) and `services/workspace_files.py` (file inventory/schema reads).
- `src/harness/services/doctor.py`: doctor diagnostics, tmp review, source checks, proposed doctor actions, and doctor event orchestration (including LLM narration / approval-request emission, see `docs/app/doctor-behaviour.md`).
- `src/harness/services/analysis.py`: analysis plan validation, model code-free plan assembly, command-path plan handling, approval request events, and pending plan packaging.
- `src/harness/services/workspace_files.py`: workspace file inventory, schema inspection, and bounded text reads shared by tools and commands.

The migration is complete: the re-export shims `src/harness/commands.py`, `src/harness/doctor.py`, and `src/harness/doctor_runner.py` are deleted. (The `src/harness/commands/` package of real command modules still exists.) Import services from `src/harness/services/*` and kernel modules from `src/harness/core/*`.

## Exposure Rule

A service method can be called by a tool, command, or orchestrator workflow. It must not appear directly in the prompt catalog, slash command catalog, command palette, or TUI controls unless wrapped by a Tool or Command descriptor.
