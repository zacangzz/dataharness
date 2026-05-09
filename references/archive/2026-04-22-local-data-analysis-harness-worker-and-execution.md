# Local Data Analysis Harness: Worker And Execution Runtime

Date: 2026-04-22
Status: Drafted from approved design discussion
Parent: `2026-04-22-local-data-analysis-harness-overview.md`

## 1. Purpose

This spec defines the execution worker, its runtime contract, and the local sandbox boundaries for arbitrary Python analysis work.

The worker exists to compute, not to decide. It runs code, emits evidence, and reports execution details. The orchestrator remains the control-plane authority.

## 2. Runtime Assumptions

- model family: Gemma 4 E4B IT GGUF
- inference stack: `llama.cpp` Python bindings
- product mode: fully local, text-first TUI
- execution mode: arbitrary Python analysis code within a configured allowlist of packages

The design assumes the model is best used for planning and code generation, while numerical truth and derived results come from Python execution.

## 3. Worker Contract

Inputs:

- step code
- declared input files and artifacts
- allowed package set
- expected output schema
- session workspace paths
- run metadata such as step id and request id

Outputs:

- `step_result.json`
- `step_report.md`
- stdout capture
- stderr capture
- generated artifacts
- execution metadata

The worker must always produce a canonical execution envelope, even on failure.

## 4. Output Conventions

### 4.1 `step_result.json`

This is the canonical machine-readable output. It should contain:

- run status
- declared output fields
- artifact references
- summary metrics
- warnings
- error details when relevant

### 4.2 `step_report.md`

This is the human-readable step report. It may include:

- method summary
- notable observations
- caveats
- artifact descriptions

The orchestrator may read Markdown for operator-facing summaries, but it must not use Markdown as the only control-plane source of truth.

### 4.3 Artifacts

Allowed artifact types may include:

- `csv`
- `parquet`
- `json`
- `png`
- `svg`
- `md`

Artifact registration must include path, type, and producing step linkage.

## 5. Allowed Package Strategy

The first version should allow a curated local analysis stack such as:

- `pandas`
- `polars`
- `pyarrow`
- `numpy`
- `scikit-learn`
- `matplotlib`
- `seaborn`
- selected statistics and time-series packages

The package allowlist is static harness configuration, not agent-learned behavior.

## 6. Sandbox Boundaries

The worker supports arbitrary Python, but within a controlled local execution envelope.

### 6.1 Filesystem Rules

- readable inputs limited to user-approved source files and registered artifacts
- writable outputs limited to the active session workspace
- no arbitrary writes outside the workspace

### 6.2 Process And Network Rules

- no outbound network
- no subprocess by default
- no arbitrary shell escape path in the initial version

### 6.3 Resource Rules

- wall-time limits
- memory limits
- artifact-size limits
- explicit runtime metadata capture

The goal is not perfect isolation. The goal is controlled, inspectable, recoverable local execution for data analysis work.

## 7. Failure Semantics

The worker must distinguish:

- Python exceptions
- resource-limit termination
- missing output files
- malformed `step_result.json`
- partial artifact generation

All of these should be reported back through the execution envelope so the orchestrator can choose between deterministic repair, code repair, retry, or stop.

## 8. Provenance Requirements

Every execution attempt should record enough context to reproduce or inspect the run:

- code hash
- package versions
- runtime environment summary
- input file references
- produced artifact paths
- timestamps

This information belongs to the session ledger and artifact registry, even if the raw files live in the session workspace.

## 9. Separation Of Responsibility

The worker must never directly mutate:

- user memory
- dataset knowledge
- validity state
- doctor findings

The worker emits evidence only. The orchestrator decides what that evidence means.

## 10. Why This Design

This product needs the power of arbitrary Python without drifting into a generic unsafe code runner. The worker boundary is therefore pragmatic:

- broad enough for real analysis
- narrow enough for control and auditability
- simple enough for a single-user local system
