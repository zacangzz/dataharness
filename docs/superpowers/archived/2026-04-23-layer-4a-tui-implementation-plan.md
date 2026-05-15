# Layer 4a TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the TUI sublayer that renders harness state, workspace control, clarification, approval, artifacts, provenance, and review controls as an operable local application.

**Architecture:** Implement the UI under `src/app/tui/` as a thin renderer over harness-owned state and commands. The TUI must stay free of prompt logic: it exposes application state, workspace switching, direct harness commands, review controls, and structured process visibility, but it never owns routing, memory policy, or maintenance semantics. Packaging belongs to the project root build flow: build scripts live in `scripts/` and package output is emitted to `dist/`.

**Tech Stack:** Python 3.12, `pydantic`, `textual`, `pytest`, `pytest-asyncio`

---

## File Structure

**Create:**
- `src/app/__init__.py`
- `src/app/tui/__init__.py`
- `src/app/tui/models.py`
- `src/app/tui/controller.py`
- `src/app/tui/app.py`
- `src/app/tui/screens.py`
- `src/cli.py`
- `scripts/build_app.sh`
- `tests/app/tui/test_controller.py`
- `tests/app/tui/test_textual_app.py`

### Task 1: Define TUI View Models And Harness Controller Boundary

**Files:**
- Create: `src/app/__init__.py`
- Create: `src/app/tui/__init__.py`
- Create: `src/app/tui/models.py`
- Create: `src/app/tui/controller.py`
- Test: `tests/app/tui/test_controller.py`

- [ ] **Step 1: Write the failing test**

```python
from app.tui.controller import HarnessViewController
from app.tui.models import WorkspaceView


def test_controller_exposes_workspace_status_and_controls() -> None:
    controller = HarnessViewController()
    view = controller.initial_view()
    assert isinstance(view.workspace, WorkspaceView)
    assert "doctor" in view.available_commands
    assert "cancel_run" in view.available_commands
    assert view.workspace_status == "ready"
    assert view.available_workspaces == ["w_0001"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/tui/test_controller.py -q`
Expected: FAIL with `ModuleNotFoundError` for `app`

- [ ] **Step 3: Write minimal implementation**

```python
# src/app/tui/models.py
from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceView(BaseModel):
    workspace_id: str
    run_state: str
    active_mode: str


class AppView(BaseModel):
    workspace: WorkspaceView
    workspace_status: str = "ready"
    available_workspaces: list[str] = Field(default_factory=list)
    available_commands: list[str] = Field(default_factory=list)
    doctor_warning_count: int = 0
    process_events: list[str] = Field(default_factory=list)
```

```python
# src/app/tui/controller.py
from __future__ import annotations

from app.tui.models import AppView, WorkspaceView


class HarnessViewController:
    def initial_view(self) -> AppView:
        return AppView(
            workspace=WorkspaceView(workspace_id="w_0001", run_state="idle", active_mode="interaction"),
            workspace_status="ready",
            available_workspaces=["w_0001"],
            available_commands=["doctor", "compact_context", "cancel_run", "retry_step", "memory_review"],
            process_events=["harness idle"],
        )
```

```python
# src/app/__init__.py
"""Application layer packages."""
```

```python
# src/app/tui/__init__.py
from app.tui.controller import HarnessViewController

__all__ = ["HarnessViewController"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/app/tui/test_controller.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/__init__.py src/app/tui/__init__.py src/app/tui/models.py src/app/tui/controller.py tests/app/tui/test_controller.py
git commit -m "feat: add tui controller boundary"
```

### Task 2: Build The Textual App Shell With Behavioral Surface Bindings

**Files:**
- Create: `src/app/tui/app.py`
- Create: `src/app/tui/widgets.py`
- Create: `src/app/tui/screens.py`
- Test: `tests/app/tui/test_textual_app.py`

This task MUST verify each surface renders real session data, not just widget-id presence. Spec §7.4 requires distinct, functional surfaces for: workspace, conversation, plan, step status, artifacts, context/memory, doctor/validity warnings, failure, provenance.

- [ ] **Step 1: Write the failing behavioral tests**

```python
import pytest
from pathlib import Path

from app.session import AppTurnResult, DataAnalysisAppSession
from app.tui.app import DataHarnessApp
from harness.control import RunStateRecord


class FakeSession:
    def __init__(self, result: AppTurnResult) -> None:
        self._result = result
        self.commands: list[tuple[str, dict]] = []

    def handle_user_turn(self, *, workspace_dir, state, user_text):
        return self._result

    def handle_direct_command(self, state, command, **arguments):
        self.commands.append((command, arguments))
        return {"command": command, "arguments": arguments, "owned_by": "harness"}


def make_result(**overrides) -> AppTurnResult:
    base = dict(
        workspace_id="w_0001",
        run_id="r_1",
        active_mode="analyst",
        assistant_text="Attrition is 12%.",
        process_events=["reload_context", "route_agent_mode", "build_prompt_package", "runtime_complete"],
        artifacts=["artifacts/tmp/r_1/s_1/output.csv"],
        plan={"id": "p_1", "goal": "Compute attrition", "steps": [{"id": "s_1", "step_order": 1, "purpose": "Aggregate", "status": "completed"}]},
        step_contract=None,
        requires_approval=False,
        clarification_question=None,
        failure=None,
        validity_warnings=[],
        doctor_recommendations=[],
        lineage_refs=[{"artifact": "artifacts/tmp/r_1/s_1/output.csv", "fingerprint": "abc", "validity": "ok"}],
    )
    base.update(overrides)
    return AppTurnResult(**base)


@pytest.mark.asyncio
async def test_workspace_bar_renders_active_workspace_run_state_and_mode() -> None:
    app = DataHarnessApp(session=FakeSession(make_result()))
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one("#workspace_bar")
        text = bar.render_str()
        assert "w_0001" in text
        assert "analyst" in text


@pytest.mark.asyncio
async def test_conversation_pane_appends_assistant_text_after_turn() -> None:
    app = DataHarnessApp(session=FakeSession(make_result(assistant_text="Hello back.")))
    async with app.run_test() as pilot:
        await app.submit_user_text("hi")
        await pilot.pause()
        pane = app.query_one("#conversation")
        assert "Hello back." in pane.render_str()


@pytest.mark.asyncio
async def test_plan_pane_renders_plan_steps_with_status() -> None:
    app = DataHarnessApp(session=FakeSession(make_result()))
    async with app.run_test() as pilot:
        await app.submit_user_text("compute")
        await pilot.pause()
        plan_pane = app.query_one("#plan")
        text = plan_pane.render_str()
        assert "Aggregate" in text
        assert "completed" in text


@pytest.mark.asyncio
async def test_artifacts_pane_lists_artifact_refs() -> None:
    app = DataHarnessApp(session=FakeSession(make_result()))
    async with app.run_test() as pilot:
        await app.submit_user_text("x")
        await pilot.pause()
        artifacts = app.query_one("#artifacts")
        assert "output.csv" in artifacts.render_str()


@pytest.mark.asyncio
async def test_doctor_pane_renders_validity_warnings_and_recommendations() -> None:
    result = make_result(
        validity_warnings=[{"path": "data/in.csv", "state": "changed"}],
        doctor_recommendations=["Rerun step s_1 — source data changed"],
    )
    app = DataHarnessApp(session=FakeSession(result))
    async with app.run_test() as pilot:
        await app.submit_user_text("doctor")
        await pilot.pause()
        doctor_pane = app.query_one("#doctor")
        text = doctor_pane.render_str()
        assert "changed" in text
        assert "Rerun step s_1" in text


@pytest.mark.asyncio
async def test_failure_pane_shows_failure_kind_and_offered_actions() -> None:
    result = make_result(
        assistant_text="",
        failure={"failure_kind": "python_exception", "failure_summary": "ZeroDivisionError", "offered_actions": ["retry", "replan", "cancel"]},
    )
    app = DataHarnessApp(session=FakeSession(result))
    async with app.run_test() as pilot:
        await app.submit_user_text("compute")
        await pilot.pause()
        pane = app.query_one("#failure")
        text = pane.render_str()
        assert "python_exception" in text
        assert "ZeroDivisionError" in text
        assert "retry" in text


@pytest.mark.asyncio
async def test_provenance_pane_renders_lineage_for_active_answer() -> None:
    app = DataHarnessApp(session=FakeSession(make_result()))
    async with app.run_test() as pilot:
        await app.submit_user_text("compute")
        await pilot.pause()
        pane = app.query_one("#provenance")
        text = pane.render_str()
        assert "abc" in text
        assert "ok" in text


@pytest.mark.asyncio
async def test_status_pane_renders_recent_process_events_not_hardcoded_string() -> None:
    app = DataHarnessApp(session=FakeSession(make_result()))
    async with app.run_test() as pilot:
        await app.submit_user_text("compute")
        await pilot.pause()
        pane = app.query_one("#status")
        text = pane.render_str()
        assert "route_agent_mode" in text
        assert "runtime_complete" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/tui/test_textual_app.py -q`
Expected: FAIL — `DataHarnessApp` does not accept a `session` argument and panes do not bind to result fields.

- [ ] **Step 3: Implement bound widgets**

```python
# src/app/tui/widgets.py
from __future__ import annotations

from collections import deque

from textual.widget import Widget
from textual.widgets import Static


class WorkspaceBar(Static):
    def update_from(self, *, workspace_id: str, run_state: str, active_mode: str) -> None:
        self.update(f"workspace: {workspace_id} | state: {run_state} | mode: {active_mode}")


class ConversationPane(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._lines: list[str] = []

    def append_user(self, text: str) -> None:
        self._lines.append(f"> {text}")
        self.update("\n".join(self._lines))

    def append_assistant(self, text: str) -> None:
        if not text:
            return
        self._lines.append(text)
        self.update("\n".join(self._lines))


class PlanPane(Static):
    def render_plan(self, plan: dict | None) -> None:
        if plan is None:
            self.update("(no plan)")
            return
        steps = plan.get("steps", [])
        body = "\n".join(f"{step['step_order']}. {step['purpose']} [{step.get('status', 'pending')}]" for step in steps)
        self.update(f"goal: {plan.get('goal', '')}\n{body}")


class StepStatusPane(Static):
    def render_contract(self, contract: dict | None, requires_approval: bool) -> None:
        if contract is None:
            self.update("(no active step)")
            return
        suffix = "  [APPROVAL REQUIRED]" if requires_approval else ""
        self.update(f"step {contract.get('step_id')} -- inputs: {contract.get('declared_inputs')}{suffix}")


class ArtifactsPane(Static):
    def render_refs(self, refs: list[str]) -> None:
        self.update("\n".join(refs) if refs else "(no artifacts)")


class ContextMemoryPane(Static):
    def render_summary(self, *, preferences: dict, notes_count: int, doctor_warning_count: int) -> None:
        self.update(
            f"prefs: {len(preferences)} keys | notes: {notes_count} | doctor warnings: {doctor_warning_count}"
        )


class DoctorPane(Static):
    def render_doctor(self, *, validity_warnings: list[dict], recommendations: list[str]) -> None:
        warning_text = "\n".join(f"  {w['path']} -> {w['state']}" for w in validity_warnings) or "(no validity warnings)"
        rec_text = "\n".join(f"- {r}" for r in recommendations) or "(no recommendations)"
        self.update(f"VALIDITY:\n{warning_text}\n\nRECOMMENDATIONS:\n{rec_text}")


class FailurePane(Static):
    def render_failure(self, failure: dict | None) -> None:
        if failure is None:
            self.update("(no failure)")
            return
        actions = ", ".join(failure.get("offered_actions", []))
        self.update(
            f"FAILURE: {failure.get('failure_kind')}\n"
            f"summary: {failure.get('failure_summary')}\n"
            f"offered: {actions}"
        )


class ProvenancePane(Static):
    def render_lineage(self, lineage_refs: list[dict]) -> None:
        if not lineage_refs:
            self.update("(no lineage)")
            return
        body = "\n".join(
            f"{ref['artifact']} | fingerprint: {ref['fingerprint']} | validity: {ref['validity']}"
            for ref in lineage_refs
        )
        self.update(body)


class StatusPane(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._events: deque[str] = deque(maxlen=20)

    def append_events(self, events: list[str]) -> None:
        for event in events:
            self._events.append(event)
        self.update(" | ".join(self._events))
```

```python
# src/app/tui/app.py
from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input

from app.session import AppTurnResult, DataAnalysisAppSession
from app.tui.widgets import (
    ArtifactsPane,
    ContextMemoryPane,
    ConversationPane,
    DoctorPane,
    FailurePane,
    PlanPane,
    ProvenancePane,
    StatusPane,
    StepStatusPane,
    WorkspaceBar,
)
from harness.control import RunStateRecord


class DataHarnessApp(App[None]):
    TITLE = "DataHarness"

    def __init__(
        self,
        *,
        session: DataAnalysisAppSession | None = None,
        workspace_dir: Path | None = None,
        state: RunStateRecord | None = None,
    ) -> None:
        super().__init__()
        self._session = session or DataAnalysisAppSession()
        self._workspace_dir = workspace_dir or Path.cwd() / "workspaces" / "w_0001"
        self._state = state or RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
        self._latest_result: AppTurnResult | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            WorkspaceBar(id="workspace_bar"),
            ConversationPane(id="conversation"),
            PlanPane(id="plan"),
            StepStatusPane(id="step_status"),
            ArtifactsPane(id="artifacts"),
            ContextMemoryPane(id="memory"),
            DoctorPane(id="doctor"),
            FailurePane(id="failure"),
            ProvenancePane(id="provenance"),
            StatusPane(id="status"),
            Input(placeholder="Ask the data analyst...", id="user_input"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#workspace_bar", WorkspaceBar).update_from(
            workspace_id=self._state.workspace_id,
            run_state=str(self._state.state),
            active_mode=self._state.active_agent_mode,
        )

    async def submit_user_text(self, text: str) -> AppTurnResult:
        self.query_one("#conversation", ConversationPane).append_user(text)
        result = self._session.handle_user_turn(
            workspace_dir=self._workspace_dir,
            state=self._state,
            user_text=text,
        )
        self._render_result(result)
        return result

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        await self.submit_user_text(event.value)
        event.input.value = ""

    def _render_result(self, result: AppTurnResult) -> None:
        self._latest_result = result
        self.query_one("#conversation", ConversationPane).append_assistant(result.assistant_text)
        self.query_one("#plan", PlanPane).render_plan(result.plan)
        self.query_one("#step_status", StepStatusPane).render_contract(result.step_contract, result.requires_approval)
        self.query_one("#artifacts", ArtifactsPane).render_refs(result.artifacts)
        self.query_one("#doctor", DoctorPane).render_doctor(
            validity_warnings=result.validity_warnings,
            recommendations=result.doctor_recommendations,
        )
        self.query_one("#failure", FailurePane).render_failure(result.failure)
        self.query_one("#provenance", ProvenancePane).render_lineage(result.lineage_refs)
        self.query_one("#status", StatusPane).append_events(result.process_events)
        self.query_one("#workspace_bar", WorkspaceBar).update_from(
            workspace_id=result.workspace_id,
            run_state=self._state.state,
            active_mode=result.active_mode,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/app/tui/test_textual_app.py -q`
Expected: PASS — every surface renders real result data.

- [ ] **Step 5: Commit**

```bash
git add src/app/tui/app.py src/app/tui/widgets.py tests/app/tui/test_textual_app.py
git commit -m "feat: behavioral tui surfaces bound to session results"
```

### Task 3: Wire Clarification, Approval, And Direct Harness Commands End-To-End

**Files:**
- Modify: `src/app/tui/app.py`
- Modify: `src/app/tui/controller.py`
- Modify: `src/app/tui/screens.py`
- Test: `tests/app/tui/test_controller.py`
- Test: `tests/app/tui/test_screens.py`

Approval and clarification MUST be first-class screens that the app pushes when `requires_approval` or `clarification_question` is set on the result. Buttons MUST drive `session.resume_approved_step` / `session.resume_with_clarification` — not return synthetic dicts. Direct commands MUST go through `session.handle_direct_command`. Spec §7.5, §7.7.

- [ ] **Step 1: Write the failing tests**

```python
# tests/app/tui/test_controller.py
from pathlib import Path

import pytest

from app.session import DataAnalysisAppSession
from app.tui.controller import HarnessViewController
from harness.control import RunStateRecord


class FakeSession:
    def __init__(self) -> None:
        self.commands: list[tuple[str, dict]] = []
        self.resumes: list[dict] = []
        self.clarifications: list[str] = []

    def handle_direct_command(self, state, command, **arguments):
        self.commands.append((command, dict(arguments)))
        return {"command": command, "arguments": arguments, "owned_by": "harness", "workspace_id": state.workspace_id}

    def resume_approved_step(self, *, state, plan_payload, contract_payload, approval):
        self.resumes.append({"plan": plan_payload, "approval": approval})
        return {"workspace_id": state.workspace_id, "active_mode": state.active_agent_mode, "assistant_text": "done"}

    def resume_with_clarification(self, *, state, clarification_text):
        self.clarifications.append(clarification_text)
        return {"workspace_id": state.workspace_id, "active_mode": state.active_agent_mode, "assistant_text": "ack"}


def make_state() -> RunStateRecord:
    return RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")


def test_invoke_command_routes_through_session_for_every_required_control() -> None:
    session = FakeSession()
    controller = HarnessViewController(session=session)
    state = make_state()
    for command, args in [
        ("doctor", {"trigger": "manual"}),
        ("compact_context", {}),
        ("cancel_run", {"run_id": state.run_id}),
        ("revise_goal", {"goal": "compare attrition"}),
        ("stop_after_current_step", {"run_id": state.run_id}),
        ("rerun_step", {"step_id": "s_2"}),
        ("challenge_conclusion", {"result_id": "r-1"}),
        ("mark_result_trusted", {"result_id": "r-1"}),
        ("mark_result_invalidated", {"result_id": "r-1"}),
        ("inspect_artifact", {"path": "artifacts/tmp/x"}),
        ("memory_review", {"target": "notes"}),
        ("provenance_inspect", {"result_id": "r-1"}),
        ("switch_workspace", {"workspace_id": "w_0002"}),
    ]:
        controller.invoke_command(state, command, **args)
    assert {cmd for cmd, _ in session.commands} == {
        "doctor", "compact_context", "cancel_run", "revise_goal",
        "stop_after_current_step", "rerun_step", "challenge_conclusion",
        "mark_result_trusted", "mark_result_invalidated", "inspect_artifact",
        "memory_review", "provenance_inspect", "switch_workspace",
    }


def test_controller_resume_approved_step_calls_session() -> None:
    session = FakeSession()
    controller = HarnessViewController(session=session)
    state = make_state()
    controller.resume_approved_step(
        state=state,
        plan_payload={"id": "p_1"},
        contract_payload={"step_id": "s_1"},
        approval={"decision": "approved", "decided_by": "user"},
    )
    assert session.resumes == [{"plan": {"id": "p_1"}, "approval": {"decision": "approved", "decided_by": "user"}}]


def test_controller_resume_with_clarification_calls_session() -> None:
    session = FakeSession()
    controller = HarnessViewController(session=session)
    state = make_state()
    controller.resume_with_clarification(state=state, clarification_text="we mean voluntary leavers")
    assert session.clarifications == ["we mean voluntary leavers"]


def test_controller_does_not_return_synthetic_dicts_for_controls() -> None:
    # Regression: previous version returned hand-built dicts that never hit the harness.
    import inspect

    import app.tui.controller as controller_module

    source = inspect.getsource(controller_module)
    # No method may build a `{"workspace_id": ...}` literal as a fake response.
    assert 'return {"workspace_id":' not in source
    assert 'return {"goal":' not in source
    assert 'return {"step_id":' not in source
```

```python
# tests/app/tui/test_screens.py
import pytest

from app.session import AppTurnResult, DataAnalysisAppSession
from app.tui.app import DataHarnessApp


class CapturingSession:
    def __init__(self, first: AppTurnResult, second: AppTurnResult) -> None:
        self._first = first
        self._second = second
        self.resumed_with: dict | None = None
        self.clarified_with: str | None = None

    def handle_user_turn(self, *, workspace_dir, state, user_text):
        return self._first

    def resume_approved_step(self, *, state, plan_payload, contract_payload, approval):
        self.resumed_with = {"plan": plan_payload, "approval": approval}
        return {"workspace_id": state.workspace_id, "active_mode": state.active_agent_mode, "assistant_text": "done"}

    def resume_with_clarification(self, *, state, clarification_text):
        self.clarified_with = clarification_text
        return {"workspace_id": state.workspace_id, "active_mode": state.active_agent_mode, "assistant_text": "ack"}


def make_paused_result() -> AppTurnResult:
    return AppTurnResult(
        workspace_id="w_0001", run_id="r_1", active_mode="analyst",
        assistant_text="approval needed",
        process_events=["create_plan", "select_step", "generate_step_contract", "await_execution_approval"],
        artifacts=[], plan={"id": "p_1", "goal": "compute"}, step_contract={"step_id": "s_1"},
        requires_approval=True, clarification_question=None, failure=None,
        validity_warnings=[], doctor_recommendations=[], lineage_refs=[],
    )


def make_clarification_result() -> AppTurnResult:
    return AppTurnResult(
        workspace_id="w_0001", run_id="r_1", active_mode="interaction",
        assistant_text="",
        process_events=["request_clarification"],
        artifacts=[], plan=None, step_contract=None,
        requires_approval=False, clarification_question="By attrition do you mean voluntary leavers?",
        failure=None, validity_warnings=[], doctor_recommendations=[], lineage_refs=[],
    )


@pytest.mark.asyncio
async def test_approval_screen_pushed_when_requires_approval_true() -> None:
    second = make_paused_result()  # not used; kept for symmetry
    session = CapturingSession(make_paused_result(), second)
    app = DataHarnessApp(session=session)
    async with app.run_test() as pilot:
        await app.submit_user_text("compute")
        await pilot.pause()
        assert app.screen.id == "approval"


@pytest.mark.asyncio
async def test_approve_button_resumes_step_via_session() -> None:
    session = CapturingSession(make_paused_result(), make_paused_result())
    app = DataHarnessApp(session=session)
    async with app.run_test() as pilot:
        await app.submit_user_text("compute")
        await pilot.pause()
        await pilot.click("#approve")
        await pilot.pause()
        assert session.resumed_with is not None
        assert session.resumed_with["approval"]["decision"] == "approved"


@pytest.mark.asyncio
async def test_reject_button_records_rejected_approval_and_returns_to_conversation() -> None:
    session = CapturingSession(make_paused_result(), make_paused_result())
    app = DataHarnessApp(session=session)
    async with app.run_test() as pilot:
        await app.submit_user_text("compute")
        await pilot.pause()
        await pilot.click("#reject")
        await pilot.pause()
        assert app.screen.id != "approval"
        # Rejected approval still routes through session.resume_approved_step with rejected decision.
        assert session.resumed_with is not None
        assert session.resumed_with["approval"]["decision"] == "rejected"


@pytest.mark.asyncio
async def test_clarification_screen_pushed_when_clarification_question_present() -> None:
    session = CapturingSession(make_clarification_result(), make_clarification_result())
    app = DataHarnessApp(session=session)
    async with app.run_test() as pilot:
        await app.submit_user_text("rate")
        await pilot.pause()
        assert app.screen.id == "clarification"
        prompt = app.screen.query_one("#clarification_prompt")
        assert "voluntary leavers" in prompt.render_str()


@pytest.mark.asyncio
async def test_clarification_response_resumes_run_via_session() -> None:
    session = CapturingSession(make_clarification_result(), make_clarification_result())
    app = DataHarnessApp(session=session)
    async with app.run_test() as pilot:
        await app.submit_user_text("rate")
        await pilot.pause()
        await app.screen.submit_clarification("yes voluntary")
        await pilot.pause()
        assert session.clarified_with == "yes voluntary"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/app/tui/test_controller.py tests/app/tui/test_screens.py -q`
Expected: FAIL — controller still returns synthetic dicts; screens not wired.

- [ ] **Step 3: Implement controller routing through session**

```python
# src/app/tui/controller.py
from __future__ import annotations

from app.session import DataAnalysisAppSession
from app.tui.models import AppView, WorkspaceView
from harness.commands import HarnessCommandRouter
from harness.control import RunStateRecord


class HarnessViewController:
    def __init__(self, session: DataAnalysisAppSession | None = None) -> None:
        self._router = HarnessCommandRouter()
        self._session = session or DataAnalysisAppSession()

    def initial_view(self) -> AppView:
        return AppView(
            workspace=WorkspaceView(workspace_id="w_0001", run_state="idle", active_mode="interaction"),
            workspace_status="ready",
            available_workspaces=["w_0001"],
            available_commands=self._router.supported_commands(),
            process_events=["harness idle"],
        )

    def invoke_command(self, state: RunStateRecord, command: str, **arguments: object) -> dict[str, object]:
        # Validate via the router so unknown commands fail loudly before crossing the boundary.
        self._router.validate(command, arguments)
        return self._session.handle_direct_command(state, command, **arguments)

    def resume_approved_step(
        self,
        *,
        state: RunStateRecord,
        plan_payload: dict[str, object],
        contract_payload: dict[str, object],
        approval: dict[str, object],
    ) -> dict[str, object]:
        return self._session.resume_approved_step(
            state=state,
            plan_payload=plan_payload,
            contract_payload=contract_payload,
            approval=approval,
        )

    def resume_with_clarification(self, *, state: RunStateRecord, clarification_text: str) -> dict[str, object]:
        return self._session.resume_with_clarification(state=state, clarification_text=clarification_text)
```

The `HarnessCommandRouter.supported_commands()` set MUST include every required control: `doctor`, `compact_context`, `cancel_run`, `retry_step`, `revise_goal`, `stop_after_current_step`, `rerun_step`, `challenge_conclusion`, `mark_result_trusted`, `mark_result_invalidated`, `inspect_artifact`, `memory_review`, `provenance_inspect`, `switch_workspace`. (Layer 3 plan, Task 5.)

- [ ] **Step 4: Implement Approval + Clarification screens with action wiring**

```python
# src/app/tui/screens.py
from __future__ import annotations

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static


class ApprovalScreen(Screen[None]):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, *, plan: dict, step_contract: dict | None) -> None:
        super().__init__(name="approval")
        self.id = "approval"
        self._plan = plan
        self._step_contract = step_contract or {}

    def compose(self):
        yield Vertical(
            Static(f"Approve plan: {self._plan.get('goal', '(unknown goal)')}", id="approval_prompt"),
            Static(f"Step: {self._step_contract.get('step_id', '?')}", id="approval_step"),
            Button("Approve", id="approve"),
            Button("Reject", id="reject"),
            Button("Revise", id="revise"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        decision = {"approve": "approved", "reject": "rejected", "revise": "revise_requested"}[event.button.id]
        self.app.handle_approval_decision(self._plan, self._step_contract, decision)


class ClarificationScreen(Screen[None]):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, *, question: str) -> None:
        super().__init__(name="clarification")
        self.id = "clarification"
        self._question = question

    def compose(self):
        yield Vertical(
            Static(self._question, id="clarification_prompt"),
            Input(placeholder="Your clarification...", id="clarification_input"),
            Button("Submit", id="submit_clarification"),
        )

    async def submit_clarification(self, text: str) -> None:
        self.app.handle_clarification_response(text)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit_clarification":
            text = self.query_one("#clarification_input", Input).value
            await self.submit_clarification(text)
```

- [ ] **Step 5: Wire app to push screens and dispatch decisions to session**

Add to `src/app/tui/app.py`:

```python
from app.tui.screens import ApprovalScreen, ClarificationScreen


def _render_result(self, result: AppTurnResult) -> None:
    # ... existing widget updates ...
    if result.requires_approval and result.plan is not None:
        self.push_screen(ApprovalScreen(plan=result.plan, step_contract=result.step_contract))
        return
    if result.clarification_question:
        self.push_screen(ClarificationScreen(question=result.clarification_question))
        return


def handle_approval_decision(self, plan: dict, step_contract: dict, decision: str) -> None:
    approval = {"decision": decision, "decided_by": "user", "approval_kind": "code_execution"}
    if decision == "revise_requested":
        # Send back to harness to replan; treated as a direct command, not a resume.
        self._session.handle_direct_command(self._state, "revise_goal", plan_id=plan.get("id"))
        self.pop_screen()
        return
    result = self._session.resume_approved_step(
        state=self._state,
        plan_payload=plan,
        contract_payload=step_contract,
        approval=approval,
    )
    self.pop_screen()
    self._render_dict_result(result)


def handle_clarification_response(self, text: str) -> None:
    result = self._session.resume_with_clarification(state=self._state, clarification_text=text)
    self.pop_screen()
    self._render_dict_result(result)
```

`_render_dict_result` mirrors `_render_result` but accepts the harness-shaped dict that resume methods return.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/app/tui -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/app/tui/controller.py src/app/tui/screens.py src/app/tui/app.py tests/app/tui/test_controller.py tests/app/tui/test_screens.py
git commit -m "feat: wire tui approval clarification and controls to session"
```

### Task 4: Add CLI Entry Point Backed By A Harness Factory

**Files:**
- Create: `src/cli.py`
- Create: `scripts/build_app.sh`
- Modify: `src/app/tui/app.py` (verify no runtime imports)
- Test: `tests/app/tui/test_textual_app.py`
- Test: `tests/app/tui/test_layer_boundaries.py`

The TUI MUST NOT construct the runtime. Spec §8.1: harness is the platform center. Runtime construction lives in `harness/factory.py::build_orchestrator` (Layer 3 plan, Task 5). The CLI builds the orchestrator and the session, then passes the session into the app.

- [ ] **Step 1: Write the failing tests**

```python
# tests/app/tui/test_textual_app.py (append)
from cli import build_app


def test_cli_builds_textual_application_with_session() -> None:
    app = build_app()
    assert app.TITLE == "DataHarness"
    assert app._session is not None
```

```python
# tests/app/tui/test_layer_boundaries.py
import ast
import pathlib


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_tui_modules_do_not_import_runtime_or_worker() -> None:
    tui_root = pathlib.Path("src/app/tui")
    for py_path in tui_root.rglob("*.py"):
        imports = _imports(py_path)
        assert "runtime" not in imports, f"{py_path} imports runtime"
        assert "worker" not in imports, f"{py_path} imports worker"


def test_agents_modules_do_not_import_runtime_or_worker() -> None:
    agents_root = pathlib.Path("src/app/agents")
    for py_path in agents_root.rglob("*.py"):
        imports = _imports(py_path)
        assert "runtime" not in imports, f"{py_path} imports runtime"
        assert "worker" not in imports, f"{py_path} imports worker"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/app/tui -q`
Expected: FAIL — `cli.py` does not yet build through the factory and TUI may still import runtime.

- [ ] **Step 3: Write minimal implementation**

```python
# src/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from app.session import DataAnalysisAppSession
from app.tui.app import DataHarnessApp
from harness.control import RunStateRecord
from harness.factory import build_orchestrator


def build_app(workspace_dir: Path | None = None) -> DataHarnessApp:
    workspace = workspace_dir or Path.cwd() / "workspaces" / "w_0001"
    orchestrator = build_orchestrator(workspace_dir=workspace)
    session = DataAnalysisAppSession(orchestrator=orchestrator)
    state = RunStateRecord(workspace_id=workspace.name, active_agent_mode="interaction")
    return DataHarnessApp(session=session, workspace_dir=workspace, state=state)


def main() -> None:
    parser = argparse.ArgumentParser(prog="dataharness")
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args()
    build_app(args.workspace).run()


if __name__ == "__main__":
    main()
```

```bash
# scripts/build_app.sh
#!/usr/bin/env bash
set -euo pipefail

mkdir -p dist
uv build --out-dir dist
```

Confirm `src/app/tui/app.py` imports do NOT include `runtime.*` or `worker.*`. If a previous draft imported `RuntimeConfig` or `LlamaCppRuntime`, delete those imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/app/tui -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cli.py src/app/tui/app.py scripts/build_app.sh tests/app/tui/test_textual_app.py tests/app/tui/test_layer_boundaries.py
git commit -m "feat: cli builds tui through harness factory"
```

## Self-Review

**Spec coverage:**
- Covers TUI surfaces, workspace visibility and switching, process visibility, clarification UI, approval controls, revise/stop/rerun/challenge flows, direct harness command invocation, memory/review hooks, and artifact/provenance display anchors.
- Cross-layer command execution is completed by `2026-04-24-layer-integration-loose-ends.md`: this plan defines the TUI controls and view surfaces, while the integration plan requires those controls to flow through `DataAnalysisAppSession` into harness-owned command handling instead of returning local synthetic dictionaries.

**Placeholder scan:**
- No placeholder markers remain.

**Type consistency:**
- `HarnessViewController`, `WorkspaceView`, `AppView`, and `DataHarnessApp` names stay consistent across tasks.
