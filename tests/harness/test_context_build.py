from __future__ import annotations

import pytest

from harness.services.context import ContextManager, list_workspace_files, read_file_schema


@pytest.mark.asyncio
async def test_build_includes_files_and_schemas(tmp_path):
    ws = tmp_path / "w_t"
    (ws / "data").mkdir(parents=True)
    csv = ws / "data" / "sales.csv"
    csv.write_text("date,region,amount\n2026-01-01,EU,12.5\n2026-01-02,US,9.0\n")
    notes = ws / "memory" / "notes"
    notes.mkdir(parents=True)
    (notes / "intro.md").write_text("project notes")

    cm = ContextManager()
    text = await cm.build(ws, token_budget=1024, status_text="WORKSPACE: w_t (idle)")

    assert "WORKSPACE: w_t" in text
    assert "FILES (1)" in text
    assert "data/sales.csv" in text
    assert "SCHEMAS:" in text
    assert "date" in text and "region" in text
    assert "MEMORY NOTES" in text


def test_list_workspace_files_empty(tmp_path):
    assert list_workspace_files(tmp_path) == []


def test_read_file_schema_csv(tmp_path):
    ws = tmp_path / "w"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "x.csv").write_text("a,b\n1,2\n3,4\n")
    schema = read_file_schema(ws, "data/x.csv")
    assert schema["kind"] == "csv"
    assert schema["columns"] == ["a", "b"]
    assert schema["row_count"] == 2


def test_read_file_schema_path_traversal_rejected(tmp_path):
    ws = tmp_path / "w"
    (ws / "data").mkdir(parents=True)
    schema = read_file_schema(ws, "../etc/passwd")
    assert "error" in schema
