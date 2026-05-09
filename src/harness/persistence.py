from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from harness.control import ApprovalRecord
from harness.db import WorkspaceDb
from observability import Telemetry, resolve_telemetry_dir
from observability.events import EventKind, Layer


class HarnessPersistence:
    def __init__(self, db: WorkspaceDb, telemetry: Telemetry | None = None) -> None:
        self.db = db
        self.telemetry = telemetry or Telemetry(resolve_telemetry_dir())

    def save_model(self, table: str, key_name: str, key_value: str, record: BaseModel) -> None:
        self.db.save_record(table, key_name, key_value, record.model_dump(mode="json"))

    def save_dict(self, table: str, key_name: str, key_value: str, record: dict[str, object]) -> None:
        start = self.telemetry.emit(
            Layer.PERSISTENCE,
            EventKind.PERSISTENCE_WRITE_START,
            payload={"table": table, "key_name": key_name, "key_value": key_value},
        )
        stamped = dict(record)
        stamped["telemetry_event_id"] = str(start.event_id)
        try:
            self.db.save_record(table, key_name, key_value, stamped)
        except Exception as exc:
            self.telemetry.emit_error(Layer.PERSISTENCE, EventKind.PERSISTENCE_ERROR, phase="save_dict", exc=exc)
            raise
        self.telemetry.emit(
            Layer.PERSISTENCE,
            EventKind.PERSISTENCE_WRITE_END,
            payload={"table": table, "key_name": key_name, "key_value": key_value},
        )

    def save_plan_with_steps(self, plan_payload: dict[str, object]) -> None:
        self.save_dict("plan_records", "id", str(plan_payload["id"]), plan_payload)
        for step in plan_payload.get("steps", []):
            self.save_dict("step_records", "id", str(step["id"]), step)

    def save_approval(self, approval: ApprovalRecord) -> None:
        self.save_model("approval_records", "id", approval.id, approval)

    def save_execution_envelope(self, envelope: dict[str, object], workspace_dir: Path | None = None) -> None:
        envelope_id = str(envelope["id"])
        run_id = str(envelope["run_id"])
        step_id = str(envelope["step_id"])
        self.save_dict("execution_envelopes", "id", envelope_id, envelope)
        self.save_dict(
            "step_action_history",
            "id",
            f"{run_id}:{step_id}:execution",
            {
                "id": f"{run_id}:{step_id}:execution",
                "run_id": run_id,
                "step_id": step_id,
                "action": "execution_envelope_recorded",
                "status": envelope["status"],
                "envelope_id": envelope_id,
            },
        )
        for path in envelope.get("artifact_refs", []):
            artifact_path = str(path)
            fingerprint_id = self._fingerprint_artifact(workspace_dir, artifact_path)
            validity_id = f"validity:{artifact_path}:ok"
            self.save_dict(
                "artifact_registry",
                "path",
                artifact_path,
                {
                    "path": artifact_path,
                    "run_id": run_id,
                    "step_id": step_id,
                    "status": "tmp_registered",
                    "source_envelope_id": envelope_id,
                    "fingerprint_id": fingerprint_id,
                    "validity_id": validity_id,
                },
            )
            self.save_dict(
                "lineage_records",
                "artifact_path",
                artifact_path,
                {
                    "id": f"lineage:{envelope_id}:{artifact_path}",
                    "run_id": run_id,
                    "step_id": step_id,
                    "artifact_path": artifact_path,
                    "source_envelope_id": envelope_id,
                    "source_files": envelope.get("execution_metadata", {}).get("input_refs", {}),
                    "executed_code_hash": envelope.get("execution_metadata", {}).get("code_hash"),
                    "fingerprint_id": fingerprint_id,
                    "validity_id": validity_id,
                },
            )

    def _fingerprint_artifact(self, workspace_dir: Path | None, artifact_path: str) -> str:
        if workspace_dir is not None:
            candidate = workspace_dir / artifact_path
            if candidate.exists() and candidate.is_file():
                return f"sha256:{hashlib.sha256(candidate.read_bytes()).hexdigest()}"
        return f"sha256:{hashlib.sha256(artifact_path.encode('utf-8')).hexdigest()}"
