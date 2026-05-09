from pathlib import Path

from harness.fingerprints import lazy_fingerprint, sha256_file


def test_first_ingest_stores_full_fingerprint(tmp_path: Path) -> None:
    file = tmp_path / "data.csv"
    file.write_text("a,b\n1,2\n")
    result = lazy_fingerprint(file, stored_size=None, stored_mtime_ns=None, stored_fingerprint=None)
    assert result.action == "fingerprinted"
    assert result.size_bytes == file.stat().st_size
    assert result.modified_time_ns == file.stat().st_mtime_ns
    assert result.fingerprint == sha256_file(file)


def test_lazy_fingerprint_skips_rehash_when_size_and_mtime_unchanged(tmp_path: Path) -> None:
    file = tmp_path / "data.csv"
    file.write_text("a,b\n1,2\n")
    first = lazy_fingerprint(file, stored_size=None, stored_mtime_ns=None, stored_fingerprint=None)
    second = lazy_fingerprint(
        file,
        stored_size=first.size_bytes,
        stored_mtime_ns=first.modified_time_ns,
        stored_fingerprint=first.fingerprint,
    )
    assert second.action == "reused_fingerprint"
    assert second.fingerprint == first.fingerprint


def test_lazy_fingerprint_rehashes_when_mtime_changed(tmp_path: Path) -> None:
    file = tmp_path / "data.csv"
    file.write_text("a,b\n1,2\n")
    first = lazy_fingerprint(file, stored_size=None, stored_mtime_ns=None, stored_fingerprint=None)
    later_mtime = first.modified_time_ns - 1_000_000_000
    rehashed = lazy_fingerprint(
        file,
        stored_size=first.size_bytes,
        stored_mtime_ns=later_mtime,
        stored_fingerprint=first.fingerprint,
    )
    assert rehashed.action == "fingerprinted"


def test_lazy_fingerprint_handles_missing_file(tmp_path: Path) -> None:
    result = lazy_fingerprint(
        tmp_path / "missing.csv",
        stored_size=10,
        stored_mtime_ns=1,
        stored_fingerprint="abc",
    )
    assert result.action == "missing"
