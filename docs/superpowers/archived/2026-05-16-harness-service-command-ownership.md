# Harness Service And Command Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the tools/commands/services split by making source ownership match the documented taxonomy without changing the already-working model tool boundary.

**Architecture:** Keep `HarnessToolRegistry` as the only model-callable surface and `HarnessCommandRegistry` as the only user/app command surface. Move reusable Layer 3 domain logic into `src/harness/services/`; keep `src/harness/tools/*` as model-facing wrappers and `src/harness/commands/*` as command-family homes. Preserve compatibility imports for one pass so existing tests and call sites can migrate safely.

**Tech Stack:** Python 3.13, Pydantic, pytest, existing harness/app/runtime/worker modules, Markdown docs.

**Repository rule:** Do not commit during execution unless the user explicitly approves. Use `git diff` and focused test output as checkpoints.

---

## File Structure

- Create: `src/harness/services/__init__.py`
  - Re-export service-owned classes and helpers that have stable public use inside Layer 3.
- Create: `src/harness/services/doctor.py`
  - Own `Doctor`, `DoctorRunner`, `TmpCleanupBlocked`, `PROMOTION_TARGETS`, and doctor workflow helpers.
- Modify: `src/harness/doctor.py`
  - Compatibility shim that re-exports `Doctor`, `TmpCleanupBlocked`, and `PROMOTION_TARGETS` from `harness.services.doctor`.
- Modify: `src/harness/doctor_runner.py`
  - Compatibility shim that re-exports `DoctorRunner` from `harness.services.doctor`.
- Create: `src/harness/commands/doctor.py`
  - Register the `doctor` command only.
- Create: `src/harness/commands/compact.py`
  - Register the `compact` command only.
- Modify: `src/harness/commands/diagnostics.py`
  - Keep only `help`. Renaming the module is out of scope for this plan.
- Modify: `src/harness/commands/__init__.py`
  - Export `register_doctor_commands` and `register_compact_commands`.
- Modify: `src/harness/orchestrator.py`
  - Import doctor service ownership from `harness.services.doctor`.
  - Register doctor and compact command modules separately.
  - Delegate analysis and workspace-file service logic after those services are introduced.
- Modify: `src/harness/factory.py`
  - Import `Doctor` from `harness.services.doctor`.
- Create: `src/harness/services/workspace_files.py`
  - Own workspace file list/inspect/content service behavior shared by `file_read` and legacy file commands.
- Modify: `src/harness/tools/file.py`
  - Call the workspace file service instead of an orchestrator private file reader.
- Create: `src/harness/services/analysis.py`
  - Own analysis plan construction, model code-free plan assembly, command-path plan validation, and approval re-request events.
- Modify: `src/harness/tools/analysis.py`
  - Call `orchestrator.analysis_service` rather than private orchestrator analysis methods.
- Modify: `src/harness/commands/run.py`
  - Register `plan_analysis` and `request_execution` against command handlers that delegate to `analysis_service`.
- Test: `tests/harness/test_service_ownership.py`
  - Prove service modules are the implementation owners and compatibility shims still work.
- Test: `tests/harness/test_command_family_ownership.py`
  - Prove `doctor` and `compact` have dedicated command modules and `diagnostics.py` no longer registers them.
- Modify: existing tests that import private helpers from `harness.orchestrator` once helpers move to service modules.
- Modify: `CODEMAP.md`
  - Update imports, call sites, definitions, and exception ownership.
- Modify: `docs/app/services.md`
  - Document current service module ownership after migration.
- Modify: `Issues.md`
  - Mark the structural drift issue resolved only after all tasks pass.
- Modify: `Lessons.md`
  - Update the temporary lesson that says the strict service layout is not complete.

---

### Task 1: Add Ownership Regression Tests

**Files:**
- Create: `tests/harness/test_service_ownership.py`
- Create: `tests/harness/test_command_family_ownership.py`

- [ ] **Step 1: Write failing service ownership tests**

Create `tests/harness/test_service_ownership.py`:

```python
from __future__ import annotations

from pathlib import Path

from harness.orchestrator import Orchestrator


def test_doctor_service_is_canonical_owner() -> None:
    from harness.services.doctor import Doctor, DoctorRunner, TmpCleanupBlocked
    from harness.doctor import Doctor as CompatDoctor
    from harness.doctor import TmpCleanupBlocked as CompatTmpCleanupBlocked
    from harness.doctor_runner import DoctorRunner as CompatDoctorRunner

    assert CompatDoctor is Doctor
    assert CompatDoctorRunner is DoctorRunner
    assert CompatTmpCleanupBlocked is TmpCleanupBlocked
    assert Doctor.__module__ == "harness.services.doctor"
    assert DoctorRunner.__module__ == "harness.services.doctor"


def test_orchestrator_uses_doctor_service_owner(tmp_path: Path) -> None:
    from harness.services.doctor import Doctor, DoctorRunner

    orch = Orchestrator(app_root=tmp_path)

    assert isinstance(orch.doctor, Doctor)
    assert isinstance(orch.doctor_runner, DoctorRunner)
    assert type(orch.doctor).__module__ == "harness.services.doctor"
    assert type(orch.doctor_runner).__module__ == "harness.services.doctor"


def test_workspace_file_service_is_canonical_reader(tmp_path: Path) -> None:
    from harness.services.workspace_files import WorkspaceFileService

    workspace_dir = tmp_path / "workspaces" / "w1"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "notes.md").write_text("hello", encoding="utf-8")

    service = WorkspaceFileService()
    result = service.read_content(workspace_dir, "data/notes.md")

    assert result["content"] == "hello"
    assert result["truncated"] is False
```

- [ ] **Step 2: Write failing command ownership tests**

Create `tests/harness/test_command_family_ownership.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.command_registry import HarnessCommandDescriptor
from harness.commands.compact import register_compact_commands
from harness.commands.diagnostics import register_diagnostics_commands
from harness.commands.doctor import register_doctor_commands
from harness.orchestrator import Orchestrator


@dataclass
class _FakeRegistry:
    names: list[str]

    def register(self, descriptor: HarnessCommandDescriptor, handler: Any) -> None:
        self.names.append(descriptor.name)


class _FakeOrchestrator:
    async def _handle_doctor(self, ctx, args):
        if False:
            yield None

    async def _handle_compact(self, ctx, args):
        if False:
            yield None

    async def _handle_help(self, ctx, args):
        if False:
            yield None


def test_doctor_and_compact_have_dedicated_command_modules() -> None:
    fake = _FakeOrchestrator()
    doctor_registry = _FakeRegistry([])
    compact_registry = _FakeRegistry([])

    register_doctor_commands(fake, doctor_registry)
    register_compact_commands(fake, compact_registry)

    assert doctor_registry.names == ["doctor"]
    assert compact_registry.names == ["compact"]


def test_diagnostics_registrar_no_longer_owns_doctor_or_compact() -> None:
    fake = _FakeOrchestrator()
    registry = _FakeRegistry([])

    register_diagnostics_commands(fake, registry)

    assert registry.names == ["help"]


def test_orchestrator_still_registers_doctor_and_compact(tmp_path) -> None:
    orch = Orchestrator(app_root=tmp_path)
    names = {descriptor.name for descriptor in orch.registry.help().commands}

    assert "doctor" in names
    assert "compact" in names
```

- [ ] **Step 3: Run tests and verify they fail for the expected missing modules**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_service_ownership.py tests/harness/test_command_family_ownership.py -q
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'harness.services'
```

or:

```text
ModuleNotFoundError: No module named 'harness.commands.doctor'
```

---

### Task 2: Move Doctor Logic Into `harness.services.doctor`

**Files:**
- Create: `src/harness/services/__init__.py`
- Create: `src/harness/services/doctor.py`
- Modify: `src/harness/doctor.py`
- Modify: `src/harness/doctor_runner.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/factory.py`
- Test: `tests/harness/test_service_ownership.py`
- Existing tests: `tests/harness/test_doctor.py`, `tests/harness/test_doctor_runner.py`, `tests/harness/test_doctor_apply.py`, `tests/app/test_doctor_flow.py`

- [ ] **Step 1: Create service package exports**

Create `src/harness/services/__init__.py`:

```python
from harness.services.doctor import Doctor, DoctorRunner, TmpCleanupBlocked

__all__ = ["Doctor", "DoctorRunner", "TmpCleanupBlocked"]
```

- [ ] **Step 2: Create `src/harness/services/doctor.py` by moving current implementation**

Create `src/harness/services/doctor.py` with:

```python
from __future__ import annotations

# Move the full current contents of src/harness/doctor.py here.
# Then append the full current contents of src/harness/doctor_runner.py below it.
# Keep one import section at the top and remove duplicate `from __future__ import annotations`.
```

When merging imports, use this final top section:

```python
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from harness.events import (
    CommandCompleted, CommandProgress, CommandStarted, DoctorActionProposed,
    DoctorFinding, DoctorReportReady, DoctorStarted, HarnessEvent,
)
from harness.fingerprints import lazy_fingerprint
from harness.knowledge import KnowledgeManager
from harness.validity import ValidityState, classify
from runtime.types import RuntimeMessage, RuntimeRequest

if TYPE_CHECKING:
    from harness.chat import ChatStore
    from harness.persistence import HarnessPersistence
    from runtime.protocol import Runtime
```

Keep these definitions in `src/harness/services/doctor.py`:

```python
PROMOTION_TARGETS = {
    "function": "memory/functions",
    "note": "memory/notes",
    "gap": "memory/notes/gaps",
    "artifact": "artifacts",
}


class TmpCleanupBlocked(RuntimeError):
    pass
```

The class names remain `Doctor` and `DoctorRunner`; the full method bodies are the current method bodies moved from the two source files.

- [ ] **Step 3: Replace `src/harness/doctor.py` with compatibility exports**

Replace the full file with:

```python
from __future__ import annotations

from harness.services.doctor import Doctor, PROMOTION_TARGETS, TmpCleanupBlocked

__all__ = ["Doctor", "PROMOTION_TARGETS", "TmpCleanupBlocked"]
```

- [ ] **Step 4: Replace `src/harness/doctor_runner.py` with compatibility exports**

Replace the full file with:

```python
from __future__ import annotations

from harness.services.doctor import DoctorRunner

__all__ = ["DoctorRunner"]
```

- [ ] **Step 5: Update direct owner imports in orchestrator and factory**

In `src/harness/orchestrator.py`, replace:

```python
from harness.doctor import Doctor
from harness.doctor_runner import DoctorRunner
```

with:

```python
from harness.services.doctor import Doctor, DoctorRunner
```

In `src/harness/factory.py`, replace:

```python
from harness.doctor import Doctor
```

with:

```python
from harness.services.doctor import Doctor
```

- [ ] **Step 6: Run doctor ownership and behavior tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_service_ownership.py tests/harness/test_doctor.py tests/harness/test_doctor_runner.py tests/harness/test_doctor_apply.py tests/app/test_doctor_flow.py -q
```

Expected:

```text
passed
```

---

### Task 3: Split Doctor And Compact Command Families

**Files:**
- Create: `src/harness/commands/doctor.py`
- Create: `src/harness/commands/compact.py`
- Modify: `src/harness/commands/diagnostics.py`
- Modify: `src/harness/commands/__init__.py`
- Modify: `src/harness/orchestrator.py`
- Test: `tests/harness/test_command_family_ownership.py`
- Existing tests: `tests/app/tui/test_command_reachability.py`, `tests/app/tui/test_compact_command.py`, `tests/harness/test_orchestrator_commands.py`

- [ ] **Step 1: Create `src/harness/commands/doctor.py`**

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_doctor_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="doctor",
            slash_alias="/doctor",
            short_description="Run the harness doctor diagnostic",
            arguments=[
                ArgSpec(
                    name="trigger",
                    type="str",
                    required=False,
                    description="trigger label",
                    example="manual",
                )
            ],
            available=True,
            disabled_reason=None,
            affected_resource="doctor",
            expected_event_types=[
                "DoctorStarted",
                "CommandProgress",
                "DoctorFinding",
                "DoctorReportReady",
                "CommandCompleted",
            ],
            example_usage="/doctor",
        ),
        orchestrator._handle_doctor,
    )
```

- [ ] **Step 2: Create `src/harness/commands/compact.py`**

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_compact_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="compact",
            slash_alias="/compact",
            short_description="Compact active chat history",
            arguments=[],
            available=True,
            affected_resource="chat",
            expected_event_types=["ChatHistoryCompacted", "CommandCompleted"],
            example_usage="/compact",
        ),
        orchestrator._handle_compact,
    )
```

- [ ] **Step 3: Reduce `src/harness/commands/diagnostics.py` to help registration only**

Replace the file with:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from harness.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_diagnostics_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="help",
            slash_alias="/help",
            short_description="Show command help",
            arguments=[
                ArgSpec(
                    name="command",
                    type="str",
                    required=False,
                    description="command name",
                    example="doctor",
                )
            ],
            available=True,
            affected_resource="run",
            expected_event_types=["CommandCompleted"],
            example_usage="/help inspect_artifact",
        ),
        orchestrator._handle_help,
    )
```

- [ ] **Step 4: Update command package exports**

In `src/harness/commands/__init__.py`, add imports:

```python
from harness.commands.compact import register_compact_commands
from harness.commands.doctor import register_doctor_commands
```

and include both names in `__all__`:

```python
"register_compact_commands",
"register_doctor_commands",
```

- [ ] **Step 5: Update orchestrator command registration**

In `Orchestrator._register_commands`, add:

```python
from harness.commands.compact import register_compact_commands
from harness.commands.doctor import register_doctor_commands
```

Then register in this order:

```python
register_doctor_commands(self, self.registry)
register_compact_commands(self, self.registry)
register_diagnostics_commands(self, self.registry)
register_chat_commands(self, self.registry)
register_workspace_commands(self, self.registry)
register_run_commands(self, self.registry)
register_memory_commands(self, self.registry)
register_provenance_commands(self, self.registry)
```

- [ ] **Step 6: Run command ownership and command reachability tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_command_family_ownership.py tests/app/tui/test_command_reachability.py tests/app/tui/test_compact_command.py tests/harness/test_orchestrator_commands.py -q
```

Expected:

```text
passed
```

---

### Task 4: Introduce Workspace File Service For Shared File Read Logic

**Files:**
- Create: `src/harness/services/workspace_files.py`
- Modify: `src/harness/services/__init__.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/tools/file.py`
- Modify: `tests/harness/test_read_file_tool.py`
- Existing tests: `tests/harness/test_file_read_tool.py`, `tests/harness/test_list_files_command.py`

- [ ] **Step 1: Create `src/harness/services/workspace_files.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.context import list_workspace_files, read_file_schema


READ_FILE_CHAR_CAP = 20000


class WorkspaceFileService:
    def list_files(self, workspace_dir: Path) -> list[dict[str, Any]]:
        return list_workspace_files(workspace_dir) if workspace_dir.exists() else []

    def inspect_file(self, workspace_dir: Path, rel_path: str) -> dict[str, Any]:
        if not workspace_dir.exists():
            return {"error": "workspace not found"}
        if not rel_path:
            return {"error": "missing required arg 'path'"}
        return read_file_schema(workspace_dir, rel_path)

    def read_content(
        self,
        workspace_dir: Path,
        rel_path: str,
        *,
        max_bytes: int = 65536,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        try:
            wd = workspace_dir.resolve()
            target = (wd / rel_path).resolve()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"invalid path: {exc}"}
        if wd != target and wd not in target.parents:
            return {"error": "path escapes workspace"}
        if not target.exists() or not target.is_file():
            return {"error": "not a file"}
        size = target.stat().st_size
        cap = max(1, int(max_bytes))
        try:
            data = target.read_bytes()[:cap]
            content = data.decode(encoding)
        except UnicodeDecodeError:
            return {"path": rel_path, "size_bytes": size, "error": "binary_file"}
        truncated = size > cap
        truncation_reason = "max_bytes" if truncated else None
        if len(content) > READ_FILE_CHAR_CAP:
            content = content[:READ_FILE_CHAR_CAP]
            truncated = True
            truncation_reason = "token_budget"
        return {
            "path": rel_path,
            "size_bytes": size,
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "content": content,
        }
```

- [ ] **Step 2: Export workspace file service**

In `src/harness/services/__init__.py`, add:

```python
from harness.services.workspace_files import WorkspaceFileService
```

and include:

```python
"WorkspaceFileService",
```

in `__all__`.

- [ ] **Step 3: Initialize service in orchestrator**

In `src/harness/orchestrator.py`, add:

```python
from harness.services.workspace_files import WorkspaceFileService
```

In `Orchestrator.__init__`, immediately after the current assignment to `self.workspace_manager`, add:

```python
self.workspace_file_service = WorkspaceFileService()
```

- [ ] **Step 4: Keep compatibility helper but delegate to service**

Replace `Orchestrator._read_workspace_file_for_tool` with:

```python
def _read_workspace_file_for_tool(
    self, workspace_dir: Path, path: str, *, max_bytes: int, encoding: str,
) -> dict[str, Any]:
    return self.workspace_file_service.read_content(
        workspace_dir,
        path,
        max_bytes=max_bytes,
        encoding=encoding,
    )
```

Replace the top-level `_read_workspace_file` function in `src/harness/orchestrator.py` with a compatibility wrapper:

```python
def _read_workspace_file(
    workspace_dir: Path, rel_path: str, *,
    max_bytes: int = 65536, encoding: str = "utf-8",
) -> dict[str, Any]:
    return WorkspaceFileService().read_content(
        workspace_dir,
        rel_path,
        max_bytes=max_bytes,
        encoding=encoding,
    )
```

- [ ] **Step 5: Update workspace command handler branches**

Inside `Orchestrator._make_workspace_handler`, replace the `list_files`, `inspect_file`, and `read_file` branches with:

```python
elif command_name == "list_files":
    workspace_dir = self.workspace_manager.workspaces_dir / (workspace_id or ctx.workspace_id or "")
    files = self.workspace_file_service.list_files(workspace_dir)
    result = {"workspace_id": workspace_id or ctx.workspace_id, "files": files}
elif command_name == "inspect_file":
    workspace_dir = self.workspace_manager.workspaces_dir / (workspace_id or ctx.workspace_id or "")
    path_arg = str(args.get("path") or "")
    result = self.workspace_file_service.inspect_file(workspace_dir, path_arg)
elif command_name == "read_file":
    workspace_dir = self.workspace_manager.workspaces_dir / (workspace_id or ctx.workspace_id or "")
    path_arg = str(args.get("path") or "")
    if not path_arg:
        result = {"error": "missing required arg 'path'"}
    else:
        result = self.workspace_file_service.read_content(
            workspace_dir,
            path_arg,
            max_bytes=int(args.get("max_bytes") or 65536),
            encoding=str(args.get("encoding") or "utf-8"),
        )
```

- [ ] **Step 6: Update file tool to call the service**

In `src/harness/tools/file.py`, replace direct helper usage with:

```python
elif operation == "list":
    result = {
        "workspace_id": workspace_id,
        "files": orchestrator.workspace_file_service.list_files(workspace_dir),
    }
elif operation == "inspect":
    result = orchestrator.workspace_file_service.inspect_file(workspace_dir, path)
elif operation == "content":
    if not path:
        result = {"error": "missing required arg 'path'"}
    else:
        result = orchestrator.workspace_file_service.read_content(
            workspace_dir,
            path,
            max_bytes=int(args.get("max_bytes") or 65536),
            encoding=str(args.get("encoding") or "utf-8"),
        )
```

- [ ] **Step 7: Update helper tests to import the service owner**

In `tests/harness/test_read_file_tool.py`, replace:

```python
from harness.orchestrator import Orchestrator, _read_workspace_file
```

with:

```python
from harness.orchestrator import Orchestrator
from harness.services.workspace_files import WorkspaceFileService
```

Add:

```python
def _read_workspace_file(wd, rel_path, **kwargs):
    return WorkspaceFileService().read_content(wd, rel_path, **kwargs)
```

- [ ] **Step 8: Run file command and tool tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_service_ownership.py tests/harness/test_read_file_tool.py tests/harness/test_file_read_tool.py tests/harness/test_list_files_command.py -q
```

Expected:

```text
passed
```

---

### Task 5: Extract Analysis Planning Into `harness.services.analysis`

**Files:**
- Create: `src/harness/services/analysis.py`
- Modify: `src/harness/services/__init__.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/tools/analysis.py`
- Modify: `src/harness/commands/run.py`
- Test: `tests/harness/test_service_ownership.py`
- Existing tests: `tests/harness/test_plan_analysis_command.py`, `tests/harness/test_agentic_turn.py`, `tests/harness/test_force_plan_tool_call.py`, `tests/harness/test_analysis_flow_inspecting.py`, `tests/harness/test_analysis_flow_sticky.py`

- [ ] **Step 1: Add analysis service ownership test**

Append to `tests/harness/test_service_ownership.py`:

```python
def test_analysis_service_is_attached_to_orchestrator(tmp_path: Path) -> None:
    from harness.services.analysis import AnalysisService

    orch = Orchestrator(app_root=tmp_path)

    assert isinstance(orch.analysis_service, AnalysisService)
```

- [ ] **Step 2: Create `src/harness/services/analysis.py`**

Create a transitional service that owns the analysis event methods while receiving the orchestrator as its owner:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness.control import Plan, PlanStep, RunStateRecord, StepContract
from harness.events import (
    ApprovalRequired, CommandCompleted, CommandProgress, HarnessEvent, PlanReady,
)
from worker.models import PermissionEnvelope
from worker.policy import WorkerPolicyValidator


class AnalysisService:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
```

Then move these methods from `Orchestrator` into `AnalysisService`, preserving their current bodies and replacing `self.` references to orchestrator-owned fields with `self.owner.` where needed. The moved methods must have these signatures:

```text
build_plan_from_arguments(self, state: RunStateRecord, *, goal: str, steps: list[dict[str, Any]]) -> tuple[Plan, list[StepContract]]
analysis_plan_events(self, *, workspace_id: str | None, chat_id: str | None, run_id: str | None, args: dict[str, Any], event_command: str) -> AsyncIterator[HarnessEvent]
assemble_plan_events(self, *, workspace_id: str | None, chat_id: str | None, run_id: str | None, args: dict[str, Any], event_command: str) -> AsyncIterator[HarnessEvent]
analysis_request_execution_events(self, *, workspace_id: str | None, chat_id: str | None, run_id: str | None, args: dict[str, Any], event_command: str) -> AsyncIterator[HarnessEvent]
validate_generated_step(self, state: RunStateRecord, goal: str, step: dict[str, Any]) -> str | None
finalize_plan(self, state: RunStateRecord, plan: Plan, contracts: list[StepContract], *, workspace_id: str | None, chat_id: str | None, run_id: str | None, event_command: str) -> AsyncIterator[HarnessEvent]
```

Apply these exact renames while moving:

```text
_build_plan_from_arguments          -> build_plan_from_arguments
_analysis_plan_events               -> analysis_plan_events
_assemble_plan_events               -> assemble_plan_events
_analysis_request_execution_events  -> analysis_request_execution_events
_validate_generated_step            -> validate_generated_step
_finalize_plan                      -> finalize_plan
```

Inside the moved methods, replace owner state access as follows:

```text
self.workspace_manager              -> self.owner.workspace_manager
self._pending_contracts             -> self.owner._pending_contracts
self._pending_plans                 -> self.owner._pending_plans
self._append_pending_plan           -> self.owner._append_pending_plan
self._generate_step_code            -> self.owner._generate_step_code
self._build_plan_from_arguments     -> self.build_plan_from_arguments
self._finalize_plan                 -> self.finalize_plan
self._validate_generated_step       -> self.validate_generated_step
```

Move analysis-only helpers with the service methods:

```python
PLAN_ALLOWED_PACKAGES = ["pathlib", "csv", "json", "math", "statistics", "time", "pandas", "numpy"]


def normalize_plan_step_code(idx: int, raw: dict[str, Any]) -> str:
    code_value = raw.get("code")
    code_lines = raw.get("code_lines")
    if code_lines is not None:
        if not isinstance(code_lines, list) or not code_lines:
            raise ValueError(f"step #{idx}: 'code_lines' must be a non-empty list of strings")
        if not all(isinstance(line, str) for line in code_lines):
            raise ValueError(f"step #{idx}: 'code_lines' must contain only strings")
        joined = "\n".join(code_lines)
        if code_value not in (None, "") and str(code_value) != joined:
            raise ValueError(f"step #{idx}: conflicting 'code' and 'code_lines'")
        return joined
    return str(code_value or "")
```

Inside the moved build method, replace `_PLAN_ALLOWED_PACKAGES` with `PLAN_ALLOWED_PACKAGES` and `_normalize_plan_step_code` with `normalize_plan_step_code`.

- [ ] **Step 3: Attach analysis service in orchestrator**

In `src/harness/orchestrator.py`, add:

```python
from harness.services.analysis import AnalysisService
```

In `Orchestrator.__init__`, after pending plan replay setup and before command/tool registration, add:

```python
self.analysis_service = AnalysisService(self)
```

- [ ] **Step 4: Replace orchestrator analysis methods with compatibility delegates**

Keep these methods on `Orchestrator` temporarily so existing tests and internal call sites can migrate during this plan:

```python
def _build_plan_from_arguments(self, state, *, goal, steps):
    return self.analysis_service.build_plan_from_arguments(state, goal=goal, steps=steps)


async def _analysis_plan_events(self, *, workspace_id, chat_id, run_id, args, event_command):
    async for ev in self.analysis_service.analysis_plan_events(
        workspace_id=workspace_id,
        chat_id=chat_id,
        run_id=run_id,
        args=args,
        event_command=event_command,
    ):
        yield ev


async def _assemble_plan_events(self, *, workspace_id, chat_id, run_id, args, event_command):
    async for ev in self.analysis_service.assemble_plan_events(
        workspace_id=workspace_id,
        chat_id=chat_id,
        run_id=run_id,
        args=args,
        event_command=event_command,
    ):
        yield ev


def _validate_generated_step(self, state, goal, step):
    return self.analysis_service.validate_generated_step(state, goal, step)


async def _analysis_request_execution_events(self, *, workspace_id, chat_id, run_id, args, event_command):
    async for ev in self.analysis_service.analysis_request_execution_events(
        workspace_id=workspace_id,
        chat_id=chat_id,
        run_id=run_id,
        args=args,
        event_command=event_command,
    ):
        yield ev
```

- [ ] **Step 5: Update model-facing analysis tool wrapper**

In `src/harness/tools/analysis.py`, replace the call to `orchestrator._assemble_plan_events` with `orchestrator.analysis_service.assemble_plan_events`.

Replace the call to `orchestrator._analysis_request_execution_events` with `orchestrator.analysis_service.analysis_request_execution_events`.

- [ ] **Step 6: Update command-facing analysis handlers**

In `Orchestrator._make_plan_analysis_handler`, replace:

```python
async for ev in self._analysis_plan_events(
```

with:

```python
async for ev in self.analysis_service.analysis_plan_events(
```

In `Orchestrator._handle_request_execution`, replace:

```python
async for ev in self._analysis_request_execution_events(
```

with:

```python
async for ev in self.analysis_service.analysis_request_execution_events(
```

- [ ] **Step 7: Run analysis service and analysis behavior tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_service_ownership.py tests/harness/test_plan_analysis_command.py tests/harness/test_agentic_turn.py tests/harness/test_force_plan_tool_call.py tests/harness/test_analysis_flow_inspecting.py tests/harness/test_analysis_flow_sticky.py tests/app/agents/test_prompt_packages.py tests/app/agents/test_analyst_mode.py -q
```

Expected:

```text
passed
```

---

### Task 6: Update Architecture Docs And CODEMAP

**Files:**
- Modify: `CODEMAP.md`
- Modify: `docs/app/services.md`
- Modify: `docs/app/tools-vs-commands.md`
- Modify: `Issues.md`
- Modify: `Lessons.md`

- [ ] **Step 1: Update `CODEMAP.md` import graph**

Update the `src/harness` section so it includes:

```text
src/harness/commands/__init__.py        → harness.commands.chat, harness.commands.compact,
                                           harness.commands.diagnostics, harness.commands.doctor,
                                           harness.commands.memory, harness.commands.provenance,
                                           harness.commands.run, harness.commands.workspace
src/harness/commands/compact.py         → harness.command_registry
src/harness/commands/doctor.py          → harness.command_registry
src/harness/services/__init__.py        → harness.services.analysis, harness.services.doctor,
                                           harness.services.workspace_files
src/harness/services/analysis.py        → harness.control, harness.events, worker.models,
                                           worker.policy
src/harness/services/doctor.py          → harness.events, harness.fingerprints,
                                           harness.knowledge, harness.validity, runtime.types
src/harness/services/workspace_files.py → harness.context
src/harness/doctor.py                   → harness.services.doctor
src/harness/doctor_runner.py            → harness.services.doctor
```

Update orchestrator imports to show:

```text
src/harness/orchestrator.py             → harness.chat, harness.command_registry,
                                           harness.commands.*,
                                           harness.services.analysis,
                                           harness.services.doctor,
                                           harness.services.workspace_files,
                                           harness.tools.*,
                                           observability, runtime.*, worker.*
```

- [ ] **Step 2: Update `CODEMAP.md` definitions**

Move the canonical rows for these definitions:

```text
| `Doctor` / `DoctorRunner` | `src/harness/services/doctor.py` |
| `AnalysisService` | `src/harness/services/analysis.py` |
| `WorkspaceFileService` | `src/harness/services/workspace_files.py` |
```

Keep a note that `src/harness/doctor.py` and `src/harness/doctor_runner.py` are compatibility shims.

- [ ] **Step 3: Update `docs/app/services.md`**

Add a new section:

```markdown
## Current Source Owners

- `src/harness/services/doctor.py`: doctor diagnostics, tmp review, source checks, proposed doctor actions, and doctor event orchestration.
- `src/harness/services/analysis.py`: analysis plan validation, model code-free plan assembly, command-path plan handling, approval request events, and pending plan packaging.
- `src/harness/services/workspace_files.py`: workspace file inventory, schema inspection, and bounded text reads shared by tools and commands.

Compatibility modules may re-export service-owned definitions during migration, but new Layer 3 code should import from `src/harness/services/*`.
```

- [ ] **Step 4: Update `docs/app/tools-vs-commands.md`**

In the source-organization or migration notes, add:

```markdown
The command split is source-level as well as registry-level: `doctor` and `compact` have dedicated command modules, while shared implementation lives under `src/harness/services/`.
```

- [ ] **Step 5: Resolve the open issue entry**

In `Issues.md`, change:

```markdown
## Tools/commands/services split still has structural drift (OPEN 2026-05-16)
```

to:

```markdown
## Tools/commands/services split still has structural drift (RESOLVED 2026-05-16)
```

Append:

```markdown
- Fix pass 2026-05-16: added service-owned modules for doctor, analysis, and workspace file operations; split doctor and compact into dedicated command-family modules; kept compatibility shims for existing imports; updated CODEMAP and app docs.
- Verification: focused harness/app split suites passed. See execution notes for exact command output.
```

- [ ] **Step 6: Update the temporary lesson**

In `Lessons.md`, replace the temporary warning with:

```markdown
- The tools/commands/services split has three separate boundaries: model calls go through `HarnessToolRegistry`, user/app commands go through `HarnessCommandRegistry`, and reusable Layer 3 implementation belongs in `src/harness/services/`. Compatibility shims may remain briefly, but new code should import canonical service owners directly.
```

- [ ] **Step 7: Run docs grep checks**

Run:

```bash
rg -n "structural drift|No src/harness/services|commands/diagnostics.py.*doctor|runtime-callable commands|list_runtime_callable" docs/app CODEMAP.md Issues.md Lessons.md
```

Expected:

```text
Issues.md
```

The only acceptable match is the resolved historical issue entry. There should be no stale claim that services are missing.

---

### Task 7: Final Verification

**Files:**
- No new files unless tests reveal a failure.

- [ ] **Step 1: Run the focused split and service suite**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_service_ownership.py tests/harness/test_command_family_ownership.py tests/harness/test_tool_registry.py tests/harness/test_file_read_tool.py tests/harness/test_read_file_tool.py tests/harness/test_list_files_command.py tests/harness/test_plan_analysis_command.py tests/harness/test_doctor.py tests/harness/test_doctor_runner.py tests/harness/test_doctor_apply.py tests/app/agents/test_prompt_packages.py tests/app/agents/test_analyst_mode.py tests/app/tui/test_command_reachability.py tests/app/tui/test_compact_command.py tests/app/test_doctor_flow.py -q
```

Expected:

```text
passed
```

- [ ] **Step 2: Run the broader affected harness/app tests**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest tests/harness/test_agentic_turn.py tests/harness/test_force_plan_tool_call.py tests/harness/test_analysis_flow_inspecting.py tests/harness/test_analysis_flow_sticky.py tests/harness/test_orchestrator_commands.py tests/app/tui/test_command_provider.py tests/app/tui/test_command_palette.py tests/app/tui/test_prompt_bar.py -q
```

Expected:

```text
passed
```

- [ ] **Step 3: Run full test suite if focused suites pass**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run pytest -q
```

Expected:

```text
passed
```

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git diff --stat
```

Expected shape:

```text
src/harness/services/
src/harness/commands/doctor.py
src/harness/commands/compact.py
src/harness/orchestrator.py
src/harness/factory.py
tests/harness/test_service_ownership.py
tests/harness/test_command_family_ownership.py
CODEMAP.md
docs/app/
Issues.md
Lessons.md
```

- [ ] **Step 5: Check no accidental public tool/command drift**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run python - <<'PY'
from harness.orchestrator import Orchestrator
orch = Orchestrator()
tools = [d.name for d in orch.tool_registry.list_tools()]
commands = [d.name for d in orch.registry.help().commands]
print("TOOLS", tools)
print("COMMANDS", commands)
assert "doctor" not in tools
assert "compact" not in tools
assert "doctor" in commands
assert "compact" in commands
assert "analysis_plan" in tools
assert "plan_analysis" in commands
PY
```

Expected:

```text
The script prints the `TOOLS` and `COMMANDS` lists and exits with status 0.
```

---

## Self-Review Notes

- Spec coverage: This plan covers the strict source ownership gap left by the prior split: dedicated command modules for doctor/compact, service-owned doctor/analysis/workspace file logic, compatibility shims, docs, `CODEMAP.md`, and public-surface verification.
- Scope control: It intentionally does not rename user-visible commands, model-visible tools, prompts, event classes, or TUI behavior.
- Compatibility: Existing imports from `harness.doctor` and `harness.doctor_runner` continue to work during migration.
- Risk: Analysis extraction is the highest-risk task because it touches approval, generated code validation, and pending plan state. It is intentionally isolated after doctor/compact and workspace-file service tasks.
