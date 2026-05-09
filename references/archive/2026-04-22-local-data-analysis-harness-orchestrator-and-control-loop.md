# Local Data Analysis Harness: Orchestrator And Control Loop

Date: 2026-04-22
Status: Drafted from approved design discussion
Parent: `2026-04-22-local-data-analysis-harness-overview.md`

## 1. Purpose

This spec defines how the orchestrator turns a user request into a visible, structured, and validated analysis workflow.

The orchestrator owns:

- fresh context loading
- structured planning
- schema validation
- worker dispatch
- result inspection
- deterministic fix and reask behavior
- replan and finish decisions
- durable state updates

The orchestrator is the only authority for control-flow decisions and the only writer for durable state beyond raw worker artifacts.

## 2. Core Loop

Each request follows a strict orchestrated loop.

### 2.1 Fresh Context Load

Before planning, the orchestrator reloads:

- user preference memory
- dataset knowledge
- active session ledger
- dataset fingerprints
- relevant prior analyses
- unresolved doctor findings

Durable memory is re-injected fresh each turn. The system must not depend on chat history alone for critical constraints or prior facts.

### 2.2 Structured Planning

The model emits a schema-bound `plan.json` with:

- atomic steps
- required inputs
- expected artifacts
- step success criteria
- explicit decision points that may require user clarification

The orchestrator validates the plan before execution. The user sees the plan in the TUI and can approve, revise, clarify, or stop.

### 2.3 Step Contract Generation

For the active step, the model produces:

- Python code to execute
- an execution contract
- an expected schema for `step_result.json`
- a report contract for `step_report.md`

The code contract and result contract must be stable enough that the orchestrator can judge success without trusting freeform model narrative.

### 2.4 Worker Dispatch

The orchestrator sends the active step to the worker with:

- code
- declared inputs
- output contract
- session workspace paths
- package and permission envelope

### 2.5 Post-Execution Inspection

The orchestrator reads the emitted `step_result.json`, `step_report.md`, and registered artifacts. The primary evidence remains on disk, not in the model transcript.

### 2.6 Replan Or Finish

After a valid step, the orchestrator:

- continues the plan
- revises the remaining plan
- asks the user for clarification
- finishes with an artifact-grounded answer

## 3. Guardrails Evaluation Pipeline

The harness should adopt the most relevant parts of the Guardrails reask model, adapted for code-driven local analysis.

After execution, the orchestrator performs:

1. `Parse`
Confirm `step_result.json` is parseable.

2. `Validate`
Confirm the parsed result matches the expected schema.

3. `Introspect`
Identify exact failing structures or fields.

4. `Assess`
Classify the failure as one of:
- output-format failure
- deterministic repair candidate
- execution or code failure
- semantic mismatch between result and step intent

This is stricter than a generic inspect step. The system must know what failed and why before retrying.

## 4. Deterministic Fix Before Reask

The orchestrator should apply safe automatic corrections before making another model call when the issue is mechanical. Examples:

- type normalization
- allowed default values for optional fields
- path normalization
- boilerplate metadata insertion
- Markdown wrapper repair

This is the local-harness equivalent of Guardrails `FIX` and `FIX_REASK`.

If deterministic repair succeeds, the loop continues with no extra model call.

## 5. Targeted Retry Behavior

If deterministic repair is insufficient, the orchestrator chooses one retry type.

### 5.1 Non-Parseable Output

When `step_result.json` cannot be parsed, request corrected structured output using:

- the previous bad output
- the expected envelope
- parse failure details

### 5.2 Schema Mismatch

When the result parses but fails schema shape validation, reask with:

- the previous output
- exact validator errors
- a pruned schema where possible

### 5.3 Field Failure

When only a subset of fields fails validation, retry only those failing fields if the underlying computation remains trustworthy.

### 5.4 Execution Or Semantic Failure

When the computation itself failed, or the result is semantically wrong even if the JSON shape is correct, request Python repair and rerun the worker. Do not merely rewrite JSON.

## 6. Retry Budget

Each retriable object has an explicit retry budget. Example:

- 1 initial attempt
- up to 2 retries

If the budget is exhausted, the orchestrator surfaces a structured failure and preserves best-effort valid output for diagnosis.

The system must not hide repeated failure inside silent internal loops.

## 7. Hard Rules

- No claim is accepted unless grounded in files the orchestrator has read.
- Output repair and code repair are separate paths.
- Retry prompts always include the previous bad output and exact validator errors.
- Only failing fields or structures are retried where possible.
- The user is notified when the system is blocked or uncertain.

## 8. Structured Control Objects

The first version should schema-validate these control-plane objects:

- plan objects
- step contracts
- execution envelopes
- step result JSON
- doctor reports
- review proposals
- memory update proposals

Markdown remains important for human inspection, but JSON is the canonical control surface for orchestration.

## 9. Why This Design

This design keeps the useful strength of Guardrails without pretending the local harness is a pure structured-output wrapper. In this system, the truth often comes from Python runs on disk, so retries must distinguish:

- malformed structured output
- deterministic repair cases
- broken analysis code

That distinction is mandatory for reliable data work.
