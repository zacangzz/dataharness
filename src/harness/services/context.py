from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_TABULAR_SUFFIXES = {".csv", ".tsv", ".parquet", ".xlsx", ".xls"}


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n/1.0:.1f} {unit}" if unit == "KB" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def list_workspace_files(workspace_dir: Path, *, max_entries: int = 200) -> list[dict[str, Any]]:
    data_dir = workspace_dir / "data"
    if not data_dir.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append({
            "path": str(path.relative_to(workspace_dir)),
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
        })
        if len(entries) >= max_entries:
            break
    return entries


def read_file_schema(workspace_dir: Path, rel_path: str, *, sample_rows: int = 3, max_cols: int = 20) -> dict[str, Any]:
    full = (workspace_dir / rel_path).resolve()
    try:
        full.relative_to(workspace_dir.resolve())
    except ValueError:
        return {"path": rel_path, "error": "path outside workspace"}
    if not full.is_file():
        return {"path": rel_path, "error": "not a file"}
    suffix = full.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return _read_csv_schema(full, rel_path, sample_rows=sample_rows, max_cols=max_cols)
    if suffix == ".parquet":
        return _read_parquet_schema(full, rel_path, sample_rows=sample_rows, max_cols=max_cols)
    if suffix in {".xlsx", ".xls"}:
        return _read_excel_schema(full, rel_path, sample_rows=sample_rows, max_cols=max_cols)
    return {
        "path": rel_path,
        "kind": "unstructured",
        "size_bytes": full.stat().st_size,
    }


def _read_csv_schema(full: Path, rel_path: str, *, sample_rows: int, max_cols: int) -> dict[str, Any]:
    delim = "\t" if full.suffix.lower() == ".tsv" else ","
    columns: list[str] = []
    samples: list[list[str]] = []
    row_count = 0
    try:
        with full.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.reader(fh, delimiter=delim)
            for idx, row in enumerate(reader):
                if idx == 0:
                    columns = row[:max_cols]
                    continue
                if len(samples) < sample_rows:
                    samples.append(row[:max_cols])
                row_count += 1
    except Exception as exc:  # noqa: BLE001
        return {"path": rel_path, "error": f"read failed: {exc}"}
    return {
        "path": rel_path,
        "kind": "csv",
        "columns": columns,
        "row_count": row_count,
        "sample_rows": samples,
    }


def _read_parquet_schema(full: Path, rel_path: str, *, sample_rows: int, max_cols: int) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq  # type: ignore
    except ImportError:
        return {"path": rel_path, "kind": "parquet", "error": "pyarrow not installed"}
    try:
        pf = pq.ParquetFile(str(full))
        schema = pf.schema_arrow
        columns = [
            {"name": schema.field(i).name, "type": str(schema.field(i).type)}
            for i in range(min(len(schema), max_cols))
        ]
        row_count = pf.metadata.num_rows if pf.metadata is not None else None
        sample = pf.read_row_group(0).slice(0, sample_rows).to_pylist() if pf.num_row_groups > 0 else []
    except Exception as exc:  # noqa: BLE001
        return {"path": rel_path, "kind": "parquet", "error": f"read failed: {exc}"}
    return {
        "path": rel_path,
        "kind": "parquet",
        "columns": columns,
        "row_count": row_count,
        "sample_rows": sample,
    }


def _read_excel_schema(full: Path, rel_path: str, *, sample_rows: int, max_cols: int) -> dict[str, Any]:
    try:
        import openpyxl  # type: ignore
    except ImportError:
        return {"path": rel_path, "kind": "excel", "error": "openpyxl not installed"}
    try:
        wb = openpyxl.load_workbook(str(full), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header = list(next(rows, ()))[:max_cols]
        samples: list[list[Any]] = []
        for r in rows:
            if len(samples) >= sample_rows:
                break
            samples.append(list(r)[:max_cols])
    except Exception as exc:  # noqa: BLE001
        return {"path": rel_path, "kind": "excel", "error": f"read failed: {exc}"}
    return {
        "path": rel_path,
        "kind": "excel",
        "columns": header,
        "sample_rows": samples,
    }


class ContextManager:
    """Builds workspace context for runtime prompts and rebuilds durable session context.

    Two responsibilities, both filesystem-pure (no harness/runtime imports):
    - `build()` (async): assemble durable workspace context text for prompt injection.
    - `rebuild()` / `compact()`: legacy session-context helpers preserved for callers.
    """

    async def build(
        self,
        workspace_dir: Path,
        *,
        token_budget: int = 4096,
        status_text: str | None = None,
        max_files: int = 50,
        max_schema_files: int = 10,
    ) -> str:
        char_budget = max(token_budget * 4, 512)
        sections: list[str] = []

        if status_text:
            sections.append(status_text.strip())

        files = list_workspace_files(workspace_dir, max_entries=max_files)
        if files:
            file_lines = [f"FILES ({len(files)}):"]
            for f in files:
                file_lines.append(
                    f"- {f['path']}  {_human_size(f['size_bytes'])}  {f['mtime'][:10]}"
                )
            sections.append("\n".join(file_lines))

            tabular = [f for f in files if Path(f["path"]).suffix.lower() in _TABULAR_SUFFIXES]
            if tabular:
                schema_lines = ["SCHEMAS:"]
                for f in tabular[:max_schema_files]:
                    schema = read_file_schema(workspace_dir, f["path"])
                    schema_lines.append(_format_schema_line(schema))
                sections.append("\n".join(schema_lines))

        artifacts = _recent_artifacts(workspace_dir)
        if artifacts:
            sections.append("RECENT ARTIFACTS:\n" + "\n".join(f"- {a}" for a in artifacts))

        notes = _memory_notes(workspace_dir)
        if notes:
            sections.append("MEMORY NOTES:\n" + notes)

        text = "\n\n".join(s for s in sections if s)
        if len(text) > char_budget:
            text = text[: char_budget - 16] + "\n[…truncated]"
        return text

    def rebuild(
        self,
        *,
        workspace_dir: Path,
        session_ledger: list[str],
        validity_states: list[str],
        chat_history: list[str],
    ) -> dict[str, object]:
        preferences_path = workspace_dir / "memory" / "preferences.json"
        preferences = json.loads(preferences_path.read_text()) if preferences_path.exists() else {}
        notes_dir = workspace_dir / "memory" / "notes"
        notes = []
        if notes_dir.exists():
            notes = [path.read_text() for path in sorted(notes_dir.glob("*.md"))]
        return {
            "preferences": preferences,
            "memory_notes": "\n".join(notes),
            "session_ledger": session_ledger,
            "validity_states": validity_states,
            "chat_history_loaded": False,
        }

    def compact(
        self,
        entries: list[str],
        *,
        active_plan_id: str,
        current_step_id: str,
        unresolved_failures: list[str],
    ) -> dict[str, object]:
        operational_atoms = [
            entry for entry in entries if entry.startswith("tool_call:") or entry.startswith("tool_output:")
        ]
        return {
            "durable": False,
            "summary": "\n".join(operational_atoms),
            "active_plan_id": active_plan_id,
            "current_step_id": current_step_id,
            "unresolved_failures": unresolved_failures,
        }


def _format_schema_line(schema: dict[str, Any]) -> str:
    path = schema.get("path", "?")
    if "error" in schema:
        return f"{path} [error: {schema['error']}]"
    cols = schema.get("columns") or []
    if cols and isinstance(cols[0], dict):
        col_str = ", ".join(f"{c.get('name')}:{c.get('type')}" for c in cols)
    else:
        col_str = ", ".join(str(c) for c in cols)
    rc = schema.get("row_count")
    rc_part = f" ({rc} rows)" if rc is not None else ""
    return f"{path} [{col_str}]{rc_part}"


def _recent_artifacts(workspace_dir: Path, *, limit: int = 5) -> list[str]:
    runs_dir = workspace_dir / "runs"
    if not runs_dir.exists():
        return []
    entries: list[tuple[float, str]] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        try:
            mtime = run_dir.stat().st_mtime
        except OSError:
            continue
        entries.append((mtime, run_dir.name))
    entries.sort(reverse=True)
    return [name for _, name in entries[:limit]]


def _memory_notes(workspace_dir: Path, *, max_chars: int = 1200) -> str:
    notes_dir = workspace_dir / "memory" / "notes"
    if not notes_dir.exists():
        return ""
    parts: list[str] = []
    for path in sorted(notes_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        parts.append(f"[{path.name}]\n{text}")
    joined = "\n\n".join(parts)
    return joined[:max_chars] + ("…" if len(joined) > max_chars else "")
