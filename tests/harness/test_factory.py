from pathlib import Path

import pytest

from harness.factory import build_orchestrator
from harness.workspace import bootstrap_workspace
from runtime.types import RuntimeEvent, TokenPressure
from worker.executor import PythonStepExecutor


class FakeRuntime:
    async def stream(self, request):
        yield RuntimeEvent(type="text_delta", request_id=request.request_id, seq=0, text="ok")
        yield RuntimeEvent(type="finish", request_id=request.request_id, seq=1, finish_reason="stop", usage={})

    async def context_window(self):
        return 4096

    async def token_pressure(self, request):
        return TokenPressure(
            request_id=request.request_id,
            context_window=4096,
            prompt_tokens=1,
            reserved_completion_tokens=request.max_completion_tokens,
            total_tokens=1 + request.max_completion_tokens,
            pressure_ratio=(1 + request.max_completion_tokens) / 4096,
            over_threshold=False,
        )

    async def validate_request(self, request):
        return None

    async def status(self):
        return "ready"


def test_factory_constructs_orchestrator_with_required_collaborators(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "preferences.json").write_text("{}")

    runtime = FakeRuntime()
    orchestrator = build_orchestrator(workspace_dir=workspace, runtime=runtime)

    assert orchestrator.runtime is runtime
    assert orchestrator.persistence is not None
    assert isinstance(orchestrator.worker, PythonStepExecutor)
    assert orchestrator.doctor is not None
    assert orchestrator.context_manager is not None


def test_factory_creates_workspace_db_at_state_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "w_0001"
    workspace.mkdir(parents=True)

    build_orchestrator(workspace_dir=workspace, runtime=FakeRuntime())

    assert (workspace / "state" / "workspace.db").exists()


@pytest.mark.asyncio
async def test_factory_sets_orchestrator_app_root_from_workspace_dir(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspaces" / "w_0001")

    orchestrator = build_orchestrator(workspace_dir=workspace, runtime=FakeRuntime())

    workspaces = await orchestrator.list_workspaces()
    assert orchestrator.app_root == tmp_path
    assert [workspace.workspace_id for workspace in workspaces] == ["w_0001"]
