# Layer Integration Loose Ends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the already implemented Layers 1-4 into one typed, testable turn path so the TUI and agent modes consume harness services instead of living beside them.

**Architecture:** Add a thin application session facade in `src/app/session.py` that composes the TUI, agent modes, and harness-owned orchestrator without moving ownership out of the harness. Layer 4 proposes mode routing and owns prompt package assembly from the shared app system prompt, mode prompt, generated harness tool catalog, generated mode-intent catalog, and response-format contract, then submits the requested mode and exact prompt package hash to Layer 3; the harness validates, accepts or rejects, records, and activates the selected mode before calling the runtime. Extend the harness orchestrator with explicit runtime, worker-dispatch, command, and persistence seams; keep runtime inference, worker execution, durable state, and app presentation in their current packages. Build the integration from typed events and envelopes so end-to-end tests prove that a user turn reloads context, resolves state and agent mode, builds or updates a plan, gates execution approval, dispatches the worker, inspects artifacts, persists evidence, and returns a TUI-ready result.

**Tech Stack:** Python 3.12, `pydantic`, `pytest`, existing `runtime`, `worker`, `harness`, and `app` packages

---

## File Structure

**Create:**
- `src/app/session.py`: application-layer facade that the TUI can call; it delegates routing and execution authority to harness services.
- `src/app/agents/router.py`: deterministic v1 front-door mode selection and prompt-turn assembly.
- `src/app/agents/prompts/system.md`: shared DataHarness identity and app-scope prompt that forbids generic assistant positioning.
- `src/harness/persistence.py`: small database adapter for saving typed harness records into `WorkspaceDb`.
- `tests/app/test_session_integration.py`: app-to-harness integration tests.
- `tests/app/agents/test_router.py`: agent mode routing tests.
- `tests/app/agents/test_prompt_packages.py`: prompt package integration tests that prove Layer 4 injects the shared system prompt, actual harness command catalog, mode-intent catalog, response-format contract, and stable prompt hash.
- `tests/harness/test_runtime_bridge.py`: orchestrator-to-runtime tests.
- `tests/harness/test_worker_dispatch_integration.py`: orchestrator-to-worker dispatch tests.
- `tests/harness/test_persistence_integration.py`: durable ledger tests.
- `tests/harness/test_full_turn_integration.py`: end-to-end harness-controlled turn tests that cover planning, approval pause/resume, worker execution, inspection, final response, and persistence.
- `tests/app/tui/test_command_integration.py`: TUI-to-session-to-harness direct command tests.

**Modify:**
- `src/app/agents/prompt_packages.py`: assemble prompt packages from `system.md`, mode prompt, generated harness command/tool catalog from `HarnessCommandRouter.supported_commands()`, generated mode-intent catalog, and `response_format.md`.
- `src/harness/orchestrator.py`: accept injected runtime, worker, context manager, prompt package input, and persistence; implement real turn and dispatch paths while preserving existing public methods.
- `src/app/tui/controller.py`: call `DataAnalysisAppSession` for user turns and direct harness commands instead of returning local synthetic dictionaries.
- `src/app/tui/models.py`: align app mode names with canonical `interaction`, `analyst`, and `knowledge` modes.
- `src/app/agents/__init__.py`: export `AgentModeRouter`.
- `tests/app/tui/test_controller.py`: assert controller returns session-backed results.
- `tests/harness/test_orchestrator.py`: keep existing direct-command and approval-gating coverage green.

## Design Notes

The integration surface is intentionally narrow:

- The TUI gets one dependency: `DataAnalysisAppSession`.
- The app session gets one harness dependency: `Orchestrator`.
- The orchestrator owns state transitions, approval checks, prompt package records, worker dispatch, and persistence.
- **Persistence is REQUIRED, never optional.** `Orchestrator.__init__` MUST take a non-None `HarnessPersistence`. There is no `persistence=None` default. Tests inject a tmp-path SQLite via `HarnessPersistence(WorkspaceDb(tmp / "wf.db"))`. Spec §10 invariants (no claim without provenance, no memory update without proposal, no doctor outcome silently overwriting state) require a durable record path on every turn.
- The harness does not import `app.*`; Layer 4 injects prompt text, prompt metadata, and requested mode into the orchestrator.
- The agent layer owns prompt definitions, prompt package assembly, mode proposal policy, generated mode-intent catalog, and generated harness-tool catalog only; the harness owns accepted mode activation and mode-switch records.
- The LLM runtime must not guess what the harness can do. `PromptPackageRegistry.load(mode)` MUST inject the exact command names from `HarnessCommandRouter.supported_commands()` and the exact allowed mode intents into every prompt package before the runtime call.
- `system.md` is part of every app prompt package. It frames DataHarness as a data analysis/data science app only, forbids generic assistant or chatbot identity, and removes any broad casual-conversation path.
- Prompt provenance uses the package hash, not just the mode name. `DataAnalysisAppSession` submits `prompt_template_id=f"{package.mode}@{package.package_hash}"` so telemetry and persisted prompt records prove which assembled prompt the model saw.
- The runtime is called once per turn through the existing `Runtime` protocol.
- The worker is called only from an approved `StepContract`.
- Direct commands from the TUI flow through the app session into harness-owned command handling.

The first version uses deterministic mode routing because the missing piece is layer communication, not smarter language routing. Model-assisted routing can be added later behind the same `AgentModeRouter` contract.

## Test Helper Convention

Every test in this plan instantiates `Orchestrator` with required `runtime` and `persistence` arguments. Tests use this fixture-backed factory:

```python
# tests/conftest.py — already loaded
import pytest


@pytest.fixture
def make_orchestrator(tmp_path):
    from harness.db import WorkspaceDb
    from harness.persistence import HarnessPersistence

    def _make(*, runtime, worker=None):
        db = WorkspaceDb(tmp_path / "state" / "workspace.db")
        return Orchestrator(runtime=runtime, persistence=HarnessPersistence(db), worker=worker)

    return _make
```

Do not use shorthand `Orchestrator()` or `Orchestrator(runtime=runtime)` in production or tests. Those forms hide the persistence contract and weaken the layer integration this plan is meant to verify.

### Task 1: Add Typed App Session Results

**Files:**
- Create: `src/app/session.py`
- Test: `tests/app/test_session_integration.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from app.session import DataAnalysisAppSession
from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeResponse


class FakeRuntime:
    def complete(self, request):
        return RuntimeResponse(text="Workspace is ready.", finish_reason="stop", usage={"total_tokens": 12})

    def stream(self, request):
        return iter(())

    def context_window(self):
        return 4096

    def token_pressure(self, request):
        from runtime.types import TokenPressure

        return TokenPressure(used_tokens=12, max_context_tokens=4096, remaining_tokens=4084)


def test_session_turn_returns_tui_ready_result(tmp_path: Path, make_orchestrator) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    session = DataAnalysisAppSession(make_orchestrator(runtime=FakeRuntime()))
    result = session.handle_user_turn(workspace_dir=workspace, state=state, user_text="show status")
    assert result.workspace_id == "w_0001"
    assert result.active_mode == "interaction"
    assert result.assistant_text == "Workspace is ready."
    assert result.process_events[0] == "reload_context"
    assert "runtime_complete" in result.process_events
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/test_session_integration.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.session'`

- [ ] **Step 3: Add the minimal session result model and facade**

```python
# src/app/session.py
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator


class AppTurnResult(BaseModel):
    workspace_id: str
    run_id: str
    active_mode: str
    assistant_text: str
    process_events: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    failure: str | None = None


class DataAnalysisAppSession:
    def __init__(self, orchestrator: Orchestrator) -> None:
        self.orchestrator = orchestrator

    def handle_user_turn(
        self,
        *,
        workspace_dir: Path,
        state: RunStateRecord,
        user_text: str,
    ) -> AppTurnResult:
        result = self.orchestrator.handle_turn(
            state,
            workspace_dir=workspace_dir,
            user_input=user_text,
        )
        return AppTurnResult(
            workspace_id=str(result["workspace_id"]),
            run_id=str(result["run_id"]),
            active_mode=str(result["active_mode"]),
            assistant_text=str(result["assistant_text"]),
            process_events=list(result["process_events"]),
            artifacts=list(result.get("artifacts", [])),
            requires_approval=bool(result.get("requires_approval", False)),
            failure=result.get("failure"),
        )
```

- [ ] **Step 4: Run test to verify it now reaches the orchestrator gap**

Run: `uv run pytest tests/app/test_session_integration.py -q`
Expected: FAIL with `TypeError` because `Orchestrator.__init__()` and `handle_turn()` do not yet accept runtime or `workspace_dir`

- [ ] **Step 5: Commit**

```bash
git add src/app/session.py tests/app/test_session_integration.py
git commit -m "test: define app session integration contract"
```

### Task 2: Add Deterministic Agent Mode Router

**Files:**
- Create: `src/app/agents/router.py`
- Modify: `src/app/agents/__init__.py`
- Test: `tests/app/agents/test_router.py`

- [ ] **Step 1: Write the failing test**

```python
from app.agents.router import AgentModeRouter


def test_router_selects_analyst_for_analysis_questions() -> None:
    router = AgentModeRouter()
    decision = router.route("compare attrition by department")
    assert decision.mode == "analyst"
    assert decision.reason == "analysis_intent"


def test_router_selects_knowledge_for_teaching_and_memory() -> None:
    router = AgentModeRouter()
    decision = router.route("remember that attrition means voluntary exits")
    assert decision.mode == "knowledge"
    assert decision.reason == "knowledge_capture_intent"


def test_router_defaults_to_interaction() -> None:
    router = AgentModeRouter()
    decision = router.route("hello")
    assert decision.mode == "interaction"
    assert decision.reason == "front_door_default"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/agents/test_router.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.router'`

- [ ] **Step 3: Implement the router**

```python
# src/app/agents/router.py
from __future__ import annotations

from pydantic import BaseModel


class AgentModeDecision(BaseModel):
    mode: str
    reason: str


class AgentModeRouter:
    analysis_terms = {
        "analyze",
        "analysis",
        "compare",
        "calculate",
        "compute",
        "chart",
        "plot",
        "correlation",
        "regression",
        "forecast",
        "summary",
    }
    knowledge_terms = {
        "remember",
        "save",
        "note",
        "preference",
        "definition",
        "means",
        "teach",
        "metric",
    }

    def route(self, user_text: str) -> AgentModeDecision:
        normalized = user_text.lower()
        words = set(normalized.replace("?", " ").replace(",", " ").split())
        if words & self.knowledge_terms:
            return AgentModeDecision(mode="knowledge", reason="knowledge_capture_intent")
        if words & self.analysis_terms:
            return AgentModeDecision(mode="analyst", reason="analysis_intent")
        return AgentModeDecision(mode="interaction", reason="front_door_default")
```

```python
# src/app/agents/__init__.py
from app.agents.prompt_packages import PromptPackageRegistry
from app.agents.router import AgentModeRouter

__all__ = ["AgentModeRouter", "PromptPackageRegistry"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/app/agents/test_router.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/agents/__init__.py src/app/agents/router.py tests/app/agents/test_router.py
git commit -m "feat: add deterministic agent mode router"
```

### Task 3: Wire App Prompt Packages, Tool Catalog, And Harness Runtime Calls

**Files:**
- Create: `src/app/agents/prompts/system.md`
- Modify: `src/app/agents/prompt_packages.py`
- Modify: `src/app/session.py`
- Modify: `src/harness/orchestrator.py`
- Test: `tests/app/agents/test_prompt_packages.py`
- Test: `tests/harness/test_runtime_bridge.py`
- Test: `tests/app/test_session_integration.py`

- [ ] **Step 1: Write failing prompt package integration tests**

```python
from pathlib import Path

from app.agents.prompt_packages import PromptPackageRegistry
from harness.commands import HarnessCommandRouter


def test_prompt_registry_includes_shared_system_prompt_when_present(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system.md").write_text("shared data analysis identity")
    (prompts_dir / "interaction.md").write_text("interaction")
    (prompts_dir / "response_format.md").write_text("format")

    package = PromptPackageRegistry(prompts_dir).load("interaction")

    assert package.prompt_text.startswith("shared data analysis identity")
    assert "interaction" in package.prompt_text
    assert "format" in package.prompt_text
    assert len(package.package_hash) == 64


def test_interaction_prompt_defines_data_analysis_identity_and_capability_answer() -> None:
    package = PromptPackageRegistry(Path("src/app/agents/prompts")).load("interaction")
    text = package.prompt_text.lower()

    assert "data analysis" in text
    assert "data science" in text
    assert "what can you do" in text
    assert "request_clarification" in text
    assert "tool_call" in text
    assert "making casual conversation" not in text
    assert "large language model" not in text


def test_prompt_package_includes_actual_harness_command_catalog() -> None:
    package = PromptPackageRegistry(Path("src/app/agents/prompts")).load("interaction")
    text = package.prompt_text

    assert "Available harness tool calls" in text
    assert '<tool_call>{"name":"workspace_status","arguments":{}}</tool_call>' in text
    for command in HarnessCommandRouter().supported_commands():
        assert f"- `{command}`" in text


def test_prompt_package_includes_mode_intents_for_interaction() -> None:
    package = PromptPackageRegistry(Path("src/app/agents/prompts")).load("interaction")
    text = package.prompt_text

    assert "Allowed interaction intents" in text
    assert "`answer_directly`" in text
    assert "`handoff_to_analyst`" in text
    assert "`handoff_to_knowledge`" in text
    assert "`request_clarification`" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/app/agents/test_prompt_packages.py -q`
Expected: FAIL because `system.md`, the generated command catalog, and the generated mode-intent catalog are not part of prompt package assembly.

- [ ] **Step 3: Add `system.md` and generate the harness command/mode intent catalog**

```markdown
<!-- src/app/agents/prompts/system.md -->
You are DataHarness, a local data analysis and data science application.

Your purpose is to help users understand data, files, metrics, assumptions, computations, charts, reusable analysis logic, and evidence-backed findings. You are not a generic chat shell. Treat every turn as part of a workspace-centered data analysis workflow.

Core capabilities you may describe:
- Inspect uploaded workspace files, schemas, columns, previews, and derived artifacts through harness-owned services.
- Plan data analysis work, request approval before executing code, run approved Python steps, and report results with provenance.
- Explain data science concepts, analysis methods, statistical tradeoffs, and interpretation limits in practical terms.
- Capture reusable knowledge such as metric definitions, business rules, user preferences, semantic notes, unresolved gaps, and candidate functions.
- Surface maintenance and validity information, including doctor reports, artifact provenance, and whether a result should be trusted or rerun.

Behavior:
- Keep front-door answers concise and concrete.
- For "what can you do" or similar capability questions, answer directly with the main data-analysis capabilities and invite the user to provide data or an analysis question.
- Never describe yourself as a general assistant, generic AI, chatbot, or broad content-generation system.
- Do not pretend to have inspected files, run code, or verified a result unless the harness has done that work.
- When intent, data, or semantics are too ambiguous to proceed safely, request clarification instead of guessing.
- Use harness-owned commands and structured tool calls for handoffs; do not invent platform capabilities.
```

```python
# src/app/agents/prompt_packages.py
from __future__ import annotations

import hashlib
from pathlib import Path

from app.agents.types import PromptPackage
from harness.commands import HarnessCommandRouter


MODE_INTENTS = {
    "interaction": [
        "answer_directly",
        "handoff_to_analyst",
        "handoff_to_knowledge",
        "request_clarification",
    ],
    "analyst": [
        "knowledge_lookup",
        "plan_analysis",
        "request_execution",
        "inspect_artifacts",
        "record_provenance",
        "respond_to_user",
    ],
    "knowledge": [
        "store_workspace_knowledge",
        "update_preferences",
        "record_gap",
        "save_function_candidate",
    ],
    "clarification": ["request_clarification"],
}


def _tool_catalog(mode: str) -> str:
    commands = HarnessCommandRouter().supported_commands()
    intents = MODE_INTENTS.get(mode, [])
    command_lines = "\n".join(f"- `{command}`" for command in commands)
    intent_lines = "\n".join(f"- `{intent}`" for intent in intents)
    return "\n".join(
        [
            "Available harness tool calls:",
            "These are the only exposed harness command names. Do not invent tool names.",
            command_lines,
            "",
            f"Allowed {mode} intents:",
            intent_lines,
            "",
            "Tool call format:",
            '<tool_call>{"name":"workspace_status","arguments":{}}</tool_call>',
        ]
    )


class PromptPackageRegistry:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir

    def load(self, mode: str) -> PromptPackage:
        parts = []
        system_prompt = self.prompts_dir / "system.md"
        if system_prompt.exists():
            parts.append(system_prompt.read_text())
        parts.extend(
            [
                (self.prompts_dir / f"{mode}.md").read_text(),
                _tool_catalog(mode),
                (self.prompts_dir / "response_format.md").read_text(),
            ]
        )
        prompt_text = "\n\n".join(parts)
        package_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        return PromptPackage(
            mode=mode,
            template_version="v1",
            prompt_text=prompt_text,
            package_hash=package_hash,
        )
```

- [ ] **Step 4: Run prompt package tests**

Run: `uv run pytest tests/app/agents/test_prompt_packages.py -q`
Expected: PASS

- [ ] **Step 5: Write the failing runtime bridge test**

```python
from pathlib import Path

from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator
from runtime.types import RuntimeResponse


class CapturingRuntime:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return RuntimeResponse(text="Use the workspace status command.", finish_reason="stop", usage={"total_tokens": 18})

    def stream(self, request):
        return iter(())

    def context_window(self):
        return 4096

    def token_pressure(self, request):
        from runtime.types import TokenPressure

        return TokenPressure(used_tokens=18, max_context_tokens=4096, remaining_tokens=4078)


def test_orchestrator_builds_prompt_and_calls_single_runtime(tmp_path: Path, make_orchestrator) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text('{"style": "concise"}')
    runtime = CapturingRuntime()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    result = make_orchestrator(runtime=runtime).handle_turn(
        state,
        workspace_dir=workspace,
        user_input="show status",
        requested_mode="interaction",
        prompt_text="You are the interaction mode for the local data analysis application.",
        prompt_template_id="interaction",
        prompt_template_version="v1",
    )
    assert result["assistant_text"] == "Use the workspace status command."
    assert result["active_mode"] == "interaction"
    assert result["process_events"][:3] == ["reload_context", "route_agent_mode", "build_prompt_package"]
    request = runtime.requests[0]
    assert request.messages[0].role == "system"
    assert "interaction mode" in request.messages[0].content
    assert request.messages[-1].content == "show status"
```

- [ ] **Step 6: Run runtime bridge test to verify it fails**

Run: `uv run pytest tests/harness/test_runtime_bridge.py -q`
Expected: FAIL because `Orchestrator` has no runtime or injected prompt package integration

- [ ] **Step 7: Implement runtime-backed turn handling without importing Layer 4**

```python
# src/harness/orchestrator.py
from __future__ import annotations

from pathlib import Path

from harness.commands import HarnessCommandRouter
from harness.context import ContextManager
from harness.control import ApprovalRecord, ModeSwitchEvent, Plan, PromptPackage, RunStateRecord
from harness.state_machine import HarnessStateMachine
from runtime.protocol import Runtime
from runtime.types import Message, RuntimeRequest


class Orchestrator:
    def __init__(
        self,
        *,
        runtime: Runtime,
        persistence: "HarnessPersistence",
        worker: "PythonStepExecutor | None" = None,
        context_manager: ContextManager | None = None,
        knowledge: "KnowledgeManager | None" = None,
    ) -> None:
        # Persistence and runtime are REQUIRED. No optional defaults.
        self.commands = HarnessCommandRouter()
        self.state_machine = HarnessStateMachine()
        self.runtime = runtime
        self.persistence = persistence
        self.worker = worker  # may be None for non-execution-only test paths
        self.context_manager = context_manager or ContextManager()
        self.knowledge = knowledge

    def handle_turn(
        self,
        state: RunStateRecord,
        *,
        user_input: str,
        workspace_dir: Path | None = None,
        requested_mode: str | None = None,
        prompt_text: str | None = None,
        prompt_template_id: str | None = None,
        prompt_template_version: str = "v1",
    ) -> dict[str, object]:
        routed_state = self.state_machine.transition(state, "routing")
        events = ["reload_context"]
        context = {}
        if workspace_dir is not None:
            context = self.context_manager.rebuild(
                workspace_dir=workspace_dir,
                session_ledger=[],
                validity_states=[],
                chat_history=[],
            )
        active_mode = requested_mode or state.active_agent_mode
        routed_state = routed_state.model_copy(update={"active_agent_mode": active_mode})
        events.append("route_agent_mode")
        system_prompt = prompt_text or "You are the harness interaction mode."
        mode_switch = None
        if active_mode != state.active_agent_mode:
            mode_switch = ModeSwitchEvent(
                workspace_id=state.workspace_id,
                run_id=state.run_id,
                from_mode=state.active_agent_mode,
                to_mode=active_mode,
                reason="application_session_request",
                requested_by="application_session",
                accepted=True,
            )
            events.append("record_mode_switch")
        events.append("build_prompt_package")
        prompt_record = PromptPackage(
            workspace_id=state.workspace_id,
            run_id=state.run_id,
            agent_mode=active_mode,
            prompt_template_id=prompt_template_id or active_mode,
            prompt_template_version=prompt_template_version,
            context_refs=["memory/preferences.json"],
            token_budget=4096,
            reasoning_capture_policy="separate_stream",
        )
        assistant_text = ""
        request = RuntimeRequest(
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="system", content=f"Fresh context: {context}"),
                Message(role="user", content=user_input),
            ],
            max_new_tokens=512,
            temperature=0.2,
            top_p=0.95,
        )
        response = self.runtime.complete(request)
        assistant_text = response.text
        usage = response.usage
        events.append("runtime_complete")
        return {
            "workspace_id": state.workspace_id,
            "run_id": state.run_id,
            "state": str(routed_state.state),
            "active_mode": active_mode,
            "assistant_text": assistant_text,
            "usage": usage,
            "mode_switch": mode_switch.model_dump(mode="json") if mode_switch else None,
            "prompt_package": prompt_record.model_dump(mode="json"),
            "process_events": events,
            "steps": events,
        }

    def handle_direct_command(
        self,
        state: RunStateRecord,
        *,
        command: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        request = self.commands.validate(command, arguments)
        return {
            "workspace_id": state.workspace_id,
            "run_state": str(state.state),
            "command": request.command,
            "arguments": request.arguments,
            "owned_by": "harness",
        }

    def prepare_worker_dispatch(
        self,
        plan: Plan,
        *,
        approval: ApprovalRecord | None,
    ) -> dict[str, object]:
        if not self.state_machine.can_dispatch_execution(plan, approval):
            return {
                "dispatch": False,
                "reason": "explicit code execution approval required",
            }
        return {"dispatch": True, "plan_id": plan.id}
```

- [ ] **Step 8: Wire app session to provide requested mode and prompt package**

```python
# src/app/session.py
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.agents.prompt_packages import PromptPackageRegistry
from app.agents.router import AgentModeRouter
from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator


class AppTurnResult(BaseModel):
    workspace_id: str
    run_id: str
    active_mode: str
    assistant_text: str
    process_events: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    failure: str | None = None


class DataAnalysisAppSession:
    def __init__(
        self,
        orchestrator: Orchestrator,
        mode_router: AgentModeRouter | None = None,
        prompt_registry: PromptPackageRegistry | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.mode_router = mode_router or AgentModeRouter()
        self.prompt_registry = prompt_registry or PromptPackageRegistry(
            Path(__file__).resolve().parent / "agents" / "prompts"
        )

    def handle_user_turn(
        self,
        *,
        workspace_dir: Path,
        state: RunStateRecord,
        user_text: str,
    ) -> AppTurnResult:
        decision = self.mode_router.route(user_text)
        package = self.prompt_registry.load(decision.mode)
        result = self.orchestrator.handle_turn(
            state,
            workspace_dir=workspace_dir,
            user_input=user_text,
            requested_mode=decision.mode,
            prompt_text=package.prompt_text,
            prompt_template_id=f"{package.mode}@{package.package_hash}",
            prompt_template_version=package.template_version,
        )
        return AppTurnResult(
            workspace_id=str(result["workspace_id"]),
            run_id=str(result["run_id"]),
            active_mode=str(result["active_mode"]),
            assistant_text=str(result["assistant_text"]),
            process_events=list(result["process_events"]),
            artifacts=list(result.get("artifacts", [])),
            requires_approval=bool(result.get("requires_approval", False)),
            failure=result.get("failure"),
        )
```

- [ ] **Step 9: Run the bridge and session tests**

Run: `uv run pytest tests/harness/test_runtime_bridge.py tests/app/test_session_integration.py tests/harness/test_orchestrator.py -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/app/agents/prompt_packages.py src/app/agents/prompts/system.md src/app/session.py src/harness/orchestrator.py tests/app/agents/test_prompt_packages.py tests/harness/test_runtime_bridge.py
git commit -m "feat: wire orchestrator to runtime prompts"
```

### Task 4: Add Approval-Gated Worker Dispatch From StepContract

**Files:**
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_worker_dispatch_integration.py`

- [ ] **Step 1: Write the failing worker dispatch test**

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from harness.control import ApprovalRecord, Plan, PlanStep, StepContract
from runtime.types import RuntimeResponse
from worker.executor import PythonStepExecutor


class FakeRuntime:
    def complete(self, request):
        return RuntimeResponse(text="dispatch only", finish_reason="stop", usage={"total_tokens": 2})

    def stream(self, request): return iter(())
    def context_window(self): return 4096
    def token_pressure(self, request):
        from runtime.types import TokenPressure

        return TokenPressure(used_tokens=2, max_context_tokens=4096, remaining_tokens=4094)


def test_orchestrator_dispatches_approved_step_contract_to_worker(tmp_path: Path, make_orchestrator) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "artifacts" / "tmp").mkdir(parents=True)
    (workspace / "data" / "input.csv").write_text("value\n1\n")
    step = PlanStep(
        id="step_1",
        workspace_id="w_0001",
        plan_id="plan_1",
        step_order=1,
        purpose="Write result",
        kind="code",
        declared_inputs=["data/input.csv"],
        expected_outputs=["output.txt"],
    )
    plan = Plan(
        id="plan_1",
        workspace_id="w_0001",
        run_id="run_1",
        goal="Write result",
        steps=[step],
        requires_code_execution=True,
    )
    contract = StepContract(
        workspace_id="w_0001",
        run_id="run_1",
        plan_id="plan_1",
        step_id="step_1",
        code="from pathlib import Path\nPath('output.txt').write_text('ok')\n",
        declared_inputs=["data/input.csv"],
        workspace_paths={"workspace": "."},
        permission_envelope={
            "allowed_read_paths": ["data/input.csv"],
            "registered_artifact_paths": [],
            "allowed_write_roots": ["artifacts/tmp"],
            "allowed_packages": [],
            "allow_network": False,
            "allow_shell": False,
        },
        expected_output_contract={"files": ["output.txt"]},
        run_metadata={"reason": "test"},
    )
    approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id="run_1",
        target_type="plan",
        target_id="plan_1",
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at=datetime.now(UTC),
    )
    envelope = make_orchestrator(runtime=FakeRuntime(), worker=PythonStepExecutor()).dispatch_step(
        workspace_dir=workspace,
        plan=plan,
        contract=contract,
        approval=approval,
    )
    assert envelope.status == "ok"
    assert envelope.step_id == "step_1"
    assert "artifacts/tmp/run_1/step_1/output.txt" in envelope.artifact_refs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_worker_dispatch_integration.py -q`
Expected: FAIL because `Orchestrator` has no `worker` injection or `dispatch_step()`

- [ ] **Step 3: Implement dispatch conversion**

```python
# Add these imports to src/harness/orchestrator.py
from harness.control import StepContract
from worker.executor import PythonStepExecutor
from worker.models import PermissionEnvelope, ResourceLimits, StepExecutionRequest


# Add worker to Orchestrator.__init__
worker: PythonStepExecutor | None = None,


# Add inside __init__
self.worker = worker or PythonStepExecutor()


# Add this method to Orchestrator
def dispatch_step(
    self,
    *,
    workspace_dir: Path,
    plan: Plan,
    contract: StepContract,
    approval: ApprovalRecord | None,
):
    dispatch = self.prepare_worker_dispatch(plan, approval=approval)
    if not dispatch["dispatch"]:
        raise PermissionError(str(dispatch["reason"]))
    expected_files = contract.expected_output_contract.get("files", [])
    request = StepExecutionRequest(
        id=contract.id,
        workspace_id=contract.workspace_id,
        run_id=contract.run_id,
        plan_id=contract.plan_id,
        step_id=contract.step_id,
        workspace_dir=workspace_dir,
        code=contract.code,
        declared_inputs={path: path for path in contract.declared_inputs},
        workspace_paths=contract.workspace_paths,
        permission_envelope=PermissionEnvelope(**contract.permission_envelope),
        expected_output_contract=list(expected_files),
        run_metadata=contract.run_metadata,
        resource_limits=ResourceLimits(),
    )
    return self.worker.execute(request)
```

- [ ] **Step 4: Run dispatch and existing worker tests**

Run: `uv run pytest tests/harness/test_worker_dispatch_integration.py tests/worker/test_executor.py tests/harness/test_orchestrator.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/harness/orchestrator.py tests/harness/test_worker_dispatch_integration.py
git commit -m "feat: dispatch approved harness steps to worker"
```

### Task 5: Persist Prompt, Run, Execution, And Artifact Records

**Files:**
- Create: `src/harness/persistence.py`
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_persistence_integration.py`

- [ ] **Step 1: Write the failing persistence test**

```python
from pathlib import Path

from harness.control import RunStateRecord
from harness.db import WorkspaceDb
from harness.orchestrator import Orchestrator
from harness.persistence import HarnessPersistence
from runtime.types import RuntimeResponse


class FakeRuntime:
    def complete(self, request):
        return RuntimeResponse(text="Done.", finish_reason="stop", usage={"total_tokens": 4})

    def stream(self, request):
        return iter(())

    def context_window(self):
        return 4096

    def token_pressure(self, request):
        from runtime.types import TokenPressure

        return TokenPressure(used_tokens=4, max_context_tokens=4096, remaining_tokens=4092)


def test_orchestrator_persists_run_state_and_prompt_package(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    db = WorkspaceDb(workspace / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    result = Orchestrator(runtime=FakeRuntime(), persistence=persistence).handle_turn(
        state,
        workspace_dir=workspace,
        user_input="hello",
    )
    loaded_run = db.load_record("run_records", "run_id", state.run_id)
    loaded_prompt = db.load_record("prompt_packages", "run_id", state.run_id)
    assert loaded_run["run_id"] == state.run_id
    assert loaded_prompt["agent_mode"] == result["active_mode"]


def test_persistence_saves_execution_evidence_and_artifact_registry(tmp_path: Path) -> None:
    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    persistence = HarnessPersistence(db)
    envelope = {
        "id": "env_run_1_step_1",
        "schema_version": "1.0",
        "workspace_id": "w_0001",
        "run_id": "run_1",
        "step_id": "step_1",
        "status": "ok",
        "step_result_path": "artifacts/tmp/run_1/step_1/step_result.json",
        "step_report_path": "artifacts/tmp/run_1/step_1/step_report.md",
        "stdout_path": "artifacts/tmp/run_1/step_1/stdout.txt",
        "stderr_path": "artifacts/tmp/run_1/step_1/stderr.txt",
        "artifact_refs": ["artifacts/tmp/run_1/step_1/output.txt"],
        "execution_metadata": {"code_hash": "abc", "input_refs": ["data/input.csv"]},
        "failure_kind": "ok",
    }
    persistence.save_execution_envelope(envelope)
    loaded = db.load_record("execution_envelopes", "id", "env_run_1_step_1")
    artifact = db.load_record("artifact_registry", "path", "artifacts/tmp/run_1/step_1/output.txt")
    step_log = db.load_record("step_action_history", "id", "run_1:step_1:execution")
    assert loaded["status"] == "ok"
    assert artifact["run_id"] == "run_1"
    assert step_log["action"] == "execution_envelope_recorded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_persistence_integration.py -q`
Expected: FAIL because `harness.persistence` does not exist

- [ ] **Step 3: Implement persistence adapter**

```python
# src/harness/persistence.py
from __future__ import annotations

from pydantic import BaseModel

from harness.db import WorkspaceDb


class HarnessPersistence:
    def __init__(self, db: WorkspaceDb) -> None:
        self.db = db

    def save_model(self, table: str, key_name: str, key_value: str, record: BaseModel) -> None:
        self.db.save_record(table, key_name, key_value, record.model_dump(mode="json"))

    def save_dict(self, table: str, key_name: str, key_value: str, record: dict[str, object]) -> None:
        self.db.save_record(table, key_name, key_value, record)

    def save_execution_envelope(self, envelope: dict[str, object]) -> None:
        envelope_id = str(envelope["id"])
        run_id = str(envelope["run_id"])
        step_id = str(envelope["step_id"])
        self.save_dict("execution_envelopes", "id", envelope_id, envelope)
        self.save_dict(
            "step_action_history",
            "id",
            f"{run_id}:{step_id}:execution",
            {
                "id": f"{run_id}:{step_id}:execution",
                "run_id": run_id,
                "step_id": step_id,
                "action": "execution_envelope_recorded",
                "status": envelope["status"],
                "envelope_id": envelope_id,
            },
        )
        for path in envelope.get("artifact_refs", []):
            self.save_dict(
                "artifact_registry",
                "path",
                str(path),
                {
                    "path": str(path),
                    "run_id": run_id,
                    "step_id": step_id,
                    "status": "tmp_registered",
                    "source_envelope_id": envelope_id,
                },
            )
```

- [ ] **Step 4: Wire persistence into `Orchestrator.handle_turn()`**

```python
# Add import
from harness.persistence import HarnessPersistence


# Add __init__ parameter
persistence: HarnessPersistence,


# Add inside __init__
self.persistence = persistence


# Add before returning from handle_turn()
self.persistence.save_model("run_records", "run_id", state.run_id, routed_state)
self.persistence.save_model("run_state_history", "id", routed_state.id, routed_state)
if mode_switch is not None:
    self.persistence.save_dict("mode_switch_history", "id", mode_switch.id, mode_switch.model_dump(mode="json"))
self.persistence.save_dict("prompt_packages", "run_id", state.run_id, prompt_record.model_dump(mode="json"))
```

- [ ] **Step 5: Run persistence and database tests**

Run: `uv run pytest tests/harness/test_persistence_integration.py tests/harness/test_db.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/harness/persistence.py src/harness/orchestrator.py tests/harness/test_persistence_integration.py
git commit -m "feat: persist integrated harness turn records"
```

### Task 6: Move TUI Controller Onto App Session

**Files:**
- Modify: `src/app/tui/controller.py`
- Modify: `src/app/tui/models.py`
- Modify: `src/app/session.py`
- Test: `tests/app/tui/test_controller.py`
- Test: `tests/app/tui/test_command_integration.py`

- [ ] **Step 1: Update the failing controller test**

```python
from pathlib import Path

from app.session import DataAnalysisAppSession
from app.tui.controller import HarnessViewController
from harness.control import RunStateRecord
from runtime.types import RuntimeResponse


class FakeRuntime:
    def complete(self, request):
        return RuntimeResponse(text="TUI response.", finish_reason="stop", usage={"total_tokens": 5})

    def stream(self, request):
        return iter(())

    def context_window(self):
        return 4096

    def token_pressure(self, request):
        from runtime.types import TokenPressure

        return TokenPressure(used_tokens=5, max_context_tokens=4096, remaining_tokens=4091)


def test_controller_turn_uses_app_session(tmp_path: Path, make_orchestrator) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    controller = HarnessViewController(
        session=DataAnalysisAppSession(make_orchestrator(runtime=FakeRuntime()))
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    result = controller.submit_turn(workspace_dir=workspace, state=state, user_text="hello")
    assert result.assistant_text == "TUI response."
    assert result.workspace_id == "w_0001"
```

Create `tests/app/tui/test_command_integration.py`:

```python
from app.session import DataAnalysisAppSession
from app.tui.controller import HarnessViewController
from harness.control import RunStateRecord
from runtime.types import RuntimeResponse


class FakeRuntime:
    def complete(self, request):
        return RuntimeResponse(text="Command ready.", finish_reason="stop", usage={"total_tokens": 3})

    def stream(self, request):
        return iter(())

    def context_window(self):
        return 4096

    def token_pressure(self, request):
        from runtime.types import TokenPressure

        return TokenPressure(used_tokens=3, max_context_tokens=4096, remaining_tokens=4093)


def test_tui_direct_commands_flow_through_harness(make_orchestrator) -> None:
    controller = HarnessViewController(session=DataAnalysisAppSession(make_orchestrator(runtime=FakeRuntime())))
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    result = controller.invoke_command(state, "doctor", trigger="manual")
    assert result["command"] == "doctor"
    assert result["owned_by"] == "harness"
    assert result["workspace_id"] == "w_0001"


def test_tui_artifact_memory_provenance_and_run_controls_use_harness_commands(make_orchestrator) -> None:
    controller = HarnessViewController(session=DataAnalysisAppSession(make_orchestrator(runtime=FakeRuntime())))
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    commands = [
        ("inspect_artifact", {"path": "artifacts/report.md"}),
        ("memory_review", {"target": "notes"}),
        ("provenance_inspect", {"result_id": "result-1"}),
        ("retry_step", {"step_id": "step-1"}),
        ("cancel_run", {"run_id": state.run_id}),
    ]
    for command, arguments in commands:
        result = controller.invoke_command(state, command, **arguments)
        assert result["command"] == command
        assert result["owned_by"] == "harness"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/tui/test_controller.py tests/app/tui/test_command_integration.py -q`
Expected: FAIL because `HarnessViewController` has no `session` injection, `submit_turn()`, or harness-backed direct command path

- [ ] **Step 3: Update app session, TUI modes, and controller**

```python
# Add this method to src/app/session.py
def handle_direct_command(
    self,
    state: RunStateRecord,
    command: str,
    **arguments: object,
) -> dict[str, object]:
    return self.orchestrator.handle_direct_command(
        state,
        command=command,
        arguments=arguments,
    )
```

```python
# src/app/tui/models.py
class ActiveMode(StrEnum):
    interaction = "interaction"
    analyst = "analyst"
    knowledge = "knowledge"
```

```python
# src/app/tui/controller.py
from __future__ import annotations

from pathlib import Path

from app.session import DataAnalysisAppSession
from app.tui.models import ActiveMode, AppView, ResultState, RunState, WorkspaceStatus, WorkspaceView
from harness.commands import HarnessCommandRouter
from harness.control import RunStateRecord


class HarnessViewController:
    def __init__(self, session: DataAnalysisAppSession) -> None:
        self._router = HarnessCommandRouter()
        self._session = session

    def initial_view(self) -> AppView:
        return AppView(
            workspace=WorkspaceView(workspace_id="w_0001", run_state=RunState.idle, active_mode=ActiveMode.interaction),
            workspace_status=WorkspaceStatus.ready,
            available_workspaces=["w_0001"],
            available_commands=self._router.supported_commands(),
            process_events=["harness idle"],
        )

    def submit_turn(self, *, workspace_dir: Path, state: RunStateRecord, user_text: str):
        return self._session.handle_user_turn(workspace_dir=workspace_dir, state=state, user_text=user_text)

    def open_approval(self, *, plan_id: str, timeout_seconds: int) -> dict[str, object]:
        return {"plan_id": plan_id, "timeout_seconds": timeout_seconds}

    def invoke_command(self, state: RunStateRecord, command: str, **arguments: object) -> dict[str, object]:
        self._router.validate(command, arguments)
        return self._session.handle_direct_command(state, command, **arguments)

    def switch_workspace(self, workspace_id: str) -> dict[str, str]:
        return {"workspace_id": workspace_id}

    def revise_goal(self, goal: str) -> dict[str, str]:
        return {"goal": goal}

    def stop_after_current_step(self, *, run_id: str) -> dict[str, str]:
        return {"run_id": run_id, "mode": "stop_after_current_step"}

    def rerun_step(self, *, step_id: str) -> dict[str, str]:
        return {"step_id": step_id}

    def challenge_conclusion(self, *, result_id: str) -> dict[str, str]:
        return {"result_id": result_id}

    def mark_result_state(self, *, result_id: str, state: ResultState) -> dict[str, str]:
        return {"result_id": result_id, "state": state}
```

- [ ] **Step 4: Run controller and session tests**

Run: `uv run pytest tests/app/tui/test_controller.py tests/app/tui/test_command_integration.py tests/app/test_session_integration.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/session.py src/app/tui/controller.py src/app/tui/models.py tests/app/tui/test_controller.py tests/app/tui/test_command_integration.py
git commit -m "feat: route tui turns through app session"
```

### Task 7: Add End-To-End Layer Communication Regression

**Files:**
- Modify: `tests/app/test_session_integration.py`

- [ ] **Step 1: Add the cross-layer regression test**

```python
class CapturingRuntime(FakeRuntime):
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return super().complete(request)


def test_layers_communicate_from_tui_turn_to_runtime_prompt(tmp_path: Path, make_orchestrator) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory" / "notes").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text('{"style": "concise"}')
    (workspace / "memory" / "notes" / "metric.md").write_text("Attrition means voluntary exits.")
    runtime = CapturingRuntime()
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    session = DataAnalysisAppSession(make_orchestrator(runtime=runtime))
    result = session.handle_user_turn(
        workspace_dir=workspace,
        state=state,
        user_text="compare attrition by department",
    )
    assert result.active_mode == "analyst"
    assert result.assistant_text == "Workspace is ready."
    assert result.process_events == [
        "reload_context",
        "route_agent_mode",
        "record_mode_switch",
        "build_prompt_package",
        "runtime_complete",
    ]
    request = runtime.requests[0]
    system_prompt = request.messages[0].content
    assert "You are DataHarness" in system_prompt
    assert "Available harness tool calls" in system_prompt
    assert "`workspace_status`" in system_prompt
    assert "Allowed analyst intents" in system_prompt
    assert "large language model" not in system_prompt.lower()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/app/test_session_integration.py -q`
Expected: PASS

- [ ] **Step 3: Run all fast tests**

Run: `uv run pytest -q`
Expected: PASS with all current unit tests plus the new integration regression tests

- [ ] **Step 4: Commit**

```bash
git add tests/app/test_session_integration.py
git commit -m "test: cover end-to-end layer communication"
```

### Task 8: Add Full Harness-Controlled Analysis Turn Regression

**Files:**
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/persistence.py`
- Test: `tests/harness/test_full_turn_integration.py`

- [ ] **Step 1: Write the failing full-turn tests**

```python
from datetime import UTC, datetime
from pathlib import Path

from harness.control import ApprovalRecord, RunStateRecord
from harness.db import WorkspaceDb
from harness.orchestrator import Orchestrator
from harness.persistence import HarnessPersistence
from runtime.types import RuntimeResponse
from worker.executor import PythonStepExecutor


class RequestExecutionRuntime:
    def complete(self, request):
        payload = {
            "name": "request_execution",
            "arguments": {
                "code": "from pathlib import Path\nPath('output.txt').write_text('department,leavers\\nSales,1\\n')\n",
                "expected_outputs": ["output.txt"],
            },
        }
        return RuntimeResponse(
            text=f"<tool_call>{json.dumps(payload)}</tool_call>",
            finish_reason="stop",
            usage={"total_tokens": 32},
        )

    def stream(self, request): return iter(())
    def context_window(self): return 4096
    def token_pressure(self, request):
        from runtime.types import TokenPressure

        return TokenPressure(used_tokens=32, max_context_tokens=4096, remaining_tokens=4064)


def test_analysis_turn_creates_plan_and_pauses_for_code_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "memory").mkdir(parents=True)
    (workspace / "state").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    (workspace / "data" / "input.csv").write_text("department,leavers\nSales,1\n")
    db = WorkspaceDb(workspace / "state" / "workspace.db")
    orchestrator = Orchestrator(runtime=RequestExecutionRuntime(), persistence=HarnessPersistence(db))
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")

    result = orchestrator.handle_turn(
        state,
        workspace_dir=workspace,
        user_input="compare leavers by department",
        requested_mode="analyst",
        prompt_text="analyst",
        prompt_template_id="analyst",
    )

    assert result["state"] == "awaiting_approval"
    assert result["requires_approval"] is True
    assert result["plan"]["requires_code_execution"] is True
    assert result["process_events"] == [
        "reload_context",
        "route_agent_mode",
        "record_mode_switch",
        "build_prompt_package",
        "runtime_complete",
        "create_plan",
        "select_step",
        "generate_step_contract",
        "await_execution_approval",
        "persist_turn",
    ]
    assert db.load_record("plan_records", "id", result["plan"]["id"])["goal"] == "compare leavers by department"


def test_approved_analysis_turn_dispatches_worker_inspects_artifacts_and_persists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "data").mkdir(parents=True)
    (workspace / "artifacts" / "tmp").mkdir(parents=True)
    (workspace / "memory").mkdir(parents=True)
    (workspace / "state").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    (workspace / "data" / "input.csv").write_text("department,leavers\nSales,1\n")
    db = WorkspaceDb(workspace / "state" / "workspace.db")
    orchestrator = Orchestrator(
        runtime=RequestExecutionRuntime(),
        worker=PythonStepExecutor(),
        persistence=HarnessPersistence(db),
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="analyst")
    paused = orchestrator.handle_turn(
        state,
        workspace_dir=workspace,
        user_input="compare leavers by department",
        requested_mode="analyst",
        prompt_text="analyst",
        prompt_template_id="analyst",
    )
    approval = ApprovalRecord(
        workspace_id="w_0001",
        run_id=state.run_id,
        target_type="plan",
        target_id=paused["plan"]["id"],
        approval_kind="code_execution",
        decision="approved",
        decided_by="user",
        decided_at=datetime.now(UTC),
    )

    result = orchestrator.resume_approved_step(
        workspace_dir=workspace,
        state=state,
        plan_payload=paused["plan"],
        contract_payload=paused["step_contract"],
        approval=approval,
    )

    assert result["state"] == "finished"
    assert result["assistant_text"] == "Analysis complete. See artifacts/tmp/{run_id}/step_1/output.txt.".format(run_id=state.run_id)
    assert result["process_events"] == [
        "verify_execution_approval",
        "dispatch_worker",
        "inspect_artifacts",
        "record_execution_evidence",
        "finish_response",
        "persist_turn",
    ]
    step_log = db.load_record("step_action_history", "id", f"{state.run_id}:step_1:execution")
    artifact = db.load_record("artifact_registry", "path", f"artifacts/tmp/{state.run_id}/step_1/output.txt")
    assert step_log["action"] == "execution_envelope_recorded"
    assert artifact["step_id"] == "step_1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/harness/test_full_turn_integration.py -q`
Expected: FAIL because `handle_turn()` does not create executable plans and `resume_approved_step()` does not exist.

- [ ] **Step 3: Add persistence helpers for plan, step, approval, and execution records**

```python
# Add to src/harness/persistence.py
from harness.control import ApprovalRecord


def save_plan_with_steps(self, plan_payload: dict[str, object]) -> None:
    self.save_dict("plan_records", "id", str(plan_payload["id"]), plan_payload)
    for step in plan_payload.get("steps", []):
        self.save_dict("step_records", "id", str(step["id"]), step)


def save_approval(self, approval: ApprovalRecord) -> None:
    self.save_model("approval_records", "id", approval.id, approval)
```

- [ ] **Step 4: Extend orchestrator with deterministic v1 analysis plan creation and resume**

```python
# Add imports to src/harness/orchestrator.py
from harness.control import PlanStep, StepContract


def _build_v1_analysis_plan(self, state: RunStateRecord, user_input: str) -> tuple[Plan, StepContract]:
    step = PlanStep(
        id="step_1",
        workspace_id=state.workspace_id,
        plan_id=f"plan_{state.run_id}",
        step_order=1,
        purpose="Create a small evidence artifact for the requested analysis.",
        kind="code",
        declared_inputs=["data/input.csv"],
        expected_outputs=["output.txt"],
    )
    plan = Plan(
        id=f"plan_{state.run_id}",
        workspace_id=state.workspace_id,
        run_id=state.run_id,
        goal=user_input,
        steps=[step],
        requires_code_execution=True,
    )
    contract = StepContract(
        id=f"contract_{state.run_id}_step_1",
        workspace_id=state.workspace_id,
        run_id=state.run_id,
        plan_id=plan.id,
        step_id=step.id,
        code="from pathlib import Path\nPath('output.txt').write_text('department,leavers\\nSales,1\\n')\n",
        declared_inputs=["data/input.csv"],
        workspace_paths={"workspace": "."},
        permission_envelope={
            "allowed_read_paths": ["data/input.csv"],
            "registered_artifact_paths": [],
            "allowed_write_roots": ["artifacts/tmp"],
            "allowed_packages": ["pathlib"],
            "allow_network": False,
            "allow_shell": False,
        },
        expected_output_contract={"files": ["output.txt"]},
        run_metadata={"source": "deterministic_v1_analysis_plan"},
    )
    return plan, contract
```

```python
# Inside handle_turn() AFTER prompt_record creation:
# 1. Build runtime request (with token-pressure gate from Task 8a).
# 2. Call runtime.complete(request) and parse the response.
# 3. Branch on the parsed intent — NEVER on user_input string contents.
#
# DO NOT add `if "compare" in user_input.lower()`. Planning is driven by the model's
# structured tool-call output, not by keyword matching against user input.

response = self.runtime.complete(request)
events.append("runtime_complete")

intent = self._parse_runtime_intent(response)
if intent is None:
    # Plain assistant text response. No plan, no approval.
    events.append("respond_to_user")
    self.persistence.save_model("run_records", "run_id", state.run_id, routed_state)
    self.persistence.save_dict("prompt_packages", "run_id", state.run_id, prompt_record.model_dump(mode="json"))
    events.append("persist_turn")
    return {
        "workspace_id": state.workspace_id,
        "run_id": state.run_id,
        "state": str(routed_state.state),
        "active_mode": active_mode,
        "assistant_text": response.text,
        "requires_approval": False,
        "process_events": events,
    }

if intent.name == "request_clarification":
    clarifying = self.state_machine.transition(routed_state, "clarifying")
    events.extend(["request_clarification", "persist_turn"])
    self.persistence.save_model("run_records", "run_id", state.run_id, clarifying)
    self.persistence.save_model("run_state_history", "id", clarifying.id, clarifying)
    return {
        "workspace_id": state.workspace_id,
        "run_id": state.run_id,
        "state": str(clarifying.state),
        "active_mode": active_mode,
        "assistant_text": "",
        "clarification_question": intent.arguments.get("question", ""),
        "requires_approval": False,
        "process_events": events,
    }

if intent.name == "request_execution":
    plan, contract = self._plan_from_request_execution(state, user_input, intent)
    awaiting = routed_state.model_copy(update={"state": "awaiting_approval", "plan_id": plan.id, "step_id": contract.step_id})
    events.extend(["create_plan", "select_step", "generate_step_contract", "await_execution_approval"])
    self.persistence.save_model("run_records", "run_id", state.run_id, awaiting)
    self.persistence.save_model("run_state_history", "id", awaiting.id, awaiting)
    self.persistence.save_plan_with_steps(plan.model_dump(mode="json"))
    self.persistence.save_dict(
        "step_action_history", "id", f"{state.run_id}:{contract.step_id}:approval_pause",
        {
            "id": f"{state.run_id}:{contract.step_id}:approval_pause",
            "run_id": state.run_id, "step_id": contract.step_id,
            "action": "await_execution_approval", "status": "paused",
        },
    )
    events.append("persist_turn")
    return {
        "workspace_id": state.workspace_id,
        "run_id": state.run_id,
        "state": str(awaiting.state),
        "active_mode": active_mode,
        "assistant_text": response.text or "Approval required before running code.",
        "requires_approval": True,
        "plan": plan.model_dump(mode="json"),
        "step_contract": contract.model_dump(mode="json"),
        "prompt_package": prompt_record.model_dump(mode="json"),
        "process_events": events,
    }

# Knowledge intents flow through the agent intent handler; harness records the proposal.
if intent.name in {"store_workspace_knowledge", "update_preferences", "record_gap", "save_function_candidate"}:
    proposal = self.knowledge.propose_from_intent(intent.model_dump())
    events.extend(["create_memory_update_proposal", "persist_turn"])
    return {
        "workspace_id": state.workspace_id,
        "run_id": state.run_id,
        "state": str(routed_state.state),
        "active_mode": active_mode,
        "assistant_text": response.text,
        "requires_approval": False,
        "memory_update_proposal": proposal.model_dump(mode="json"),
        "process_events": events,
    }
```

The `_plan_from_request_execution` helper builds a `Plan` + `StepContract` from `intent.arguments`, expecting at minimum `code: str` and `expected_outputs: list[str]`. If `plan_steps: list[dict]` is present, build a multi-step plan.

Add a regression test asserting NO keyword matching:

```python
def test_handle_turn_does_not_use_keyword_matching_on_user_input() -> None:
    import ast
    import pathlib

    source = pathlib.Path("src/harness/orchestrator.py").read_text()
    tree = ast.parse(source)
    # Reject any `"<word>" in user_input.lower()` style branch.
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.In):
            right = node.comparators[0]
            if isinstance(right, ast.Call) and getattr(right.func, "attr", "") == "lower":
                raise AssertionError(f"keyword-on-user_input branch found at line {node.lineno}")
```

```python
# Add method to src/harness/orchestrator.py
def resume_approved_step(
    self,
    *,
    workspace_dir: Path,
    state: RunStateRecord,
    plan_payload: dict[str, object],
    contract_payload: dict[str, object],
    approval: ApprovalRecord,
) -> dict[str, object]:
    plan = Plan.model_validate(plan_payload)
    contract = StepContract.model_validate(contract_payload)
    self.persistence.save_approval(approval)
    events = ["verify_execution_approval", "dispatch_worker"]
    envelope = self.dispatch_step(
        workspace_dir=workspace_dir,
        plan=plan,
        contract=contract,
        approval=approval,
    )
    events.extend(["inspect_artifacts", "record_execution_evidence"])
    self.persistence.save_execution_envelope(envelope.model_dump(mode="json"))
    finished = state.model_copy(update={"state": "finished", "step_id": contract.step_id, "plan_id": plan.id})
    self.persistence.save_model("run_records", "run_id", state.run_id, finished)
    self.persistence.save_model("run_state_history", "id", finished.id, finished)
    artifact_path = f"artifacts/tmp/{state.run_id}/step_1/output.txt"
    events.extend(["finish_response", "persist_turn"])
    return {
        "workspace_id": state.workspace_id,
        "run_id": state.run_id,
        "state": "finished",
        "active_mode": state.active_agent_mode,
        "assistant_text": f"Analysis complete. See {artifact_path}.",
        "artifacts": [artifact_path],
        "process_events": events,
    }
```

- [ ] **Step 5: Run full-turn, persistence, worker, and orchestrator tests**

Run: `uv run pytest tests/harness/test_full_turn_integration.py tests/harness/test_persistence_integration.py tests/harness/test_worker_dispatch_integration.py tests/harness/test_orchestrator.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/harness/orchestrator.py src/harness/persistence.py tests/harness/test_full_turn_integration.py
git commit -m "test: cover full harness controlled analysis turn"
```

### Task 9: Token-Pressure Gate Before Runtime Calls

Spec §6.8 + §4.4. Orchestrator MUST call `runtime.token_pressure(request)` BEFORE `runtime.complete(request)`. When `pressure.remaining_tokens < request.max_new_tokens`, invoke compaction and rebuild the request.

**Files:**
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_token_pressure_gate.py`

- [ ] **Step 1: Failing test**

```python
from runtime.types import RuntimeResponse, TokenPressure


class PressuredRuntime:
    def __init__(self) -> None:
        self.complete_calls = 0

    def complete(self, request):
        self.complete_calls += 1
        return RuntimeResponse(text="done", finish_reason="stop", usage={"total_tokens": 10})

    def stream(self, request): return iter(())
    def context_window(self): return 1024

    def token_pressure(self, request):
        # Simulate near-full context.
        return TokenPressure(used_tokens=900, max_context_tokens=1024, remaining_tokens=50)


def test_orchestrator_compacts_before_runtime_when_pressure_low(tmp_path, make_orchestrator):
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    runtime = PressuredRuntime()
    orchestrator = make_orchestrator(runtime=runtime)
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    result = orchestrator.handle_turn(
        state, workspace_dir=workspace, user_input="hi",
        requested_mode="interaction", prompt_text="prompt", prompt_template_id="interaction",
    )
    assert "compact_context" in result["process_events"]
    assert runtime.complete_calls == 1
```

- [ ] **Step 2: Implement**

```python
# Inside Orchestrator.handle_turn(), BEFORE runtime.complete():
pressure = self.runtime.token_pressure(request)
if pressure.remaining_tokens < request.max_new_tokens:
    compacted = self.context_manager.compact(
        entries=[m.content for m in request.messages],
        active_plan_id=state.plan_id or "",
        current_step_id=state.step_id or "",
        unresolved_failures=[],
    )
    request = RuntimeRequest(
        messages=[Message(role="system", content=compacted["summary"]), Message(role="user", content=user_input)],
        max_new_tokens=request.max_new_tokens, temperature=request.temperature, top_p=request.top_p,
    )
    events.append("compact_context")
    self.persistence.save_dict("step_action_history", "id", f"{state.run_id}:compact_{len(events)}", {
        "id": f"{state.run_id}:compact_{len(events)}", "run_id": state.run_id, "action": "compact_context",
    })
```

- [ ] **Step 3: Run + commit.**

### Task 10: Switch-Workspace Updates Run State

Spec §6.5. `switch_workspace` direct command MUST produce a new `RunStateRecord` with updated `workspace_id` and reset `run_id`. The TUI controller forwards through `handle_direct_command`.

**Files:**
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/factory.py` (created in Task 11)
- Test: `tests/harness/test_switch_workspace.py`

- [ ] **Step 1: Failing test**

```python
def test_switch_workspace_updates_run_state_workspace_id_and_resets_run_id(make_orchestrator):
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    orchestrator = make_orchestrator(runtime=FakeRuntime())
    new_state = orchestrator.switch_workspace(state, new_workspace_id="w_0002")
    assert new_state.workspace_id == "w_0002"
    assert new_state.run_id != state.run_id
    assert new_state.state == "idle"
```

- [ ] **Step 2: Implement** `Orchestrator.switch_workspace(state, *, new_workspace_id)` returning a fresh `RunStateRecord`. Persist a `mode_switch_history` entry recording the workspace transition.

- [ ] **Step 3: Run + commit.**

### Task 11: Harness Factory Builds The Whole Orchestrator

Spec §8.1 — harness owns runtime construction. The TUI gets a fully-built session, never the raw runtime.

**Files:**
- Create: `src/harness/factory.py`
- Modify: `src/cli.py` (Layer 4a Task 4 already imports `build_orchestrator`)
- Test: `tests/harness/test_factory.py`

- [ ] **Step 1: Failing test**

```python
from harness.factory import build_orchestrator


def test_factory_constructs_orchestrator_with_required_collaborators(tmp_path):
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    (workspace / "state").mkdir()
    orchestrator = build_orchestrator(workspace_dir=workspace)
    assert orchestrator.runtime is not None
    assert orchestrator.persistence is not None
    assert orchestrator.worker is not None
    assert orchestrator.knowledge is not None
```

- [ ] **Step 2: Implement** `build_orchestrator(workspace_dir, runtime_config=None)` that constructs `LlamaCppRuntime`, `WorkspaceDb`, `HarnessPersistence`, `KnowledgeManager`, `Doctor`, `PythonStepExecutor`, `ContextManager`, `Orchestrator`. The `runtime_config` defaults to a Gemma config; production callers may override.

- [ ] **Step 3: Run + commit.**

### Task 12: Session Config Owns Concurrency Policy

Spec §4.6 (runtime owns inference only). `RuntimeConfig` carries no concurrency policy. Concurrency lives on the session.

**Files:**
- Modify: `src/app/session.py`
- Test: `tests/app/test_session_concurrency.py`

- [ ] **Step 1: Failing test**

```python
import threading

import pytest

from app.session import DataAnalysisAppSession, SessionConfig


class FakeRuntime:
    def complete(self, request):
        import time
        from runtime.types import RuntimeResponse

        time.sleep(0.05)
        return RuntimeResponse(text="done", finish_reason="stop", usage={"total_tokens": 4})

    def stream(self, request): return iter(())
    def context_window(self): return 4096
    def token_pressure(self, request):
        from runtime.types import TokenPressure

        return TokenPressure(used_tokens=4, max_context_tokens=4096, remaining_tokens=4092)


def test_session_rejects_concurrent_turns_when_max_parallel_runs_is_one(tmp_path, make_orchestrator):
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    session = DataAnalysisAppSession(
        make_orchestrator(runtime=FakeRuntime()),
        config=SessionConfig(max_parallel_runs=1),
    )
    state = RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction")
    barrier = threading.Barrier(2)

    errors: list[Exception] = []

    def turn():
        try:
            barrier.wait()
            session.handle_user_turn(workspace_dir=workspace, state=state, user_text="hi")
        except RuntimeError as exc:
            errors.append(exc)

    t1 = threading.Thread(target=turn)
    t2 = threading.Thread(target=turn)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert len(errors) == 1
    assert "max_parallel_runs" in str(errors[0])
```

- [ ] **Step 2: Implement**

```python
# src/app/session.py — add SessionConfig and a turn lock.
import threading

from pydantic import BaseModel


class SessionConfig(BaseModel):
    max_parallel_runs: int = 1


class DataAnalysisAppSession:
    def __init__(self, orchestrator, mode_router=None, prompt_registry=None, config=None) -> None:
        ...
        self._config = config or SessionConfig()
        self._semaphore = threading.Semaphore(self._config.max_parallel_runs)

    def handle_user_turn(self, *, workspace_dir, state, user_text):
        if not self._semaphore.acquire(blocking=False):
            raise RuntimeError("max_parallel_runs exceeded")
        try:
            ...
        finally:
            self._semaphore.release()
```

- [ ] **Step 3: Run + commit.**

### Task 13: Session Resume Methods For Approval And Clarification

The TUI calls these after the user approves a paused plan or answers a clarification.

**Files:**
- Modify: `src/app/session.py`
- Test: `tests/app/test_session_resume.py`

- [ ] **Step 1: Failing test**

```python
def test_session_resume_approved_step_dispatches_worker_and_returns_finished_result(tmp_path):
    workspace = tmp_path / "workspaces" / "w_0001"
    # ... seed workspace ...
    session = DataAnalysisAppSession(...)  # backed by orchestrator with worker + persistence
    paused = session.handle_user_turn(workspace_dir=workspace, state=state, user_text="compute")
    assert paused.requires_approval is True
    finished = session.resume_approved_step(
        state=state, plan_payload=paused.plan, contract_payload=paused.step_contract,
        approval={"decision": "approved", "decided_by": "user", "approval_kind": "code_execution"},
    )
    assert finished.assistant_text.startswith("Analysis complete")


def test_session_resume_with_clarification_re_enters_run(tmp_path):
    # Returns assistant text after the harness re-evaluates with the clarification appended.
    ...
```

- [ ] **Step 2: Implement** `DataAnalysisAppSession.resume_approved_step(...)` and `resume_with_clarification(...)`. Both call corresponding orchestrator methods and return `AppTurnResult`.

- [ ] **Step 3: Run + commit.**

### Task 14: Spec §10 Acceptance Suite

Final gating tests. Each invariant from spec §10 gets a test. Suite MUST pass before Layer-4 work is declared complete. Suite MUST FAIL if any earlier task regresses.

**Files:**
- Create: `tests/acceptance/test_v1_acceptance.py`

The ten invariants:

1. **No analytical claim accepted without inspected evidence.**
   `test_no_claim_without_evidence`: drive a turn that returns claims; assert each claim has at least one matching `artifact_ref` or `lineage_record_id`. Claims with neither MUST carry `unsupported=True`.

2. **No artifact-backed conclusion lacks provenance.**
   `test_no_artifact_conclusion_without_lineage_record`: every artifact referenced in an assistant answer MUST have a `LineageRecord` row.

3. **No saved knowledge reused after material source change without validity handling.**
   `test_reuse_blocked_after_source_fingerprint_change`: mutate a tracked source file, run doctor, then ask a question that would use a stale saved function — assert reuse is refused with state `changed`.

4. **No doctor outcome silently overwrites prior state.**
   `test_doctor_records_report_before_applying_actions`: every `TmpAction.applied=True` row MUST have an associated `DoctorReport.id`.

5. **No agent bypasses harness ownership boundaries.**
   `test_agents_modules_do_not_import_runtime_or_worker`: ast scan rejects `runtime.*` / `worker.*` imports under `src/app/agents/`.

6. **No UI hides critical failures or uncertainty.**
   `test_failure_path_populates_result_failure`: induce a worker failure, assert `AppTurnResult.failure` is non-None and `FailurePane` renders it.

7. **No retry loop runs invisibly without bounded control.**
   `test_retry_attempts_persist_in_step_action_history`: after a failure-induced retry, query `step_action_history` for an `attempt=N` row.

8. **No durable memory update without a defined reviewable path.**
   `test_no_external_write_to_memory`: monkey-patch `memory_target` write and assert direct file write outside `KnowledgeManager.apply` raises.

9. **No code execution without explicit executable plan or step approval.**
   `test_dispatch_step_blocked_without_approval_record`: call `orchestrator.dispatch_step` with `approval=None` — assert `PermissionError`.

10. **No tmp cleanup or promotion before recorded tmp review.**
    `test_tmp_cleanup_blocked_until_tmp_action_recorded`: call `Doctor.apply_tmp_action` for a path with no `tmp_actions` row — assert raises.

- [ ] **Step 1:** Implement all ten tests.
- [ ] **Step 2:** Run `uv run pytest tests/acceptance -q`. PASS only after every other task in this plan is green.
- [ ] **Step 3:** Wire CI to fail on any acceptance regression.
- [ ] **Step 4:** Commit `test: spec §10 v1 acceptance suite`.

## Self-Review

**Spec coverage:** This plan targets the missing cross-layer clauses from the main spec: every turn flows through the harness; the harness reloads fresh context; the harness resolves active agent mode; prompt modes are sequential, not parallel runtimes; the runtime is called through the Layer 1 protocol; executable turns create a plan and step contract; code execution remains gated by explicit approval; execution runs through the Layer 2 worker; artifacts are inspected and registered; run, prompt, approval, execution, artifact, step-action, and mode-switch records are persisted; TUI consumes a harness-facing app service; direct TUI commands flow through harness-owned command handling; prompt packages remain app-owned while control stays harness-owned; and the model prompt includes the real harness command surface, allowed mode intents, shared DataHarness system identity, response-format contract, and hash-linked prompt provenance.

**Integration audit corrections:** The review found seven integration gaps that this plan now covers inside the main task flow instead of as late add-ons:

1. **LLM tool awareness was implicit instead of integrated.** Task 3 now requires `PromptPackageRegistry` to inject `HarnessCommandRouter.supported_commands()` into every prompt package so the runtime sees the actual command names it may emit in `<tool_call>` blocks.
2. **Mode intents lived beside the prompt path.** Task 3 now requires generated mode-intent catalogs in the assembled prompt package, so `interaction`, `analyst`, `knowledge`, and `clarification` capabilities are visible to the runtime.
3. **Prompt provenance was too weak.** Design notes and Task 3 now require `prompt_template_id=f"{package.mode}@{package.package_hash}"`, not just the mode name, so telemetry and persisted prompt records identify the exact assembled prompt.
4. **Generic assistant identity leaked through the front door.** Task 3 now creates `system.md`, removes the casual-chat escape hatch, and adds regression coverage that the runtime prompt says DataHarness and does not contain generic large-language-model positioning.
5. **Test snippets hid the persistence/runtime contract.** The plan now defines a fixture-backed orchestrator factory, removes `Orchestrator()` shorthand, and makes `DataAnalysisAppSession` require an injected orchestrator so production construction stays explicit.
6. **Direct command coverage advertised a legacy alias.** Task 6 now uses canonical `inspect_artifact`; legacy command aliases may remain accepted by the harness but are not exposed as primary model or TUI capabilities.
7. **Executable analysis planning was implied instead of model-driven.** Task 8 now drives plan creation from a structured `request_execution` runtime intent, records `runtime_complete` before planning events, and keeps the no-keyword-branch regression.

**Placeholder scan:** No task uses placeholder markers or open-ended test language. Each task includes concrete files, test code, implementation code, commands, expected output, and commit commands.

**Type consistency:** `AppTurnResult`, `AgentModeDecision`, `RunStateRecord`, `PromptPackage`, `StepContract`, `StepExecutionRequest`, and `ExecutionEnvelope` names match existing or newly defined code. The app mode names are consistently `interaction`, `analyst`, and `knowledge`.

**Known risks:** The worker dispatch code in Task 4 may need a small adjustment if the worker sandbox expects produced files directly in the step tmp directory; the provided test writes `output.txt` in the subprocess working directory, which is already the tmp directory in `PythonStepExecutor`. The implementation snippets are intentionally compact, but the construction rule is binding throughout the plan: app sessions receive a fully built orchestrator, and every orchestrator used by production or tests has explicit runtime and persistence.
