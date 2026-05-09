# Collection of Outstanding Issues

## Git object database is missing tracked objects
- Observed 2026-05-09 while verifying a Python 3.14 metadata update: `git status --short` failed with `fatal: unable to read tree (f7efc85010a5980a7ba2b917c7bc8df3e1732f49)` and `git diff -- pyproject.toml uv.lock` failed with `fatal: unable to read 211498efae0897414e1243c56e4c18f7c9de1b19`.
- `git fsck --no-progress` reports invalid cache-tree pointers plus many missing blobs/trees, including the tracked blobs for `pyproject.toml` and `uv.lock`.
- Impact: Git diff/status cannot be trusted until the object database is repaired or the repo is recloned/refetched.
- Status: documented only; no repair attempted in this turn.
