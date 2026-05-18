# L3 Prompt-Profiles / Harness Core — Follow-up Cleanups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the seven OPEN follow-up issues recorded in `Issues.md` (section "L3 prompt-profiles / Harness Core refactor — review follow-ups (OPEN 2026-05-18)") from the merged refactor `20247ad`, without changing observable behavior except where a cleanup intentionally unifies a convention.

**Architecture:** All work is internal to Layer 3 (`src/harness/`). Each task is independent, behavior-preserving, and individually committable. No Layer 1/2/4 surface changes. Tests are TDD-first where behavior is observable; rename/constant tasks lead with a guard test that locks the new shape.

**Tech Stack:** Python 3.13, `uv`, `pytest`, pydantic v2, SQLite (`harness/core/db.py`).

**Baseline:** Full suite green at HEAD — `661 passed`. Every task must keep `uv run pytest -q` green.

---

## Pre-flight (all tasks)

Run from repo root. Environment:

```bash
uv venv .venv --python 3.13
source .venv/bin/activate
```

Baseline check before starting:

```bash
uv run pytest -q
```
Expected: `661 passed` (1 warning).

---

### Task 1: Kill the `PromptPackage` name collision (rename services model → `RenderedPrompt`)

**Issue:** Two same-named classes inside `harness/`: `harness/control.py:158` `PromptPackage(HarnessRecord)` (persisted run record) vs `harness/services/prompt_profiles.py:11` `PromptPackage(BaseModel)` (rendered-prompt value), the latter re-exported from `services/__init__.py`. Confirmed: orchestrator imports the **control** one; no source/test imports the services one by name (`test_prompt_profiles.py` imports only `PromptProfileRegistry`).

**Files:**
- Modify: `src/harness/services/prompt_profiles.py`
- Modify: `src/harness/services/__init__.py`
- Test: `tests/harness/test_prompt_profiles.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/harness/test_prompt_profiles.py`:

```python
def test_load_returns_rendered_prompt_type():
    from harness.services import RenderedPrompt
    from harness.services.prompt_profiles import RenderedPrompt as RP2

    reg = PromptProfileRegistry(Path("src/harness/prompts"))
    pkg = reg.load("interaction")
    assert isinstance(pkg, RenderedPrompt)
    assert RenderedPrompt is RP2
    assert pkg.prompt_text and pkg.package_hash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_prompt_profiles.py::test_load_returns_rendered_prompt_type -q`
Expected: FAIL with `ImportError: cannot import name 'RenderedPrompt'`.

- [ ] **Step 3: Rename the class and all in-module references**

In `src/harness/services/prompt_profiles.py`:
- `class PromptPackage(BaseModel):` → `class RenderedPrompt(BaseModel):`
- `self._cache: dict[str, PromptPackage] = {}` → `self._cache: dict[str, RenderedPrompt] = {}`
- `def load(self, mode: str) -> PromptPackage:` → `def load(self, mode: str) -> RenderedPrompt:`
- `package = PromptPackage(` → `package = RenderedPrompt(`

- [ ] **Step 4: Update the package re-export**

In `src/harness/services/__init__.py`:
- `from harness.services.prompt_profiles import PromptPackage, PromptProfileRegistry` → `from harness.services.prompt_profiles import RenderedPrompt, PromptProfileRegistry`
- In `__all__`, replace `"PromptPackage"` with `"RenderedPrompt"`.

- [ ] **Step 5: Run the new test + full prompt-profile + suite-wide collision guard**

Run: `uv run pytest tests/harness/test_prompt_profiles.py -q && uv run pytest -q -k "prompt or orchestrator or session"`
Expected: PASS, no `PromptPackage` import errors.

- [ ] **Step 6: Confirm no stale references remain**

Run: `grep -rn "services.*PromptPackage\|PromptPackage" src tests --include="*.py" | grep -v "control"`
Expected: no matches (only `control.PromptPackage` survives, which this grep excludes).

- [ ] **Step 7: Commit**

```bash
git add src/harness/services/prompt_profiles.py src/harness/services/__init__.py tests/harness/test_prompt_profiles.py
git commit -m "refactor(harness): rename services PromptPackage -> RenderedPrompt to end name collision"
```

---

### Task 2: Introduce shared profile-mode constants (de-stringly-type the closed set)

**Issue:** `"interaction"/"analyst"/"knowledge"/"clarification"` literals duplicated across `mode_router.py`, `prompt_profiles.MODE_TOOL_NAMES`, `orchestrator._select_profile`, and `mode_router._classify_with_llm`'s inline valid-set. Closed set, no single source.

**Design decision:** Use plain module-level `str` constants + a `frozenset` (NOT an enum — YAGNI; keeps zero behavior change since values stay identical strings). Scope: introduce the module, replace the **validity set** and the `ProfileDecision(...)` constructions and orchestrator's `"analyst"` comparisons. The `MODE_TOOL_NAMES` dict keys are a data table and stay literal (documented below — replacing them is cosmetic churn with no DRY win).

**Files:**
- Create: `src/harness/services/profile_modes.py`
- Modify: `src/harness/services/mode_router.py`
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_profile_modes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/harness/test_profile_modes.py`:

```python
from harness.services.profile_modes import (
    INTERACTION, ANALYST, KNOWLEDGE, CLARIFICATION, VALID_PROFILE_MODES,
)


def test_constants_match_canonical_strings():
    assert INTERACTION == "interaction"
    assert ANALYST == "analyst"
    assert KNOWLEDGE == "knowledge"
    assert CLARIFICATION == "clarification"


def test_valid_set_is_exactly_the_four_modes():
    assert VALID_PROFILE_MODES == frozenset(
        {"interaction", "analyst", "knowledge", "clarification"}
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_profile_modes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.services.profile_modes'`.

- [ ] **Step 3: Create the constants module**

Create `src/harness/services/profile_modes.py`:

```python
"""Canonical Layer 3 prompt-profile mode identifiers.

Single source of truth for the closed set of prompt-profile names used by the
intent router, the prompt-profile registry, and the orchestrator. Values are
the exact historical strings so persistence/serialization is unchanged.
"""
from __future__ import annotations

INTERACTION = "interaction"
ANALYST = "analyst"
KNOWLEDGE = "knowledge"
CLARIFICATION = "clarification"

VALID_PROFILE_MODES = frozenset({INTERACTION, ANALYST, KNOWLEDGE, CLARIFICATION})
```

- [ ] **Step 4: Use constants in `mode_router.py`**

In `src/harness/services/mode_router.py`:
- Add import after line 9: `from harness.services.profile_modes import (INTERACTION, ANALYST, KNOWLEDGE, CLARIFICATION, VALID_PROFILE_MODES)`
- Line 69: `ProfileDecision(mode="knowledge", ...)` → `ProfileDecision(mode=KNOWLEDGE, ...)`
- Line 78: `ProfileDecision(mode="analyst", ...)` → `ProfileDecision(mode=ANALYST, ...)`
- Line 83: `classified != "interaction"` → `classified != INTERACTION`
- Line 88: `ProfileDecision(mode="interaction", ...)` → `ProfileDecision(mode=INTERACTION, ...)`
- Line 119: `if result in {"interaction", "analyst", "knowledge", "clarification"}:` → `if result in VALID_PROFILE_MODES:`

- [ ] **Step 5: Use constants in `orchestrator.py` `_select_profile` / handoff**

In `src/harness/orchestrator.py`:
- Add to the existing `from harness.services...` import block (near line 42): `from harness.services.profile_modes import INTERACTION, ANALYST`
- `_select_profile` (lines 1457-1460): replace the two `"interaction"` literals with `INTERACTION`.
- `run_agentic_turn` sticky check (line 1488 `active_mode != "analyst"`, 1500 `active_mode = "analyst"`, 1501 `state.active_agent_mode = "analyst"`, 1502 `if active_mode == "analyst":`): replace each `"analyst"` with `ANALYST`.
- Handoff block (line 1642 `if handoff_target == "analyst":`): `ANALYST`.

(Leave `MODE_TOOL_NAMES` dict keys in `prompt_profiles.py` as string literals — they are a lookup table keyed by mode; substituting constants there is cosmetic and adds an import cycle risk for no DRY benefit. This is intentional, noted in `Issues.md` resolution.)

- [ ] **Step 6: Run focused + full suite**

Run: `uv run pytest tests/harness/test_profile_modes.py tests/harness/test_mode_router.py tests/harness/test_mode_router_legacy.py tests/harness/test_mode_continuity.py tests/harness/test_agentic_turn.py -q && uv run pytest -q`
Expected: PASS; full suite still `661 passed` plus the new file's tests.

- [ ] **Step 7: Commit**

```bash
git add src/harness/services/profile_modes.py src/harness/services/mode_router.py src/harness/orchestrator.py tests/harness/test_profile_modes.py
git commit -m "refactor(harness): single source for profile-mode identifiers"
```

---

### Task 3: Consolidate the mode-router keyword taxonomy

**Issue:** `_transformation_match` (`mode_router.py:95-107`) re-lists inline literal subsets (`has_rule_language` set, `{"one","hot"}`, `{"min","max"}`/`{"normalize","normalized"}`) that overlap class-level `transformation_terms`. Duplicated taxonomy → drift risk.

**Constraint:** Behavior must be **identical**. This is a pure refactor: extract the inline literal sets to named class-level frozensets and reference them; do not change which inputs match.

**Files:**
- Modify: `src/harness/services/mode_router.py`
- Test: `tests/harness/test_mode_router_taxonomy.py`

- [ ] **Step 1: Write the characterization test (locks current behavior before refactor)**

Create `tests/harness/test_mode_router_taxonomy.py`:

```python
from harness.services.mode_router import ModeRouter

R = ModeRouter()

MATCHING = [
    "derive a new column in data/sales.csv",
    "one hot encode the category field",
    "min max normalize the revenue column",
    "add a rolling average column",
    "join data/a.csv with data/b.csv",
]
NON_MATCHING = [
    "hello there",
    "what is the weather",
    "tell me a joke",
]


def test_transformation_inputs_route_to_analyst():
    for text in MATCHING:
        assert R.route(text).mode == "analyst", text


def test_non_transformation_inputs_do_not_route_to_analyst():
    for text in NON_MATCHING:
        assert R.route(text).mode != "analyst", text
```

- [ ] **Step 2: Run test to verify it passes (characterizes current behavior)**

Run: `uv run pytest tests/harness/test_mode_router_taxonomy.py -q`
Expected: PASS (this captures the behavior we must preserve through the refactor).

- [ ] **Step 3: Extract named subsets, remove inline duplicates**

In `src/harness/services/mode_router.py`, add these class-level attributes next to `transformation_terms` (after line 47):

```python
    rule_language_terms = frozenset({
        "derive", "derived", "transform", "transformed", "normalize", "normalized",
        "encode", "bucket", "map", "join", "merge", "flag", "classify", "lookup",
        "enrich", "moving", "rolling", "lag", "lead", "cumulative",
    })
    column_language_terms = frozenset({"column", "columns", "field", "fields"})
```

Rewrite `_transformation_match` (lines 95-107) to:

```python
    def _transformation_match(self, normalized: str, words: set[str]) -> bool:
        if not (words & self.transformation_terms):
            return False
        has_workspace_ref = any(p in normalized for p in self.workspace_reference_patterns)
        has_column_language = bool(words & self.column_language_terms)
        has_rule_language = bool(words & self.rule_language_terms)
        one_hot = {"one", "hot"} <= words
        min_max = {"min", "max"} <= words and bool(words & {"normalize", "normalized"})
        return has_workspace_ref or has_column_language or has_rule_language or one_hot or min_max
```

(`one_hot` / `min_max` stay inline: they are 2-element ordered-pair guards, not taxonomy lists — extracting them adds no DRY value.)

- [ ] **Step 4: Run characterization test + router suite to verify unchanged behavior**

Run: `uv run pytest tests/harness/test_mode_router_taxonomy.py tests/harness/test_mode_router.py tests/harness/test_mode_router_legacy.py tests/harness/test_mode_continuity.py -q`
Expected: PASS — identical routing outcomes.

- [ ] **Step 5: Commit**

```bash
git add src/harness/services/mode_router.py tests/harness/test_mode_router_taxonomy.py
git commit -m "refactor(harness): de-duplicate mode-router keyword taxonomy"
```

---

### Task 4: Remove the redundant `requested_mode` parameter from `run_turn`

**Issue:** `run_turn` keeps `requested_mode: str | None = None` (`orchestrator.py:2056`) used only at `2063` as `requested_mode or state.active_agent_mode`. For every non-test caller `requested_mode` already equals `state.active_agent_mode` (caller `1595` passes `active_mode` which `_select_profile` already wrote to the record). Only tests inject it. `state.active_agent_mode` is now the single source of truth.

**Callers to update (verified):**
- Source: `orchestrator.py:1593-1596` (internal), `orchestrator.py:2512` (resume — already does not pass it).
- Tests passing `requested_mode=`: `tests/app/test_app_session_async.py:17,40` (FakeOrchestrator + call), `tests/harness/test_plan_gap_closures.py:59`, `tests/harness/test_runtime_bridge.py:54`, `tests/harness/test_token_pressure_gate.py:74,97`.

- [ ] **Step 1: Write the failing test**

Append to `tests/harness/test_mode_continuity.py`:

```python
import inspect
from harness.orchestrator import Orchestrator


def test_run_turn_has_no_requested_mode_param():
    sig = inspect.signature(Orchestrator.run_turn)
    assert "requested_mode" not in sig.parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_mode_continuity.py::test_run_turn_has_no_requested_mode_param -q`
Expected: FAIL — `requested_mode` still in signature.

- [ ] **Step 3: Drop the parameter and its use in `run_turn`**

In `src/harness/orchestrator.py`:
- Delete line 2056 (`        requested_mode: str | None = None,`).
- Line 2063: `active_mode = requested_mode or state.active_agent_mode` → `active_mode = state.active_agent_mode`.

- [ ] **Step 4: Update the internal caller**

In `src/harness/orchestrator.py` lines 1593-1596, the `run_turn(...)` call currently passes `requested_mode=active_mode`. Since `_select_profile` already wrote `active_mode` into `state.active_agent_mode` (line 1461) and the sticky/analyst override also writes it (line 1501), remove the `requested_mode=active_mode,` argument from this call. Resulting call keeps `user_input=current_input, prompt_text=prompt_text, durable_context=durable, persist_user_message=first_iter,`.

- [ ] **Step 5: Update tests that injected `requested_mode`**

- `tests/app/test_app_session_async.py:17` — `FakeOrchestrator.run_turn` signature: drop `requested_mode=None`. Line ~25 uses `active_mode=requested_mode or "interaction"` → `active_mode=state.active_agent_mode`. Line ~40 call: drop `requested_mode=state.active_agent_mode,` (already redundant).
- `tests/harness/test_plan_gap_closures.py:59`, `tests/harness/test_runtime_bridge.py:54`, `tests/harness/test_token_pressure_gate.py:74` and `:97` — each constructs a `RunStateRecord` then calls `run_turn(..., requested_mode="interaction", ...)`. For each: ensure the `RunStateRecord` is built with `active_agent_mode="interaction"` (it is a required field, so it is already set — verify the value), then delete the `requested_mode="interaction",` argument from the `run_turn(...)` call.

- [ ] **Step 6: Run affected tests then full suite**

Run: `uv run pytest tests/app/test_app_session_async.py tests/harness/test_plan_gap_closures.py tests/harness/test_runtime_bridge.py tests/harness/test_token_pressure_gate.py tests/harness/test_mode_continuity.py -q && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 7: Commit**

```bash
git add src/harness/orchestrator.py tests/app/test_app_session_async.py tests/harness/test_plan_gap_closures.py tests/harness/test_runtime_bridge.py tests/harness/test_token_pressure_gate.py tests/harness/test_mode_continuity.py
git commit -m "refactor(harness): drop redundant requested_mode param; state.active_agent_mode is source of truth"
```

---

### Task 5: Unify state-mutation convention — `resume_with_clarification` mutates the live record in place

**Issue:** `_select_profile` (1461) and handoff (1641) mutate `state` in place (the spec-mandated write-back fix), but `resume_with_clarification` (`orchestrator.py:2511`) still does `state.model_copy(update=...)` and runs the turn on the throwaway copy. Two contradictory conventions for the same record. Spec §"Mode Continuity" explicitly wants in-place, not throwaway `model_copy`, so the long-lived TUI state stays correct.

**Behavior intent:** After resume, the **same** `RunStateRecord` object the TUI holds reflects `state == CLARIFYING`-cleared (`pending_clarification_id == None`) and retains its prior `active_agent_mode` (continuity). `RunStateRecord` is a mutable pydantic model (already mutated in place at line 1461), so direct assignment is valid.

**Files:**
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_mode_continuity.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/harness/test_mode_continuity.py` (reuse the existing module's `orch`/`state` construction helpers at the top of that file; if it builds them via a fixture/factory, use the same):

```python
import asyncio
from harness.control import RunState


def test_resume_with_clarification_mutates_live_record_in_place(orch_and_state):
    orch, state = orch_and_state  # same factory the other tests in this file use
    state.active_agent_mode = "analyst"
    state.state = RunState.CLARIFYING
    state.pending_clarification_id = "clar_1"
    original_id = id(state)

    async def drain():
        async for _ in orch.resume_with_clarification(
            workspace_dir=state_workspace(state),  # same helper the file uses
            state=state,
            clarification_text="the 2024 one",
        ):
            pass

    asyncio.run(drain())

    assert id(state) == original_id  # same object, not a copy
    assert state.pending_clarification_id is None
    assert state.active_agent_mode == "analyst"  # continuity preserved
```

> Note for implementer: `tests/harness/test_mode_continuity.py` already constructs an `Orchestrator` + `RunStateRecord` for its existing tests (lines 7/20/30/38 call `orch._select_profile(state, ...)`). Reuse that exact construction (promote it to a `pytest.fixture` named `orch_and_state` and a `state_workspace` helper if not already factored). Do not invent a new harness.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_mode_continuity.py::test_resume_with_clarification_mutates_live_record_in_place -q`
Expected: FAIL — `id(state)` differs (current code runs the turn on `cleared`, a `model_copy`), so `state.pending_clarification_id` is still `"clar_1"`.

- [ ] **Step 3: Replace the `model_copy` with in-place mutation**

In `src/harness/orchestrator.py` `resume_with_clarification` (lines 2510-2515), replace:

```python
        # model_copy carries active_agent_mode forward → profile continuity across the clarification resume.
        cleared = state.model_copy(update={"state": RunState.CLARIFYING, "pending_clarification_id": None})
        async for ev in self.run_turn(
            cleared, workspace_dir=workspace_dir, chat_id=state.run_id,
            user_input=clarification_text,
        ):
            yield ev
```

with:

```python
        # In-place mutation keeps the long-lived TUI RunStateRecord correct and
        # preserves active_agent_mode for profile continuity across the resume.
        state.state = RunState.CLARIFYING
        state.pending_clarification_id = None
        async for ev in self.run_turn(
            state, workspace_dir=workspace_dir, chat_id=state.run_id,
            user_input=clarification_text,
        ):
            yield ev
```

- [ ] **Step 4: Run the new test + continuity + orchestrator async suite**

Run: `uv run pytest tests/harness/test_mode_continuity.py tests/harness/test_orchestrator_async.py tests/harness/test_orchestrator.py tests/harness/test_persistence_integration.py -q && uv run pytest -q`
Expected: PASS; full suite green (`661 + new tests`).

- [ ] **Step 5: Commit**

```bash
git add src/harness/orchestrator.py tests/harness/test_mode_continuity.py
git commit -m "fix(harness): resume_with_clarification mutates live RunStateRecord in place (convention unification)"
```

---

### Task 6: Replace doctor full-table scan with a keyed persistence query

**Issue:** `doctor._collect_tmp_actions` (`services/doctor.py:560-567`) calls `self.persistence.db.list_records("tmp_actions")` then filters in Python by `doctor_report_id`. `db.py` already has the `json_extract` keyed pattern (`load_record`, lines 119-129). Add a multi-row keyed variant and use it.

**Files:**
- Modify: `src/harness/core/db.py`
- Modify: `src/harness/services/doctor.py`
- Test: `tests/harness/test_db.py` (create if absent — check first with `ls tests/harness/test_db.py`)

- [ ] **Step 1: Write the failing test**

Add to `tests/harness/test_db.py` (if the file does not exist, create it with the import block mirroring `tests/harness/test_persistence_integration.py`'s DB construction):

```python
def test_list_records_where_filters_by_json_field(tmp_path):
    from harness.core.db import Db  # use the same import the persistence tests use

    db = Db(tmp_path / "t.sqlite")  # match existing test construction if it differs
    db.append_record("tmp_actions", "a1", {"id": "a1", "doctor_report_id": "r1"})
    db.append_record("tmp_actions", "a2", {"id": "a2", "doctor_report_id": "r2"})
    db.append_record("tmp_actions", "a3", {"id": "a3", "doctor_report_id": "r1"})

    rows = db.list_records_where("tmp_actions", "doctor_report_id", "r1")
    assert sorted(r["id"] for r in rows) == ["a1", "a3"]
    assert db.list_records_where("tmp_actions", "doctor_report_id", "rX") == []
```

> Implementer note: confirm the exact `Db` constructor / factory used by `tests/harness/test_persistence_integration.py` (line ~49 constructs it) and mirror it; do not assume the signature.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_db.py::test_list_records_where_filters_by_json_field -q`
Expected: FAIL — `AttributeError: 'Db' object has no attribute 'list_records_where'`.

- [ ] **Step 3: Add the keyed query to `db.py`**

In `src/harness/core/db.py`, add directly after `list_records` (after line 117):

```python
    def list_records_where(
        self, table: str, key_name: str, key_value: str
    ) -> list[dict[str, object]]:
        if table not in AUTHORITATIVE_TABLES:
            raise ValueError(f"unknown table: {table}")
        _validate_key_name(key_name)
        rows = self.conn.execute(
            f"select record_json from {table} "
            f"where json_extract(record_json, '$.{key_name}') = ?",
            (key_value,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]
```

(Mirrors the existing `load_record` `json_extract` + `_validate_key_name` pattern; multi-row instead of single.)

- [ ] **Step 4: Use it in the doctor service**

In `src/harness/services/doctor.py`, `_collect_tmp_actions` (lines 560-567), replace the body that does `list_records("tmp_actions")` + Python filter with:

```python
    def _collect_tmp_actions(self, report_id: str) -> list[dict[str, Any]]:
        try:
            return self.persistence.db.list_records_where(
                "tmp_actions", "doctor_report_id", report_id
            )
        except Exception:  # noqa: BLE001 - persistence backend missing/empty
            return []
```

(Preserve the existing try/except contract — if the original swallowed errors to return `[]`, keep that exact fallback semantics; only the query strategy changes.)

- [ ] **Step 5: Run db + doctor suites then full suite**

Run: `uv run pytest tests/harness/test_db.py -q && uv run pytest -q -k doctor && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/harness/core/db.py src/harness/services/doctor.py tests/harness/test_db.py
git commit -m "perf(harness): keyed tmp_actions query replaces doctor full-table scan"
```

---

### Task 7: Minor hardening — drop dead defensiveness, retire the `request_mode` alias

**Issue (minors):** (a) `mode_router.request_mode` is a pure pass-through alias to `route()` kept only for two historical-name tests — dual public API. (b) `doctor.py` `_collect_tmp_actions` bare `except Exception: return []` is broad (now scoped in Task 6 — verify a comment documents WHY). (c) The `findings or []` dead defensiveness on a non-optional `findings: list[DoctorFinding]` (`doctor.py:561` area — confirm exact line at implement time via `grep -n "findings or \[\]" src/harness/services/doctor.py`).

**Decision:** Retire the `request_mode` alias and migrate its two callers to `route()` (single public entry point). Remove the dead `findings or []`.

**Files:**
- Modify: `src/harness/services/mode_router.py`
- Modify: `tests/harness/test_mode_router.py`
- Modify: `tests/harness/test_mode_router_legacy.py`
- Modify: `src/harness/services/doctor.py`

- [ ] **Step 1: Write the failing guard test**

Append to `tests/harness/test_mode_router.py`:

```python
def test_request_mode_alias_removed():
    from harness.services.mode_router import ModeRouter
    assert not hasattr(ModeRouter, "request_mode")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_mode_router.py::test_request_mode_alias_removed -q`
Expected: FAIL — `request_mode` still defined.

- [ ] **Step 3: Migrate the two existing callers to `route()`**

- `tests/harness/test_mode_router.py:21` — `decision = r.request_mode("count the rows in data/sales.csv")` → `decision = r.route("count the rows in data/sales.csv")`.
- `tests/harness/test_mode_router_legacy.py:6` — `request = router.request_mode("compare attrition by department")` → `request = router.route("compare attrition by department")`. (If this file's only purpose was the legacy alias, keep the file but it now exercises `route()`; rename of the file is out of scope.)

- [ ] **Step 4: Delete the alias**

In `src/harness/services/mode_router.py`, delete the `request_mode` method (lines 60-62):

```python
    def request_mode(self, user_text: str) -> ProfileDecision:
        """Stable public entry point that delegates to route(); kept for callers and tests that use the historical name."""
        return self.route(user_text)
```

- [ ] **Step 5: Remove the dead `findings or []`**

Run `grep -n "findings or \[\]" src/harness/services/doctor.py`. At the reported line, `findings` is typed `list[DoctorFinding]` (non-optional) and callers pass a concrete list. Replace `(findings or [])` with `findings` in the loop expression. If the surrounding context shows `findings` can legitimately be `None` at that call site, **do not change it** — record that in `Issues.md` instead and skip this step.

- [ ] **Step 6: Run router + doctor + full suite**

Run: `uv run pytest tests/harness/test_mode_router.py tests/harness/test_mode_router_legacy.py -q && uv run pytest -q -k doctor && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 7: Commit**

```bash
git add src/harness/services/mode_router.py src/harness/services/doctor.py tests/harness/test_mode_router.py tests/harness/test_mode_router_legacy.py
git commit -m "refactor(harness): retire request_mode alias; drop dead findings defensiveness"
```

---

### Task 8: Close out `Issues.md`

**Files:**
- Modify: `Issues.md`
- Modify: `CODEMAP.md` (only if the four tracked relationship types changed)

- [ ] **Step 1: Append resolution note to the OPEN section**

In `Issues.md`, under the "L3 prompt-profiles / Harness Core refactor — review follow-ups (OPEN 2026-05-18)" section, append (do not delete the original entries — AGENTS.md rule):

```markdown
- Fix pass 2026-05-18: RESOLVED — (1) services `PromptPackage` renamed `RenderedPrompt` (collision gone); (2) `harness/services/profile_modes.py` is now the single source for mode identifiers (`MODE_TOOL_NAMES` keys intentionally left literal — table data, no DRY win); (3) mode-router keyword taxonomy de-duplicated into named frozensets; (4) `requested_mode` param removed from `run_turn` (`state.active_agent_mode` is source of truth); (5) `resume_with_clarification` mutates the live `RunStateRecord` in place (convention unified with `_select_profile`/handoff); (6) `Db.list_records_where` keyed query replaces the doctor `tmp_actions` full-table scan; (7) `request_mode` alias retired, dead `findings or []` removed. Verified: `uv run pytest -q` green.
```

- [ ] **Step 2: Update `CODEMAP.md` if structure changed**

The new files are `src/harness/services/profile_modes.py` (imported by `mode_router.py` and `orchestrator.py`) and the new `Db.list_records_where` definition. If `CODEMAP.md` tracks module imports/definitions at this granularity, add: `profile_modes.py` (imported by `mode_router`, `orchestrator`); `Db.list_records_where` definition; the renamed `RenderedPrompt`. If `CODEMAP.md` does not track at this level, state that and skip.

- [ ] **Step 3: Final full-suite verification**

Run: `uv run pytest -q`
Expected: `PASS` — `661` baseline + all new task tests, zero failures.

- [ ] **Step 4: Commit**

```bash
git add Issues.md CODEMAP.md
git commit -m "docs: close out L3 refactor follow-up issues; codemap update"
```

---

## Self-Review

**1. Spec/issue coverage** — every OPEN `Issues.md` bullet maps to a task:
- Duplicate `PromptPackage` → Task 1.
- Mixed state-mutation convention → Task 5.
- `requested_mode` param sprawl → Task 4.
- Stringly-typed modes → Task 2.
- Duplicated keyword taxonomy → Task 3.
- Doctor full-table scan → Task 6.
- Minors (`request_mode` alias, bare except, `findings or []`) → Task 7.
- Bookkeeping (`Issues.md`, `CODEMAP.md`) → Task 8.
No gaps.

**2. Placeholder scan** — no TBD/TODO/"add error handling"/"similar to Task N". Test bodies and edits are concrete. Two implementer notes (Task 5 fixture reuse, Task 6 `Db` constructor) explicitly say *reuse the exact existing construction* rather than leaving it blank — these are necessary because the harness fixtures already exist and must not be reinvented; the note pins the source of truth (the named existing test lines) so there is no ambiguity.

**3. Type/name consistency** — `RenderedPrompt` used consistently (Tasks 1, 8). `profile_modes` constant names (`INTERACTION`/`ANALYST`/`KNOWLEDGE`/`CLARIFICATION`/`VALID_PROFILE_MODES`) identical across Tasks 2 and the module. `list_records_where(table, key_name, key_value)` signature identical in db.py (Task 6 Step 3) and its caller (Step 4) and test (Step 1). `requested_mode` removal (Task 4) consistent across signature, internal caller, and all four named test files.

**Risk ordering:** Tasks 1→3 are pure refactors (lowest risk). Task 4 touches a semi-public internal signature + 4 test files. Task 5 is the one intentional behavior unification (covered by its own failing-test-first). Task 6 adds a new DB method (additive, low risk). Task 7 is minor cleanup. Each task is independently revertable.
