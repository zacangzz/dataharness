# Local Data Analysis Harness: TUI And Verification

Date: 2026-04-22
Status: Drafted from approved design discussion
Parent: `2026-04-22-local-data-analysis-harness-overview.md`

## 1. Purpose

This spec defines the operator-facing behavior of the TUI and the verification requirements that keep the harness trustworthy.

The product is conversational, but it must remain inspectable and interruptible at all times.

## 2. TUI Operating Model

The TUI should be chat-first with persistent operational visibility.

Required surfaces:

- conversation pane
- current plan pane
- step execution status
- artifact and result browser
- active memory and dataset context summary
- doctor and validity warning area

The user should never be forced to infer what the system is doing from a single scrolling transcript.

## 3. Required User Controls

The user must be able to:

- approve a plan
- revise or clarify a goal
- stop after the current step
- cancel a run
- rerun a step
- inspect an artifact
- run doctor
- review learned updates
- mark a result trusted
- invalidate a prior conclusion

These controls are part of the core product behavior, not optional convenience features.

## 4. Failure Visibility

The system must surface what failed and why.

At minimum, the user should be told about:

- parse failure
- schema validation failure
- field-level validation failure
- execution error
- semantic mismatch between result and step intent
- missing artifact
- stale upstream data

The user should also see what the harness attempted in response, such as deterministic fix, structured retry, code repair, or replan.

## 5. Trust And Provenance UX

The TUI should make it easy to inspect why the system believes something:

- what source files were used
- what their fingerprints were
- what step produced the result
- what artifacts back the claim
- whether the conclusion is currently valid, stale, or needs review

The design should make provenance visible enough that the user can challenge or trust results intelligently.

## 6. Verification Strategy

Three verification layers are required.

### 6.1 Control-Plane Validation

Schema tests for:

- plan objects
- step contracts
- execution envelopes
- step result JSON
- doctor reports
- review proposals
- memory update proposals

### 6.2 Execution Validation

Tests that verify worker behavior under:

- successful runs
- Python exceptions
- malformed JSON output
- missing report files
- artifact registration errors
- resource-limit failures

### 6.3 Product Validation

End-to-end scenarios such as:

1. analyze a CSV and produce an artifact-backed answer
2. reuse the same dataset and benefit from remembered dataset knowledge
3. change the source file and run doctor
4. mark earlier conclusions as stale and propose reruns

## 7. Acceptance Rules

The product should not be considered correct unless it can demonstrate:

- no unsupported claim without artifact-backed evidence
- no silent overwrite of prior conclusions
- no silent learning of durable knowledge without a review path
- no reuse of dataset knowledge when fingerprints show material change

## 8. Why This Design

If the product only focuses on the internal agent loop, it will still feel unreliable to the user. The TUI and verification layer are what make the harness operationally understandable and defensible in real analysis work.
