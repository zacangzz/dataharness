from pathlib import Path

from harness.orchestrator import Orchestrator


def test_doctor_service_is_canonical_owner() -> None:
    from harness.services.doctor import PHASES, Doctor, DoctorRunner, TmpCleanupBlocked

    assert Doctor.__module__ == "harness.services.doctor"
    assert DoctorRunner.__module__ == "harness.services.doctor"
    assert TmpCleanupBlocked.__module__ == "harness.services.doctor"
    assert PHASES.__class__.__module__ == "builtins"
    assert len(PHASES) > 0


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


def test_analysis_service_is_attached_to_orchestrator(tmp_path: Path) -> None:
    from harness.services.analysis import AnalysisService

    orch = Orchestrator(app_root=tmp_path)

    assert isinstance(orch.analysis_service, AnalysisService)
