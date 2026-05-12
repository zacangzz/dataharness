from harness.validity import ValidityState, classify


def test_validity_states_cover_all_six_per_spec() -> None:
    assert {state.value for state in ValidityState} == {
        "ok",
        "changed",
        "stale",
        "needs_review",
        "revalidated",
        "broken_lineage",
    }


def test_classify_first_ingest_is_ok() -> None:
    assert (
        classify(fingerprint_action="fingerprinted", stored_fingerprint=None, new_fingerprint="abc")
        == ValidityState.OK
    )


def test_classify_changed_when_fingerprint_differs() -> None:
    assert (
        classify(fingerprint_action="fingerprinted", stored_fingerprint="old", new_fingerprint="new")
        == ValidityState.CHANGED
    )


def test_classify_reused_fingerprint_is_ok() -> None:
    assert (
        classify(fingerprint_action="reused_fingerprint", stored_fingerprint="abc", new_fingerprint="abc")
        == ValidityState.OK
    )


def test_classify_missing_is_broken_lineage() -> None:
    assert (
        classify(fingerprint_action="missing", stored_fingerprint="abc", new_fingerprint=None)
        == ValidityState.BROKEN_LINEAGE
    )


def test_classify_stale_when_dependent_inputs_stale() -> None:
    assert (
        classify(
            fingerprint_action="reused_fingerprint",
            stored_fingerprint="abc",
            new_fingerprint="abc",
            has_dependents_with_stale_inputs=True,
        )
        == ValidityState.STALE
    )


def test_classify_needs_review_flag() -> None:
    assert (
        classify(
            fingerprint_action="reused_fingerprint",
            stored_fingerprint="abc",
            new_fingerprint="abc",
            needs_user_review=True,
        )
        == ValidityState.NEEDS_REVIEW
    )


def test_classify_revalidated_flag() -> None:
    assert (
        classify(
            fingerprint_action="fingerprinted",
            stored_fingerprint="old",
            new_fingerprint="new",
            user_revalidated=True,
        )
        == ValidityState.REVALIDATED
    )
