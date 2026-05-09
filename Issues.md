# Collection of Outstanding Issues

## Git object database is missing tracked objects (RESOLVED 2026-05-10)
- Observed 2026-05-09 while verifying a Python 3.14 metadata update: `git status --short` failed with `fatal: unable to read tree (f7efc85010a5980a7ba2b917c7bc8df3e1732f49)` and `git diff -- pyproject.toml uv.lock` failed with `fatal: unable to read 211498efae0897414e1243c56e4c18f7c9de1b19`.
- `git fsck --no-progress` reported invalid cache-tree pointers plus many missing blobs/trees, including HEAD subtree `f7efc85`.
- Root cause: object DB partially missing; HEAD tree itself unreadable. No remote configured, only one prior commit (`fc58b05 initial`), so no fetch/clone repair path.
- Fix: backed up corrupted `.git` to `.git.broken-2026-05-10/` (still on disk, ignored via `.gitignore`), ran `git init -b main`, staged working tree (277 files), committed as `7f654ea initial (recovered from corrupted object db)`.
- Post-fix `git fsck` shows only dangling blobs (orphan objects, cleared by `git gc`). `git status` and `git diff` work normally.
- Follow-up: delete `.git.broken-2026-05-10/` once confident nothing else needed from it; consider adding a remote so this is recoverable next time.
