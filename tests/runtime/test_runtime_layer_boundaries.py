import ast
from pathlib import Path


def test_runtime_layer_does_not_import_harness_or_app() -> None:
    bad: list[str] = []
    for path in Path("src/runtime").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "harness" or alias.name.startswith("harness."):
                        bad.append(f"{path}: {alias.name}")
                    if alias.name == "app" or alias.name.startswith("app."):
                        bad.append(f"{path}: {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "harness" or node.module.startswith("harness."):
                    bad.append(f"{path}: {node.module}")
                if node.module == "app" or node.module.startswith("app."):
                    bad.append(f"{path}: {node.module}")
    assert not bad, bad
