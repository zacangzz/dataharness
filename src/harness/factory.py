from __future__ import annotations

from pathlib import Path

from harness.context import ContextManager
from harness.db import WorkspaceDb
from harness.doctor import Doctor
from harness.knowledge import KnowledgeManager
from harness.orchestrator import Orchestrator
from harness.persistence import HarnessPersistence
from observability import Telemetry, resolve_telemetry_dir
from runtime.protocol import Runtime
from worker.executor import PythonStepExecutor


def build_orchestrator(
    *,
    workspace_dir: Path,
    runtime: Runtime | None = None,
    telemetry: Telemetry | None = None,
) -> Orchestrator:
    """Spec §8.1: harness owns runtime construction and orchestrator wiring.

    The CLI / TUI MUST go through this factory. Layer 4 must not import runtime.* directly.
    """
    telemetry = telemetry or Telemetry(resolve_telemetry_dir())
    db_path = workspace_dir / "state" / "workspace.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = WorkspaceDb(db_path)
    db.connect()
    persistence = HarnessPersistence(db, telemetry=telemetry)
    app_root = workspace_dir.parent.parent if workspace_dir.parent.name == "workspaces" else workspace_dir.parent
    return Orchestrator(
        runtime=runtime,
        context_manager=ContextManager(),
        worker=PythonStepExecutor(),
        persistence=persistence,
        doctor=Doctor(),
        knowledge_manager=KnowledgeManager(workspace_dir=workspace_dir, persistence=persistence),
        telemetry=telemetry,
        app_root=app_root,
    )
