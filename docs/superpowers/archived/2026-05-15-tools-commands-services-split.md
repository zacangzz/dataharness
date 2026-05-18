# Tools, Commands, And Services Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every exposed DataHarness operation clearly classified as either a model-callable Tool or a Layer 4 reachable Command, with shared internals documented as Services.

**Architecture:** Layer 1 remains parse-only for model-emitted `<tool_call>` blocks. Layer 3 owns two explicit exposed registries: LLM Tools and Harness Commands. Shared implementation belongs in services and may be called by tools or commands, but services are not exposed surfaces. Implement the full split in one pass: tool registry, prompt call-site migration, dispatch enforcement, command-family source organization, Layer 4 reachability tests, and docs.

**Tech Stack:** Python 3.13, Pydantic, existing harness/app/runtime modules, pytest, Markdown docs.

---

## File Structure

- Modify: `docs/app/tools-vs-commands.md`
  - Rewrite the taxonomy around Tool, Command, and Service.
  - Document Option A tool consolidation using operation-based umbrella tools.
  - List current and target tool/command families.
- Create: `docs/app/services.md`
  - Define services as internal Layer 3 implementation units.
  - Document how services are shared by tools and commands without becoming exposed surfaces.
- Modify: `src/harness/command_registry.py`
  - Keep command registration user/app-facing.
  - Add enforcement helpers only if needed for rejecting model access to commands.
- Create: `src/harness/tools/registry.py`
  - Define the model-callable tool registry, descriptors, `ToolContext`, allowed-value validation, and regex validation.
- Create: `src/harness/tools/file.py`
  - Implement `file_read` with `operation=list|inspect|content`.
- Create: `src/harness/tools/control.py`
  - Register model-emitted control intents that are consumed by the agentic control loop.
- Create: `src/harness/tools/analysis.py`
  - Move/adapt `plan_analysis` and `request_execution` as analysis-family tools.
- Create: `src/harness/tools/knowledge.py`
  - Move knowledge proposal/recall model-callable behavior behind knowledge-family tools.
- Create: `src/harness/commands/`
  - Required command-family home for chat, workspace, doctor, compact, run, memory, and provenance command registration in this implementation.
- Modify: `src/harness/orchestrator.py`
  - Dispatch model tool calls through the tool registry only.
  - Dispatch Layer 4 commands through the command registry only.
- Modify: `src/app/agents/prompt_packages.py`
  - Build the prompt tool catalog from the tool registry, not command descriptors.
- Modify: `src/app/session.py`
  - Pass `orchestrator.tool_registry` into `PromptPackageRegistry`; do not pass `orchestrator.registry`.
- Modify: `src/app/agents/prompts/interaction.md`
  - Replace `list_files`, `inspect_file`, `read_file` examples with `file_read` operation examples.
- Modify: `src/app/agents/prompts/analyst.md`
  - Replace schema/content examples with `file_read`.
  - Keep analysis planning examples under the analysis tool family.
- Modify: `CODEMAP.md`
  - Required if new `src/harness/tools/*` or `src/harness/commands/*` modules are added.
- Test: `tests/harness/test_tool_registry.py`
  - Cover tool registry inventory, argument validation, allowed values, regex validation, and command rejection.
- Test: `tests/harness/test_file_read_tool.py`
  - Cover `file_read` operations.
- Test: `tests/app/tui/test_command_reachability.py`
  - Cover that command registry entries are reachable from the Layer 4 command catalog.
- Modify: existing prompt and agentic turn tests that assert old tool names.

Do not commit these changes unless the user explicitly asks for a commit.

## Single-Pass Completion Rule

Do not split this work into implementation phases. The implementation is not complete until all of these are true in the same change set:

- Model dispatch uses `HarnessToolRegistry` only and cannot fall back to `HarnessCommandRegistry`.
- Prompt packages are backed by `tool_registry` at every production constructor/call site, especially `src/app/session.py`.
- Tests that assert advertised tools construct `PromptPackageRegistry` with an orchestrator-backed `tool_registry`.
- Command registration is organized under `src/harness/commands/` by family.
- Layer 4 command reachability is tested against the command registry.
- `CODEMAP.md` is updated for all new imports, definitions, and call sites.

---

### Task 1: Update The Taxonomy Docs

**Files:**
- Modify: `docs/app/tools-vs-commands.md`
- Create: `docs/app/services.md`

- [ ] **Step 1: Replace the top-level definitions in `tools-vs-commands.md`**

Write the definitions exactly this way:

```markdown
- **Tool**: model-callable surface emitted as a `<tool_call>` through Layer 1 parsing, then validated and dispatched by Layer 3.
- **Command**: user/app-callable harness surface invoked from Layer 4 TUI, slash commands, command palette, or app controls, then validated and dispatched by Layer 3.
- **Service**: internal implementation unit, usually Layer 3, that owns domain logic used by tools and/or commands. Services are not directly exposed to the model or TUI.
```

- [ ] **Step 2: Add the no-orphan invariant**

Add this rule near the definitions:

```markdown
No exposed harness operation may be surface-less.

If the model can call it, it is a Tool and must be listed in the tool registry and prompt catalog.
If the user or app can call it, it is a Command and must be listed in the command registry and reachable from Layer 4.
If neither is true, it is an internal Service/helper and must not be documented as a tool or command.

Model-emitted control intents that use `<tool_call>` are Tools in the `control` family even when their handler only updates the agentic control loop.

Tool argument descriptors must support deterministic validation before handler execution: required fields, type coercion, allowed values, and regex checks for bounded string/path formats.
```

- [ ] **Step 3: Document target tool families**

Add these target tool families:

```markdown
## Tool Families

### Core Tools
- `file_read`: read-only workspace file discovery and inspection with `operation=list|inspect|content`.
- `file_write`: target definition for workspace-bound writes; do not register it in this pass.
- `shell_command`: target definition for tightly allowlisted read-only shell execution; do not register it in this pass.

### Control Tools
- `answer_directly`: model control signal consumed by the agentic loop.
- `handoff_to_analyst`: model control signal consumed by the agentic loop.
- `handoff_to_knowledge`: model control signal consumed by the agentic loop.
- `request_clarification`: model control signal consumed by the agentic loop.
- `respond_to_user`: model control signal consumed by the agentic loop.

### Analysis Tools
- `analysis_plan`: create a validated analysis plan and emit `ApprovalRequired`.
- `analysis_request_execution`: re-emit approval for an existing pending plan step.
- `analysis_inspect_artifact`: inspect analysis artifacts.
- `analysis_inspect_provenance`: inspect lineage for analysis outputs.
- `analysis_inspect_validity`: inspect trust/validity state for results.

### Knowledge Tools
- `knowledge_recall`: retrieve saved workspace knowledge.
- `knowledge_propose_update`: propose notes, preferences, gaps, or function candidates without bypassing review.
```

- [ ] **Step 4: Document target command families**

Add these command families:

```markdown
## Command Families

### App Commands
- `help`
- `exit` / `quit` handled locally by Layer 4 when appropriate.

### Chat Commands
- `create_chat`
- `list_chats`
- `view_chat`
- `resume_chat`
- `delete_chat`
- `compact`

### Workspace Commands
- `list_workspaces`
- `create_workspace`
- `rename_workspace`
- `delete_workspace`
- `switch_workspace`
- `workspace_status`
- `workspace_inventory`

### Doctor Commands
- `doctor`
- doctor action review/application paths surfaced by Layer 4 approval UI.

### Run And Review Commands
- `cancel_run`
- `stop_after_current_step`
- `retry_step`
- `rerun_step`
- `revise_goal`
- `mark_result_trusted`
- `mark_result_invalidated`
- `challenge_conclusion`

### Memory Commands
- `memory_review`
- memory proposal approval/rejection/application commands when added.
```

- [ ] **Step 5: Create `services.md`**

Create `docs/app/services.md` with this structure:

```markdown
# Services

Services are internal implementation units. They are not Tools and they are not Commands.

## Boundary Rule

- Tools expose model-callable operations.
- Commands expose Layer 4 user/app-callable operations.
- Services hold shared domain logic used by tools, commands, or orchestrator workflows.

## Why Services Exist

Services prevent duplicated logic between model-callable tools and user-callable commands. A command and a tool may both inspect workspace facts, but the workspace inspection logic should live once in a service and be wrapped by separate exposed surfaces.

## Current Service Areas

- Chat service: chat records, compaction, runtime request building.
- Workspace service: workspace listing, activation, ingest, inventory.
- Doctor service: diagnostics, tmp review, source checks, proposed actions.
- Knowledge service: preferences, notes, gaps, function candidates, memory proposals.
- Analysis service: plan validation, step contracts, approval state, artifact/provenance access.
- Context service: durable workspace context, file schema snapshots, token-budgeted context assembly.
- Status service: authoritative workspace/run/chat status snapshots.

## Exposure Rule

A service method can be called by a tool, command, or orchestrator workflow. It must not appear directly in the prompt catalog, slash command catalog, command palette, or TUI controls unless wrapped by a Tool or Command descriptor.
```

- [ ] **Step 6: Self-check docs**

Run:

```bash
rg -n "runtime-callable harness tools|Knowledge Intent Tools|Current Edge Case: `read_file`|list_files|inspect_file|read_file" docs/app/tools-vs-commands.md docs/app/services.md
```

Expected:
- No stale section called `Current Edge Case: read_file`.
- Old file tool names only appear in migration notes or current inventory, not as target model-callable tools.

---

### Task 2: Introduce A Tool Registry Without Changing Behavior Yet

**Files:**
- Create: `src/harness/tools/__init__.py`
- Create: `src/harness/tools/registry.py`
- Test: `tests/harness/test_tool_registry.py`
- Modify: `CODEMAP.md`

- [ ] **Step 1: Write failing tests for registry inventory**

Create `tests/harness/test_tool_registry.py`:

```python
import pytest

from harness.tools.registry import HarnessToolRegistry, ToolArgSpec, ToolDescriptor


def test_tool_registry_lists_model_callable_tools_only():
    registry = HarnessToolRegistry()
    registry.register(
        ToolDescriptor(
            name="file_read",
            family="core",
            short_description="Read workspace file information",
            arguments=[
                ToolArgSpec(
                    name="operation",
                    type="str",
                    required=True,
                    description="list|inspect|content",
                    allowed_values=["list", "inspect", "content"],
                ),
            ],
        ),
        lambda _ctx, _args: None,
    )

    names = [tool.name for tool in registry.list_tools()]
    assert names == ["file_read"]


def test_tool_registry_rejects_unknown_tool():
    registry = HarnessToolRegistry()
    with pytest.raises(ValueError, match="unknown tool"):
        registry.validate("doctor", {})


def test_tool_registry_rejects_disallowed_value():
    registry = HarnessToolRegistry()
    registry.register(
        ToolDescriptor(
            name="file_read",
            family="core",
            short_description="Read workspace file information",
            arguments=[
                ToolArgSpec(
                    name="operation",
                    type="str",
                    required=True,
                    description="list|inspect|content",
                    allowed_values=["list", "inspect", "content"],
                ),
            ],
        ),
        lambda _ctx, _args: None,
    )

    with pytest.raises(ValueError, match="invalid value"):
        registry.validate("file_read", {"operation": "delete"})


def test_tool_registry_rejects_regex_mismatch():
    registry = HarnessToolRegistry()
    registry.register(
        ToolDescriptor(
            name="file_read",
            family="core",
            short_description="Read workspace file information",
            arguments=[
                ToolArgSpec(
                    name="path",
                    type="path",
                    required=True,
                    description="workspace-relative path",
                    regex=r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$)).+",
                ),
            ],
        ),
        lambda _ctx, _args: None,
    )

    with pytest.raises(ValueError, match="does not match"):
        registry.validate("file_read", {"path": "../secret.txt"})
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_tool_registry.py -q
```

Expected: import failure because `harness.tools.registry` does not exist.

- [ ] **Step 3: Implement minimal registry**

Create `src/harness/tools/registry.py`:

```python
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from harness.events import HarnessEvent

ToolFamily = Literal["core", "control", "analysis", "knowledge"]
ToolArgType = Literal["str", "int", "float", "bool", "path", "json"]


class ToolContext(BaseModel):
    workspace_id: str | None
    chat_id: str | None
    run_id: str | None
    has_pending_approval: bool
    has_pending_clarification: bool


class ToolArgSpec(BaseModel):
    name: str
    type: ToolArgType
    required: bool
    description: str
    example: str | None = None
    allowed_values: list[str] | None = None
    regex: str | None = None


class ToolDescriptor(BaseModel):
    name: str
    family: ToolFamily
    short_description: str
    arguments: list[ToolArgSpec] = Field(default_factory=list)


ToolHandler = Callable[[ToolContext, dict[str, Any]], AsyncIterator[HarnessEvent]]


class HarnessToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[ToolDescriptor, ToolHandler]] = {}

    def register(self, descriptor: ToolDescriptor, handler: ToolHandler) -> None:
        self._handlers[descriptor.name] = (descriptor, handler)

    def list_tools(self) -> list[ToolDescriptor]:
        return sorted((descriptor for descriptor, _ in self._handlers.values()), key=lambda d: d.name)

    def get_handler(self, name: str) -> ToolHandler:
        if name not in self._handlers:
            raise KeyError(name)
        return self._handlers[name][1]

    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._handlers:
            raise ValueError(f"unknown tool: {name}")
        descriptor, _ = self._handlers[name]
        validated: dict[str, Any] = {}
        for spec in descriptor.arguments:
            if spec.required and spec.name not in arguments:
                raise ValueError(f"missing required arg '{spec.name}' for {name}")
            if spec.name in arguments:
                value = self._coerce(spec, arguments[spec.name])
                if spec.allowed_values is not None and str(value) not in spec.allowed_values:
                    allowed = ", ".join(spec.allowed_values)
                    raise ValueError(f"invalid value for '{spec.name}' in {name}: {value!r}; expected one of {allowed}")
                if spec.regex is not None and not re.fullmatch(spec.regex, str(value)):
                    raise ValueError(f"'{spec.name}' for {name} does not match required pattern")
                validated[spec.name] = value
        return validated

    def _coerce(self, spec: ToolArgSpec, value: Any) -> Any:
        if spec.type == "json":
            return value
        if spec.type in {"str", "path"}:
            return str(value)
        if spec.type == "int":
            return int(value)
        if spec.type == "float":
            return float(value)
        if spec.type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).lower() in {"1", "true", "yes", "on"}
        return value
```

Create `src/harness/tools/__init__.py`:

```python
from harness.tools.registry import HarnessToolRegistry, ToolArgSpec, ToolContext, ToolDescriptor

__all__ = ["HarnessToolRegistry", "ToolArgSpec", "ToolContext", "ToolDescriptor"]
```

- [ ] **Step 4: Run tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_tool_registry.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Update `CODEMAP.md`**

Add imports/definitions for:

```text
src/harness/tools/__init__.py -> harness.tools.registry
src/harness/tools/registry.py -> re, harness.events
```

Add definitions:

```text
ToolContext
ToolArgSpec
ToolDescriptor
HarnessToolRegistry
```

---

### Task 3: Consolidate File Tools Into `file_read`

**Files:**
- Create: `src/harness/tools/file.py`
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_file_read_tool.py`
- Modify: `CODEMAP.md`

- [ ] **Step 1: Write failing tests for `file_read` operations**

Create `tests/harness/test_file_read_tool.py`:

```python
import pytest

from harness.events import CommandCompleted
from harness.orchestrator import Orchestrator
from harness.tools.registry import ToolContext


async def _complete(orch, name, ctx, args):
    validated = orch.tool_registry.validate(name, args)
    handler = orch.tool_registry.get_handler(name)
    events = [event async for event in handler(ctx, validated)]
    return next(event for event in events if isinstance(event, CommandCompleted))


def _ctx(workspace_id="w1"):
    return ToolContext(
        workspace_id=workspace_id,
        chat_id=None,
        run_id=None,
        has_pending_approval=False,
        has_pending_clarification=False,
    )


async def test_file_read_list_operation(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    ws = await orch.create_workspace("w1")
    (ws.workspace_dir / "data" / "sales.csv").write_text("a,b\n1,2\n")

    completed = await _complete(
        orch,
        "file_read",
        _ctx(),
        {"operation": "list"},
    )

    assert any(item["path"].endswith("sales.csv") for item in completed.result["files"])


async def test_file_read_inspect_operation(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    ws = await orch.create_workspace("w1")
    (ws.workspace_dir / "data" / "sales.csv").write_text("a,b\n1,2\n")

    completed = await _complete(
        orch,
        "file_read",
        _ctx(),
        {"operation": "inspect", "path": "data/sales.csv"},
    )

    assert completed.result["kind"] == "csv"
    assert completed.result["columns"] == ["a", "b"]


async def test_file_read_content_operation(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    ws = await orch.create_workspace("w1")
    (ws.workspace_dir / "data" / "notes.md").write_text("hello")

    completed = await _complete(
        orch,
        "file_read",
        _ctx(),
        {"operation": "content", "path": "data/notes.md"},
    )

    assert completed.result["content"] == "hello"


async def test_file_read_rejects_unknown_operation(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    await orch.create_workspace("w1")

    with pytest.raises(ValueError, match="invalid value"):
        orch.tool_registry.validate("file_read", {"operation": "delete", "path": "data/notes.md"})
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_file_read_tool.py -q
```

Expected: failure because `Orchestrator.tool_registry` and `file_read` do not exist.

- [ ] **Step 3: Implement `file_read` handler**

Create `src/harness/tools/file.py` with a factory function:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from harness.context import list_workspace_files, read_file_schema
from harness.events import CommandCompleted, CommandStarted, HarnessEvent
from harness.tools.registry import ToolContext


def make_file_read_handler(orchestrator):
    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        operation = str(args.get("operation") or "")
        path = str(args.get("path") or "")
        workspace_id = ctx.workspace_id or ""
        workspace_dir = orchestrator.workspace_manager.workspaces_dir / workspace_id

        yield CommandStarted(
            ts=datetime.now(UTC),
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            command="file_read",
            arguments=args,
        )

        if not workspace_dir.exists():
            result = {"error": "workspace not found"}
        elif operation == "list":
            result = {"workspace_id": workspace_id, "files": list_workspace_files(workspace_dir)}
        elif operation == "inspect":
            result = {"error": "missing required arg 'path'"} if not path else read_file_schema(workspace_dir, path)
        elif operation == "content":
            if not path:
                result = {"error": "missing required arg 'path'"}
            else:
                result = orchestrator._read_workspace_file_for_tool(
                    workspace_dir,
                    path,
                    max_bytes=int(args.get("max_bytes") or 65536),
                    encoding=str(args.get("encoding") or "utf-8"),
                )
        else:
            result = {"error": f"unknown file_read operation: {operation}"}

        yield CommandCompleted(
            ts=datetime.now(UTC),
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            command="file_read",
            result=result,
        )

    return handler
```

Expose `_read_workspace_file` safely from `Orchestrator` as a private wrapper:

```python
def _read_workspace_file_for_tool(self, workspace_dir: Path, path: str, *, max_bytes: int, encoding: str) -> dict[str, Any]:
    return _read_workspace_file(workspace_dir, path, max_bytes=max_bytes, encoding=encoding)
```

- [ ] **Step 4: Register `file_read` on orchestrator initialization**

In `Orchestrator.__init__`, after `self.registry = HarnessCommandRegistry()`:

```python
from harness.tools.registry import HarnessToolRegistry, ToolArgSpec, ToolDescriptor
from harness.tools.file import make_file_read_handler

self.tool_registry = HarnessToolRegistry()
```

After `_register_commands()` add `_register_tools()`:

```python
def _register_tools(self) -> None:
    self.tool_registry.register(
        ToolDescriptor(
            name="file_read",
            family="core",
            short_description="Read workspace file inventory, schema, or text content",
            arguments=[
                ToolArgSpec(
                    name="operation",
                    type="str",
                    required=True,
                    description="list|inspect|content",
                    example="inspect",
                    allowed_values=["list", "inspect", "content"],
                ),
                ToolArgSpec(
                    name="path",
                    type="path",
                    required=False,
                    description="workspace-relative path",
                    example="data/sales.csv",
                    regex=r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$)).*",
                ),
                ToolArgSpec(name="max_bytes", type="int", required=False, description="content byte cap", example="8192"),
                ToolArgSpec(name="encoding", type="str", required=False, description="text encoding", example="utf-8"),
            ],
        ),
        make_file_read_handler(self),
    )
```

- [ ] **Step 5: Run tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_file_read_tool.py tests/harness/test_read_file_tool.py tests/harness/test_list_files_command.py -q
```

Expected: existing command tests still pass and new `file_read` tests pass.

---

### Task 4: Register Control Tools And Enforce Tool Versus Command Dispatch

**Files:**
- Create: `src/harness/tools/control.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/app/agents/prompt_packages.py`
- Modify: `src/app/session.py`
- Test: `tests/harness/test_agentic_turn.py`
- Test: `tests/app/agents/test_prompt_packages.py`
- Modify: `CODEMAP.md` if imports changed

- [ ] **Step 1: Add failing tests for control tools and command rejection**

Add to `tests/harness/test_agentic_turn.py`:

```python
async def test_control_intents_are_registered_as_tools(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    names = {tool.name for tool in orch.tool_registry.list_tools()}

    assert "answer_directly" in names
    assert "handoff_to_analyst" in names
    assert "handoff_to_knowledge" in names
    assert "request_clarification" in names
    assert "respond_to_user" in names


async def test_model_tool_call_cannot_dispatch_harness_command(tmp_path, workspace):
    orch = Orchestrator(runtime=_Scenario(tool_calls=[{"name": "doctor", "arguments": {}}]), app_root=tmp_path)
    await orch.create_workspace(workspace.workspace_id)
    state = RunStateRecord(workspace_id=workspace.workspace_id, run_id="run_1", active_agent_mode="interaction")

    events = [
        event async for event in orch.run_agentic_turn(
            state,
            workspace_dir=workspace.workspace_dir,
            chat_id="chat_1",
            user_input="run doctor",
            prompt_provider=lambda _mode: "emit tool call",
        )
    ]

    completed = [event for event in events if getattr(event, "event_name", "") == "CommandCompleted"]
    assert any(event.command == "doctor" and "unknown tool" in event.result.get("error", "") for event in completed)
```

- [ ] **Step 2: Run failing test**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_agentic_turn.py -k "cannot_dispatch_harness_command" -q
```

Expected: failure because control intents are not yet in `tool_registry`, and `_dispatch_tool_call()` currently falls back to `self.registry.get_handler(name)`.

- [ ] **Step 3: Implement control tool registration**

Create `src/harness/tools/control.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from harness.events import CommandCompleted, HarnessEvent
from harness.tools.registry import ToolContext


CONTROL_TOOL_NAMES = [
    "answer_directly",
    "handoff_to_analyst",
    "handoff_to_knowledge",
    "request_clarification",
    "respond_to_user",
]


def make_control_handler(name: str):
    async def handler(ctx: ToolContext, args: dict[str, Any]) -> AsyncIterator[HarnessEvent]:
        yield CommandCompleted(
            ts=datetime.now(UTC),
            workspace_id=ctx.workspace_id,
            chat_id=ctx.chat_id,
            run_id=ctx.run_id,
            command=name,
            result={"ok": True, "note": f"{name} consumed by control loop", "arguments": args},
        )

    return handler
```

In `Orchestrator._register_tools()`, register each name in `CONTROL_TOOL_NAMES` with `family="control"` and no arguments. The existing handoff detection may continue to inspect raw tool calls for routing, but control names must also be visible through `tool_registry.list_tools()` and the prompt catalog.

- [ ] **Step 4: Change `_dispatch_tool_call()` to use only `tool_registry`**

Replace the registry fallback block:

```python
handler = self.registry.get_handler(name)
validated = self.registry.validate(name, args)
```

with:

```python
try:
    handler = self.tool_registry.get_handler(name)
except KeyError:
    yield CommandCompleted(
        ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
        command=name, result={"error": f"unknown tool: {name}"},
    )
    return

try:
    validated = self.tool_registry.validate(name, args)
except Exception as exc:
    yield CommandCompleted(
        ts=datetime.now(UTC), workspace_id=state.workspace_id, run_id=state.run_id,
        command=name, result={"error": f"invalid arguments: {exc}"},
    )
    return
```

Build the handler context with `ToolContext`, not `CommandContext`:

```python
ctx = ToolContext(
    workspace_id=state.workspace_id,
    chat_id=getattr(state, "chat_id", None),
    run_id=state.run_id,
    has_pending_approval=False,
    has_pending_clarification=False,
)
```

**Control intent dispatch — Option A (catalog-only, required):** The agentic loop at `orchestrator.py:1579` already skips `_TERMINAL_INTENTS` and `_HANDOFF_INTENTS` via `continue` before reaching `_dispatch_tool_call`. Control tool handlers in `tool_registry` are therefore for prompt catalog visibility only — they never fire at runtime. This is intentional.

Delete lines 1724-1729 in `_dispatch_tool_call()` (the early-return block for `_TERMINAL_INTENTS`/`_HANDOFF_INTENTS`) as dead-code cleanup. Do not remove the `continue` at line 1579 — loop termination routing stays there.

Also delete `list_runtime_callable()` from `HarnessCommandRegistry` (`command_registry.py:108-121`) and any callers. After this step, `HarnessToolRegistry.list_tools()` is the sole source of model-callable surface.

- [ ] **Step 5: Build prompt catalog from `tool_registry`**

In `src/app/agents/prompt_packages.py`, change `_tool_catalog(...)` to receive a tool registry or a list of tool descriptors. The catalog must list `file_read(...)` and control tools, and must not list command-only names such as `doctor`, `compact`, or `delete_workspace`.

Change `PromptPackageRegistry.__init__` from `command_registry=` to `tool_registry=` and update `src/app/session.py`:

```python
self.prompt_registry = prompt_registry or PromptPackageRegistry(
    Path(__file__).resolve().parent / "agents" / "prompts",
    tool_registry=getattr(self.orchestrator, "tool_registry", None),
)
```

Update all production call sites that pass `command_registry=`. Verify with:

```bash
rg -n "command_registry=" src/app tests/app
```

Expected after the migration:
- No `PromptPackageRegistry(..., command_registry=...)` calls remain.
- `src/app/session.py` passes `tool_registry=getattr(self.orchestrator, "tool_registry", None)`.
- Tests that assert advertised tool names pass `tool_registry=orch.tool_registry`.
- Tests that only check prompt hashing or mode text may keep constructing `PromptPackageRegistry(prompts_dir)` without a registry.

Example output lines:

```text
- `file_read(operation:str, path:path?, max_bytes:int?, encoding:str?)` — Read workspace file inventory, schema, or text content
- `handoff_to_analyst()` — Handoff to analyst mode
```

- [ ] **Step 6: Update prompt tests**

Update `tests/app/agents/test_prompt_packages.py` to build the package with an orchestrator-backed tool registry:

```python
from harness.orchestrator import Orchestrator


def test_prompt_package_advertises_tool_registry_not_commands(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    package = PromptPackageRegistry(
        Path("src/app/agents/prompts"),
        tool_registry=orch.tool_registry,
    ).load("interaction")
    text = package.prompt_text

    assert "file_read" in text
    assert "handoff_to_analyst" in text
    assert "list_files" not in text
    assert "inspect_file" not in text
    assert "read_file" not in text
    assert "doctor(" not in text
    assert "compact(" not in text
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_agentic_turn.py tests/app/agents/test_prompt_packages.py -q
```

Expected: all pass.

---

### Task 5: Move Analysis And Knowledge Into Tool Families

**Files:**
- Create: `src/harness/tools/analysis.py`
- Create: `src/harness/tools/knowledge.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/app/agents/prompts/analyst.md`
- Modify: `src/app/agents/prompts/interaction.md`
- Modify: `src/app/agents/prompt_packages.py`
- Test: `tests/harness/test_plan_analysis_command.py`
- Test: `tests/harness/test_agentic_turn.py`
- Test: `tests/app/agents/test_prompt_packages.py`
- Modify: `CODEMAP.md`

- [ ] **Step 1: Register analysis aliases while keeping command compatibility**

Add model-facing tools:

```text
analysis_plan -> existing plan_analysis behavior
analysis_request_execution -> existing request_execution behavior
```

Keep `/plan_analysis` and `/request_execution` as harness commands during migration so old TUI paths and tests keep working.

**Required:** Fix hardcoded name check at `orchestrator.py:1588`. After the model emits `analysis_plan`, the repair-prompt logic must fire for both old and new names:

```python
# before
if name == "plan_analysis" and ...
# after
if name in {"plan_analysis", "analysis_plan"} and ...
```

- [ ] **Step 2: Register knowledge tools and remove `KNOWLEDGE_INTENTS` bypass**

Add model-facing tools:

```text
knowledge_recall -> existing recall_knowledge behavior
knowledge_propose_update -> current store/update/gap/function proposal behavior with an operation/type field
```

Preserve `KnowledgeManager` as the only durable memory writer.

**Required:** Remove the `KNOWLEDGE_INTENTS` bypass block at `orchestrator.py:1731-1751`. This block dispatches `store_workspace_knowledge`, `update_preferences`, `record_gap`, `save_function_candidate` directly — bypassing tool_registry. These are orphan model-callable operations (no L4 slash alias, not in tool_registry) that violate the no-orphan rule. After removal:

- The four old names hit the `tool_registry.get_handler` path and return `{"error": "unknown tool: <name>"}`.
- `knowledge_propose_update` with an `operation` argument covers all four semantically. Map old names to `knowledge_propose_update` in prompts if recall compatibility is needed.
- Remove `from harness.knowledge_intents import KNOWLEDGE_INTENTS, handle_knowledge_intent` from `orchestrator.py` if no other callers remain.

- [ ] **Step 3: Update prompts**

In `analyst.md`, replace:

```text
<tool_call>{"name":"inspect_file","arguments":{"path":"data/customers.csv"}}</tool_call>
<tool_call>{"name":"plan_analysis","arguments":{...}}</tool_call>
```

with:

```text
<tool_call>{"name":"file_read","arguments":{"operation":"inspect","path":"data/customers.csv"}}</tool_call>
<tool_call>{"name":"analysis_plan","arguments":{...}}</tool_call>
```

In `interaction.md`, replace file examples with `file_read` examples.

- [ ] **Step 4: Add compatibility tests**

Assert:

```python
tool_names = {d.name for d in orch.tool_registry.list_tools()}
assert "analysis_plan" in tool_names
assert "knowledge_recall" in tool_names

command_names = {d.name for d in orch.registry.help().commands}
assert "plan_analysis" in command_names
assert "recall_knowledge" in command_names
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_plan_analysis_command.py tests/harness/test_agentic_turn.py tests/app/agents/test_prompt_packages.py -q
```

Expected: all pass with both old command compatibility and new tool names.

---

### Task 6: Organize Commands Into Families

**Files:**
- Create: `src/harness/commands/__init__.py`
- Create: `src/harness/commands/chat.py`
- Create: `src/harness/commands/workspace.py`
- Create: `src/harness/commands/doctor.py`
- Create: `src/harness/commands/compact.py`
- Create: `src/harness/commands/run.py`
- Create: `src/harness/commands/memory.py`
- Create: `src/harness/commands/provenance.py`
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_orchestrator_commands.py`
- Test: `tests/app/tui/test_command_reachability.py`
- Test: `tests/app/tui/test_prompt_bar.py`
- Modify: `CODEMAP.md`

- [ ] **Step 1: Add Layer 4 reachability test before extraction**

Create `tests/app/tui/test_command_reachability.py`:

```python
from app.session import AppSession
from harness.command_registry import CommandContext
from harness.orchestrator import Orchestrator


async def test_all_harness_commands_are_reachable_from_l4_command_list(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    session = AppSession(orchestrator=orch)
    ctx = CommandContext(
        workspace_id=None,
        chat_id=None,
        run_id=None,
        has_pending_approval=False,
        has_pending_clarification=False,
    )

    harness_command_names = {descriptor.name for descriptor in orch.registry.help().commands}
    l4_command_names = {descriptor.name for descriptor in await session.list_commands(ctx)}

    assert harness_command_names <= l4_command_names
```

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/app/tui/test_command_reachability.py -q
```

Expected: pass before and after command-family extraction.

- [ ] **Step 2: Extract command registration without changing descriptors**

Move command descriptor construction and handler factories out of `Orchestrator._register_commands()` by family. Each command module should expose:

```python
def register_<family>_commands(orchestrator, registry) -> None:
    ...
```

The first extraction target should be low-risk command families:

```text
chat.py
workspace.py
```

- [ ] **Step 3: Keep Layer 4 reachability intact**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/app/tui/test_command_reachability.py tests/app/tui/test_prompt_bar.py -q
```

Expected: command palette and slash prompt tests still see command descriptors.

- [ ] **Step 4: Extract doctor and compact commands**

Move:

```text
doctor
compact
```

to command family modules while preserving exact handler behavior and event ordering.

- [ ] **Step 5: Extract run/review/memory/provenance command families**

Move:

```text
cancel_run
stop_after_current_step
retry_step
rerun_step
revise_goal
mark_result_trusted
mark_result_invalidated
challenge_conclusion
memory_review
inspect_artifact
provenance_inspect
validity_inspect
```

Keep business logic in services or orchestrator methods where it already belongs; command modules should wrap exposed command surface and call shared logic.

- [ ] **Step 6: Run command suite**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_orchestrator_commands.py tests/app/tui/test_command_reachability.py tests/app/tui/test_prompt_bar.py -q
```

Expected: all pass.

---

### Task 7: Final Verification And Documentation Consistency

**Files:**
- Modify as needed: `CODEMAP.md`
- Modify as needed: `Lessons.md`
- Modify as needed: `Issues.md`

- [ ] **Step 1: Check stale naming**

Run:

```bash
rg -n "runtime-callable harness tools|Knowledge Intent Tools|Current Edge Case: `read_file`|list_runtime_callable|list_files|inspect_file|read_file|plan_analysis|request_execution|recall_knowledge" docs/app src/app/agents src/harness tests
```

Expected:
- `list_files`, `inspect_file`, and `read_file` may remain as command compatibility names only.
- Prompt docs should prefer `file_read`.
- Model-facing docs should prefer `analysis_plan`, `analysis_request_execution`, and `knowledge_*`.

- [ ] **Step 2: Run focused test suites**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_tool_registry.py tests/harness/test_file_read_tool.py tests/harness/test_read_file_tool.py tests/harness/test_list_files_command.py tests/harness/test_plan_analysis_command.py tests/harness/test_agentic_turn.py tests/app/agents/test_prompt_packages.py tests/app/tui/test_command_reachability.py tests/app/tui/test_prompt_bar.py -q
```

Expected: all pass.

- [ ] **Step 3: Run broader harness/app smoke tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness tests/app/agents tests/app/tui/test_command_reachability.py tests/app/tui/test_prompt_bar.py -q
```

Expected: all pass or only known unrelated failures documented in `Issues.md`.

- [ ] **Step 4: Update `CODEMAP.md`**

If any new imports, definitions, call sites, or class relationships were introduced, update the four tracked relationship types:

```text
imports
call sites
inheritance
definitions
```

- [ ] **Step 5: Update lessons only if a new durable gotcha was learned**

If execution reveals a durable command, test, or architecture gotcha, add one concise bullet to `Lessons.md`. Do not duplicate existing lessons.

---

## Self-Review

**Spec coverage:** This plan covers the clarified Tool/Command definitions, the explicit Layer 4 reachability rule for Commands, Option A umbrella tool consolidation for `file_read`, deterministic tool validation with allowed values and regex checks, `ToolContext` separation from command context, control tools for model-emitted flow control, a new services document, analysis and knowledge tool families, command-family cleanup, source organization into tools/commands/services, prompt catalog updates, dispatch enforcement, and CODEMAP maintenance.

**Placeholder scan:** The plan contains no unresolved placeholders. Where future migration keeps compatibility names, the exact old and new names are listed.

**Type consistency:** Tool registry types are consistently named `ToolContext`, `ToolArgSpec`, `ToolDescriptor`, and `HarnessToolRegistry`. The umbrella file tool is consistently named `file_read` with `operation=list|inspect|content`. Analysis tool names are consistently `analysis_plan` and `analysis_request_execution`. Control tools are consistently registered as the `control` family.
