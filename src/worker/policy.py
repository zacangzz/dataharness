from __future__ import annotations

import ast
from pathlib import Path

from worker.models import PermissionEnvelope, ResourceLimits

NETWORK_MODULES = frozenset({"socket", "urllib", "http", "requests"})
SHELL_MODULES = frozenset({"subprocess", "pty", "shlex"})
STDLIB_ALLOWLIST = frozenset({"pathlib", "json", "csv", "_csv", "math", "statistics", "time"})


class WorkerPolicyError(ValueError):
    pass


class WorkerPolicyValidator:
    def __init__(self, workspace_dir: Path, permission_envelope: PermissionEnvelope) -> None:
        self.workspace_dir = workspace_dir.resolve()
        self.permission_envelope = permission_envelope

    def _resolve_relative(self, path_text: str) -> Path:
        path = Path(path_text)
        if path.is_absolute():
            raise WorkerPolicyError(f"path must be workspace-relative: {path_text}")
        candidate = (self.workspace_dir / path).resolve()
        if not candidate.is_relative_to(self.workspace_dir):
            raise WorkerPolicyError(f"workspace escape blocked: {path_text}")
        return candidate

    def validate_read(self, path_text: str) -> Path:
        candidate = self._resolve_relative(path_text)
        allowed = {
            self._resolve_relative(p)
            for p in self.permission_envelope.allowed_read_paths
            + self.permission_envelope.registered_artifact_paths
        }
        if candidate not in allowed:
            raise WorkerPolicyError(f"read outside allowed inputs: {path_text}")
        return candidate

    def validate_write(self, path_text: str) -> Path:
        candidate = self._resolve_relative(path_text)
        allowed_roots = [self._resolve_relative(root) for root in self.permission_envelope.allowed_write_roots]
        if not any(candidate.is_relative_to(root) for root in allowed_roots):
            raise WorkerPolicyError(f"write outside allowed tmp roots: {path_text}")
        return candidate

    def _import_names(self, node: ast.AST) -> list[str]:
        if isinstance(node, ast.Import):
            return [alias.name.split(".", 1)[0] for alias in node.names]
        if isinstance(node, ast.ImportFrom):
            if node.level:
                raise WorkerPolicyError("relative imports not allowed in submitted code")
            if not node.module:
                return []
            return [node.module.split(".", 1)[0]]
        return []

    def validate_code_imports(self, code: str) -> None:
        envelope = self.permission_envelope
        for node in ast.walk(ast.parse(code)):
            for name in self._import_names(node):
                if name in NETWORK_MODULES and not envelope.allow_network:
                    raise WorkerPolicyError(f"network import not allowed: {name}")
                if name in SHELL_MODULES and not envelope.allow_shell:
                    raise WorkerPolicyError(f"shell import not allowed: {name}")
                if name not in envelope.allowed_packages and name not in STDLIB_ALLOWLIST:
                    raise WorkerPolicyError(f"package not allowed: {name}")

    def validate_resource_limits(self, limits: ResourceLimits) -> None:
        values = (
            limits.timeout_seconds,
            limits.memory_mb,
            limits.artifact_bytes,
            limits.stdout_bytes,
            limits.stderr_bytes,
        )
        if any(value <= 0 for value in values):
            raise WorkerPolicyError("resource ceilings must be positive")
