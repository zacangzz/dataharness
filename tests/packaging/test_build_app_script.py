from pathlib import Path
import tomllib


def test_build_app_includes_dynamically_imported_textual_app() -> None:
    script = Path("scripts/build_app.sh").read_text()

    assert "--hidden-import app.tui.app" in script


def test_build_app_rebuilds_pyinstaller_analysis_cache() -> None:
    script = Path("scripts/build_app.sh").read_text()

    assert "--clean" in script


def test_build_app_bundles_runtime_prompt_resources() -> None:
    script = Path("scripts/build_app.sh").read_text()

    assert "--add-data" in script
    assert "src/app/agents/prompts:app/agents/prompts" in script
    assert "src/harness/prompts:harness/prompts" in script
    assert "--collect-submodules observability" in script


def test_build_app_bundles_tui_tcss() -> None:
    script = Path("scripts/build_app.sh").read_text()

    assert "src/app/tui/dataharness.tcss:app/tui" in script
    assert "src/app/tui/dataharness.tcss:app/tui/dataharness.tcss" not in script


def test_build_app_collects_local_packages_reached_by_dynamic_imports() -> None:
    script = Path("scripts/build_app.sh").read_text()

    assert "--hidden-import app.session" in script
    assert "--hidden-import harness.control" in script
    assert "--hidden-import harness.factory" in script
    assert "--hidden-import harness.workspace" in script
    assert "--hidden-import runtime.config" in script
    assert "--hidden-import runtime.llama_cpp_runtime" in script
    assert "--hidden-import worker.sandbox_bootstrap" in script
    assert "--collect-submodules app" in script
    assert "--collect-submodules harness" in script
    assert "--collect-submodules runtime" in script
    assert "--collect-submodules worker" in script


def test_wheel_exposes_dataharness_console_script_and_cli_module() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text())

    assert config["project"]["scripts"]["dataharness"] == "cli:main"
    force_include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["src/cli.py"] == "cli.py"
