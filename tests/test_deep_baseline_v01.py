from anima.experiments.deep_audit_v01 import (
    AUDIT_VERSION,
    default_audit_corpus,
)


def test_v01_preserves_case_count_and_ground_truth():
    corpus = default_audit_corpus()

    assert AUDIT_VERSION == "deep-baseline-v0.1"
    assert len(corpus) == 30
    assert len({case.case_id for case in corpus}) == 30


def test_v01_adds_explicit_scope_to_every_evidence_item():
    for case in default_audit_corpus():
        payload = case.view_payload()
        assert payload["audit_version"] == AUDIT_VERSION
        for item in payload["evidence"]:
            assert isinstance(item.get("entity"), str) and item["entity"]
            assert isinstance(item.get("predicate"), str) and item["predicate"]


def test_v01_preserves_intentional_entity_ambiguity():
    cases = {case.case_id: case for case in default_audit_corpus()}

    for case_id in ("S09", "H05"):
        evidence = cases[case_id].view_payload()["evidence"]
        assert evidence[0]["entity"] != evidence[1]["entity"]
        assert evidence[0]["identity_status"] == "same_physical_device_unresolved"
        assert evidence[1]["identity_status"] == "same_physical_device_unresolved"


def test_v01_noise_cases_mark_unrelated_predicates_explicitly():
    cases = {case.case_id: case for case in default_audit_corpus()}

    m10 = cases["M10"].view_payload()["evidence"]
    assert [item["predicate"] for item in m10] == [
        "cpu_model",
        "cpu_model",
        "ram",
        "location",
    ]

    h10 = cases["H10"].view_payload()["evidence"]
    assert [item["predicate"] for item in h10] == [
        "location",
        "location",
        "temperature",
        "availability",
    ]
