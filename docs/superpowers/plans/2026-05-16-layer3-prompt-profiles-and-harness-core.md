# Layer 3 Prompt Profiles And Harness Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the Layer 4b "agent" concept, make Layer 3 own prompt-profile selection + routing, fix the `active_agent_mode` write-back, move doctor narration into Layer 3, and reorganize loose `src/harness/*.py` into a `core/` kernel + `services/`.

**Architecture:** Routing and persona prompts become Layer 3 services (`mode_router`, `prompt_profiles`) called inside `Orchestrator.run_agentic_turn`. `AppSession` becomes a pure passthrough (no router/prompt callback, no `runtime.*`). Doctor narration consolidates into the existing `DoctorRunner` (already has runtime). Loose harness files are hard-moved into `src/harness/core/` (separable kernel) or `src/harness/services/` (latent domain logic); re-export shims are deleted.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, `uv`. Run all tests with `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest ... -q` from repo root.

**Spec:** `docs/superpowers/specs/2026-05-16-layer3-prompt-profiles-and-harness-core-design.md`

**Commit policy (AGENTS.md):** All work happens on an isolated worktree/branch. Commit per task on the branch. Do **not** push or merge to `main`; the final single squash-merge to `main` is a separate, explicitly-authorized step.

---

## File Structure

**New (Layer 3 services):**
- `src/harness/services/mode_router.py` — intent→profile classifier (ex-`AgentModeRouter`).
- `src/harness/services/prompt_profiles.py` — `PromptPackage` type + `PromptProfileRegistry` (ex-`PromptPackageRegistry`, `_tool_catalog`, `MODE_TOOL_NAMES`).

**New (Core kernel folder):**
- `src/harness/core/__init__.py` + 13 moved kernel modules.

**Moved (latent services):** `knowledge`, `knowledge_intents`, `chat`, `context`, `repair`, `provenance` → `src/harness/services/*`; `workspace_async.py` → `src/harness/services/workspace.py`.

**Moved (prompts):** all `src/app/agents/prompts/*.md` → `src/harness/prompts/`.

**Deleted:** `src/app/agents/` (whole package); `src/harness/commands.py`, `src/harness/doctor.py`, `src/harness/doctor_runner.py` (re-export shims).

**Modified (key):** `src/harness/orchestrator.py`, `src/app/session.py`, `src/harness/services/doctor.py`, `src/harness/services/__init__.py`, `tests/harness/test_service_ownership.py`, `CODEMAP.md`, docs.

---

## Phase Order

1. Worktree setup.
2. Agents → Layer 3 prompt profiles + routing + mode-continuity fix (behavioral; TDD).
3. Doctor narration → Layer 3.
4. Harness Core folder.
5. Latent services migration + shim deletion.
6. Docs (canonical spec, services.md, tools-vs-commands.md, doctor-behaviour.md, Lessons.md, CODEMAP).
7. Final verification.

Each phase ends with the full suite green and a commit.

---

### Task 1: Isolated Worktree

**Files:** none (git only)

- [ ] **Step 1: Create the worktree**

Use the `superpowers:using-git-worktrees` skill to create an isolated worktree for branch `feat/l3-prompt-profiles-harness-core`. If unavailable, fallback:

```bash
cd /Users/zacang/Documents/datascience/research-llm-harness
git worktree add ../rlh-l3-core -b feat/l3-prompt-profiles-harness-core
cd ../rlh-l3-core
```

- [ ] **Step 2: Baseline test run**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest -q 2>&1 | tail -n 5
```

Expected: a green baseline (record the passed count; one known worker-sandbox timeout flake is acceptable per `Lessons.md`). All later phases compare against this baseline.

---

### Task 2: Create `mode_router` service (move, no behavior change)

**Files:**
- Create: `src/harness/services/mode_router.py`
- Test: `tests/harness/test_mode_router.py`

- [ ] **Step 1: Write the test**

Create `tests/harness/test_mode_router.py`:

```python
from harness.services.mode_router import ModeRouter


def test_router_routes_analysis_intent():
    r = ModeRouter()
    assert r.route("count the rows in data/sales.csv").mode == "analyst"


def test_router_routes_knowledge_intent():
    r = ModeRouter()
    assert r.route("remember that revenue means net of refunds").mode == "knowledge"


def test_router_defaults_to_interaction():
    r = ModeRouter()
    assert r.route("hello there").mode == "interaction"
```

- [ ] **Step 2: Run, expect fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_mode_router.py -q`
Expected: FAIL — `ModuleNotFoundError: harness.services.mode_router`.

- [ ] **Step 3: Move the file**

```bash
git mv src/app/agents/router.py src/harness/services/mode_router.py
```

- [ ] **Step 4: Rename the class and fix telemetry layer**

In `src/harness/services/mode_router.py`: rename class `AgentModeRouter` → `ModeRouter`; rename `AgentModeRequest` → `ProfileDecision` (keep an alias `AgentModeRequest = ProfileDecision` is **not** added — no shims). Change the telemetry emit from `Layer.APP` to `Layer.HARNESS`:

```python
    def _emit_decision(self, decision: ProfileDecision, user_text: str) -> None:
        self.telemetry.emit(
            Layer.HARNESS,
            EventKind.AGENT_MODE_PROPOSED,
            payload={"mode": decision.mode, "reason": decision.reason, "input_chars": len(user_text)},
        )
```

Update the internal type name references (`AgentModeRequest`→`ProfileDecision`, `AgentModeDecision` line removed) and `request_mode`/`route` return types accordingly. Keep all keyword sets and routing logic byte-for-byte identical.

- [ ] **Step 5: Run, expect pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_mode_router.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor: move AgentModeRouter -> harness.services.ModeRouter"
```

---

### Task 3: Create `prompt_profiles` service (move PromptPackageRegistry + types)

**Files:**
- Create: `src/harness/services/prompt_profiles.py`
- Test: `tests/harness/test_prompt_profiles.py`

- [ ] **Step 1: Write the test**

Create `tests/harness/test_prompt_profiles.py`:

```python
from pathlib import Path

from harness.orchestrator import Orchestrator
from harness.services.prompt_profiles import PromptProfileRegistry


def test_profile_package_advertises_tools_not_commands(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    reg = PromptProfileRegistry(
        Path("src/harness/prompts"),
        tool_registry=orch.tool_registry,
    )
    text = reg.load("interaction").prompt_text
    assert "file_read" in text
    assert "handoff_to_analyst" in text
    assert "list_files" not in text
    assert "doctor(" not in text


def test_profile_package_hash_stable(tmp_path):
    reg = PromptProfileRegistry(Path("src/harness/prompts"))
    a = reg.load("analyst")
    b = reg.load("analyst")
    assert a.package_hash == b.package_hash
```

- [ ] **Step 2: Run, expect fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_prompt_profiles.py -q`
Expected: FAIL — module + prompts dir missing.

- [ ] **Step 3: Move prompt fragments to the shared root**

```bash
git mv src/app/agents/prompts/system.md src/harness/prompts/system.md
git mv src/app/agents/prompts/interaction.md src/harness/prompts/interaction.md
git mv src/app/agents/prompts/analyst.md src/harness/prompts/analyst.md
git mv src/app/agents/prompts/knowledge.md src/harness/prompts/knowledge.md
git mv src/app/agents/prompts/clarification.md src/harness/prompts/clarification.md
git mv src/app/agents/prompts/response_format.md src/harness/prompts/response_format.md
git mv src/app/agents/prompts/doctor_narrator.md src/harness/prompts/doctor_narrator.md
```

(`src/harness/prompts/` already holds `compaction.md`, `doctor.md`, `knowledge_reconcile.md`; no name clashes.)

- [ ] **Step 4: Create the merged service module**

```bash
git mv src/app/agents/prompt_packages.py src/harness/services/prompt_profiles.py
```

In `src/harness/services/prompt_profiles.py`:
- Add the `PromptPackage` model at the top (moved from `types.py`):

```python
from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from harness.tools.registry import HarnessToolRegistry


class PromptPackage(BaseModel):
    mode: str
    template_version: str
    prompt_text: str
    package_hash: str
```

- Delete the old `from app.agents.types import PromptPackage` import.
- Rename class `PromptPackageRegistry` → `PromptProfileRegistry`. Keep `MODE_TOOL_NAMES`, `_tool_catalog`, and `load()` logic unchanged.

- [ ] **Step 5: Delete the dead `types.py`**

```bash
git rm src/app/agents/types.py
```

- [ ] **Step 6: Run, expect pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_prompt_profiles.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor: move prompt packages + persona prompts into harness.services.prompt_profiles"
```

---

### Task 4: Delete dead `*Mode` classes and the `app.agents` package shell

**Files:**
- Delete: `src/app/agents/analyst.py`, `interaction.py`, `knowledge.py`, `__init__.py`

- [ ] **Step 1: Confirm no callers**

Run: `rg -n "app\.agents\.(analyst|interaction|knowledge)|InteractionMode|AnalystMode|KnowledgeMode|build_turn" src tests`
Expected: only matches inside `src/app/agents/` itself (the dead files) and possibly tests we will fix in Task 7. No production caller of `build_turn`.

- [ ] **Step 2: Delete the dead files**

```bash
git rm src/app/agents/analyst.py src/app/agents/interaction.py src/app/agents/knowledge.py src/app/agents/__init__.py
rmdir src/app/agents/prompts 2>/dev/null || true
rmdir src/app/agents 2>/dev/null || true
```

(`src/app/session.py` still imports `app.agents`; it is fixed in Task 6. The directory may not delete until Step done — that is fine, the `rmdir` is best-effort.)

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "refactor: delete dead app.agents *Mode classes"
```

---

### Task 5: Mode-continuity fix — write `active_agent_mode` back in place (TDD, behavioral)

**Files:**
- Modify: `src/harness/orchestrator.py` (`run_agentic_turn` ~1458-1620; `resume_with_clarification` ~2486-2490)
- Test: `tests/harness/test_mode_continuity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/harness/test_mode_continuity.py`:

```python
from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator


def _profile_for(orch, state, text):
    # Pure routing helper the orchestrator will expose (Task 6 wires it in).
    return orch._select_profile(state, chat_id="c1", user_input=text)


async def test_router_picks_analyst_for_analysis_text(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="interaction")
    assert _profile_for(orch, state, "count rows in data/x.csv") == "analyst"


async def test_active_agent_mode_written_back_in_place(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="interaction")
    orch._select_profile(state, chat_id="c1", user_input="count rows in data/x.csv")
    # Same object mutated, not a copy:
    assert state.active_agent_mode == "analyst"


async def test_ambiguous_followup_keeps_prior_profile(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="analyst")
    # "the 2024 one" has no analysis keywords -> must stay analyst, not interaction.
    assert orch._select_profile(state, chat_id="c1", user_input="the 2024 one") == "analyst"
```

- [ ] **Step 2: Run, expect fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_mode_continuity.py -q`
Expected: FAIL — `Orchestrator` has no `_select_profile`.

- [ ] **Step 3: Add the router + profile registry to `Orchestrator.__init__`**

In `src/harness/orchestrator.py`, near the other service construction in `__init__` (after `self.doctor_runner = ...`, ~line 290), add:

```python
from harness.services.mode_router import ModeRouter
from harness.services.prompt_profiles import PromptProfileRegistry

        self.mode_router = ModeRouter(telemetry=self.telemetry)
        self.prompt_profiles = PromptProfileRegistry(
            Path(__file__).resolve().parent / "prompts",
            tool_registry=self.tool_registry,
        )
```

(Imports go at module top with the other `harness.services` imports; shown here inline for locality.)

- [ ] **Step 4: Implement `_select_profile` (router + continuity + in-place write-back)**

Add this method to `Orchestrator` (near `run_agentic_turn`):

```python
    def _select_profile(self, state: RunStateRecord, *, chat_id: str, user_input: str) -> str:
        """Pick the prompt profile for this turn and persist it on `state` in place.

        Routing is keyword-based on the user text. When the text is ambiguous
        the router returns 'interaction'; in that case we keep the prior
        non-interaction profile (continuity for clarification / follow-ups).
        The chosen profile is written back into the *same* RunStateRecord
        object (not a model_copy) so the long-lived TUI state stays correct.
        """
        routed = self.mode_router.route(user_input).mode
        prior = state.active_agent_mode
        if routed == "interaction" and prior and prior != "interaction":
            chosen = prior
        else:
            chosen = routed
        state.active_agent_mode = chosen
        return chosen
```

- [ ] **Step 5: Run, expect pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_mode_continuity.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: L3 _select_profile with in-place active_agent_mode write-back (continuity fix)"
```

---

### Task 6: Wire orchestrator to route internally; drop `requested_mode`/`prompt_provider`

**Files:**
- Modify: `src/harness/orchestrator.py` (`run_agentic_turn`, `run_turn`, `resume_with_clarification`, handoff block)
- Modify: `src/app/session.py`
- Test: `tests/harness/test_agentic_turn.py`, `tests/app/test_app_session_async.py`

- [ ] **Step 1: Update `run_agentic_turn` signature and internals**

In `src/harness/orchestrator.py`:

Change the signature (remove `requested_mode` and `prompt_provider`):

```python
    async def run_agentic_turn(
        self,
        state: RunStateRecord,
        *,
        workspace_dir: Path,
        chat_id: str,
        user_input: str,
        max_iterations: int = 4,
    ) -> AsyncIterator[HarnessEvent]:
```

Replace the opening mode block (current lines ~1458-1479):

```python
        active_mode = self._select_profile(state, chat_id=chat_id, user_input=user_input)
        sticky_flow = self._get_flow(chat_id)
        if (
            sticky_flow is not None
            and not sticky_flow.is_terminal()
            and active_mode != "analyst"
        ):
            yield ModeHandoffAccepted(
                ts=datetime.now(UTC), workspace_id=state.workspace_id,
                chat_id=chat_id, run_id=state.run_id,
                from_mode=active_mode, to_mode="analyst",
                reason="analysis_flow_sticky",
            )
            _log.info(
                "run_agentic_turn sticky_override chat_id=%s routed=%s -> analyst phase=%s",
                chat_id, active_mode, sticky_flow.phase,
            )
            active_mode = "analyst"
            state.active_agent_mode = "analyst"
        if active_mode == "analyst":
            self._ensure_inspecting_flow(state, chat_id, user_input)
        prompt_text = self.prompt_profiles.load(active_mode).prompt_text
```

- [ ] **Step 2: Fix the mid-turn handoff block**

Replace current lines ~1614-1616 (`prompt_provider(handoff_target)` + `model_copy`):

```python
                active_mode = handoff_target
                prompt_text = self.prompt_profiles.load(handoff_target).prompt_text
                state.active_agent_mode = handoff_target
```

- [ ] **Step 3: Fix the log line that referenced `requested_mode`**

Current ~line 1548-1549: change `requested_mode=%s` / `requested_mode` to `routed=%s` / `active_mode`.

- [ ] **Step 4: Update `resume_with_clarification`**

In `src/harness/orchestrator.py` (~2486): `run_turn(...)` no longer takes `requested_mode`. The cleared state already carries `active_agent_mode` (continuity anchor). Change:

```python
        cleared = state.model_copy(update={"state": RunState.CLARIFYING, "pending_clarification_id": None})
        cleared.active_agent_mode = state.active_agent_mode
        async for ev in self.run_turn(
            cleared, workspace_dir=workspace_dir, chat_id=state.run_id,
            user_input=clarification_text,
        ):
            yield ev
```

- [ ] **Step 5: Update `run_turn` to stop requiring `requested_mode`**

In `run_turn` (~2024-2038): keep the keyword-only param but make it optional and default to the state's profile (it is an internal helper still called by `run_agentic_turn` with `requested_mode=active_mode`). Change line ~2031 to `requested_mode: str | None = None,` and line ~2038 stays `active_mode = requested_mode or state.active_agent_mode`. The `run_agentic_turn` inner `self.run_turn(... requested_mode=active_mode ...)` call is unchanged (internal).

- [ ] **Step 6: Update `AppSession.run_user_turn`**

In `src/app/session.py`: delete `from app.agents.prompt_packages import PromptPackageRegistry` and `from app.agents.router import AgentModeRouter`. Remove `mode_router` and `prompt_registry` constructor params and their attribute assignments. Replace the body of `run_user_turn`'s turn section:

```python
            with bind_turn(turn_id):
                self.telemetry.emit(Layer.APP, EventKind.TURN_START, payload={"input_chars": len(user_text)})
                async for h_ev in self.orchestrator.run_agentic_turn(
                    state, workspace_dir=workspace_dir, chat_id=chat_id, user_input=user_text,
                ):
                    yield to_app_event(h_ev)
                self.telemetry.emit(Layer.APP, EventKind.TURN_END, payload={"chat_id": chat_id})
```

Remove the now-unused `mode_router`/`prompt_registry` constructor kwargs from `__init__` and their docstrings. (`run_user_turn` public signature is unchanged.)

- [ ] **Step 7: Update `tests/app/test_app_session_async.py`**

Its `FakeOrchestrator.run_agentic_turn` declares `requested_mode`/`prompt_provider`. Change its signature to `async def run_agentic_turn(self, state, *, workspace_dir, chat_id, user_input, max_iterations=4):` and delete the `prompt_provider(requested_mode)` call line and any `requested_mode=` usage; default the recorded mode to `state.active_agent_mode`.

- [ ] **Step 8: Update `tests/harness/test_agentic_turn.py`**

Replace every `run_agentic_turn(... requested_mode=..., prompt_provider=...)` call with the reduced kwargs. Where a test needs a starting profile, set `state.active_agent_mode` (e.g. `RunStateRecord(..., active_agent_mode="analyst")`) instead of passing `requested_mode`. Replace any `prompt_provider=lambda m: "..."` by relying on the real `PromptProfileRegistry` (tests use the orchestrator's own).

- [ ] **Step 9: Run the focused suites**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_agentic_turn.py tests/app/test_app_session_async.py tests/harness/test_analysis_flow.py tests/harness/test_analysis_flow_sticky.py tests/harness/test_approval_pending_hybrid.py tests/harness/test_force_plan_tool_call.py -q
```

Expected: all pass (the analysis-flow sticky/approval tests must stay green — they exercise the same mode block).

- [ ] **Step 10: Full suite**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest -q 2>&1 | tail -n 5`
Expected: equal to baseline minus the (now relocated) prompt-package tests handled in Task 7; no new failures other than known prompt-package import errors fixed next.

- [ ] **Step 11: Commit**

```bash
git add -A && git commit -m "refactor: orchestrator routes internally; drop requested_mode/prompt_provider plumbing"
```

---

### Task 7: Relocate old prompt-package/router tests; purge `app.agents` test imports

**Files:**
- Delete/relocate: `tests/app/agents/test_prompt_packages.py` (and any `tests/app/agents/` router test)
- Modify: any test importing `app.agents.*`

- [ ] **Step 1: Find the stragglers**

Run: `rg -ln "app\.agents" tests`
Expected: a small list (e.g. `tests/app/agents/test_prompt_packages.py`, possibly `tests/app/test_app_session_async.py` already handled).

- [ ] **Step 2: Relocate the prompt-package test**

```bash
git mv tests/app/agents/test_prompt_packages.py tests/harness/test_prompt_profiles_legacy.py
rmdir tests/app/agents 2>/dev/null || true
```

In `tests/harness/test_prompt_profiles_legacy.py`: replace `from app.agents.prompt_packages import PromptPackageRegistry` with `from harness.services.prompt_profiles import PromptProfileRegistry`, replace the class name usages, and construct it with `Path("src/harness/prompts")` + an `Orchestrator(app_root=tmp_path).tool_registry`. Replace any `command_registry=` kwarg with `tool_registry=`.

- [ ] **Step 3: Repoint any remaining `app.agents` test imports**

For each remaining file from Step 1, replace `app.agents.router`→`harness.services.mode_router` (`AgentModeRouter`→`ModeRouter`) and `app.agents.prompt_packages`→`harness.services.prompt_profiles` (`PromptPackageRegistry`→`PromptProfileRegistry`).

- [ ] **Step 4: Verify no `app.agents` references remain**

Run: `rg -n "app\.agents" src tests`
Expected: **no output**.

- [ ] **Step 5: Run, expect pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_prompt_profiles_legacy.py tests/app -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "test: relocate prompt-profile/router tests off app.agents"
```

---

### Task 8: Doctor narration → Layer 3 (consolidate into DoctorRunner)

**Files:**
- Modify: `src/harness/services/doctor.py` (`DoctorRunner.run`, after `DoctorReportReady` ~line 542)
- Modify: `src/app/session.py` (delete doctor-narration logic + `runtime.types` import)
- Test: `tests/harness/test_doctor_narration_l3.py`

- [ ] **Step 1: Write the failing test**

Create `tests/harness/test_doctor_narration_l3.py`:

```python
from harness.events import DoctorApprovalRequested, DoctorNarrationReady, DoctorReportReady
from harness.orchestrator import Orchestrator
from harness.control import RunStateRecord


async def test_doctor_command_emits_narration_and_approval_from_l3(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    await orch.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="interaction")

    events = [
        ev async for ev in orch.handle_direct_command(
            state, command="doctor", arguments={"chat_id": "c1"},
        )
    ]
    kinds = [type(ev).__name__ for ev in events]
    assert "DoctorReportReady" in kinds
    # Narration + approval now originate in L3, after the report:
    assert "DoctorNarrationReady" in kinds
    assert "DoctorApprovalRequested" in kinds
    assert kinds.index("DoctorReportReady") < kinds.index("DoctorNarrationReady")
```

- [ ] **Step 2: Run, expect fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_doctor_narration_l3.py -q`
Expected: FAIL — no `DoctorNarrationReady`/`DoctorApprovalRequested` emitted by L3 (currently AppSession synthesizes them).

- [ ] **Step 3: Add narration + approval emission to `DoctorRunner.run`**

In `src/harness/services/doctor.py`, after the `yield DoctorReportReady(...)` (~line 542), add a finalizer that ports the AppSession logic. Add these imports to the existing `from harness.events import (...)` line: `DoctorNarrationReady, DoctorApprovalRequested, DoctorActionsApplied`. Add a module constant for the prompt path and these methods/calls:

```python
from pathlib import Path as _Path

_DOCTOR_NARRATOR_PROMPT = _Path(__file__).resolve().parents[2] / "harness" / "prompts" / "doctor_narrator.md"
```

Immediately after the `DoctorReportReady` yield in `run(...)`:

```python
        async for nev in self._narrate_and_request_approval(report_id, chat_id, workspace_id):
            yield nev
```

Add (port of `AppSession._stream_doctor_narration_and_approval` + `_render_doctor_narration` + `_fallback_doctor_narration` + `_collect_tmp_actions`, using `self.persistence` and `self.runtime`):

```python
    def _collect_tmp_actions(self, report_id: str) -> list[dict]:
        if self.persistence is None:
            return []
        try:
            rows = self.persistence.db.list_records("tmp_actions")
        except Exception:
            return []
        return [r for r in rows if r.get("doctor_report_id") == report_id]

    @staticmethod
    def _fallback_narration(findings: list[dict], action_summaries: list[str]) -> str:
        lines = [f"Doctor sweep produced {len(findings)} finding(s)."]
        for f in findings:
            lines.append(f"- [{f['severity']}] {f['summary']}")
        if action_summaries:
            lines.append("Proposed cleanup:")
            lines.extend(f"- {s}" for s in action_summaries)
        else:
            lines.append("No cleanup actions to apply.")
        lines.append("Apply all proposed actions? (yes / no)")
        return "\n".join(lines)

    async def _render_narration(self, findings: list[dict], action_summaries: list[str]) -> str:
        if not self.runtime:
            return self._fallback_narration(findings, action_summaries)
        try:
            template = _DOCTOR_NARRATOR_PROMPT.read_text()
        except Exception:
            return self._fallback_narration(findings, action_summaries)
        import json as _json
        from uuid import uuid4 as _uuid4
        prompt = template.format(
            findings_json=_json.dumps(findings, indent=2),
            actions_text="\n".join(action_summaries) or "(none)",
        )
        request = RuntimeRequest(
            messages=[
                RuntimeMessage(role="system", content=prompt),
                RuntimeMessage(role="user", content="Produce the narration now."),
            ],
            max_completion_tokens=320,
            request_id=f"req_doctor_{_uuid4().hex[:8]}",
        )
        chunks: list[str] = []
        try:
            async for ev in self.runtime.stream(request):
                if getattr(ev, "type", None) == "text_delta":
                    chunks.append(getattr(ev, "text", "") or "")
        except Exception:
            return self._fallback_narration(findings, action_summaries)
        return "".join(chunks).strip() or self._fallback_narration(findings, action_summaries)

    async def _narrate_and_request_approval(self, report_id, chat_id, workspace_id):
        from datetime import UTC, datetime
        records = self._collect_tmp_actions(report_id)
        proposed = [r for r in records if not r.get("applied") and r.get("action") != "kept_temporarily"]
        summaries = [
            f"{r.get('action')}: {r.get('item_path')}"
            + (f" -> {r['destination_path']}" if r.get("destination_path") else "")
            for r in proposed
        ]
        base = dict(ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=None)
        findings_payload = [
            {"category": f.get("category"), "severity": f.get("severity"),
             "summary": f.get("summary"), "details": f.get("details")}
            for f in (self._last_findings or [])
        ]
        if not proposed:
            yield DoctorNarrationReady(**base, report_id=report_id,
                narration_text="Doctor sweep clean: no cleanup needed.", action_summaries=[])
            yield DoctorActionsApplied(**base, report_id=report_id,
                applied_count=0, skipped_count=0, details=[])
            return
        narration = await self._render_narration(findings_payload, summaries)
        yield DoctorNarrationReady(**base, report_id=report_id,
            narration_text=narration, action_summaries=summaries)
        yield DoctorApprovalRequested(**base, report_id=report_id,
            question="Apply all proposed actions? (yes / no)", action_count=len(proposed))
```

In `DoctorRunner.run(...)`, before the final report yield, capture findings for `_last_findings` (set `self._last_findings = <the findings list already assembled in run>`; initialize `self._last_findings = []` in `__init__`).

- [ ] **Step 4: Run, expect pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_doctor_narration_l3.py -q`
Expected: PASS.

- [ ] **Step 5: Strip doctor-narration logic from `AppSession`**

In `src/app/session.py`:
- Delete `_stream_doctor_narration_and_approval`, `handle_doctor_approval`'s narration coupling stays (it is a plain passthrough — keep it), `_collect_tmp_actions`, `_render_doctor_narration`, `_fallback_doctor_narration`, and `_DOCTOR_PROMPT_PATH`.
- Simplify `handle_direct_command` to a pure passthrough (remove the `command == "doctor"` accumulation + the trailing `_stream_doctor_narration_and_approval` call):

```python
    async def handle_direct_command(
        self, state: RunStateRecord, *, command: str, arguments: dict[str, Any],
    ) -> AsyncIterator[AppEvent]:
        async for h_ev in self.orchestrator.handle_direct_command(
            state, command=command, arguments=arguments,
        ):
            yield to_app_event(h_ev)
```

- Delete `from runtime.types import RuntimeMessage, RuntimeRequest` and the now-unused `import json`, `Path` (keep `Path` only if still used elsewhere — verify), `DoctorActionsApplied/DoctorApprovalRequested/DoctorNarrationReady`/`AppDoctor*` imports that are no longer referenced. Keep `handle_doctor_approval` (still a real passthrough to `apply_doctor_actions`).

- [ ] **Step 6: Verify no `runtime` import in `src/app`**

Run: `rg -n "from runtime|import runtime" src/app`
Expected: **no output**.

- [ ] **Step 7: Run doctor + app suites**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_doctor.py tests/harness/test_doctor_runner.py tests/harness/test_doctor_narration_l3.py tests/app -q
```

Expected: all pass. (`tests/harness/test_doctor*.py` import the `harness.doctor`/`harness.doctor_runner` shims — still present until Task 11; fine here.)

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "refactor: doctor narration+approval emitted from L3 DoctorRunner; AppSession passthrough; fixes §3.3"
```

---

### Task 9: Create `src/harness/core/` and move the kernel modules

**Files:**
- Create: `src/harness/core/__init__.py`
- Move: 13 kernel modules into `src/harness/core/`

- [ ] **Step 1: Enumerate importers (baseline inventory)**

Run and save the output:

```bash
for m in state_machine factory command_registry validity approval analysis_flow db persistence app_store paths fingerprints workspace prompt_registry; do
  echo "== $m =="; rg -l "harness\.$m\b|from harness import .*\b$m\b" src tests
done
```

This is the exact repoint worklist for Step 4.

- [ ] **Step 2: Create the package and move files**

```bash
mkdir -p src/harness/core
: > src/harness/core/__init__.py
for m in state_machine factory command_registry validity approval analysis_flow db persistence app_store paths fingerprints workspace prompt_registry; do
  git mv src/harness/$m.py src/harness/core/$m.py
done
```

- [ ] **Step 3: Fix intra-core imports**

Inside the moved files, sibling imports like `from harness.db import ...` must become `from harness.core.db import ...`. Apply across `src/harness/core/`:

```bash
cd src/harness/core
for m in state_machine factory command_registry validity approval analysis_flow db persistence app_store paths fingerprints workspace prompt_registry; do
  perl -pi -e "s/\bfrom harness\.$m import/from harness.core.$m import/g; s/\bimport harness\.$m\b/import harness.core.$m/g" *.py
done
cd -
```

- [ ] **Step 4: Repoint all external importers**

Apply the same transformation across `src` and `tests` (excluding `src/harness/core` already done):

```bash
for m in state_machine factory command_registry validity approval analysis_flow db persistence app_store paths fingerprints workspace prompt_registry; do
  rg -l "harness\.$m\b" src tests | grep -v "src/harness/core/" | while read -r f; do
    perl -pi -e "s/\bfrom harness\.$m import/from harness.core.$m import/g; s/\bimport harness\.$m\b/import harness.core.$m/g" "$f"
  done
done
```

Then handle `from harness import X` style (rare): `rg -n "from harness import" src tests` and fix any that pull a moved name to `from harness.core.<m> import X`.

- [ ] **Step 5: Sanity import check**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run python -c "import harness.orchestrator, harness.core.db, harness.core.command_registry, harness.core.analysis_flow; print('ok')"
```

Expected: `ok`.

- [ ] **Step 6: Update `tests/harness/test_service_ownership.py`**

Adjust its expected module locations for the moved kernel files (`harness.core.*`). Run it:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_service_ownership.py -q
```

Expected: PASS.

- [ ] **Step 7: Full suite**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest -q 2>&1 | tail -n 5`
Expected: baseline-equivalent (no new failures).

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "refactor: move separable kernel into src/harness/core/"
```

---

### Task 10: Migrate latent services into `src/harness/services/`

**Files:**
- Move: `knowledge`, `knowledge_intents`, `chat`, `context`, `repair`, `provenance` → `services/*`; `workspace_async.py` → `services/workspace.py`
- Modify: `src/harness/services/__init__.py`

- [ ] **Step 1: Enumerate importers**

```bash
for m in knowledge knowledge_intents chat context repair provenance workspace_async; do
  echo "== $m =="; rg -l "harness\.$m\b" src tests
done
```

- [ ] **Step 2: Move files**

```bash
for m in knowledge knowledge_intents chat context repair provenance; do
  git mv src/harness/$m.py src/harness/services/$m.py
done
git mv src/harness/workspace_async.py src/harness/services/workspace.py
```

- [ ] **Step 3: Repoint importers**

```bash
for m in knowledge knowledge_intents chat context repair provenance; do
  rg -l "harness\.$m\b" src tests | grep -v "src/harness/services/" | while read -r f; do
    perl -pi -e "s/\bfrom harness\.$m import/from harness.services.$m import/g; s/\bimport harness\.$m\b/import harness.services.$m/g" "$f"
  done
done
rg -l "harness\.workspace_async\b" src tests | while read -r f; do
  perl -pi -e "s/\bfrom harness\.workspace_async import/from harness.services.workspace import/g; s/\bimport harness\.workspace_async\b/import harness.services.workspace/g" "$f"
done
```

Fix intra-services sibling imports the same way (e.g. `services/chat.py` importing `harness.context` → `harness.services.context`; `services/knowledge.py` importing moved core like `harness.persistence` → `harness.core.persistence` if not already done in Task 9 Step 4 — re-run the Task 9 Step 4 codemod scoped to `src/harness/services` if needed).

- [ ] **Step 4: Update `src/harness/services/__init__.py`**

Append the new exports (keep existing ones):

```python
from harness.services.chat import *  # noqa: F401,F403  (re-export public chat API as before)
from harness.services.context import *  # noqa: F401,F403
from harness.services.knowledge import *  # noqa: F401,F403
```

(Only add wildcard re-exports if `__init__` previously exposed these names; otherwise add the specific symbols that other modules import. Check `rg "from harness.services import" src tests` and ensure those names resolve.)

- [ ] **Step 5: Import sanity check**

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run python -c "import harness.orchestrator, harness.services.chat, harness.services.knowledge, harness.services.context, harness.services.workspace; print('ok')"
```

Expected: `ok`.

- [ ] **Step 6: Full suite**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest -q 2>&1 | tail -n 5`
Expected: baseline-equivalent.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor: migrate latent services (knowledge/chat/context/repair/provenance/workspace) into harness.services"
```

---

### Task 11: Delete re-export shims

**Files:**
- Delete: `src/harness/commands.py`, `src/harness/doctor.py`, `src/harness/doctor_runner.py`

- [ ] **Step 1: Repoint shim importers to canonical owners**

```bash
rg -l "harness\.commands\b" src tests | grep -v "src/harness/commands/" | while read -r f; do
  perl -pi -e "s/\bfrom harness\.commands import/from harness.core.command_registry import/g" "$f"; done
rg -l "harness\.doctor\b|harness\.doctor_runner\b" src tests | while read -r f; do
  perl -pi -e "s/\bfrom harness\.doctor_runner import/from harness.services.doctor import/g; s/\bfrom harness\.doctor import/from harness.services.doctor import/g" "$f"; done
```

(`HarnessCommandRegistry` now lives at `harness.core.command_registry` after Task 9; `Doctor`/`DoctorRunner`/`PHASES`/`PROMOTION_TARGETS`/`TmpCleanupBlocked` at `harness.services.doctor`.)

- [ ] **Step 2: Delete the shims**

```bash
git rm src/harness/commands.py src/harness/doctor.py src/harness/doctor_runner.py
```

- [ ] **Step 3: Verify no references remain**

Run: `rg -n "from harness\.commands import|from harness\.doctor import|from harness\.doctor_runner import" src tests`
Expected: **no output**.

- [ ] **Step 4: Update `test_service_ownership.py`**

Remove shim-location assertions; assert canonical owners (`harness.services.doctor`, `harness.core.command_registry`).

- [ ] **Step 5: Full suite**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest -q 2>&1 | tail -n 5`
Expected: baseline-equivalent.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor: delete harness.commands/doctor/doctor_runner re-export shims"
```

---

### Task 12: Documentation updates (no code)

**Files:** `docs/superpowers/specs/2026-05-11-dataharness-comprehensive-app-spec.md`, `docs/app/services.md`, `docs/app/tools-vs-commands.md`, `docs/app/doctor-behaviour.md`, `Lessons.md`, `CODEMAP.md`

- [ ] **Step 1: Canonical spec amendments**

In `2026-05-11-...-app-spec.md`: §3.3/§4 remove Layer 4b (Layer 4 = TUI 4a + AppSession facade); §7 add Layer 3 ownership of prompt profiles + intent routing + the Harness Core (kernel) and the three surfaces; §9 delete 9.2/9.4/9.5 Layer-4b content and rewrite 9.1/9.3 so AppSession no longer owns routing/prompt selection; §15 reword "no agent bypasses harness ownership" to the profile/Core model.

- [ ] **Step 2: `docs/app/services.md`**

Add the Harness Core (kernel) section + boundary. Add source owners: `services/mode_router.py`, `services/prompt_profiles.py`, `services/knowledge.py`, `services/knowledge_intents.py`, `services/chat.py`, `services/context.py`, `services/repair.py`, `services/provenance.py`, `services/workspace.py`. Correct the "Analysis flow" entry to point at `harness.core.analysis_flow` (Core, not a service module). Prune the deleted shims.

- [ ] **Step 3: `docs/app/tools-vs-commands.md`**

Add the Harness Core (kernel) note; state prompt profiles + mode router are Layer 3 services (not tools/commands).

- [ ] **Step 4: `docs/app/doctor-behaviour.md` anomaly note**

Add: LLM doctor narration and the `DoctorNarrationReady`/`DoctorApprovalRequested` event pair are off-canonical additions over the spec's required tmp-review approval gate, now emitted from Layer 3 `DoctorRunner`, flagged for future review.

- [ ] **Step 5: `Lessons.md`**

In the "Routing And Prompt Packages" section: rewrite the L4-`AgentModeRouter` lessons — routing/prompt-profile selection is Layer 3 (`ModeRouter`/`PromptProfileRegistry`), `Orchestrator._select_profile` writes `active_agent_mode` back into the live `RunStateRecord` (closing the long-standing "loop never writes back" bug). Add a "Harness Core" lesson: separable kernel in `src/harness/core/`; shared contracts (`control/events/exceptions/status`) + `orchestrator.py` stay at `src/harness/` root; services live under `src/harness/services/`. Append per the user's workflow (end of file, only after code verified).

- [ ] **Step 6: `CODEMAP.md`**

Update the four tracked relationship types for: new `harness.services.mode_router`/`prompt_profiles`; `src/harness/core/*` moves; `src/harness/services/*` migrations; deleted shims; `app.session` no longer importing `app.agents`/`runtime`; `DoctorRunner` new narration methods.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "docs: spec/services/tools/doctor/Lessons/CODEMAP for L3 profiles + Harness Core"
```

---

### Task 13: Final verification

**Files:** none

- [ ] **Step 1: Stale-reference scan**

Run:

```bash
rg -n "app\.agents|AgentModeRouter|PromptPackageRegistry|prompt_provider|requested_mode=" src tests
rg -n "from runtime|import runtime" src/app
rg -n "from harness\.(commands|doctor|doctor_runner) import|harness\.workspace_async" src tests
```

Expected: no `app.agents`; no `runtime` in `src/app`; no shim/`workspace_async` imports. `requested_mode` may remain only as the internal optional `run_turn` kwarg (not as a caller `requested_mode=` outside `run_agentic_turn`'s internal `run_turn` call) — verify each remaining hit is that one internal call.

- [ ] **Step 2: Full suite**

Run: `UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest -q 2>&1 | tail -n 8`
Expected: passed count ≥ baseline (plus the new tests from Tasks 2,3,5,8). Only the known worker-sandbox timeout flake may differ; re-run it isolated if it appears (`tests/worker/test_executor.py::test_executor_blocks_dynamic_import_of_disallowed_package`).

- [ ] **Step 3: Spec acceptance checklist**

Verify against the spec's Acceptance section: `src/app/agents/` gone; no `runtime.*`/`app.agents` in `src/app`; orchestrator selects profile from text with no L4 param; `active_agent_mode` written back (continuity test green); persona prompts load from `src/harness/prompts/`; no re-export shims; `src/harness/core/` holds the kernel; docs updated. Note any gap.

- [ ] **Step 4: Final commit**

```bash
git add -A && git commit -m "chore: final verification for L3 profiles + Harness Core refactor" --allow-empty
```

- [ ] **Step 5: Handoff (do NOT merge)**

Report status to the user. The single squash-merge to `main` (per AGENTS.md) is a separate, explicitly-authorized step — do not perform it here.

---

## Self-Review

**Spec coverage:**
- Collapse Layer 4b → Tasks 2–7. ✓
- L3 routes from text, no override seam → Task 6 (signature drop), Task 5 (`_select_profile`). ✓
- Mode continuity / `active_agent_mode` write-back → Task 5 (TDD). ✓
- `src/app/agents/` removed; router/profiles→services, personas→`src/harness/prompts/`, dead `*Mode` deleted → Tasks 2,3,4,7. ✓
- Doctor narration → L3; §3.3 fixed; anomaly note → Task 8, Task 12 Step 4. ✓
- Harness Core folder; shared contracts stay at root → Task 9. ✓
- Latent services migrated; shims deleted → Tasks 10,11. ✓
- Hard move, no shims, `test_service_ownership` + CODEMAP updated → Tasks 9–12. ✓
- Canonical spec + services.md + tools-vs-commands + doctor-behaviour + Lessons + CODEMAP → Task 12. ✓
- Layer 4 wiring (TUI unchanged; session.py only) → Task 6 Step 6, verified Task 13 Step 1. ✓
- Tests relocated/updated incl. `test_app_session_async.py` → Tasks 6,7. ✓

**Placeholder scan:** No TBD/TODO. Mass-repoint steps use exact deterministic `git mv` + `perl -pi` codemods + import-sanity + full-suite gates (concrete, not hand-waved). The one behavioral change (mode continuity) has full failing-test-first code.

**Type consistency:** `ModeRouter`/`ProfileDecision`, `PromptProfileRegistry`/`PromptPackage`, `Orchestrator._select_profile`, `DoctorRunner._narrate_and_request_approval` used consistently across tasks. `run_agentic_turn` reduced signature used identically in Tasks 6, 7, 8 tests and `session.py`.

**Risk note:** Tasks 9–10 are high-churn codemods; the import-sanity (`python -c import ...`) + full-suite gate after each is the safety net. If a codemod misfires, `git diff` the unexpected files before committing.
