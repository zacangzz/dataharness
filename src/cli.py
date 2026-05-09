from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path
from uuid import uuid4

from observability import (
    Telemetry,
    bind_boot,
    configure_logging,
    resolve_app_root,
    resolve_log_dir,
    resolve_telemetry_dir,
)
from observability.events import EventKind, Layer


def _default_runtime_factory(config, telemetry):
    runtime_module = importlib.import_module("runtime.llama_cpp_runtime")
    return runtime_module.LlamaCppRuntime(config, telemetry=telemetry)


def build_app(
    telemetry: Telemetry | None = None,
    *,
    workspace_id: str | None = None,
    app_root: Path | None = None,
    runtime_factory=None,
    runtime=None,
):
    """Build TUI through harness factory. TUI must NOT construct runtime."""
    telemetry = telemetry or Telemetry(resolve_telemetry_dir())
    telemetry.emit(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_IMPORT_START, payload={"module": "app.tui.app"})
    try:
        tui_module = importlib.import_module("app.tui.app")
        session_module = importlib.import_module("app.session")
        control_module = importlib.import_module("harness.control")
        factory_module = importlib.import_module("harness.factory")
        workspace_module = importlib.import_module("harness.workspace")
    except Exception as exc:
        telemetry.emit_error(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_IMPORT_ERROR, phase="import", exc=exc)
        raise
    telemetry.emit(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_IMPORT_END, payload={"module": "app.tui.app"})

    resolved_app_root = app_root or Path(os.getenv("DATAHARNESS_APP_ROOT", resolve_app_root()))
    manager = workspace_module.WorkspaceManager(resolved_app_root)
    active = (
        manager.open_workspace(workspace_id)
        if workspace_id is not None
        else manager.open_default_workspace()
    )

    if runtime is None and runtime_factory is not None:
        runtime_config_module = importlib.import_module("runtime.config")
        default_model_path = Path("models/gemma-4-E4B-it-Q4_K_M.gguf")
        configured = os.getenv("DATAHARNESS_MODEL_PATH")
        model_path = Path(configured) if configured else default_model_path
        if not model_path.is_absolute():
            model_path = resolved_app_root / model_path
        runtime = runtime_factory(runtime_config_module.RuntimeConfig(model_path=str(model_path)), telemetry)

    orchestrator = factory_module.build_orchestrator(
        workspace_dir=active.workspace_dir, runtime=runtime, telemetry=telemetry
    )
    session = session_module.DataAnalysisAppSession(orchestrator=orchestrator, telemetry=telemetry)
    state = control_module.RunStateRecord(
        workspace_id=active.workspace_id, active_agent_mode="interaction"
    )

    telemetry.emit(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_APP_CONSTRUCT_START)
    try:
        app = tui_module.DataHarnessApp(
            session=session,
            workspace_dir=active.workspace_dir,
            state=state,
            telemetry=telemetry,
        )
    except Exception as exc:
        telemetry.emit_error(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_ERROR, phase="construct", exc=exc)
        raise
    telemetry.emit(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_APP_CONSTRUCT_END)
    return app


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dataharness")
    parser.add_argument("--workspace", type=str, default=None)
    parser.add_argument("--app-root", type=Path, default=None)
    return parser.parse_known_args(argv)[0]


def main() -> None:
    args = _parse_argv(sys.argv[1:])
    log_dir = configure_logging(resolve_log_dir())
    telemetry = Telemetry(resolve_telemetry_dir())
    with bind_boot(uuid4()):
        telemetry.emit(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_START, payload={"log_dir": str(log_dir)})
        app = build_app(
            telemetry,
            workspace_id=args.workspace,
            app_root=args.app_root,
            runtime_factory=_default_runtime_factory,
        )
        telemetry.emit(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_RUN_START)
        try:
            app.run()
        except Exception as exc:
            telemetry.emit_error(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_ERROR, phase="run", exc=exc)
            raise
        telemetry.emit(Layer.BOOTSTRAP, EventKind.BOOTSTRAP_RUN_END)


if __name__ == "__main__":
    main()
