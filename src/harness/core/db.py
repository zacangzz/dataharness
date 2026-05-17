from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


AUTHORITATIVE_TABLES = [
    "workspace_metadata",
    "run_records",
    "run_state_history",
    "plan_records",
    "step_records",
    "approval_records",
    "execution_envelopes",
    "step_results",
    "prompt_packages",
    "artifact_registry",
    "file_registry",
    "validity_state",
    "lineage_records",
    "doctor_history",
    "tmp_actions",
    "review_proposals",
    "memory_update_proposals",
    "validation_failures",
    "note_index",
    "function_index",
    "mode_switch_history",
    "step_action_history",
]


def _validate_key_name(key_name: str) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_]+", key_name):
        raise ValueError(f"invalid key_name: {key_name!r}")


def create_schema() -> str:
    statements = [
        f"""
        create table if not exists {table_name} (
            id text primary key,
            record_json text not null,
            created_at text not null default current_timestamp
        );
        """
        for table_name in AUTHORITATIVE_TABLES
    ]
    statements.extend(
        [
            "create unique index if not exists idx_run_records_run_id on run_records (json_extract(record_json, '$.run_id'));",
            "create unique index if not exists idx_plan_records_plan_id on plan_records (json_extract(record_json, '$.id'));",
            "create index if not exists idx_file_registry_workspace on file_registry (json_extract(record_json, '$.workspace_id'));",
            "create index if not exists idx_validity_subject on validity_state (json_extract(record_json, '$.subject_id'));",
        ]
    )
    return "\n".join(statements)


class WorkspaceDb:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("pragma journal_mode = wal")
        self._conn.executescript(create_schema())
        self._conn.commit()
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            return self.connect()
        return self._conn

    def list_tables(self) -> list[str]:
        rows = self.conn.execute("select name from sqlite_master where type='table'").fetchall()
        return [row[0] for row in rows]

    def append_record(self, table: str, record_id: str, record: dict[str, object]) -> None:
        if table not in AUTHORITATIVE_TABLES:
            raise ValueError(f"unknown table: {table}")
        self.conn.execute(
            f"insert into {table} (id, record_json) values (?, ?)",
            (record_id, json.dumps(record, sort_keys=True)),
        )
        self.conn.commit()

    def save_record(self, table: str, key_name: str, key_value: str, record: dict[str, object]) -> None:
        if table not in AUTHORITATIVE_TABLES:
            raise ValueError(f"unknown table: {table}")
        _validate_key_name(key_name)
        existing = self.conn.execute(
            f"select id from {table} where json_extract(record_json, '$.{key_name}') = ?",
            (key_value,),
        ).fetchone()
        record_id = str(record.get("id") or key_value)
        if existing:
            self.conn.execute(
                f"update {table} set record_json = ? where id = ?",
                (json.dumps(record, sort_keys=True), existing[0]),
            )
        else:
            self.append_record(table, record_id, record)
            return
        self.conn.commit()

    def list_records(self, table: str) -> list[dict[str, object]]:
        if table not in AUTHORITATIVE_TABLES:
            raise ValueError(f"unknown table: {table}")
        rows = self.conn.execute(f"select record_json from {table}").fetchall()
        return [json.loads(row[0]) for row in rows]

    def load_record(self, table: str, key_name: str, key_value: str) -> dict[str, object]:
        if table not in AUTHORITATIVE_TABLES:
            raise ValueError(f"unknown table: {table}")
        _validate_key_name(key_name)
        row = self.conn.execute(
            f"select record_json from {table} where json_extract(record_json, '$.{key_name}') = ?",
            (key_value,),
        ).fetchone()
        if row is None:
            raise KeyError(key_value)
        return json.loads(row[0])
