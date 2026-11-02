from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit_v02 import CANDIDATES, default_audit_corpus
from scripts.benchmark_deep_order_probe import ordered_request


def test_order_probe_changes_only_candidate_order_and_audit_version():
    case = default_audit_corpus()[0]
    original = case.view_payload()
    reversed_candidates = tuple(reversed(CANDIDATES))

    request = ordered_request(case, CognitiveRole.FAST, reversed_candidates)
    payload = request.view.to_dict()

    assert payload["candidates"] == list(reversed_candidates)
    assert payload["evidence"] == original["evidence"]
    assert payload["input"] == original["input"]
    assert payload["operation"] == original["operation"]
    assert payload["output_contract"] == original["output_contract"]
    assert payload["audit_case"] == original["audit_case"]
    assert payload["audit_version"] != original["audit_version"]
    assert request.role == CognitiveRole.FAST
    assert request.view.consumer == "FAST"


def test_reverse_order_moves_previous_first_candidate_to_last():
    reversed_candidates = tuple(reversed(CANDIDATES))

    assert reversed_candidates[0] == CANDIDATES[-1]
    assert reversed_candidates[-1] == CANDIDATES[0]
