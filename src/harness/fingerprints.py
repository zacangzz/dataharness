"""Fingerprints module — stub matching legacy doctor test expectations."""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple
import hashlib


class FingerprintResult(NamedTuple):
    action: str
    fingerprint: str | None
    size_bytes: int | None
    modified_time_ns: int | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def lazy_fingerprint(
    path: Path,
    *,
    stored_size: int | None = None,
    stored_mtime_ns: int | None = None,
    stored_fingerprint: str | None = None,
) -> FingerprintResult:
    """Return a fingerprint result for the given path.

    Actions match legacy expectations:
      - "fingerprinted": file exists and was newly fingerprinted (no stored metadata)
      - "reused_fingerprint": metadata unchanged, fingerprint reused without re-reading
      - "changed": file changed and the recomputed fingerprint differs
      - "missing": file does not exist
    """
    if not path.exists():
        return FingerprintResult(action="missing", fingerprint=None, size_bytes=None, modified_time_ns=None)
    stat = path.stat()
    size = stat.st_size
    mtime = stat.st_mtime_ns
    # Fast path: metadata identical — reuse stored fingerprint
    if stored_size is not None and stored_mtime_ns is not None and stored_size == size and stored_mtime_ns == mtime:
        return FingerprintResult(
            action="reused_fingerprint",
            fingerprint=stored_fingerprint,
            size_bytes=size,
            modified_time_ns=mtime,
        )
    # Must actually compute fingerprint
    fingerprint = sha256_file(path)
    if stored_fingerprint is None:
        action = "fingerprinted"
    elif fingerprint == stored_fingerprint:
        action = "fingerprinted"
    else:
        action = "changed"
    return FingerprintResult(action=action, fingerprint=fingerprint, size_bytes=size, modified_time_ns=mtime)
