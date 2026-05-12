# Observability

Runtime diagnostics are written under `logs/` at the repository root.

- `bootstrap.log` / `bootstrap.events.jsonl`: CLI startup, import, app construction, uncaught exceptions.
- `app.log` / `app.events.jsonl`: Textual lifecycle, compose, mount, widget health, controller input, turn boundaries.
- `harness.log` / `harness.events.jsonl`: routing, context rebuild, prompt packaging, plans, approvals, dispatch.
- `runtime.log` / `runtime.events.jsonl`: prompt size, model call start/end, stream start/end, usage, parser outcomes.
- `worker.log` / `worker.events.jsonl`: sandbox config, subprocess start/end, timeouts, sandbox violations, artifacts.
- `persistence.log` / `persistence.events.jsonl`: database writes and persistence errors.

Useful triage commands:

```bash
grep -E "bootstrap|app.lifecycle|app.compose|app.mount|app.screen|app.error" logs/bootstrap.log logs/app.log
grep "turn=<turn_id>" logs/*.log
jq 'select(.outcome=="error")' logs/*.events.jsonl
jq 'select(.kind=="runtime.model.call.end") | .duration_ms' logs/runtime.events.jsonl
jq 'select(.kind=="worker.subprocess.end") | .payload' logs/worker.events.jsonl
```

For a blank app, compare `app.lifecycle.constructed`, `app.compose.end`, `app.mount.end`, and `app.screen.snapshot`. If construction appears but compose does not, the failure is in Textual composition. If compose appears but mount or screen snapshot is missing, inspect `app.error` and `bootstrap.error`.
