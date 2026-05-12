from harness.provenance import ClaimChecker, ProvenanceRecord


def test_provenance_record_tracks_required_claim_lineage() -> None:
    record = ProvenanceRecord(
        workspace_id="w_0001",
        claim_id="claim_1",
        source_files=["data/employees.csv"],
        fingerprints={"data/employees.csv": "sha256:abc"},
        executed_code_hash="sha256:def",
        artifacts=["artifacts/attrition.csv"],
        plan_id="plan_1",
        step_id="step_1",
        validity_state="ok",
        active_prompt_mode="analyst",
        prompt_template_id="analyst_v1",
        prompt_template_version="v1",
    )
    assert record.step_id == "step_1"
    assert record.prompt_template_version == "v1"


def test_claim_checker_rejects_unsupported_claims() -> None:
    checker = ClaimChecker()
    claims = [
        {"text": "Attrition is 12%", "evidence_refs": ["artifact:attrition.csv"]},
        {"text": "Revenue improved", "evidence_refs": []},
    ]
    result = checker.check_claims(claims)
    assert result["supported"] == ["Attrition is 12%"]
    assert result["unsupported"] == ["Revenue improved"]


def test_claim_checker_marks_unsupported_when_db_lineage_missing(tmp_path):
    from harness.db import WorkspaceDb
    from harness.provenance import ClaimChecker

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    checker = ClaimChecker(db=db)
    result = checker.check_claims(
        [{"text": "Attrition is 12%", "evidence_refs": ["artifact:artifacts/attrition.csv"]}]
    )
    assert result["unsupported"] == ["Attrition is 12%"]


def test_claim_checker_supports_claim_when_lineage_row_present(tmp_path):
    from harness.db import WorkspaceDb
    from harness.provenance import ClaimChecker

    db = WorkspaceDb(tmp_path / "state" / "workspace.db")
    db.connect()
    db.append_record(
        "lineage_records",
        "lineage:e1:artifacts/attrition.csv",
        {
            "id": "lineage:e1:artifacts/attrition.csv",
            "artifact_path": "artifacts/attrition.csv",
            "fingerprint_id": "sha256:abc",
            "validity_id": "validity:artifacts/attrition.csv:ok",
        },
    )
    checker = ClaimChecker(db=db)
    result = checker.check_claims(
        [{"text": "Attrition is 12%", "evidence_refs": ["artifact:artifacts/attrition.csv"]}]
    )
    assert result["supported"] == ["Attrition is 12%"]


def test_artifact_registry_includes_fingerprint_and_validity_ids(tmp_path):
    from pathlib import Path

    from harness.db import WorkspaceDb
    from harness.persistence import HarnessPersistence

    workspace = tmp_path / "w_0001"
    artifact_dir = workspace / "artifacts" / "tmp" / "run_1" / "step_1"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "out.txt").write_text("data")
    db = WorkspaceDb(workspace / "state" / "workspace.db")
    db.connect()
    persistence = HarnessPersistence(db)
    envelope = {
        "id": "env_1",
        "run_id": "run_1",
        "step_id": "step_1",
        "status": "ok",
        "artifact_refs": ["artifacts/tmp/run_1/step_1/out.txt"],
        "execution_metadata": {"input_refs": {}, "code_hash": "sha256:c"},
    }
    persistence.save_execution_envelope(envelope, workspace_dir=workspace)
    artifact = db.load_record("artifact_registry", "path", "artifacts/tmp/run_1/step_1/out.txt")
    assert artifact["fingerprint_id"].startswith("sha256:")
    assert artifact["validity_id"].startswith("validity:")
    lineage = db.load_record("lineage_records", "artifact_path", "artifacts/tmp/run_1/step_1/out.txt")
    assert lineage["fingerprint_id"] == artifact["fingerprint_id"]
    assert lineage["validity_id"] == artifact["validity_id"]


def test_reuse_blocked_after_source_fingerprint_change():
    from harness.provenance import reuse_allowed_for_source

    assert reuse_allowed_for_source(validity_state="ok") is True
    assert reuse_allowed_for_source(validity_state="revalidated") is True
    assert reuse_allowed_for_source(validity_state="changed") is False
    assert reuse_allowed_for_source(validity_state="broken_lineage") is False
    assert reuse_allowed_for_source(validity_state="needs_review") is False
    assert reuse_allowed_for_source(validity_state="stale") is False
