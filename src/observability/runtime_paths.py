from __future__ import annotations

import sys
from pathlib import Path


def repo_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resolve_app_root() -> Path:
    return repo_root()


def resolve_log_dir() -> Path:
    return resolve_app_root() / "harness" / "logs"


def resolve_telemetry_dir() -> Path:
    return resolve_app_root() / "harness" / "telemetry"
