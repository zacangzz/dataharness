# Local Data Analysis Harness: Consolidated Design

Date: 2026-04-22
Status: Drafted from approved design discussion
Supersedes: `2026-04-21-llm-data-harness-design.md`, `2026-04-21-llm-data-harness-design-sub1.md`, `2026-04-21-llm-data-harness-design-sub2.md`, `2026-04-22-llm-data-harness-design-sub3.md`

## 1. Purpose

This document defines the target design for a fully local LLM harness focused on data analysis work.

The product is a single-user terminal TUI application that uses Gemma 4 E4B IT GGUF through `llama.cpp` Python bindings as its reasoning engine. The harness is chat-first, but it does not operate as a freeform chatbot. It is a state-centric analysis system with explicit planning, controlled Python execution, structured outputs, durable memory, artifact lineage, and dataset-aware validity checks.

The core principle is:

`conversation is the interface, state is the source of truth, code execution is the evidence`

## 2. Product Scope

### 2.1 In Scope

- Single-user local desktop workflow only
- Terminal TUI interface
- File-based analysis inputs only
- Conversational interaction with visible plans
- User ability to stop, revise, or clarify plans before and during execution
- Arbitrary Python analysis code within an allowed local package set
- Structured result reading from JSON and Markdown files emitted by worker code
- Persistent learning about user preferences, dataset semantics, prior workflows, and data validity
- On-demand doctor and review functions for stale-analysis detection and learning updates

### 2.2 Out of Scope

- Multi-user collaboration
- Remote execution or cloud workers
- Background autonomous self-modification of prompts, tools, or code
- Network-dependent data access in the first version
- Database connectors in the first version

## 3. Design Goals

1. Produce trustworthy data analysis grounded in executed Python and inspected artifacts.
2. Make the system useful over time by learning user preferences and dataset knowledge.
3. Preserve full provenance for plans, code, artifacts, and conclusions.
4. Detect when previous conclusions may no longer be valid because the underlying data changed.
5. Keep the harness operationally simple for a single local user.

## 4. Non-Negotiable Principles

### 4.1 Read Before Claim

The orchestrator must read schemas, file fingerprints, prior step outputs, and generated result files before making or accepting analytical claims.

### 4.2 Tool-Centric Truth

The model does not "do" analysis in prose. It plans and writes Python. The truth comes from worker outputs and artifacts, not from the model's unaudited text.

### 4.3 Atomic Step Execution

User goals are decomposed into small, verifiable steps with explicit success criteria and expected outputs.

### 4.4 Lossless State Before Lossy Compression

Critical durable knowledge lives in state and memory stores that are reloaded each turn. Chat history may be compressed later, but authoritative state may not depend on chat retention alone.

### 4.5 Fixed Harness, Adaptive Memory

The base harness behavior is fixed. Long-term adaptation is limited to user preferences, dataset knowledge, workflow patterns, and validity status.

## 5. System Architecture

The app consists of six core subsystems.

### 5.1 TUI Shell

The TUI is the user-facing control surface. It is chat-first, but always exposes the current plan, step state, artifacts, active memory, and doctor warnings. The user can approve, stop, revise, rerun, or inspect from the interface.

### 5.2 Orchestrator

The orchestrator owns:

- turn handling
- fresh context loading
- structured planning
- schema validation
- worker dispatch
- result inspection
- reask and replan logic
- memory and state updates
- doctor and review workflows

The orchestrator is the only writer for durable state beyond raw worker artifacts.

### 5.3 Execution Worker

The worker runs Python analysis code inside a controlled local execution envelope. It reads approved source files and registered artifacts, writes outputs into the active session workspace, and emits a canonical execution result contract.

The worker never writes directly to long-term memory, dataset knowledge, or validity state.

### 5.4 State Store

The state store is the authoritative local record of sessions, plans, steps, artifacts, memories, dataset fingerprints, and validity status. It is the system's persistent backbone.

### 5.5 Memory System

Memory is split into distinct stores for user preferences, dataset knowledge, and working session context. This keeps durable facts, reusable analysis knowledge, and temporary state separate.

### 5.6 Doctor And Review Service

Doctor and review are explicit callable workflows. They inspect state, datasets, and past analyses, then propose updates or reruns. They do not run silently in the background in the first version.

## 6. Model And Runtime Assumptions

- Model: Gemma 4 E4B IT GGUF
- Inference stack: `llama.cpp` Python bindings
- Deployment style: fully local
- Primary mode: text-only reasoning for TUI
- Reasoning style: structured planning followed by code generation and artifact inspection

The design assumes Gemma is strongest when allowed to plan explicitly, produce schema-bound control objects, and operate with separate temperatures or modes for reasoning versus final structured outputs.

## 7. Interaction Model

The harness is conversational, but not opaque. For each request, the system surfaces:

- the interpreted objective
- the current plan
- the active step
- the status of retries or replans
- the artifacts and reports produced so far
- any uncertainty, blockage, or doctor warning

The user must be able to:

- approve a plan
- edit or clarify a goal
- stop after the current step
- cancel a run
- rerun a step
- open an artifact
- run doctor
- review and accept or reject memory updates

## 8. Control Loop

Each request follows a strict orchestrated loop.

### 8.1 Fresh Context Load

Before planning, the orchestrator reloads:

- user preference memory
- dataset knowledge
- active session ledger
- dataset fingerprints
- relevant prior analyses
- unresolved doctor findings

This mirrors the useful Claude Code principle that durable memory is re-injected fresh each turn instead of being trusted only from chat history.

### 8.2 Structured Planning

The model emits a schema-bound `plan.json` containing:

- atomic steps
- required inputs
- expected artifacts
- step success criteria
- decision points that may require user clarification

The orchestrator validates the plan before execution. The TUI exposes the plan for user supervision.

### 8.3 Step Contract Generation

For the active step, the model produces:

- Python code to execute
- an execution contract
- an expected schema for `step_result.json`
- a report contract for `step_report.md`

### 8.4 Worker Execution

The worker runs the Python code and writes canonical outputs and artifacts into the session workspace. The primary evidence remains on disk.

### 8.5 Guardrails Evaluation

After execution, the orchestrator performs:

1. `Parse` - confirm `step_result.json` is parseable.
2. `Validate` - confirm the parsed result matches the expected schema.
3. `Introspect` - identify exact failing structures or fields.
4. `Assess` - classify the failure as output-format failure, deterministic repair candidate, or execution/code failure.

### 8.6 Deterministic Fix Before Reask

The orchestrator applies safe automatic corrections before making another model call when the issue is mechanical. Examples:

- type normalization
- allowed default values for optional fields
- path normalization
- boilerplate metadata insertion
- Markdown wrapper repair

This is the simplified equivalent of Guardrails `FIX` and `FIX_REASK`.

### 8.7 Targeted Retry Path

If deterministic repair is insufficient, the orchestrator chooses one retry mode:

- `Non-parseable output`: request corrected structured output
- `Schema mismatch`: reask with previous output, exact validator errors, and a pruned schema
- `Field failure`: retry only failing fields when the underlying computation is still valid
- `Execution failure or semantically wrong result`: request Python repair and rerun the worker rather than rewriting JSON only

Retry prompts must include the previous bad output and exact validator errors. Only failing fields or structures should be retried where possible.

### 8.8 Bounded Retry Budget

Every retriable object has an explicit retry budget. Example:

- 1 initial attempt
- up to 2 retries

If the budget is exhausted, the orchestrator surfaces a structured failure with best-effort valid output preserved for diagnosis.

### 8.9 Replan Or Finish

After each valid step:

- continue the plan
- revise the remaining plan
- ask the user for clarification
- finish with an artifact-grounded answer

### 8.10 Hard Rules

- No claim is accepted unless grounded in files the orchestrator has read.
- Output repair and code repair are separate paths.
- Repeated failure is surfaced to the user rather than hidden inside silent loops.

## 9. Execution Model And Sandbox

The worker supports arbitrary Python analysis code, but within a controlled local execution envelope designed for data work.

### 9.1 Worker Contract

Inputs:

- step code
- declared input files and artifacts
- allowed package set
- output schema
- session workspace paths

Outputs:

- `step_result.json`
- `step_report.md`
- stdout and stderr capture
- generated artifacts
- execution metadata

### 9.2 Allowed Package Strategy

The first version should allow a curated local analysis stack such as:

- `pandas`
- `polars`
- `pyarrow`
- `numpy`
- `scikit-learn`
- `matplotlib`
- `seaborn`
- selected statistics and time-series packages

The allowlist is part of the harness configuration, not learned dynamically by the agent.

### 9.3 Sandbox Boundaries

- readable inputs limited to user-approved source files and registered artifacts
- writable outputs limited to the active session workspace
- no outbound network
- no subprocess by default
- resource limits for wall time, memory, and artifact size
- explicit capture of package versions and runtime environment

The goal is not perfect isolation. The goal is controlled, inspectable, recoverable local execution.

## 10. State Model

The harness treats state as a first-class subsystem rather than relying on a chat transcript.

### 10.1 Session Ledger

The session ledger records:

- user requests
- approved plan versions
- step contracts
- code hashes
- execution attempts
- retry history
- reports
- artifacts
- final conclusions

### 10.2 User Memory

This store captures stable user preferences and working style, such as:

- preferred answer structure
- preferred level of detail
- naming conventions
- recurring business definitions
- trusted workflow habits

### 10.3 Dataset Knowledge

This store captures reusable knowledge tied to specific files or file families:

- schema summaries
- column semantics
- entity definitions
- common filters
- prior anomalies
- business glossary
- known quality issues
- reusable analysis patterns

### 10.4 Working Session Context

This layer holds temporary session state needed during an active run, such as:

- open goals
- current plan branch
- active assumptions
- unresolved step issues

### 10.5 Validity And Doctor Registry

This layer tracks whether past analyses remain trustworthy. Every conclusion links back to the exact dataset fingerprints, steps, and artifacts that produced it.

Statuses should include:

- `ok`
- `changed`
- `stale`
- `needs_review`
- `revalidated`
- `broken_lineage`

## 11. Dataset Fingerprinting And Change Detection

The system must fingerprint datasets so that learned knowledge and prior conclusions have an explicit validity basis.

### 11.1 File Fingerprint

- file path
- file size
- modified time
- content hash

### 11.2 Schema Fingerprint

- column names
- data types
- sheet or partition structure where relevant
- row-count or shard markers where practical

### 11.3 Profile Fingerprint

Optional but recommended lightweight summaries:

- sampled-content summaries
- simple statistical signatures
- null-rate and distinct-count sketches

These fingerprints let the system detect both obvious file changes and more meaningful semantic shifts.

## 12. Learning Model

Learning in this harness means updating:

- user memory
- dataset knowledge
- workflow patterns
- validity state

Learning does not mean changing the base harness architecture, toolset, or prompt contract automatically.

The system may propose new reusable knowledge after a session, but persistence should remain explicit and reviewable.

## 13. Doctor And Review Workflows

Hermes-style review behavior is kept as an explicit function rather than background autonomy.

### 13.1 Doctor

Doctor is an on-demand workflow that:

- rescans tracked source files
- recomputes fingerprints
- compares them with prior sessions
- detects schema drift, content drift, missing files, renamed files, and broken lineage
- identifies which prior plans, artifacts, and conclusions are affected
- emits a structured doctor report

The output should say what is:

- still valid
- stale
- broken
- safe to reuse
- recommended for rerun
- recommended for user review

### 13.2 Review

Review is a lighter-weight session-end or on-demand workflow that proposes:

- user preference updates
- dataset knowledge updates
- reusable workflow notes
- unresolved quality observations

Review proposes changes; the user accepts or rejects them.

## 14. TUI Design Requirements

The TUI should remain operationally clear rather than decorative. It should provide persistent visibility into what the system is doing and why.

Required surfaces:

- conversation pane
- current plan pane
- step execution status
- artifact and result browser
- active memory and dataset context summary
- doctor and validity warning area

Required commands or controls:

- approve plan
- revise goal
- stop after current step
- rerun step
- inspect artifact
- run doctor
- review learned updates
- mark result trusted
- invalidate prior conclusion

## 15. Structured Output Contracts

The first version should treat the following as schema-validated control-plane objects:

- plan objects
- step contracts
- execution envelopes
- step result JSON
- doctor reports
- review proposals
- memory update proposals

Markdown remains important for human inspection, but JSON is the canonical control surface for orchestration.

## 16. Provenance And Auditability

Every material conclusion should be traceable back to:

- the source files used
- their fingerprints at run time
- the plan and step that produced the result
- the code hash or execution record
- the emitted artifacts
- the validation status at the time of conclusion

No prior conclusion should be silently overwritten. If validity changes, the system records a new state transition.

## 17. Failure Handling

The design must treat failure as expected behavior, not as an exceptional afterthought.

The orchestrator should distinguish:

- parse failure
- schema failure
- field-level validation failure
- execution error
- semantic mismatch between result and step intent
- missing artifact
- stale upstream data

The user should be told which class occurred, what the system attempted, and what remains blocked.

## 18. Verification And Testing Strategy

Three verification layers are required.

### 18.1 Control-Plane Validation

Schema tests for:

- plan objects
- step contracts
- result envelopes
- doctor reports
- memory and review proposals

### 18.2 Execution Validation

Tests that verify worker behavior under:

- successful runs
- Python exceptions
- malformed JSON output
- missing report files
- artifact registration errors
- resource-limit failures

### 18.3 Product Validation

End-to-end scenarios such as:

1. analyze a CSV and produce an artifact-backed answer
2. reuse the same dataset and benefit from remembered dataset knowledge
3. change the source file and run doctor
4. mark earlier conclusions as stale and propose reruns

## 19. Initial Implementation Boundaries

To keep this spec implementable as one focused project, the first build should target:

- one local model configuration
- one local worker runtime
- file inputs only
- one session workspace root
- explicit doctor and review commands
- no autonomous background improvement loops

This is intentionally narrower than a general-purpose agent platform.

## 20. Why This Design

This design takes the strongest applicable principles from the reference materials and adapts them to the specific product:

- from the must-haves: atomic tasks, read-before-write, tool-centric execution, structured state
- from Guardrails: explicit parse, validate, introspect, deterministic-fix, and bounded reask behavior
- from Hermes memory/session design: durable memory separated from transient session state
- from Hermes self-improvement: useful review behavior, limited here to explicit user-invoked learning flows
- from Claude Code context management: authoritative durable context should be reloaded fresh each turn rather than trusted only from conversational history

The result is not a generic agent shell. It is a local, auditable, dataset-aware analysis harness optimized for practical data work.
