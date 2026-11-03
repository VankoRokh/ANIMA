import json
from pathlib import Path

from anima.semantic import (
    DeterministicRelationEvaluator,
    EvaluationPlan,
    ExactUnitRegistry,
    evaluate_document,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "stage7" / "classify_relation_0_1"


def test_exact_unit_conversion_does_not_round_large_decimal_values():
    registry = ExactUnitRegistry.reference_defaults()

    left = {
        "type": "quantity",
        "value": "100000000000000000000000000000",
        "unit": "unit.m",
    }
    right = {
        "type": "quantity",
        "value": "10000000000000000000000000000001",
        "unit": "unit.cm",
    }

    assert registry.compare(left, right) is False


def test_exact_time_comparison_preserves_submicrosecond_fractional_order():
    request_path = FIXTURE_ROOT / "block_b" / "CR-017" / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["claims"][0]["validity"]["at"]["value"] = (
        "2026-11-03T12:00:00.0000001Z"
    )
    request["claims"][1]["validity"]["at"]["value"] = (
        "2026-11-03T12:00:00.0000002Z"
    )

    result = evaluate_document(json.dumps(request, separators=(",", ":")))

    assert isinstance(result, EvaluationPlan)
    assert result.content == {
        "kind": "relation",
        "relation": "TEMPORAL_SUCCESSION",
        "earlier_claim_ref": "c1",
        "later_claim_ref": "c2",
        "evidence_refs": ["e1", "e2"],
    }


def test_exact_time_comparison_normalizes_rfc3339_offsets_without_losing_fraction():
    evaluator = DeterministicRelationEvaluator()
    left = {
        "value": "2026-11-03T10:00:00.0000001Z",
        "clock": "clock.utc",
    }
    right = {
        "value": "2026-11-03T11:00:00.0000001+01:00",
        "clock": "clock.utc",
    }

    assert evaluator._timepoint_cmp(left, right) == 0
