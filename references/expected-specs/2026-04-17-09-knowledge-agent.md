# Spec 9 — Persistent knowledge store + tool contracts

**Date:** 2026-04-17
**Parent:** `2026-04-17-00-openai-agents-migration-design.md`
**Depends on:** specs 1, 2, 3, 4, 5, 6, 7, 8
**Blocks:** spec 10 (analyst consumes store), spec 11 (knowledge agent body), spec 12 (doctor agent body)

> **Split note.** This spec defines the **store** and **tool contracts** only. Knowledge agent behavior, entry points, and prompt live in spec 11. Doctor agent behavior, entry points, and prompt live in spec 12. Earlier drafts bundled all three here; they were split out for clarity and independent buildability.

> **Note on examples.** JSON blobs, markdown samples, file names, gap topics, and fixture prompts in this spec are **illustrative only**. The app is problem-agnostic — the knowledge agent adapts to whatever domain the user brings (HR, finance, logistics, research, anything else). Nothing in the runtime hardcodes "bonus", "salary", "attrition", "department", or any other domain term; wherever those appear below they are placeholders for the user's actual content.

## 1. Purpose

Define the **persistent knowledge store** and its **tool contracts**. Metadata, reusable Python helpers, distilled markdown notes, a notes search index, and gap-signal files live inside the workspace. Agents (spec 10 analyst, spec 11 knowledge, spec 12 doctor) read + write through the tools declared here. The store is file-based, grep-able, version-controllable, portable (moves with the workspace folder), and survives session wipes.

Intake is **optional**. If the user skips a file, the store stays minimal for that file and the analyst relies on structural inspection. The user can resume intake later via the knowledge agent (spec 11 §6).

### Workspace ≠ store

The **workspace** is an app-level feature: a sandbox + playground threaded through the whole app. It is scaffolded, opened, switched, and watched by dedicated workspace code (`WorkspaceManager`, `filedrop.py`, active-dir context var — see umbrella spec 00 §11 Workspace contract). The store **operates inside** a workspace but does not own it. Workspace setup, drop routing, lazy migration, and active-dir propagation are not this spec's responsibility.

Writing rules are absolute and symmetric:
- **User** writes only to `<workspace>/data/` (via filedrop or OS file manager).
- **Agents** write only to `<workspace>/memory/` (via scoped sandbox mount).

## 2. Scope

### In scope

- Persistent knowledge store schema under `<workspace>/memory/` (files metadata with `intake_status`, explicit user preferences, saved functions, distilled notes with `notes/index.json`, gaps).
- Freshness / drift detection: `intake_status` field on file metadata, lazy stale-digest detection in tool read-paths, `drift` block inside `list_knowledge` manifest (consumed by Pipeline pre-triage `drift_detected` signal — spec 5 §4).
- Knowledge + document `@function_tool` callables (signatures declared in spec 3 §5.1; semantics + atomic-write + schema-validation rules live here):
  - `get_file_metadata`, `set_file_metadata`
  - `get_user_preferences`, `update_user_preferences`
  - `list_saved_functions`, `save_python_function`, `run_saved_function`
  - `read_text`, `extract_document_text`
  - `write_knowledge_note`
  - `search`, `file_digest`
  - `list_knowledge(verbosity="manifest"|"detail")`
  - `call_knowledge(task, context)` — Option D sub-run contract (tool body; caller allow-list: `data_analyst` + `doctor`)
  - `delete_saved_function`, `delete_knowledge_note`, `delete_file_metadata`, `rebuild_index(kind)` — doctor-exclusive destructive tools with caller-auth
- Sandbox mount delta (spec 8): `/workspace/data` RO + `/workspace/memory` RW.
- Gemma multimodal document text extraction (see §5.7).
- Ownership table (§7) — which agent may write which part of the store, which delegation pattern.
- Tool + store telemetry attributes.

### Out of scope

- Knowledge agent behavior, entry points, prompt — **spec 11**.
- Doctor agent behavior, entry points, collaboration body, prompt — **spec 12**.
- Analyst behavior — spec 10.
- Triage signal computation / handoff rules — spec 5.
- Advanced document extraction beyond Gemma multimodal (OCR, table reconstruction, layout preservation) — future spec.
- Versioning or history of metadata edits (last-write-wins JSON).
- Inferred preferences from behavior. Migration scope persists only explicit user-stated preferences.
- Vector search / embeddings over notes (literal + regex `search` covers current queries).
- Editing saved functions via UI (edit via agent conversation).
- Cross-workspace knowledge sharing.
- Workspace scaffolding, drop routing, lazy migration, active-dir propagation — owned by spec 00 §11 Workspace contract.

## 3. Knowledge store layout

Illustrative tree — the only fixed parts are the directory names (`files/`, `functions/`, `notes/`, `notes/gaps/`) and schemas in §3.1–§3.5.

```
<workspace>/
├── data/                           # user writes; RO to agents
│   ├── <user file>.csv
│   ├── <user file>.xlsx
│   ├── <user doc>.pdf
│   └── <user notes>.md
└── memory/                         # agent writes; user may inspect/edit
    ├── session.db                  # SQLiteSession (spec 6)
    ├── files/                      # metadata JSON per data file
    │   └── <user file>.csv.json
    ├── preferences.json            # explicit user-stated preferences
    ├── functions/                  # reusable .py + index
    │   ├── index.json
    │   └── <fn_name>.py
    └── notes/                      # agent-distilled markdown
        ├── index.json              # search guidance — summary + keywords per note
        ├── <topic>.md
        └── gaps/                   # analyst → knowledge handoff signals (spec 10 §7)
            └── <topic>.md
```

### 3.1 `memory/files/<filename>.json` (schema)

Example shown with HR-ish content; same schema applies to any domain. Fields marked with `?` are optional.

```json
{
  "schema_version": 1,
  "path": "data/<user file>.csv",
  "source_digest": "sha256:abcdef…",
  "intake_status": "complete",
  "last_onboarded_at": "2026-04-18T10:22:13Z",
  "last_checked_at": "2026-04-18T10:22:13Z",
  "summary": "<one-sentence purpose>",
  "columns": [
    {
      "name": "<column>",
      "dtype": "<pandas dtype>",
      "meaning": "<what it represents>",
      "unit": "<unit, e.g. USD, hours, count>",
      "notes": "<caveats, exclusions>"
    }
  ],
  "metrics": [
    {
      "name": "<metric name>",
      "definition": "<how to compute>"
    }
  ],
  "notes_refs": ["memory/notes/<topic>.md"]
}
```

Atomic writes (`.tmp` → rename). `source_digest` lets the agent detect a re-uploaded changed file and re-trigger intake.

**`intake_status` values** (drives `drift_detected` triage signal per spec 5 §4):

| Value | Meaning | Set by |
|---|---|---|
| `complete` | Full intake done; columns/metrics captured. | knowledge agent on successful intake. |
| `minimal` | User said "skip"; only `path` + `source_digest` + timestamps stored. | knowledge agent per spec 11 §6 skip path. |
| `stale` | `source_digest` no longer matches the current file on disk. | Lazy detection inside tool read-paths (§5 stale-digest check); stamped atomically; `last_checked_at` updated. |
| `orphan` | `path` no longer exists in `data/`. | Detected at `list_knowledge` assembly time; stamped atomically if the metadata file itself still exists. |

Doctor resolves all three non-`complete` states (spec 12 §5.3). Knowledge agent only writes `complete` or `minimal`.

### 3.2 `memory/functions/index.json` (schema)

```json
{
  "schema_version": 1,
  "entries": [
    {
      "name": "<fn_name>",
      "file": "<fn_name>.py",
      "signature": "run(path: str) -> dict",
      "docstring": "<short description>",
      "inputs_required": ["path"],
      "source_files": ["data/<user file>.csv"],
      "source_digests": {"data/<user file>.csv": "sha256:abcdef…"},
      "schema_fingerprint": "<stable schema hash for the files this function expects>",
      "created_by": "knowledge" | "data_analyst",
      "created_at": "2026-04-18T10:22:13Z",
      "last_used_at": "2026-04-18T10:24:02Z",
      "validated_at": "2026-04-18T10:24:02Z",
      "validation_status": "valid" | "stale" | "schema_mismatch"
    }
  ]
}
```

Both `knowledge` and `data_analyst` can write here (see §5.4, §7).

### 3.2a `memory/preferences.json` (schema)

Explicit user-stated preferences only. No behavioral inference in migration scope.

```json
{
  "schema_version": 1,
  "answer_style": {
    "format": "table" | "bullets" | "short_prose",
    "include_sources": true
  },
  "units": {
    "<metric_or_column>": "<preferred_unit>"
  },
  "naming": {
    "<field_or_metric>": "<preferred_label>"
  },
  "updated_at": "2026-04-18T10:22:13Z",
  "updated_by": "knowledge"
}
```

This file is intentionally small. It exists so specialists can honor persistent user preferences without loading them into triage.

### 3.3 `memory/functions/<name>.py`

Each file exposes exactly one `run(**kwargs) -> dict`. Invoked via subprocess (§5.5). Sample (generic):

```python
"""<one-line description>."""

import pandas as pd

def run(path: str) -> dict:
    df = pd.read_csv(path)
    # ... user-taught computation ...
    return {...}
```

### 3.4 `memory/notes/*.md` (schema)

Agent-authored distilled knowledge. Frontmatter captures provenance + source files:

```markdown
---
created_by: knowledge
created_at: 2026-04-18T10:22:13Z
source_files: [data/<user doc>.pdf]
topic: <short-slug>
---

# <Topic title>

<agent-distilled summary>
```

Consumed by the analyst via `read_text("memory/notes/<name>.md")` or listed via `list_knowledge`.

### 3.4a `memory/notes/index.json` (schema)

Search-guidance index. Lets `list_knowledge` manifest inclusion stay cheap: one JSON read, no per-file frontmatter parse.

```json
{
  "schema_version": 1,
  "entries": [
    {
      "path": "memory/notes/<topic>.md",
      "topic": "<short-slug>",
      "title": "<one-line>",
      "summary": "<= 200 chars — 2-sentence digest of the note body>",
      "keywords": ["<kw1>", "<kw2>", "…"],
      "source_files": ["data/<file>.csv"],
      "created_at": "2026-04-18T10:22:13Z",
      "last_updated_at": "2026-04-18T10:22:13Z"
    }
  ]
}
```

**Size discipline** (keeps manifest small regardless of note count):

| Field | Cap |
|---|---|
| `topic` | 64 chars |
| `title` | 120 chars |
| `summary` | 200 chars |
| `keywords` | max 10 entries, each ≤ 32 chars |

Rough budget: 50 notes × ~300 bytes ≈ 15 KB. Safe for per-turn manifest injection.

**Write discipline:**

- `write_knowledge_note` atomically updates both the `.md` file and `index.json` in a single write pair (`.tmp` + rename per file). On partial failure (one written, one not), next `list_knowledge` call detects the drift and stamps `drift_detected` for doctor.
- `rebuild_index("notes")` regenerates `index.json` from `.md` frontmatter if the index is missing, truncated, or fails schema validation.

**Read discipline:**

- Analyst uses `keywords` + `summary` in the manifest to decide *whether* to `read_text` a note body. Full note bodies never ride in the manifest.
- Doctor uses the index to detect duplicates (overlapping keywords + source_files), short notes to consolidate, and orphans (entries pointing at non-existent `.md` files).

### 3.5 `memory/notes/gaps/*.md` (schema)

Written by the analyst when it hits a knowledge gap mid-turn (spec 10 §7). Consumed by the knowledge agent on its next turn to prompt the user. Symmetric handoff, file-based, no in-memory queue.

## 4. Agent consumers (split out)

Agent bodies no longer live in this spec. Cross-refs:

- **Knowledge agent** (entry points, behavior, skip + resume, prompt, telemetry, tests) → **spec 11**.
- **Doctor agent** (entry points, scan-first + never-assume rules, resolution matrix, collaboration, guardrails, prompt, telemetry, tests) → **spec 12**.

This spec defines the **store** they write to and the **tool contracts** they call. Everything below is agent-agnostic.

## 5. Tools (spec 3 delta)

All follow the envelope from spec 3 §3. Live in `src/core/tools/knowledge.py` + `src/core/tools/documents.py` (extraction isolated for clarity).

Workspace scoping (path roots) is enforced via an **active-workspace context var** set by the Pipeline at turn start (see spec 00 §11 Workspace contract). Tools resolve relative paths against that root; no tool hardcodes `<workspace>` or imports `WorkspaceManager`. This is why none of the tool names include the word "workspace" — scoping is a framework concern, not a naming concern.

**Lazy stale-digest detection.** Read-path tools (`inspect_file_schema`, `preview_file`, `column_stats`, `read_text` on `data/`, `extract_document_text`) compute `file_digest` of the opened file once per turn per path (cached in a context var). If the digest differs from `memory/files/<path>.json` `source_digest`, the tool stamps `intake_status="stale"` atomically on the metadata file and emits a telemetry event `knowledge.stale_detected`. The original tool call still returns its result; no retry or user interruption. Next Pipeline pre-triage pass emits `drift_detected`. Cheap (digest only on first touch); self-healing (resolved by doctor on the next triaged drift turn).

### 5.1 `get_file_metadata(path: str) -> str`

Reads `memory/files/<path>.json`. Returns `{status: "missing"}` if absent (not an error).

### 5.2 `set_file_metadata(path: str, metadata: dict) -> str`

Merges `metadata` into the existing JSON (or creates it). Schema-validated against §3.1. Atomic write. `last_onboarded_at` stamped automatically.

### 5.2a `get_user_preferences() -> str`

Reads `memory/preferences.json`. Returns `{status: "missing"}` if absent. This tool is for specialist-local adaptation only; triage never receives these preferences as injected context.

### 5.2b `update_user_preferences(preferences: dict) -> str`

Merges into `memory/preferences.json` atomically. Only explicit user-stated preferences are persisted in migration scope. Knowledge agent is the owner; other agents route preference writes through `call_knowledge`.

### 5.3 `list_saved_functions() -> str`

Returns parsed `memory/functions/index.json`. Called by analyst directly when the question suggests reusable computation.

### 5.4 `save_python_function(name, code, signature, docstring, overwrite=False) -> str`

Writes `memory/functions/<name>.py`, updates `index.json` atomically. Validates:
- `name` matches `^[a-z][a-z0-9_]{0,62}$`.
- `code` defines a top-level `run(...)` matching `signature`.
- No existing entry with same `name` unless `overwrite=True`.
- `code` parses under `ast.parse` (rejects malformed files; does not execute).

`created_by` in the index is populated from the calling agent's name (via context var set by the Pipeline). Both `knowledge` and `data_analyst` can call. Callers should populate `source_files`, `source_digests`, and `schema_fingerprint` from the data actually used to produce the function so later runs can be validated cheaply.

### 5.5 `run_saved_function(name, args) -> str`

Subprocess execution inside the sandbox:

```
python /workspace/memory/functions/<name>.py <json-encoded args>
```

Wrapper reads JSON args from argv, calls `run(**args)`, prints JSON result to stdout. Timeout: 60 s. Stderr captured on non-zero exit. `last_used_at` updated in `index.json`.

Before subprocess execution, the tool performs a **freshness preflight**:

- every `source_file` still exists
- every `source_digest` still matches, or the function is marked stale
- current schema fingerprint still matches, or the function is marked `schema_mismatch`

If preflight fails, the tool returns `status="error"`, `reason="stale_saved_function"` or `reason="schema_mismatch"` and updates `validation_status` in `index.json`. It does **not** execute the saved function blindly. Analyst falls back to deterministic tools or shell analysis in the same turn; doctor handles cleanup or rewrite later.

### 5.6 `read_text(path: str, max_bytes: int = 64_000) -> str`

Reads a `.md`, `.txt`, or `.json` file from anywhere in the workspace (data or memory). Hard byte cap (truncation flagged in envelope). Binary / unknown extensions return `status="error"` with `reason="unsupported_file_type"` — callers route to `extract_document_text` instead.

### 5.7 `extract_document_text(path, max_pages=50, page_range=None) -> str`

Plain-text extraction for `.docx` and `.pdf` via **Gemma multimodal** — the in-process GGUF model already loaded for turn inference is prompted with the document bytes (or page images) and produces text output. No separate extraction library; no extra dependencies.

Contract:

```json
{
  "status": "ok",
  "data": {
    "pages": [{"page": 1, "text": "..."}],
    "total_pages": 12,
    "extraction_engine": "gemma-multimodal",
    "truncated": false,
    "phase": {"returned": [1, 10], "remaining": [11, 12]}
  }
}
```

**Phased reading.** Long documents exceed Gemma's context. The tool splits extraction into page-range phases. Each call returns one phase (default 10 pages) plus a `phase.remaining` hint so the caller can loop. The `page_range` argument lets the agent target a specific range when a later phase is needed. Default `max_pages=50` bounds total extraction per conversation.

The exact chunk size, phase-loop protocol, and Gemma prompting template are **TBD — pinned during the spec 9 probe task** (see §12 probe fixtures `onboard-pdf-short` and `onboard-pdf-long`). The tool contract above stays stable regardless of the chosen chunking strategy.

### 5.8 `write_knowledge_note(name, content, source_files=[], topic=None, summary=None, keywords=[], overwrite=False) -> str`

Writes markdown with frontmatter (§3.4) to `memory/notes/<name>.md` **and** appends/updates the matching entry in `memory/notes/index.json` (§3.4a) — both writes atomic as a pair (both rename-from-`.tmp` after both succeed; partial failures roll back and the call returns `status="error"`). `name` sanitized to `^[a-z0-9_-]+$`. Overwrite-protection on by default — callers pass `overwrite=True` to replace.

`summary` (≤ 200 chars) and `keywords` (≤ 10, each ≤ 32 chars) are required for the index entry. Callers that pass `None`/`[]` get a `status="error"`, `reason="missing_index_fields"` — the knowledge agent's prompt must always supply them. Doctor-authored consolidation uses the same contract via `call_knowledge` delegation.

Gap notes (`name` starting with `gaps/`) are exempt from the index write — gaps live outside the search index.

### 5.9 `search(query, path_glob="**/*", regex=False, max_matches=50) -> str`

Literal (default) or regex search across `data/` + `memory/`. Returns list of `{path, line, snippet}`. Grep-like. Used by knowledge to check for prior notes and by analyst to find reference material.

### 5.10 `file_digest(path) -> str`

Returns sha256 + size + mtime. Used by knowledge to detect re-uploaded files (`source_digest` drift → re-trigger intake prompt).

### 5.11 `list_knowledge(verbosity: Literal["manifest", "detail"] = "manifest") -> str`

One-call aggregate used by doctor and by agents for explicit orientation. Two modes. It is **not** part of the triage hot path in migration scope; triage uses dedicated tiny routing helpers instead.

**Manifest (default)** — names + one-liners only. Cheap. Safe for per-turn injection regardless of workspace size. Sourced from `memory/notes/index.json` + `memory/functions/index.json` + `memory/files/*.json` headers — no per-file body parsing.

```json
{
  "data_files": ["data/<file>.csv", "data/<file>.xlsx"],
  "knowledge_files": [
    {
      "path": "memory/files/<file>.csv.json",
      "summary": "<one-line summary>",
      "intake_status": "complete"     // complete | minimal | stale | orphan
    }
  ],
  "saved_functions": [
    {"name": "<fn>", "docstring": "<one-line description>"}
  ],
  "notes": [
    {
      "path": "memory/notes/<topic>.md",
      "topic": "<topic>",
      "summary": "<= 200 chars — from notes/index.json>",
      "keywords": ["<kw1>", "<kw2>"]
    }
  ],
  "gaps":  [{"path": "memory/notes/gaps/<topic>.md", "topic": "<topic>"}],
  "drift": {
    "stale":   ["data/<file>.csv"],
    "minimal": ["data/<other>.xlsx"],
    "orphan_metadata":  ["memory/files/<missing>.json"],
    "orphan_notes":     [],
    "orphan_functions": [],
    "index_missing":    []            // "functions" | "notes" if index absent/corrupt
  }
}
```

Notes `summary` + `keywords` ride along from `notes/index.json` — agents can decide relevance without a second tool call. `drift` block surfaces the full picture for doctor + Pipeline pre-triage (spec 5 §4 reads this).

No `columns` array, no function `signature`, no note bodies. Agents that need more call the lookup tools:

| Need | Tool |
|---|---|
| Columns / metrics / units for a tabular file | `get_file_metadata(path)` |
| Source of a saved function (for reuse or adaptation) | `read_text("memory/functions/<name>.py")` |
| Body of a knowledge note | `read_text("memory/notes/<topic>.md")` |
| Body of a gap note | `read_text("memory/notes/gaps/<topic>.md")` |

**Detail** — opt-in via `verbosity="detail"`. Returns the richer pre-redesign shape: `knowledge_files[].columns`, `saved_functions[].signature`, `saved_functions[].docstring` (full), `notes[].summary_first_line`. Rarely needed; typical use is a one-off structured dump when the user explicitly asks "what do you know?".

**Budget cap.** Both modes cap total output chars at `get_obs_max_chars()` (spec 3 §3). On truncation, the envelope includes a `"truncated"` sub-object reporting dropped-chars per list so the caller knows the lists are incomplete:

```json
{
  "status": "ok",
  "tool": "list_knowledge",
  "schema_version": 1,
  "data": { ... },
  "truncated": {"data_files": 0, "knowledge_files": 12400, "saved_functions": 0, "notes": 3200, "gaps": 0}
}
```

Truncation order: oldest entries (by `last_onboarded_at` / `created_at`) drop first within each list. Manifest mode is aggressive enough that truncation should be rare; detail mode truncates much sooner.

Detail form is opt-in inside a turn. Migration scope prefers lazy retrieval over automatic manifest injection.

Cheap — parses JSONs and note frontmatter without loading note bodies.

### 5.12 `call_knowledge(task: str, context: str) -> str`

Option D sub-run entry (spec 3 §5.1, spec 10 §4, spec 11 §4.4, spec 12 §6). Analyst *or doctor* invokes to delegate a semantic write — column meaning / formula capture / business-rule note / intake resume / merged-note body — without a triage handoff. Body (sketch):

```python
@function_tool
async def call_knowledge(task: str, context: str) -> str:
    run_config = _parent_run_config_ctx.get()   # Pipeline-set context var
    on_event  = _parent_on_event_ctx.get()      # streaming consumer
    child_session = _ephemeral_session(parent_turn_id())
    result = await Runner.run_streamed(
        knowledge_agent,
        input=f"TASK: {task}\n\nCONTEXT:\n{context}",
        session=child_session,
        run_config=run_config,
        on_event=on_event,       # proxy child events to parent's consumer
    )
    return result.final_text    # short confirmation from knowledge agent
```

Contract:

- `task` — imperative, one sentence: e.g. `"capture formula for metric X"`.
- `context` — raw material: user quote, file path + column scope, or analysis excerpt.
- Return value — short confirmation, inlined as the analyst's tool output. Analyst then continues its turn with updated `memory/`.

Guardrails:

- Child run inherits the parent's `run_config` (same sandbox client + manifest), so writes land in the same `memory/` volume.
- Child cannot invoke `call_knowledge` itself (prevent recursion); enforced by a `sub_run_depth` context var — incremented on entry, checked on invocation, max depth = 1. Applies regardless of caller (analyst or doctor).
- Caller allow-list: `data_analyst` + `doctor`. Other agents (conversational, clarification, triage, knowledge itself) get `status="error"`, `reason="not_authorized"`.
- Child budget: `max_turns=3` (spec 6 §8 default 8 is too loose for a focused capture). Configurable; pinned by spec 9 probe.
- If the nested-sub-run probe (spec 1 §10) fails: this tool is dropped from analyst's AND doctor's tool sets (Option A fallback — triage handoff on the next turn for analyst; doctor either limits scope to structural-only ops or itself runs as a multi-turn conversation that hands back to knowledge between steps).

Telemetry: child span nests under parent turn's `turn_id`/`run_id`; attribute `agent.invocation="sub_run"` distinguishes from triage-handoff invocations.

### 5.13 `delete_saved_function(name: str) -> str`

Doctor-exclusive. Removes `memory/functions/<name>.py` and the matching entry from `functions/index.json` atomically. If the function is referenced in `write_knowledge_note.source_files` for any note, the note's index entry is left untouched (doctor handles orphan notes separately). Returns `status="error"`, `reason="not_authorized"` if the caller context var is not `doctor`.

### 5.14 `delete_knowledge_note(path: str) -> str`

Doctor-exclusive. Removes `memory/notes/<topic>.md` and the matching entry from `notes/index.json` atomically. Also removes cross-references from `memory/files/*.json` `notes_refs` arrays (one pass). Caller-authorization same as §5.13.

### 5.15 `delete_file_metadata(path: str) -> str`

Doctor-exclusive. Removes `memory/files/<path>.json`. Does not touch the underlying `data/<path>` file (doctor never writes to `data/`). Caller-authorization same as §5.13.

### 5.16 `rebuild_index(kind: Literal["functions", "notes"]) -> str`

Doctor-exclusive. Regenerates the named index from the filesystem:

- `kind="functions"` — walks `memory/functions/*.py`, parses each via `ast.parse` to extract signature + docstring, emits a fresh `functions/index.json`. Creation/use timestamps reset to `last_checked_at = now()`; original `created_at` recovered from file `st_birthtime` (or falls back to `st_mtime`).
- `kind="notes"` — walks `memory/notes/*.md` (excluding `gaps/`), reads frontmatter (`topic`, `source_files`, `created_at`, `last_updated_at`), derives `title` from the first `#` heading, derives `summary` from the first non-heading paragraph truncated to 200 chars, derives `keywords` via a naive token-frequency pass (top 5 stopword-filtered noun-like tokens) — **OR** the doctor may first `call_knowledge(task="regenerate keywords/summary for <topic>", ...)` for a semantic pass. Default is the naive pass; doctor upgrades to the semantic pass on user request.

Atomic write (`.tmp` → rename). Returns a summary: how many entries were restored, how many skipped (unparseable files), and the path of any quarantined content.

Caller-authorization same as §5.13.

### Renamed from earlier drafts (spec 3)

| Old | New | Reason |
|---|---|---|
| `list_workspace_files` | `list_files` | scoping is framework-level, not a naming concern |
| `preview_workspace_file` | `preview_file` | same |
| `read_workspace_text` | `read_text` | same |
| `search_workspace` | `search` | same |
| `list_workspace_knowledge` | `list_knowledge` | same |
| `describe_workspace_file` | `inspect_file_schema` | semantic vs structural contrast |

### Removed from spec 3

- `format_table`, `format_key_value_list` — agents emit markdown directly.

## 6. Triage integration (cross-ref)

Four handoff signals computed from the store feed triage (spec 5 §4): `new_files`, `definitional_content`, `gaps_open`, `drift_detected`. Signal computation lives in `src/core/knowledge_store.py` (helper functions `list_new_files`, `list_gaps`, `summarize_drift`). Signal → handoff routing rules live in spec 5. Knowledge-agent scan-check on `gaps/` lives in spec 11 §4.3. Doctor triggers live in spec 12 §4.

## 7. Data analyst integration (spec 10)

Analyst-specific internals live in spec 10. This spec defines only the contract.

### 7.1 Ownership split (Option D)

| Write | Owner | How |
|---|---|---|
| `memory/functions/*.py` + `functions/index.json` (new entries + updates) | analyst (primary) + knowledge (intake + teach paths) | both call `save_python_function` directly. Code is an analysis artifact; analyst knows it works because it just ran it. |
| `memory/functions/*.py` + `functions/index.json` (deletions + index rebuild) | **doctor only** | `delete_saved_function`, `rebuild_index("functions")`. |
| `memory/files/*.json` (semantic fields: columns, metrics, meanings) | knowledge only | analyst or doctor delegates via `call_knowledge` (§5.12). |
| `memory/files/*.json` (structural stamps: `source_digest`, `intake_status="stale"`, `last_checked_at`) | tool read-paths (automatic) + doctor | lazy stale check writes automatically; doctor restamps on resolution. |
| `memory/files/*.json` (deletion) | **doctor only** | `delete_file_metadata` after user confirmation. |
| `memory/preferences.json` | knowledge only | explicit user-stated preferences are written directly by knowledge or via `call_knowledge` from another agent. |
| `memory/notes/*.md` + `notes/index.json` (new + updates) | knowledge only | analyst or doctor delegates via `call_knowledge`. Topic naming, source tracking, distillation belong in the knowledge agent's prompt. |
| `memory/notes/*.md` + `notes/index.json` (deletions + index rebuild) | **doctor only** | `delete_knowledge_note`, `rebuild_index("notes")`. |
| `memory/notes/gaps/*.md` (write) | analyst only | analyst signals deferred gaps inline via `write_knowledge_note` targeting `gaps/` (one-line append, no curation, no index entry). |
| `memory/notes/gaps/*.md` (delete on resolve) | knowledge only | part of gap-resolution turn. |

### 7.2 Contract

- Analyst uses lazy retrieval in migration scope. No Pipeline-injected manifest is required for the hot path; analyst pulls `get_file_metadata`, `list_saved_functions`, `get_user_preferences`, `read_text`, and `list_knowledge` only when needed (spec 10 §3).
- Analyst's tool set (spec 4 §3) excludes `set_file_metadata` and `write_knowledge_note`. Semantic writes route exclusively through `call_knowledge(task, context)` — knowledge agent is the sole owner of semantic curation.
- Analyst owns `save_python_function` directly — code persistence is an analysis output, not curation.
- Analyst writes `memory/notes/gaps/<topic>.md` only when a prerequisite cannot be resolved this turn (user absent / no data source / out-of-scope). If the prerequisite *can* be captured now (user just said it, or it's sitting in a file the analyst can read), the analyst uses `call_knowledge` instead — keeps the turn useful.

### 7.3 Why Option D (not full strict owner)

Pure strict-owner would force every semantic write through a triage handoff: user asks question → analyst detects missing column meaning → handoff to knowledge → knowledge asks → user answers → handoff back → analyst re-routes question from scratch. Multi-turn ceremony for a one-sentence clarification. Option D keeps the UX single-turn by making knowledge callable as a tool. The *owner* of semantic writes stays knowledge (prompts, instructions, test surface all live in knowledge agent); the *invocation mechanism* gains a second path (sub-run, not just handoff). Telemetry distinguishes the two via `agent.invocation="handoff"` vs `"sub_run"`.

## 8. UI integration (spec 7 delta)

### 8.1 Filedrop trigger

`src/cli/filedrop.py` is owned by the workspace contract (spec 00 §11). For this spec's purposes:
- All drops target `<workspace>/data/`.
- After copy, a synthetic user input fires: `I just added <filename>.<ext>`.
- Guard: if a turn is in flight, queue the prompt and fire on completion.

### 8.2 Status bar

Knowledge handoffs produce `StatusUpdate(text="Capturing knowledge…", level="handoff", agent="knowledge")` — already covered by spec 6 §3.1. No new surface area here.

## 9. Sandbox mount (spec 8 delta)

Two-volume mount at the same mount point `/workspace`:

| Host path | Container path | Mode |
|---|---|---|
| `<workspace>/data/` | `/workspace/data` | RO |
| `<workspace>/memory/` | `/workspace/memory` | RW |

No path-allow-list regex needed — the sandbox backend enforces per-volume mode. If `UnixLocalSandboxClient` does not support per-volume modes, fall back to the path-guard wrapper from the prior draft. Probe pinned in spec 8 §5.

## 10. Dependencies

No new dependencies. Document extraction uses the already-loaded Gemma GGUF model (see §5.7). Earlier draft's `python-docx` + `pypdf` are **not** added — dropped from the plan.

## 11. Telemetry (store + tools)

Agent-level spans (`agent.knowledge`, `agent.doctor`) live in specs 11 + 12 respectively. This spec covers tool + store spans consumed by both.

- Tool spans per §5 tools: `tool.name`, standard envelope attributes.
- `tool.extract_document_text`: `engine="gemma-multimodal"`, `pages_extracted`, `phase_returned`, `phase_remaining`, `truncated`.
- `tool.run_saved_function` adds `name`, `preflight_status` (`ok` | `stale_saved_function` | `schema_mismatch` | `missing_dependency`), `preflight_reason`, `wall_time_ms`, `exit_code`, `output_bytes`. When preflight fails, execution fields remain null/zeroed as appropriate and the refusal is still logged as a completed tool span.
- `tool.delete_saved_function` / `tool.delete_knowledge_note` / `tool.delete_file_metadata` / `tool.rebuild_index`: `caller` (agent name from context var), `authorized` (bool), `target_path`, `atomic_success` (bool). On unauthorized caller: span status = error, `reason="not_authorized"`.
- `tool.call_knowledge`: `caller` (`data_analyst` | `doctor`), `sub_run_depth_at_entry`, `child_turn_id`, `child_run_id`, `child_final_chars`, `child_tool_count`, `wall_time_ms`.
- `knowledge.stale_detected` event (emitted by lazy stale-digest check inside read-path tools): `path`, `old_digest`, `new_digest`, `tool` (which read tool triggered the stamp).
- Pipeline per-turn: `knowledge.files_known`, `knowledge.saved_functions_known`, `knowledge.notes_known`, `knowledge.gaps_open`, `knowledge.new_files_detected`, `knowledge.drift_count` (sum across drift categories from `list_knowledge` manifest).

## 12. Testing (store + tools)

Agent-level integration fixtures live in specs 11 (knowledge) and 12 (doctor). This spec covers store + tool tests.

**Unit:**

- JSON schema validation for `set_file_metadata`.
- `save_python_function` rejects invalid names, malformed python, silent clobbers.
- `run_saved_function` honors 60 s timeout; captures stderr on non-zero.
- `get_user_preferences` returns `{}` on an empty workspace and the exact stored shape after writes.
- `update_user_preferences` merges explicit user-stated preferences deterministically; rejects non-dict payloads and unknown top-level types.
- `run_saved_function` preflight returns `stale_saved_function` / `schema_mismatch` without executing stale code; telemetry records the preflight outcome.
- `extract_document_text` (Gemma): `.docx` + `.pdf` fixtures extract to plausible text; unsupported extension returns envelope error; encrypted PDF returns `reason="pdf_encrypted"`; phase-loop protocol returns correct `phase.remaining` on a long fixture.
- `read_text`: `max_bytes` truncation; rejects binary extensions.
- `write_knowledge_note`: overwrite protection; frontmatter round-trips; path sanitization; dual atomic write of `.md` + `notes/index.json`; `missing_index_fields` error on absent `summary`/`keywords`.
- `search`: literal + regex modes; respects `max_matches`; excludes `memory/session.db` automatically.
- `file_digest`: stable across reads; changes on content change.
- `list_knowledge(verbosity="manifest")`: returns all lists; no `columns`, no `signature`, no note bodies; includes `drift` block; survives empty workspace. `verbosity="detail"` returns the richer shape. Oversized workspace (10k+ notes / files) truncates oldest first and reports `truncated` per list.
- `call_knowledge(task, context)`: nested sub-run completes; returns a confirmation string; writes land in `memory/` under the parent turn's run config; child span nests under parent `turn_id`. Recursion guard: child calling `call_knowledge` → `status="error"`, `reason="recursive_sub_run"`. Caller allow-list: any caller other than `data_analyst` / `doctor` → `reason="not_authorized"`.
- Caller-auth matrix on destructive tools (`delete_saved_function`, `delete_knowledge_note`, `delete_file_metadata`, `rebuild_index`): conversational / analyst / clarification / knowledge callers → `reason="not_authorized"`; doctor caller → success.
- Lazy stale-digest stamp: editing the underlying file → next read-path tool stamps `intake_status="stale"` atomically; emits `knowledge.stale_detected` event; tool output still returned.
- `rebuild_index`: regenerates from filesystem; skips unparseable files; reports counts.
- Mount guard (or path-guard fallback): writes to `/workspace/data` denied; writes to `/workspace/memory` permitted.

**Integration fixtures:** listed in their owning agent specs (spec 11 §9 for knowledge fixtures, spec 12 §10 for doctor fixtures).

Latency budgets live in `tests/integration/budgets.json`.

## 13. Files

**New:**
- `src/core/tools/knowledge.py` — `get_file_metadata`, `set_file_metadata`, `list_saved_functions`, `save_python_function`, `run_saved_function`, `write_knowledge_note`, `list_knowledge`, `call_knowledge`, `search`, `file_digest`, `delete_saved_function`, `delete_knowledge_note`, `delete_file_metadata`, `rebuild_index`.
- `src/core/tools/documents.py` — `read_text`, `extract_document_text` (Gemma multimodal backend).
- `src/core/knowledge_store.py` — filesystem layer (path computation, atomic writes, schema validation, frontmatter parse, notes-index read/write, lazy stale-digest stamp, pre-triage helpers `list_new_files` / `list_gaps` / `summarize_drift`). Shared by tools and the knowledge / analyst / doctor agents.
- `tests/core/test_knowledge_store.py` — atomic write pairs (`.md` + `index.json`), notes-index schema validation, lazy stale-digest stamp, `intake_status` transitions, pre-triage helper outputs.
- `tests/core/tools/test_knowledge.py` — tool unit tests + caller-auth matrix for the four doctor-exclusive tools + recursion guard on `call_knowledge`.
- `tests/core/tools/test_documents.py`

**Agent files (owned by downstream specs):**
- Knowledge agent files — spec 11 §10.
- Doctor agent files — spec 12 §11.

**Modified:**
- `src/core/pipeline.py` — injects only tiny triage signals at turn start (spec 6); also calls `list_new_files` / `list_gaps` / `summarize_drift` for pre-triage signals (spec 5).
- `hragent.spec` (spec 8) — include `src/core/tools/knowledge.py` + `src/core/tools/documents.py`; **do not** add `docx` or `pypdf` hiddenimports (Gemma backend, no extra libs).

**Workspace-contract refs (spec 00 §11):**
- `src/core/workspace.py`, `src/cli/filedrop.py` are owned by the workspace contract, not this spec. This spec depends on the contract but does not modify those files.

**Renamed in spec 3:** see §5 rename table.

**Dropped from spec 3:** `format_table`, `format_key_value_list`.

**Retired:** none.

## 14. Acceptance (store + tools)

- Store layout created on first agent write; subsequent writes atomic (`.tmp` → rename).
- All §3 schemas validate round-trip; `intake_status` transitions (complete / minimal / stale / orphan) observable on disk.
- `write_knowledge_note` dual-writes `.md` + `notes/index.json` atomically; partial-failure rollback preserves consistent state.
- `.docx` and `.pdf` extraction via Gemma produces usable plain text on short and long fixture files; long-doc phase loop returns multi-phase results.
- Saved functions persist across session wipe (delete `memory/session.db`, reopen — functions still listed and runnable).
- Mount enforces `data/` RO + `memory/` RW; write-guard fixture confirms denial of user-data mutation.
- Caller-auth rejects non-doctor callers on all four destructive tools; `call_knowledge` caller allow-list rejects callers outside `data_analyst` / `doctor`.
- Recursion guard on `call_knowledge` blocks nested invocation.
- Lazy stale-digest stamp fires on any read-path tool when `source_digest` drifts; stamps atomically; emits `knowledge.stale_detected` event.
- Pre-triage helpers (`list_new_files`, `list_gaps`, `summarize_drift`) return structured outputs consumed by spec 5 §4.
- Integration suite green; latencies within budgets.
- `git log <workspace>/memory/` shows a human-readable diff of every agent action — user-facing audit trail.

Agent-level acceptance lives in specs 11 §11 (knowledge) and 12 §12 (doctor).
