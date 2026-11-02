from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit_v02 import (
    AUDIT_VERSION,
    CANDIDATES,
    default_audit_corpus,
    make_request,
    normalize_exact,
    parse_semantic_axes,
)


def test_v02_corpus_preserves_30_cases_and_scoped_evidence():
    corpus = default_audit_corpus()

    assert len(corpus) == 30
    assert len({case.case_id for case in corpus}) == 30
    assert all(case.expected_candidate in CANDIDATES for case in corpus)
    assert all(
        "entity" in item and "predicate" in item
        for case in corpus
        for item in case.evidence
    )


def test_v02_separates_contradiction_from_unresolved_state():
    by_id = {case.case_id: case for case in default_audit_corpus()}

    assert by_id["S04"].expected_relation == "CONTRADICTION"
    assert by_id["S04"].expected_resolution == "UNRESOLVED"
    assert by_id["S04"].expected_candidate == "CONTRADICTION|UNRESOLVED"

    assert by_id["S05"].expected_relation == "INSUFFICIENT"
    assert by_id["S05"].expected_resolution == "UNRESOLVED"
    assert by_id["S05"].expected_candidate == "INSUFFICIENT|UNRESOLVED"


def test_v02_request_uses_candidate_contract_instead_of_text_metadata():
    case = default_audit_corpus()[0]
    request = make_request(case, CognitiveRole.FAST)
    payload = request.view.to_dict()

    assert payload["audit_version"] == AUDIT_VERSION
    assert payload["operation"] == "CLASSIFY_SEMANTIC_EVIDENCE"
    assert payload["output_contract"] == "candidate"
    assert tuple(payload["candidates"]) == CANDIDATES
    assert "text" not in payload["candidates"]


def test_v02_semantic_parser_scores_axes_independently():
    assert parse_semantic_axes("CONTRADICTION|UNRESOLVED") == (
        "CONTRADICTION",
        "UNRESOLVED",
    )
    assert parse_semantic_axes(
        "CONTRADICTION because the direct sensors disagree; therefore UNRESOLVED."
    ) == ("CONTRADICTION", "UNRESOLVED")
    assert parse_semantic_axes("CORRECTION") == ("CORRECTION", None)


def test_v02_exact_normalization_does_not_hide_contract_violations():
    assert normalize_exact(" support|resolved ") == "SUPPORT|RESOLVED"
    assert normalize_exact("SUPPORT|RESOLVED.") == "SUPPORT|RESOLVED."
