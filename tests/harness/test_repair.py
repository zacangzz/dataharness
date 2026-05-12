from harness.repair import try_deterministic_repair


def test_wrapper_repair_wraps_scalar_arguments() -> None:
    payload = {"name": "doctor", "arguments": "manual"}
    result = try_deterministic_repair(payload, failure_kind="schema_mismatch")
    assert result.kind == "applied"
    assert result.recipe == "wrapper_repair"
    assert result.payload["arguments"] == {"value": "manual"}


def test_type_normalization_converts_numeric_strings() -> None:
    payload = {"name": "compute", "arguments": {"limit": "100", "ratio": "0.5"}}
    result = try_deterministic_repair(payload, failure_kind="schema_mismatch")
    assert result.kind == "applied"
    assert result.payload["arguments"] == {"limit": 100, "ratio": 0.5}


def test_metadata_insertion_fills_missing_canonical_fields() -> None:
    payload = {
        "workspace_id": "w_0001",
        "run_id": "r_1",
        "memory_target": "memory/notes/x.md",
        "source_refs": [],
        "proposed_content": "x",
    }
    result = try_deterministic_repair(
        payload, failure_kind="schema_mismatch", record_kind="MemoryUpdateProposal"
    )
    assert result.kind == "applied"
    assert result.payload["schema_version"] == "1.0"
    assert "id" in result.payload
    assert "created_at" in result.payload


def test_path_normalization_strips_leading_slash_and_normalizes_separators() -> None:
    payload = {"declared_inputs": ["/data\\employees.csv"]}
    result = try_deterministic_repair(payload, failure_kind="schema_mismatch")
    assert result.kind == "applied"
    assert result.payload["declared_inputs"] == ["data/employees.csv"]


def test_returns_not_applicable_when_no_recipe_matches() -> None:
    result = try_deterministic_repair({"completely": "unrelated"}, failure_kind="python_exception")
    assert result.kind == "not_applicable"
    assert result.payload == {"completely": "unrelated"}


def test_returns_not_applicable_when_failure_kind_excluded() -> None:
    result = try_deterministic_repair({"name": "x", "arguments": "y"}, failure_kind="execution_failure")
    assert result.kind == "not_applicable"
