from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit_v02 import CANDIDATES
from scripts.benchmark_deep_cross_role_order import (
    CROSS_ARMS,
    ORDERS,
    response_counts,
    selected_cases,
)


def test_cross_role_plan_contains_only_missing_model_role_combinations():
    assert CROSS_ARMS == (
        ("Qwen3-0.6B-Q8_0", CognitiveRole.DEEP),
        ("SmolLM3-3B-Q8_0", CognitiveRole.FAST),
    )


def test_cross_role_orders_preserve_same_candidate_set():
    assert ORDERS["original"] == tuple(CANDIDATES)
    assert ORDERS["reverse"] == tuple(reversed(CANDIDATES))
    assert set(ORDERS["original"]) == set(ORDERS["reverse"])


def test_cross_role_probe_uses_only_ten_simple_cases():
    cases = selected_cases()
    assert len(cases) == 10
    assert all(case.difficulty.value == "simple" for case in cases)


def test_response_counts_separates_non_exact_outputs():
    rows = [
        {"exact_candidate": "SUPPORT|RESOLVED"},
        {"exact_candidate": "SUPPORT|RESOLVED"},
        {"exact_candidate": None},
    ]
    assert response_counts(rows) == {
        "SUPPORT|RESOLVED": 2,
        "<non-exact>": 1,
    }
