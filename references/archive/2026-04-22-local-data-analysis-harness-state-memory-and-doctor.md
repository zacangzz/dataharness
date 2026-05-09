# Local Data Analysis Harness: State, Memory, And Doctor

Date: 2026-04-22
Status: Drafted from approved design discussion
Parent: `2026-04-22-local-data-analysis-harness-overview.md`

## 1. Purpose

This spec defines the persistent state model for the harness.

The system must remember enough to be useful across sessions, but it must also know when remembered conclusions may no longer be valid because source data changed. That makes state, memory, and doctoring first-class features rather than add-ons.

## 2. State Layers

The harness should keep four distinct persistent layers.

### 2.1 Session Ledger

The authoritative record of an analysis session:

- user requests
- approved plan versions
- step contracts
- execution attempts
- code hashes
- retry history
- reports
- artifacts
- final conclusions

### 2.2 User Memory

Stable user preferences and working style, such as:

- preferred answer structure
- preferred level of detail
- naming conventions
- recurring business definitions
- trusted workflow habits

### 2.3 Dataset Knowledge

Reusable knowledge tied to specific files or file families:

- schema summaries
- column semantics
- entity definitions
- common filters
- prior anomalies
- business glossary
- known quality issues
- reusable workflow patterns

### 2.4 Working Session Context

Temporary state needed during an active run, such as:

- open goals
- current plan branch
- active assumptions
- unresolved step issues

This may be compressed or discarded later. It is not a substitute for durable state.

## 3. Validity Registry

Past analysis is not timeless. Every conclusion should carry provenance back to the exact dataset fingerprints, steps, and artifacts that produced it.

Statuses should include:

- `ok`
- `changed`
- `stale`
- `needs_review`
- `revalidated`
- `broken_lineage`

No prior conclusion should be silently overwritten. Validity changes are recorded as state transitions.

## 4. Dataset Fingerprinting

The harness must fingerprint datasets so that learned knowledge and prior conclusions have a concrete validity basis.

### 4.1 File Fingerprint

- file path
- file size
- modified time
- content hash

### 4.2 Schema Fingerprint

- column names
- data types
- sheet or partition structure where relevant
- row-count or shard markers where practical

### 4.3 Profile Fingerprint

Optional but recommended lightweight summaries:

- sampled-content summaries
- simple statistical signatures
- null-rate and distinct-count sketches

These fingerprints help detect both obvious file changes and more meaningful semantic shifts.

## 5. Learning Model

Learning in this harness means updating:

- user memory
- dataset knowledge
- workflow patterns
- validity state

Learning does not mean changing the base harness architecture, tools, or prompt contract automatically.

All proposed long-term memory updates should remain reviewable.

## 6. Doctor Workflow

Doctor is an explicit on-demand workflow, not an autonomous background daemon in the first version.

It should:

- rescan tracked source files
- recompute fingerprints
- compare them with prior sessions
- detect schema drift, content drift, missing files, renamed files, and broken lineage
- identify which plans, artifacts, and conclusions are affected
- emit a structured doctor report

The doctor report should say what is:

- still valid
- stale
- broken
- safe to reuse
- recommended for rerun
- recommended for user review

## 7. Review Workflow

Review is lighter than doctor. It is used to propose learning updates after a session or on demand.

Review may propose:

- user preference updates
- dataset knowledge updates
- reusable workflow notes
- unresolved quality observations

Review proposes. The user accepts or rejects.

## 8. Memory Hygiene Rules

- durable memory must be separated from working session context
- user memory must not be polluted by one-off task details
- dataset knowledge must not be reused when fingerprints indicate a materially different source
- validity state must be traceable to evidence rather than intuition

## 9. Why This Design

The harness needs to be helpful across time without becoming careless about stale knowledge. Splitting state this way makes it possible to:

- remember how the user likes to work
- remember what the data means
- remember what happened in a session
- detect when those memories should no longer be trusted
