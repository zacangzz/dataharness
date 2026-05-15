# Layer 4b Agent Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the application-defining agent modes that give the app its prompt identity, voice, and domain-specific analytical behavior.

**Architecture:** Implement the agent modes under `src/app/agents/` as prompt packages and small policy modules that run sequentially on the single runtime owned by the harness. The harness still owns accepted mode activation, transitions, provenance, runtime calls, and platform functions; Layer 4b owns prompt definitions, prompt assembly rules, harness-facing intent schemas, and role-specific behavior for `interaction`, `analyst`, and `knowledge`. Agent policies may propose a mode or harness intent, but the harness validates, records, and applies any state change. Avoid hardcoded app behavior in this layer except for validating or normalizing structured intents returned by the model.

**Tech Stack:** Python 3.12, `pydantic`, `pytest`, `hashlib`, `json`, markdown prompt files

---

## File Structure

**Create:**
- `src/app/agents/__init__.py`
- `src/app/agents/types.py`
- `src/app/agents/prompt_packages.py`
- `src/app/agents/interaction.py`
- `src/app/agents/analyst.py`
- `src/app/agents/knowledge.py`
- `src/app/agents/prompts/interaction.md`
- `src/app/agents/prompts/analyst.md`
- `src/app/agents/prompts/knowledge.md`
- `src/app/agents/prompts/clarification.md`
- `src/app/agents/prompts/response_format.md`
- `tests/app/agents/test_prompt_packages.py`
- `tests/app/agents/test_interaction_mode.py`
- `tests/app/agents/test_analyst_mode.py`
- `tests/app/agents/test_knowledge_mode.py`

### Task 1: Define Prompt Packages And Stable Prompt Hashing

**Files:**
- Create: `src/app/agents/__init__.py`
- Create: `src/app/agents/types.py`
- Create: `src/app/agents/prompt_packages.py`
- Create: `src/app/agents/prompts/interaction.md`
- Create: `src/app/agents/prompts/analyst.md`
- Create: `src/app/agents/prompts/knowledge.md`
- Create: `src/app/agents/prompts/clarification.md`
- Create: `src/app/agents/prompts/response_format.md`
- Test: `tests/app/agents/test_prompt_packages.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from app.agents.prompt_packages import PromptPackageRegistry


def test_prompt_registry_hashes_prompt_package_contents(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "interaction.md").write_text("hello")
    (prompts_dir / "response_format.md").write_text("format")
    registry = PromptPackageRegistry(prompts_dir)
    package = registry.load("interaction")
    assert package.mode == "interaction"
    assert len(package.package_hash) == 64
    assert "format" in package.prompt_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/agents/test_prompt_packages.py -q`
Expected: FAIL with missing agent prompt registry

- [ ] **Step 3: Write minimal implementation**

```python
# src/app/agents/types.py
from __future__ import annotations

from pydantic import BaseModel


class PromptPackage(BaseModel):
    mode: str
    template_version: str
    prompt_text: str
    package_hash: str
```

```python
# src/app/agents/prompt_packages.py
from __future__ import annotations

import hashlib
from pathlib import Path

from app.agents.types import PromptPackage


class PromptPackageRegistry:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir

    def load(self, mode: str) -> PromptPackage:
        parts = [
            (self.prompts_dir / f"{mode}.md").read_text(),
            (self.prompts_dir / "response_format.md").read_text(),
        ]
        prompt_text = "\n\n".join(parts)
        package_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        return PromptPackage(
            mode=mode,
            template_version="v1",
            prompt_text=prompt_text,
            package_hash=package_hash,
        )
```

```python
# src/app/agents/__init__.py
from app.agents.prompt_packages import PromptPackageRegistry

__all__ = ["PromptPackageRegistry"]
```

```markdown
<!-- src/app/agents/prompts/interaction.md -->
You are the interaction mode for the local data analysis application.
Handle the front-door user turn, keep responses concise, and decide whether the turn should route to analysis, knowledge capture, or clarification.
```

```markdown
<!-- src/app/agents/prompts/analyst.md -->
You are the data analyst mode for the local data analysis application.
Use harness planning, execution, artifact inspection, saved function reuse, and provenance-backed reporting to answer analytical questions.
```

```markdown
<!-- src/app/agents/prompts/knowledge.md -->
You are the knowledge mode for the local data analysis application.
Capture reusable workspace knowledge, preferences, notes, gaps, and function candidates through harness-owned memory services.
```

```markdown
<!-- src/app/agents/prompts/clarification.md -->
Ask one clear clarification question at a time when user intent is too ambiguous to proceed safely.
```

```markdown
<!-- src/app/agents/prompts/response_format.md -->
When you need a harness command or handoff, return one short status line followed by one structured tool call block.
Otherwise answer directly.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/app/agents/test_prompt_packages.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/agents/__init__.py src/app/agents/types.py src/app/agents/prompt_packages.py src/app/agents/prompts/interaction.md src/app/agents/prompts/analyst.md src/app/agents/prompts/knowledge.md src/app/agents/prompts/clarification.md src/app/agents/prompts/response_format.md tests/app/agents/test_prompt_packages.py
git commit -m "feat: add agent prompt package registry"
```

### Task 2: Implement Interaction Mode Prompt Assembly And Handoff Intents

**Files:**
- Create: `src/app/agents/interaction.py`
- Test: `tests/app/agents/test_interaction_mode.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from app.agents.interaction import InteractionMode
from app.agents.prompt_packages import PromptPackageRegistry


def test_interaction_mode_builds_prompt_turn_and_allowed_intents(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "interaction.md").write_text("interaction")
    (prompts_dir / "response_format.md").write_text("format")
    mode = InteractionMode(PromptPackageRegistry(prompts_dir))
    turn = mode.build_turn("what is the attrition rate?")
    assert turn["package"].mode == "interaction"
    assert "handoff_to_analyst" in turn["allowed_harness_intents"]
    assert "request_clarification" in turn["allowed_harness_intents"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/agents/test_interaction_mode.py -q`
Expected: FAIL with missing interaction mode

- [ ] **Step 3: Write minimal implementation**

```python
# src/app/agents/interaction.py
from __future__ import annotations

from app.agents.prompt_packages import PromptPackageRegistry


class InteractionMode:
    def __init__(self, registry: PromptPackageRegistry) -> None:
        self.registry = registry

    def build_turn(self, user_text: str) -> dict[str, object]:
        return {
            "package": self.registry.load("interaction"),
            "user_text": user_text,
            "allowed_harness_intents": [
                "answer_directly",
                "handoff_to_analyst",
                "handoff_to_knowledge",
                "request_clarification",
            ],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/app/agents/test_interaction_mode.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/agents/interaction.py tests/app/agents/test_interaction_mode.py
git commit -m "feat: add interaction mode routing"
```

### Task 3: Implement Analyst Mode As Harness-Managed Prompt Logic

**Files:**
- Create: `src/app/agents/analyst.py`
- Test: `tests/app/agents/test_analyst_mode.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from app.agents.analyst import AnalystMode
from app.agents.prompt_packages import PromptPackageRegistry


def test_analyst_mode_builds_prompt_turn_with_harness_intents(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "analyst.md").write_text("analyst")
    (prompts_dir / "response_format.md").write_text("format")
    mode = AnalystMode(PromptPackageRegistry(prompts_dir))
    result = mode.build_turn("calculate attrition rate")
    assert result["package"].mode == "analyst"
    assert "plan_analysis" in result["allowed_harness_intents"]
    assert "inspect_artifacts" in result["allowed_harness_intents"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/agents/test_analyst_mode.py -q`
Expected: FAIL with missing analyst mode

- [ ] **Step 3: Write minimal implementation**

```python
# src/app/agents/analyst.py
from __future__ import annotations

from app.agents.prompt_packages import PromptPackageRegistry


class AnalystMode:
    def __init__(self, registry: PromptPackageRegistry) -> None:
        self.registry = registry

    def build_turn(self, user_text: str) -> dict[str, object]:
        return {
            "package": self.registry.load("analyst"),
            "user_text": user_text,
            "allowed_harness_intents": [
                "knowledge_lookup",
                "plan_analysis",
                "request_execution",
                "inspect_artifacts",
                "record_provenance",
                "respond_to_user",
            ],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/app/agents/test_analyst_mode.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/agents/analyst.py tests/app/agents/test_analyst_mode.py
git commit -m "feat: add analyst mode harness contract"
```

### Task 4: Implement Knowledge Mode With Intent → MemoryUpdateProposal Handler

**Files:**
- Create: `src/app/agents/knowledge.py`
- Create: `src/app/agents/intent_handlers.py`
- Test: `tests/app/agents/test_knowledge_mode.py`
- Test: `tests/app/agents/test_intent_handlers.py`

Knowledge mode MUST end in a durable harness write path. Spec §7.16 flow 2: "knowledge agent turns user teaching into harness memory or saved-function updates." `build_turn` alone does not satisfy this; an intent handler converts the model's tool-call into a `MemoryUpdateProposal` submitted to `KnowledgeManager.propose_update` (Layer 3 plan, Task 8).

- [ ] **Step 1: Write the failing tests**

```python
# tests/app/agents/test_knowledge_mode.py
from pathlib import Path

from app.agents.knowledge import KnowledgeMode
from app.agents.prompt_packages import PromptPackageRegistry


def test_knowledge_mode_builds_prompt_turn_for_memory_capture(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "knowledge.md").write_text("knowledge")
    (prompts_dir / "response_format.md").write_text("format")
    mode = KnowledgeMode(PromptPackageRegistry(prompts_dir))
    result = mode.build_turn("remember that attrition = total leavers / average headcount")
    assert result["package"].mode == "knowledge"
    intents = set(result["allowed_harness_intents"])
    assert {"store_workspace_knowledge", "update_preferences", "record_gap", "save_function_candidate"} <= intents
```

```python
# tests/app/agents/test_intent_handlers.py
from app.agents.intent_handlers import handle_knowledge_intent


class FakeKnowledgeManager:
    def __init__(self) -> None:
        self.proposals: list[dict] = []

    def propose_update(self, *, memory_target: str, source_refs: list[str], proposed_content: str, conflicts: list[str] | None = None):
        proposal = {
            "memory_target": memory_target,
            "source_refs": source_refs,
            "proposed_content": proposed_content,
            "conflicts": conflicts or [],
            "status": "pending",
        }
        self.proposals.append(proposal)
        return proposal


def test_store_workspace_knowledge_intent_creates_pending_proposal_to_notes() -> None:
    manager = FakeKnowledgeManager()
    handle_knowledge_intent(
        manager,
        tool_call={"name": "store_workspace_knowledge", "arguments": {"title": "attrition", "content": "voluntary leavers / avg headcount", "source_refs": ["turn:r_1"]}},
    )
    assert manager.proposals[0]["memory_target"].startswith("memory/notes/")
    assert manager.proposals[0]["status"] == "pending"


def test_update_preferences_intent_targets_preferences_file() -> None:
    manager = FakeKnowledgeManager()
    handle_knowledge_intent(
        manager,
        tool_call={"name": "update_preferences", "arguments": {"key": "style", "value": "concise", "source_refs": ["turn:r_1"]}},
    )
    assert manager.proposals[0]["memory_target"] == "memory/preferences.json"


def test_record_gap_intent_targets_memory_notes_gaps() -> None:
    manager = FakeKnowledgeManager()
    handle_knowledge_intent(
        manager,
        tool_call={"name": "record_gap", "arguments": {"description": "missing department mapping", "source_refs": ["turn:r_1"]}},
    )
    assert manager.proposals[0]["memory_target"].startswith("memory/notes/gaps/")


def test_save_function_candidate_intent_targets_memory_functions() -> None:
    manager = FakeKnowledgeManager()
    handle_knowledge_intent(
        manager,
        tool_call={"name": "save_function_candidate", "arguments": {"name": "attrition_rate", "code": "def attrition_rate(...): ...", "source_refs": ["turn:r_1"]}},
    )
    assert manager.proposals[0]["memory_target"].startswith("memory/functions/")
    assert "def attrition_rate" in manager.proposals[0]["proposed_content"]


def test_unknown_intent_raises_so_caller_can_record_failure() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown knowledge intent"):
        handle_knowledge_intent(FakeKnowledgeManager(), tool_call={"name": "bogus", "arguments": {}})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/app/agents/test_knowledge_mode.py tests/app/agents/test_intent_handlers.py -q`
Expected: FAIL — knowledge mode + intent handlers missing.

- [ ] **Step 3: Implement knowledge mode**

```python
# src/app/agents/knowledge.py
from __future__ import annotations

from app.agents.prompt_packages import PromptPackageRegistry


class KnowledgeMode:
    def __init__(self, registry: PromptPackageRegistry) -> None:
        self.registry = registry

    def build_turn(self, user_text: str) -> dict[str, object]:
        return {
            "package": self.registry.load("knowledge"),
            "user_text": user_text,
            "allowed_harness_intents": [
                "store_workspace_knowledge",
                "update_preferences",
                "record_gap",
                "save_function_candidate",
                "request_clarification",
            ],
        }
```

- [ ] **Step 4: Implement intent handler**

```python
# src/app/agents/intent_handlers.py
from __future__ import annotations

import re
from typing import Any, Protocol


class KnowledgeManagerProtocol(Protocol):
    def propose_update(self, *, memory_target: str, source_refs: list[str], proposed_content: str, conflicts: list[str] | None = None) -> Any: ...


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-") or "untitled"


def handle_knowledge_intent(manager: KnowledgeManagerProtocol, *, tool_call: dict[str, Any]) -> Any:
    name = tool_call.get("name")
    arguments = tool_call.get("arguments") or {}
    source_refs = list(arguments.get("source_refs") or [])

    if name == "store_workspace_knowledge":
        target = f"memory/notes/{_slug(arguments['title'])}.md"
        return manager.propose_update(
            memory_target=target,
            source_refs=source_refs,
            proposed_content=arguments["content"],
        )
    if name == "update_preferences":
        return manager.propose_update(
            memory_target="memory/preferences.json",
            source_refs=source_refs,
            proposed_content=f'{{"{arguments["key"]}": {arguments["value"]!r}}}',
        )
    if name == "record_gap":
        target = f"memory/notes/gaps/{_slug(arguments['description'])[:40]}.md"
        return manager.propose_update(
            memory_target=target,
            source_refs=source_refs,
            proposed_content=arguments["description"],
        )
    if name == "save_function_candidate":
        target = f"memory/functions/{_slug(arguments['name'])}.py"
        return manager.propose_update(
            memory_target=target,
            source_refs=source_refs,
            proposed_content=arguments["code"],
        )
    raise ValueError(f"unknown knowledge intent: {name}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/app/agents -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/app/agents/knowledge.py src/app/agents/intent_handlers.py tests/app/agents/test_knowledge_mode.py tests/app/agents/test_intent_handlers.py
git commit -m "feat: knowledge intents create memory update proposals"
```

### Task 5: Add Clarification Intent And Resume Path

**Files:**
- Modify: `src/app/agents/interaction.py`
- Modify: `src/app/agents/prompts/interaction.md`
- Modify: `src/app/agents/prompts/clarification.md`
- Test: `tests/app/agents/test_clarification_flow.py`

Spec §7.16 flow 5. The interaction agent MUST request clarification when intent is too ambiguous to proceed. The harness owns the resume rules; this task only contributes the prompt instruction and a parser test.

- [ ] **Step 1: Write the failing test**

```python
# tests/app/agents/test_clarification_flow.py
from pathlib import Path

from app.agents.interaction import InteractionMode
from app.agents.prompt_packages import PromptPackageRegistry


def test_interaction_prompt_text_instructs_model_to_emit_clarification_tool_call(tmp_path: Path) -> None:
    prompts_dir = Path("src/app/agents/prompts")
    mode = InteractionMode(PromptPackageRegistry(prompts_dir))
    turn = mode.build_turn("rate")
    text = turn["package"].prompt_text.lower()
    assert "request_clarification" in text
    assert "tool_call" in text
    assert "request_clarification" in turn["allowed_harness_intents"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/agents/test_clarification_flow.py -q`
Expected: FAIL — interaction prompt does not yet name the tool call.

- [ ] **Step 3: Update prompt content + interaction mode**

```markdown
<!-- src/app/agents/prompts/interaction.md -->
You are the interaction mode for the local data analysis application.
Handle the front-door user turn. Keep responses concise.

When the user's intent is too ambiguous to proceed safely, emit exactly one structured tool_call:
<tool_call>{"name":"request_clarification","arguments":{"question":"..."}}</tool_call>
Otherwise route to analysis or knowledge capture, or answer directly.
```

```python
# src/app/agents/interaction.py — add request_clarification to allowed intents
class InteractionMode:
    def __init__(self, registry: PromptPackageRegistry) -> None:
        self.registry = registry

    def build_turn(self, user_text: str) -> dict[str, object]:
        return {
            "package": self.registry.load("interaction"),
            "user_text": user_text,
            "allowed_harness_intents": [
                "answer_directly",
                "handoff_to_analyst",
                "handoff_to_knowledge",
                "request_clarification",
            ],
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/app/agents -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/agents/interaction.py src/app/agents/prompts/interaction.md tests/app/agents/test_clarification_flow.py
git commit -m "feat: interaction mode emits structured clarification intent"
```

### Task 6: Analyst Gap Intent Routes Through Knowledge Handler

**Files:**
- Modify: `src/app/agents/analyst.py`
- Test: `tests/app/agents/test_analyst_mode.py`

Spec §7.16 flow 3 (gap loop). Analyst can record an unresolved semantic gap. The intent reuses the `record_gap` handler from Task 4.

- [ ] **Step 1: Add failing test**

```python
def test_analyst_mode_allows_record_gap_intent(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "analyst.md").write_text("analyst")
    (prompts_dir / "response_format.md").write_text("format")
    mode = AnalystMode(PromptPackageRegistry(prompts_dir))
    result = mode.build_turn("there is no department field")
    assert "record_gap" in result["allowed_harness_intents"]
```

- [ ] **Step 2: Add `record_gap` to analyst's `allowed_harness_intents` list.**

- [ ] **Step 3: Run + commit.**

### Task 7: Mode Router Returns A Request, Not A Decision

**Files:**
- Modify: `src/app/agents/router.py`
- Test: `tests/app/agents/test_router.py`

Spec §7.14: harness chooses when to activate a prompt mode. The router proposes; the harness disposes. Method MUST return an `AgentModeRequest`, and the session MUST consult `result["active_mode"]` from the orchestrator (which may differ from the request when the harness rejects the switch — e.g. during `executing` or `awaiting_approval`).

- [ ] **Step 1: Failing test**

```python
def test_router_returns_request_object_not_authoritative_decision() -> None:
    router = AgentModeRouter()
    request = router.request_mode("compare attrition by department")
    assert request.mode == "analyst"
    assert request.reason == "analysis_intent"
    # The class name signals it is a request, not a decision.
    assert type(request).__name__ == "AgentModeRequest"
```

- [ ] **Step 2:** Rename `AgentModeDecision` → `AgentModeRequest`. Add `request_mode` method (keep `route` as deprecated alias).
- [ ] **Step 3:** Update integration plan call sites. Run tests + commit.

### Task 8: Provenance Linkage Between Agent Prompt Hash And Harness PromptPackage

**Files:**
- Modify: `src/app/session.py` (touched in integration plan)
- Test: `tests/app/test_session_integration.py`

Spec §6.14, §8.4. The harness `PromptPackage.prompt_template_id` MUST encode the exact prompt hash so provenance can reproduce the prompt that shaped any answer.

- [ ] **Step 1: Failing test**

```python
def test_session_passes_template_id_with_package_hash_to_orchestrator(tmp_path: Path) -> None:
    # FakeOrchestrator captures the prompt_template_id passed in.
    captured = {}

    class FakeOrch:
        def handle_turn(self, state, **kwargs):
            captured.update(kwargs)
            return {"workspace_id": state.workspace_id, "run_id": state.run_id, "active_mode": kwargs["requested_mode"], "assistant_text": "", "process_events": []}

    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")
    session = DataAnalysisAppSession(orchestrator=FakeOrch())
    session.handle_user_turn(
        workspace_dir=workspace,
        state=RunStateRecord(workspace_id="w_0001", active_agent_mode="interaction"),
        user_text="hello",
    )
    template_id = captured["prompt_template_id"]
    assert template_id.startswith("interaction@")
    assert len(template_id.split("@", 1)[1]) == 64  # sha256 hex
```

- [ ] **Step 2:** In `src/app/session.py`, set `prompt_template_id=f"{package.mode}@{package.package_hash}"`. Implement.
- [ ] **Step 3:** Run + commit.

## Self-Review

**Spec coverage:**
- Covers Layer 4b prompt ownership, prompt-package hashing and assembly, harness-facing agent intents, analyst/knowledge behavior, and the rule that agent modes are sequential harness-managed prompt modes rather than parallel runtimes.
- Cross-layer ownership is completed by `2026-04-24-layer-integration-loose-ends.md`: this plan proposes mode and harness intents, while the integration plan requires the harness to validate, accept or reject, record, and activate mode changes.

**Placeholder scan:**
- No placeholder markers remain.

**Type consistency:**
- `PromptPackage`, `PromptPackageRegistry`, `InteractionMode`, `AnalystMode`, and `KnowledgeMode` are used consistently across tasks.
