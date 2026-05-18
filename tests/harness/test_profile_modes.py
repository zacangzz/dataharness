from harness.services.profile_modes import (
    INTERACTION, ANALYST, KNOWLEDGE, CLARIFICATION, VALID_PROFILE_MODES,
)


def test_constants_match_canonical_strings():
    assert INTERACTION == "interaction"
    assert ANALYST == "analyst"
    assert KNOWLEDGE == "knowledge"
    assert CLARIFICATION == "clarification"


def test_valid_set_is_exactly_the_four_modes():
    assert VALID_PROFILE_MODES == frozenset(
        {"interaction", "analyst", "knowledge", "clarification"}
    )
