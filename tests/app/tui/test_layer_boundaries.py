import ast
from pathlib import Path


def test_tui_does_not_import_orchestrator_directly():
    tui_dir = Path("src/app/tui")
    bad: list[str] = []
    for py in tui_dir.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("harness.orchestrator"):
                    bad.append(str(py))
    assert not bad, bad


def test_tui_does_not_import_runtime_module():
    tui_dir = Path("src/app/tui")
    bad: list[str] = []
    for py in tui_dir.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "runtime" or node.module.startswith("runtime."):
                    bad.append(f"{py}: {node.module}")
    assert not bad, bad


def test_app_session_is_async_only():
    import inspect

    from app.session import AppSession
    for name in (
        "run_user_turn", "resume_approved_step", "resume_with_clarification",
        "handle_direct_command", "compact_chat_history", "resume_chat",
    ):
        method = getattr(AppSession, name)
        assert inspect.isasyncgenfunction(method) or inspect.iscoroutinefunction(method), name
