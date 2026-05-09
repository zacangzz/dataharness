# Spec 8 — Packaging + sandbox runtime

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3, 4, 5, 6, 7
**Blocks:** specs 9, 10 (RW mount + write-guard introduced here is the prerequisite for the knowledge store and analyst feedback loop)

## 1. Purpose

Make the Agents SDK migration ship-capable: PyInstaller build, `UnixLocalSandboxClient` runtime validation, and dep cleanup.

## 2. Scope

### In scope

- `pyproject.toml` updates: remove `smolagents`, add `openai-agents`.
- `hragent.spec` updates: hidden imports, prompt datas, sandbox-runtime glue.
- Probe: confirm `UnixLocalSandboxClient` can execute `python`, `pandas`, and friends inside the packaged binary context.
- If the sandbox needs an external python runtime, decide and implement a minimal strategy (see §5).
- Smoke-test script that builds and launches the binary.
- Documentation update: `APP.MD` describes the new runtime story.

### Out of scope

- Docker backend (deferred per umbrella non-goals).
- Cross-compilation for non-macOS targets.
- Any runtime changes beyond packaging.

## 3. `pyproject.toml`

**Remove:**
```
smolagents>=1.0.0
```

**Add:**
```
openai-agents>=0.1.0
```

(`openai-agents` minimum version pinned after spec 1's probe produces a known-good release. **No new document-parsing deps.** `extract_document_text` (spec 9 §5.7) uses the Gemma multimodal backend already bundled via llama_cpp — no `python-docx` / `pypdf`.)

Retain all other production dependencies unchanged. Dev dependencies unchanged.

## 4. `hragent.spec`

Changes:

- `hiddenimports`: remove `smolagents` (and any `smolagents.*`). Add `agents`, `agents.sandbox`, `agents.sandbox.entries`, `agents.sandbox.capabilities`, `agents.sandbox.sandboxes.unix_local`, `agents.tracing`. No `docx` / `pypdf` — Gemma handles doc extraction.
- `datas`: replace `hr.md` with `triage.md`, `conversational.md`, `analyst.md`, `clarification.md`, `knowledge.md` (spec 11), `doctor.md` (spec 12). Include `compaction_summarize.md` (renamed from `memory_summarize.md`, contents unchanged).
- `datas`: include any auxiliary shell/glue files shipped by `UnixLocalSandboxClient` (discovered during the probe task — listed as concrete paths in the implementation PR).
- Bundle `openai` client and `tiktoken` (if SDK imports it).

## 5. Sandbox runtime probe + strategy

### Probe task (blocking)

1. Build the app as a PyInstaller onefile.
2. Launch the binary; open a workspace with a CSV.
3. Trigger an analyst turn that requires shell + python (for example: "what's the mean of the numeric columns?").
4. Observe how `UnixLocalSandboxClient` spawns processes:
   - Which python does it find?
   - Are pandas / numpy / openpyxl importable inside the sandbox process?
   - Does it inherit the PyInstaller bootloader's temp-extract directory?

### Strategies based on probe outcome

| Outcome | Strategy |
|---|---|
| Sandbox finds host python + packages | No change needed. Document as a runtime requirement: user must have python 3.12 with pandas/numpy/openpyxl installed. |
| Sandbox can reuse the frozen binary's embedded python | Prefer this. Configure `UnixLocalSandboxClient` to point at the PyInstaller-extracted python and bundled site-packages. Document. |
| Neither works | Fall back to Docker backend. Document that analyst turns require Docker. Add `openai-agents[docker]` to deps. Packaged binary detects missing Docker and surfaces a clear error. |

The strategy selected is recorded in the spec's implementation PR description, and `APP.MD` is updated accordingly.

### Data safety

- Workspace is mounted as **two volumes** (spec 9 §9):
  - `<workspace>/data/` → `/workspace/data` — **read-only** to agents. User data files (CSVs, XLSXs, PDFs, MD, etc.) live here.
  - `<workspace>/memory/` → `/workspace/memory` — **read-write** to agents. Holds `session.db`, `files/*.json`, `functions/*.py`, `notes/*.md`.
- Preferred implementation: `UnixLocalSandboxClient` per-volume mode. If the backend does not expose per-volume modes, fall back to `src/core/sandbox_guard.py` — a thin wrapper rejecting write syscalls whose canonical path does not resolve under `/workspace/memory/`. Concrete hook pinned during the probe task (§5).
- Sandbox shell commands are bounded to 60 seconds each (spec 6).
- Workspace switch invalidates sandbox client (spec 6).
- Saved-function execution (`run_saved_function`, spec 9 §5.5) runs inside the same sandbox as shell commands — isolated, time-bounded, no elevated privileges.

Write access is **scoped**, not general: only `memory/` is mutable, so user data stays safe from accidental agent mutation. The transparent split (no hidden folder) lets users inspect, edit, or back up `memory/` directly.

## 6. Smoke test script

`scripts/smoke_packaged.sh` (new or updated):

1. `uv run python -m build` or equivalent to produce wheel (sanity).
2. `scripts/build_app.sh` to produce the onefile binary.
3. Launch binary against a fixture workspace with `data/employees.csv` (20 rows, numeric `salary`) + `data/hr_policy.pdf` (1 page, plain text). Workspace scaffold uses the `data/` + `memory/` split from spec 9 §3.
4. Script-drive the canonical fixtures from spec 6 §10: `greet`, `list-files`, `column-stats`. Record per-fixture wall time + first-token latency to `local/smoke-latency.json`.
5. Assert each turn completes with a final message; `list-files` output contains `data/employees.csv`; `column-stats` output contains a numeric value.
5a. Write-guard assertion: script triggers an analyst turn that tries to overwrite `data/employees.csv`; expect `Error{kind="sandbox_denied"}`. Separately, a `save_python_function` turn succeeds and the `.py` file lands in `<workspace>/memory/functions/`. Validates spec 9 §9 write-scoping on the packaged binary.
5b. Document-extraction assertion: knowledge-agent turn on `data/hr_policy.pdf` invokes `extract_document_text` (Gemma multimodal backend); call returns non-empty text within budget (warn > 30s for a 1-page PDF on reference tier); `memory/notes/hr_policy*.md` written; plain-text content non-empty. Validates Gemma doc-extraction path end-to-end inside the packaged binary (no `pypdf` / `python-docx` involved).
6. Assert no network egress — run the binary under a network namespace or an `LD_PRELOAD` / `DYLD_INSERT_LIBRARIES` shim that refuses connections to non-loopback; any egress attempt fails the smoke test.
7. Assert `hragent-telemetry.log` contains `span_start` + `span_end` records for every turn, with `turn_id` / `run_id` populated.
8. Compare recorded latencies against `tests/integration/budgets.json`; warn if > 1× budget, hard-fail if > 1.5× budget.

Runs in CI on the macOS runner (matching dev environment); other OS targets deferred.

## 7. Documentation

- `APP.MD`: add a "Sandbox runtime" section describing how the analyst agent executes shell commands, what the workspace mount is, and which sandbox backend is in use.
- `README.md`: add a user-facing note about dependencies required in the sandbox runtime (if the probe lands on the host-python strategy).

## 8. Testing

**Smoke (in CI):**
- `uv run pytest -m "not integration"` green (fast gate, every push).
- `uv run pytest -m integration` green on nightly + release-tag CI (real-model suite).
- `scripts/smoke_packaged.sh` exits 0.
- Socket-patched end-to-end turn completes.
- `grep -r smolagents src/ tests/` returns zero.
- Packaged binary launches and serves a turn.

`pyproject.toml` gains `[tool.pytest.ini_options]` with `markers = ["integration: real-model + real-UI slow tests, require HRAGENT_TEST_MODEL_PATH"]`.

## 9. Files

**Modified:**
- `pyproject.toml`
- `hragent.spec`
- `APP.MD`
- `README.md`
- `scripts/build_app.sh` (if required by the probe outcome)

**New:**
- `scripts/smoke_packaged.sh`

**Tests retired:** none. Packaging smoke is covered by `scripts/smoke_packaged.sh`, not pytest.

## 10. Acceptance

- Packaged binary runs an analyst turn end-to-end on a fixture workspace.
- Chosen sandbox-runtime strategy is documented in `APP.MD`.
- CI gates pass.
- `grep -r smolagents .` across the repo returns zero matches.
