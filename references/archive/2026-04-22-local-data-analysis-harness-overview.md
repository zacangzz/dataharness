# Local Data Analysis Harness: Overview

Date: 2026-04-22
Status: Superseded by `2026-04-23-custom-data-analysis-llm-v1-main-spec.md`
Replaces: `archive/2026-04-22-local-data-analysis-harness-design.md`
Archives: `archive/2026-04-21-llm-data-harness-design.md`, `archive/2026-04-21-llm-data-harness-design-sub1.md`, `archive/2026-04-21-llm-data-harness-design-sub2.md`, `archive/2026-04-22-llm-data-harness-design-sub3.md`

Canonical spec: `2026-04-23-custom-data-analysis-llm-v1-main-spec.md`

## 1. Purpose

This spec set defines a fully local LLM harness for data analysis work.

The product is a single-user terminal TUI application that uses Gemma 4 E4B IT GGUF through `llama.cpp` Python bindings. It is chat-first, but it is not a generic chatbot shell. It is a state-centric analysis system with visible planning, controlled Python execution, structured outputs, durable memory, provenance, and dataset-aware validity checks.

Core principle:

`conversation is the interface, state is the source of truth, code execution is the evidence`

## 2. Scope

### 2.1 In Scope

- single-user local desktop workflow only
- terminal TUI interface
- file-based analysis inputs only
- conversational interaction with visible plans
- user ability to stop, revise, or clarify plans before and during execution
- arbitrary Python analysis code within an allowed local package set
- structured result reading from worker-emitted JSON and Markdown files
- persistent learning about user preferences, dataset semantics, prior workflows, and data validity
- on-demand doctor and review functions

### 2.2 Out of Scope

- multi-user collaboration
- remote execution or cloud workers
- database connectors in the first version
- network-dependent data access in the first version
- autonomous self-modification of prompts, tools, or code
- autonomous background review loops

## 3. Design Goals

1. Produce trustworthy analysis grounded in executed Python and inspected artifacts.
2. Improve over time by learning user preferences and dataset knowledge.
3. Preserve provenance for plans, code, artifacts, and conclusions.
4. Detect when previous conclusions may no longer be valid because source data changed.
5. Keep the harness operationally simple for one local user.

## 4. Non-Negotiable Principles

### 4.1 Read Before Claim

The orchestrator must read schemas, file fingerprints, prior outputs, and generated result files before making or accepting analytical claims.

### 4.2 Tool-Centric Truth

The model does not do analysis in prose. It plans and writes Python. Truth comes from worker outputs and artifacts, not from unaudited model text.

### 4.3 Atomic Step Execution

User goals are decomposed into small, verifiable steps with explicit success criteria and expected outputs.

### 4.4 Durable State Over Chat History

Critical knowledge must live in durable state and memory stores that are reloaded each turn. Chat history alone is never authoritative.

### 4.5 Fixed Harness, Adaptive Memory

The base harness behavior is fixed. Long-term adaptation is limited to user memory, dataset knowledge, workflow patterns, and validity status.

## 5. System Map

The product has six core subsystems:

1. `TUI shell`
Chat-first interface with persistent operational visibility.

2. `Orchestrator`
Owns turn handling, planning, validation, worker dispatch, inspection, retry, replan, and durable state updates.

3. `Execution worker`
Runs Python analysis code inside a controlled local execution envelope and emits canonical outputs.

4. `State store`
Authoritative local record of sessions, plans, steps, artifacts, memories, fingerprints, and validity states.

5. `Memory system`
Separate stores for user preferences, dataset knowledge, and active session context.

6. `Doctor and review service`
On-demand workflows for stale-analysis detection and reviewable learning updates.

## 6. Active Spec Set

This overview is intentionally short. The current design is split into focused specs:

1. [Orchestrator And Control Loop](./2026-04-22-local-data-analysis-harness-orchestrator-and-control-loop.md)
Purpose: planning, schema validation, guardrails-style retries, and orchestration rules.

2. [Worker And Execution Runtime](./2026-04-22-local-data-analysis-harness-worker-and-execution.md)
Purpose: Python execution model, sandbox boundaries, artifact contracts, and runtime assumptions.

3. [State, Memory, And Doctor](./2026-04-22-local-data-analysis-harness-state-memory-and-doctor.md)
Purpose: session ledger, user memory, dataset knowledge, fingerprints, validity, doctor, and review.

4. [TUI And Verification](./2026-04-22-local-data-analysis-harness-tui-and-verification.md)
Purpose: user-facing operating model, required controls, failure visibility, and testing strategy.

## 7. Initial Implementation Boundary

The first implementation should target:

- one local model configuration
- one local worker runtime
- one session workspace root
- file inputs only
- explicit doctor and review commands
- no autonomous background improvement loops

This is a focused product, not a general-purpose agent platform.

## 8. Why This Structure

The previous draft specs and the first consolidated rewrite established the core direction, but they packed too many decisions into a single document. This split keeps:

- product intent and scope in one short overview
- orchestration logic separate from runtime mechanics
- state and doctoring separate from interaction design
- verification requirements visible without burying them inside architecture prose

This should make the spec set easier to review, implement, and update incrementally.
