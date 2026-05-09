from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from harness.db import WorkspaceDb


class ProvenanceRecord(BaseModel):
    workspace_id: str
    claim_id: str
    source_files: list[str]
    fingerprints: dict[str, str]
    executed_code_hash: str
    artifacts: list[str]
    plan_id: str
    step_id: str
    validity_state: str
    active_prompt_mode: str
    prompt_template_id: str
    prompt_template_version: str


class ClaimChecker:
    def __init__(self, db: "WorkspaceDb | None" = None) -> None:
        self.db = db

    def check_claims(self, claims: list[dict[str, object]]) -> dict[str, list[str]]:
        supported: list[str] = []
        unsupported: list[str] = []
        for claim in claims:
            text = str(claim["text"])
            evidence_refs = list(claim.get("evidence_refs") or [])
            if not evidence_refs:
                unsupported.append(text)
                continue
            if self.db is not None and not self._refs_have_lineage(evidence_refs):
                unsupported.append(text)
                continue
            supported.append(text)
        return {"supported": supported, "unsupported": unsupported}

    def _refs_have_lineage(self, refs: list[str]) -> bool:
        assert self.db is not None
        for ref in refs:
            artifact_path = ref.split(":", 1)[1] if ":" in ref else ref
            try:
                self.db.load_record("lineage_records", "artifact_path", artifact_path)
            except KeyError:
                return False
        return True


def reuse_allowed_for_source(
    *,
    validity_state: str,
) -> bool:
    """Spec §6.13/§6.14: reuse of saved knowledge is blocked unless source validity is ok or revalidated."""
    return validity_state in {"ok", "revalidated"}
