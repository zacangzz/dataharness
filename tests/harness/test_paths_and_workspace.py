from pathlib import Path

from harness.app_store import AppStore
from harness.paths import AppPaths, WorkspacePaths
from harness.workspace import WorkspaceManager, bootstrap_workspace


def test_app_paths_match_workspace_first_layout(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path)
    assert paths.app_dir == tmp_path / "app"
    assert paths.app_store_path == tmp_path / "app" / "app.json"
    assert paths.harness_dir == tmp_path / "harness"
    assert paths.telemetry_dir == tmp_path / "harness" / "telemetry"
    assert paths.logs_dir == tmp_path / "harness" / "logs"
    assert paths.workspaces_dir == tmp_path / "workspaces"


def test_workspace_paths_are_workspace_relative(tmp_path: Path) -> None:
    workspace = WorkspacePaths.from_workspace_dir(tmp_path / "workspaces" / "w_0001")
    assert workspace.data_dir == workspace.root / "data"
    assert workspace.tmp_artifacts_dir == workspace.root / "artifacts" / "tmp"
    assert workspace.preferences_path == workspace.root / "memory" / "preferences.json"
    assert workspace.workspace_db_path == workspace.root / "state" / "workspace.db"
    assert workspace.relative(workspace.root / "artifacts" / "report.md") == Path("artifacts/report.md")


def test_bootstrap_workspace_creates_required_directories_and_preferences(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspaces" / "w_0001")
    assert (workspace / "data").exists()
    assert (workspace / "artifacts" / "tmp").exists()
    assert (workspace / "memory" / "preferences.json").read_text() == "{}\n"
    assert (workspace / "memory" / "notes" / "gaps").exists()
    assert (workspace / "memory" / "functions").exists()
    assert (workspace / "state").exists()


def test_app_store_remains_non_authoritative_for_workspace_truth(tmp_path: Path) -> None:
    store_path = tmp_path / "app" / "app.json"
    store = AppStore(path=store_path)
    store.register_workspace("w_0001", tmp_path / "workspaces" / "w_0001")
    loaded = AppStore.load(store_path)
    assert loaded.last_opened_workspace == "w_0001"
    assert loaded.known_workspaces["w_0001"] == str(tmp_path / "workspaces" / "w_0001")
    assert "run_records" not in loaded.model_dump()


def test_workspace_manager_opens_default_workspace_under_app_root(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)

    active = manager.open_default_workspace()

    assert active.workspace_id == "w_0001"
    assert active.workspace_dir == tmp_path / "workspaces" / "w_0001"
    assert (active.workspace_dir / "data").exists()
    assert (active.workspace_dir / "memory" / "preferences.json").read_text() == "{}\n"

    loaded = AppStore.load(tmp_path / "app" / "app.json")
    assert loaded.last_opened_workspace == "w_0001"
    assert loaded.known_workspaces["w_0001"] == str(active.workspace_dir)
