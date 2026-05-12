from __future__ import annotations

import builtins
import json
import os
import runpy
import sys
from pathlib import Path

try:
    import resource
except ImportError:
    resource = None

NETWORK_MODULES = frozenset({"socket", "urllib", "http", "requests"})
SHELL_MODULES = frozenset({"subprocess", "pty", "shlex"})
STDLIB_ALLOWLIST = frozenset({
    "pathlib", "csv", "json", "math", "statistics", "pandas", "numpy",
    "tabulate",
    "openpyxl",
    "xlrd",
    "_csv",
    "time",
})
CODE_SUFFIXES = frozenset({".py", ".pyc", ".so", ".pyd", ".dll", ".dylib"})
BLOCKED_AUDIT_EVENTS = frozenset({"socket.__new__", "subprocess.Popen", "os.system"})
WRITE_OPEN_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
WRITE_MODE_CHARS = ("w", "a", "+", "x")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_write_mode(mode_raw: object) -> bool:
    if isinstance(mode_raw, int):
        return bool(mode_raw & WRITE_OPEN_FLAGS)
    return any(flag in str(mode_raw) for flag in WRITE_MODE_CHARS)


def main() -> int:
    config = json.loads(Path(sys.argv[1]).read_text())
    tmp_dir = Path(config["tmp_dir"]).resolve()
    workspace_dir = Path(config["workspace_dir"]).resolve()
    allowed_reads = {Path(path).resolve() for path in config["allowed_reads"]}
    allowed_write_roots = [Path(path).resolve() for path in config["allowed_write_roots"]]
    allowed_code_roots = [Path(path).resolve() for path in config["allowed_code_roots"]]
    allowed_packages = set(config["allowed_packages"])
    allow_network = bool(config["allow_network"])
    allow_shell = bool(config["allow_shell"])
    script_path = Path(config["script_path"]).resolve()
    memory_bytes = int(config["memory_bytes"])
    # Compute Python install roots once; used to allow stdlib data file reads
    # (e.g. zoneinfo, ssl certs, locale data) which live under sys.prefix.
    python_install_roots = list({
        Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(),
    })
    # PyInstaller frozen worker: the subprocess has its own `_MEIPASS` bundle
    # dir, which holds `.pyc`/`.so`/data files for every bundled package. Allow
    # reads from there so `import pandas` etc. don't trip the audit hook.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_resolved = Path(meipass).resolve()
        if meipass_resolved not in python_install_roots:
            python_install_roots.append(meipass_resolved)
        if meipass_resolved not in allowed_code_roots:
            allowed_code_roots.append(meipass_resolved)
    if getattr(sys, "frozen", False):
        try:
            exe_parent = Path(sys.executable).resolve().parent
            if exe_parent not in allowed_code_roots:
                allowed_code_roots.append(exe_parent)
        except (OSError, ValueError):
            pass

    if resource is not None:
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except (ValueError, resource.error):
            # macOS does not support RLIMIT_AS enforcement; best-effort only.
            pass

    # Pre-import everything runpy.run_path needs internally so they appear in sys.modules
    # before we install the guarded import. This prevents the guard from blocking
    # Python's own infrastructure.
    import importlib  # noqa: F401
    import importlib.abc  # noqa: F401
    import importlib.machinery  # noqa: F401
    import importlib.util  # noqa: F401
    import pkgutil  # noqa: F401

    original_import = builtins.__import__
    # Capture modules already loaded by Python internals before user code runs.
    # These are implicitly allowed so the runtime infrastructure can function.
    preloaded = set(sys.modules.keys())

    def _check_module_allowed(root_name: str, context: str) -> None:
        if root_name in NETWORK_MODULES and not allow_network:
            raise PermissionError(f"network import not allowed at {context}: {root_name}")
        if root_name in SHELL_MODULES and not allow_shell:
            raise PermissionError(f"shell import not allowed at {context}: {root_name}")

    def _is_runtime_importer(globals_obj: object) -> bool:
        if not isinstance(globals_obj, dict):
            return False
        file_value = globals_obj.get("__file__")
        if not isinstance(file_value, (str, bytes, os.PathLike)):
            return False
        try:
            importer_path = Path(file_value).resolve()
        except (OSError, ValueError):
            return False
        if _is_relative_to(importer_path, workspace_dir):
            return False
        return any(_is_relative_to(importer_path, root) for root in allowed_code_roots)

    def _allowed_package_frame_active() -> bool:
        frame = sys._getframe()
        while frame is not None:
            file_value = frame.f_globals.get("__file__")
            if isinstance(file_value, (str, bytes, os.PathLike)):
                try:
                    frame_path = Path(file_value).resolve()
                except (OSError, ValueError):
                    frame = frame.f_back
                    continue
                if (
                    not _is_relative_to(frame_path, workspace_dir)
                    and any(_is_relative_to(frame_path, root) for root in allowed_code_roots)
                    and any(part in allowed_packages for part in frame_path.parts)
                ):
                    return True
            frame = frame.f_back
        return False

    def guarded_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0) -> object:
        if level > 0:
            return original_import(name, globals, locals, fromlist, level)
        root_name = name.split(".", 1)[0]
        package_dependency = _is_runtime_importer(globals) or _allowed_package_frame_active()
        # Explicitly block dangerous modules first — before any preload bypass.
        if not package_dependency:
            _check_module_allowed(root_name, "runtime")
        # Allow re-imports of stdlib/infrastructure modules already loaded before user code runs.
        if root_name in preloaded or name in preloaded:
            return original_import(name, globals, locals, fromlist, level)
        # Block anything not in the explicit allowlist.
        if root_name not in allowed_packages and root_name not in STDLIB_ALLOWLIST:
            if package_dependency:
                return original_import(name, globals, locals, fromlist, level)
            raise PermissionError(f"package not allowed at runtime: {root_name}")
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = guarded_import

    def _check_open(args: tuple[object, ...]) -> None:
        target = args[0]
        if not isinstance(target, (str, bytes, os.PathLike)):
            return
        path = Path(target).resolve()
        mode_raw = args[1] if len(args) > 1 and args[1] is not None else "r"
        if _is_write_mode(mode_raw):
            if not any(_is_relative_to(path, root) for root in allowed_write_roots):
                raise PermissionError(f"write outside sandbox: {path}")
            return
        if _is_relative_to(path, workspace_dir):
            if not (_is_relative_to(path, tmp_dir) or path in allowed_reads or path == script_path):
                raise PermissionError(f"read outside sandbox: {path}")
        elif path.suffix in CODE_SUFFIXES:
            if not any(_is_relative_to(path, root) for root in allowed_code_roots):
                raise PermissionError(f"code import outside allowed runtime roots: {path}")
        else:
            # Allow stdlib data files (zoneinfo, ssl certs, locale, etc.) that live
            # under the Python installation prefix. This fixes over-restriction of
            # datetime/ssl/zoneinfo/locale which read non-code data files.
            if any(_is_relative_to(path, root) for root in python_install_roots):
                return
            # Block reads outside workspace unless explicitly in allowed_reads
            # or under an allowed_code_root (for .py/.so etc already handled above).
            if path not in allowed_reads and not any(_is_relative_to(path, root) for root in allowed_code_roots):
                raise PermissionError(f"read outside sandbox: {path}")

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event == "open" and args:
            _check_open(args)
        elif event == "import" and args:
            name = str(args[0]).split(".", 1)[0]
            if not name:
                return
            package_dependency = _allowed_package_frame_active()
            if not package_dependency:
                _check_module_allowed(name, "runtime")
            if name in sys.modules:
                return  # already loaded — allow
            if name not in allowed_packages and name not in STDLIB_ALLOWLIST:
                if package_dependency:
                    return
                raise PermissionError(f"package not allowed at runtime: {name}")
        elif event in BLOCKED_AUDIT_EVENTS:
            raise PermissionError(f"operation blocked by sandbox: {event}")

    sys.addaudithook(audit)
    runpy.run_path(str(script_path), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
