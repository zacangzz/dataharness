# Services

Services are internal implementation units. They are not Tools and they are not Commands.

## Boundary Rule

- Tools expose model-callable operations.
- Commands expose Layer 4 user/app-callable operations.
- Services hold shared domain logic used by tools, commands, or orchestrator workflows.

## Why Services Exist

Services prevent duplicated logic between model-callable tools and user-callable commands. A command and a tool may both inspect workspace facts, but the workspace inspection logic should live once in a service and be wrapped by separate exposed surfaces.

## Current Service Areas

- Chat service: chat records, compaction, runtime request building.
- Workspace service: workspace listing, activation, ingest, inventory.
- Doctor service: diagnostics, tmp review, source checks, proposed actions.
- Knowledge service: preferences, notes, gaps, function candidates, memory proposals.
- Analysis service: plan validation, step contracts, approval state, artifact/provenance access. The model path is two-step — the model emits a code-free plan (gen-1); the harness synthesizes each step's Python via an internal fenced gen-2 (one bounded retry per step), validates it, then emits a single approval. The command path supplies code directly and skips gen-2.
- Analysis flow: a Layer-3-owned per-chat state machine (`AnalysisPhase`: INSPECTING → PLAN_PENDING → APPROVAL_PENDING → EXECUTING → DONE/FAILED) persisted in `state/analysis_flows.jsonl` (mirror of pending plans, replayed on init, terminal/dropped pruned). While a flow is in-flight the orchestrator overrides the per-message routed mode to analyst (sticky); the per-message Layer-4 router can no longer lose it. When the analyst answers in prose without emitting the plan tool call — but only after it actually inspected data or signalled plan intent — the orchestrator FORCES one code-free `analysis_plan` tool call via a dedicated non-persisted generation with `stop=["</tool_call>"]`, one bounded retry, then a loud `FinalMessage` if still absent (never a silent dead turn). This obsoletes a GBNF grammar. While APPROVAL_PENDING, approve/reject/show-plan are handled deterministically with no model turn (cannot hallucinate "already ran it"); free-form questions run a normal analyst turn with the stashed plan injected for grounding. The command path (`/plan_analysis`) creates no flow and is unaffected.
- Context service: durable workspace context, file schema snapshots, token-budgeted context assembly.
- Status service: authoritative workspace/run/chat status snapshots.

## Current Source Owners

- `src/harness/services/doctor.py`: doctor diagnostics, tmp review, source checks, proposed doctor actions, and doctor event orchestration.
- `src/harness/services/analysis.py`: analysis plan validation, model code-free plan assembly, command-path plan handling, approval request events, and pending plan packaging.
- `src/harness/services/workspace_files.py`: workspace file inventory, schema inspection, and bounded text reads shared by tools and commands.

Compatibility modules may re-export service-owned definitions during migration, but new Layer 3 code should import from `src/harness/services/*`.

## Exposure Rule

A service method can be called by a tool, command, or orchestrator workflow. It must not appear directly in the prompt catalog, slash command catalog, command palette, or TUI controls unless wrapped by a Tool or Command descriptor.
