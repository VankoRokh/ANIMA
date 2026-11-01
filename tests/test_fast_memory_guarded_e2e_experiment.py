from scripts.run_fast_epistemic_guard_experiment import ALLOW_FAST, BLOCK_UNGROUNDED
from scripts.run_fast_memory_guarded_e2e_experiment import (
    GUARDED_E2E_CORPUS,
    UNKNOWN_RESPONSE,
)


def _case(case_id):
    return next(case for case in GUARDED_E2E_CORPUS if case["id"] == case_id)


def test_unknown_personal_cases_are_blocked():
    assert _case("missing_information")["expected_action"] == BLOCK_UNGROUNDED
    assert _case("unknown_personal_tea")["expected_action"] == BLOCK_UNGROUNDED


def test_open_cases_are_allowed_without_memory():
    assert _case("open_arithmetic")["expected_action"] == ALLOW_FAST
    assert _case("open_general_knowledge")["expected_action"] == ALLOW_FAST
    assert _case("open_arithmetic")["memories"] == ()
    assert _case("open_general_knowledge")["memories"] == ()


def test_known_personal_cases_are_allowed():
    assert _case("direct_recall")["expected_action"] == ALLOW_FAST
    assert _case("semantic_paraphrase")["expected_action"] == ALLOW_FAST


def test_blocked_response_is_explicit_unknown():
    assert "нет этой информации" in UNKNOWN_RESPONSE.casefold()


def test_corpus_covers_block_allow_and_noise_paths():
    ids = {case["id"] for case in GUARDED_E2E_CORPUS}
    assert {
        "direct_recall",
        "missing_information",
        "relevant_among_noise",
        "semantic_paraphrase",
        "related_facts",
        "unknown_personal_tea",
        "open_arithmetic",
        "open_general_knowledge",
    } <= ids
