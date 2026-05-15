# Async Layered Architecture — Implementation Plan Index

Date: 2026-05-03
Spec: [`docs/superpowers/specs/2026-05-01-async-layered-architecture-design.md`](../specs/2026-05-01-async-layered-architecture-design.md)

This migration is split into six implementation plans plus a cleanup/acceptance plan. Plans must be executed roughly in order; later plans assume earlier plans are merged because they import the new types.

| # | Plan | Spec § | Depends On |
|---|------|--------|------------|
| 1 | [Layer 1 Runtime](./2026-05-03-async-layer-1-runtime.md) | §6 | — |
| 2 | [Layer 2 Worker](./2026-05-03-async-layer-2-worker.md) | §7 | 1 |
| 3a | [Layer 3 Orchestrator + Events + Status](./2026-05-03-async-layer-3a-orchestrator-events-status.md) | §8 (events, status, run guard) | 1, 2 |
| 3b | [Layer 3 Chat Sessions + Persistence + Compaction](./2026-05-03-async-layer-3b-chat-sessions.md) | §8 (chat, request assembly, compaction) | 3a |
| 3c | [Layer 3 Commands + Workspace + Doctor](./2026-05-03-async-layer-3c-commands-workspace-doctor.md) | §8 (command surface, slash, /help, /doctor, workspace) | 3a, 3b |
| 4 | [Layer 4 Async TUI + AppSession](./2026-05-03-async-layer-4-tui.md) | §3, §9 | 3a, 3b, 3c |
| 5 | [Cleanup + V1 Acceptance](./2026-05-03-async-migration-cleanup-and-acceptance.md) | §11, §12, §13 | all of the above |

## Execution Notes

- Each plan is TDD: every code-producing step has a failing-test step in front of it.
- Each plan ends with a self-review checklist mapping its tasks back to the relevant spec section.
- Plan 5 contains the V1 acceptance binding from spec §13. It is the only plan that should turn red if any earlier plan left a gap.
- Per `AGENTS.md`: do not commit without permission; do not skip hooks; use `uv` for dependency changes; update `Lessons.md` / `Issues.md` via cheap subagents.
- Per spec §11: this is a breaking migration. There must be no compatibility shims for `Runtime.complete`, sync `stream`, sync `PythonStepExecutor.execute`, `Orchestrator.handle_turn`, `AppTurnResult`, `SessionConfig.max_parallel_runs`, `compact_context`, or `WorkspaceActivated` after plan 5 completes.
