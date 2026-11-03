import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anima.semantic import (
    REVISION_SYSTEM_PROMPT,
    DeterministicRelationEvaluator,
    EvaluationPlan,
    ExactUnitRegistry,
    ProcessFailure,
    ResidualModelError,
    RevisionResidualBackend,
    complete_with_residual,
    evaluate_document,
    parse_and_validate_request,
    parse_revision_proposal,
    validate_assessment,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "stage7" / "classify_relation_0_1"


def _residual_case(case_id="CR-028"):
    case_dir = FIXTURE_ROOT / "block_c" / case_id
    raw = (case_dir / "request.json").read_text(encoding="utf-8")
    request = parse_and_validate_request(raw)
    plan = evaluate_document(raw)
    assert isinstance(plan, EvaluationPlan)
    assert plan.residual_facets == ("revision",)
    return raw, request, plan


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


def test_residual_plan_is_bound_to_the_exact_request_that_created_it():
    raw, _, plan = _residual_case()
    changed_request = json.loads(raw)
    changed_request["claims"][0]["value"]["value"] = "513"

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        complete_with_residual(changed_request, plan)


def test_no_declaration_must_cover_the_full_supplied_evidence_slice():
    _, request, _ = _residual_case()
    raw_proposal = '{"decision":"no_declaration","evidence_refs":["e1"]}'

    with pytest.raises(ResidualModelError, match="full supplied evidence slice"):
        parse_revision_proposal(raw_proposal, request)


def test_standalone_validator_rejects_no_declaration_with_partial_evidence_slice():
    _, request, plan = _residual_case()
    assessment = {
        "profile": request["profile"],
        "kind": "assessment",
        "content": dict(plan.content),
        "revision": {
            "kind": "no_declaration_in_scope",
            "evidence_refs": ["e1"],
        },
    }

    with pytest.raises(ProcessFailure) as exc_info:
        validate_assessment(assessment, request)

    assert exc_info.value.stage == "semantic_validation"
    assert exc_info.value.code == "invalid_no_declaration_scope"
    assert exc_info.value.details == {"field": "revision.evidence_refs"}


def test_standalone_validator_rejects_no_declaration_without_complete_coverage():
    _, request, plan = _residual_case()
    request = json.loads(json.dumps(request))
    request["coverage"] = {
        "completeness": "partial",
        "limitations": ["other_selection_limit"],
    }
    assessment = {
        "profile": request["profile"],
        "kind": "assessment",
        "content": dict(plan.content),
        "revision": {
            "kind": "no_declaration_in_scope",
            "evidence_refs": [item["ref"] for item in request["evidence"]],
        },
    }

    with pytest.raises(ProcessFailure) as exc_info:
        validate_assessment(assessment, request)

    assert exc_info.value.stage == "semantic_validation"
    assert exc_info.value.code == "invalid_no_declaration_scope"
    assert exc_info.value.details == {"field": "coverage.completeness"}


def test_rejected_residual_output_remains_observable_in_call_history():
    _, request, plan = _residual_case()
    raw_output = (
        '{"decision":"ambiguous_correction",'
        '"missing":"not_a_valid_gap","evidence_ref":"e1"}'
    )

    class FakeTransport:
        def complete(self, **kwargs):
            return SimpleNamespace(text=raw_output, model="fake")

    backend = RevisionResidualBackend(FakeTransport())
    with pytest.raises(ResidualModelError, match="invalid missing reason"):
        complete_with_residual(request, plan, backend)

    assert len(backend.call_history) == 1
    assert backend.call_history[0].text == raw_output


def test_residual_prompt_does_not_present_enum_alternatives_as_one_literal_value():
    assert "correction_intent|source_attribution|correction_target|evidence_fragment" not in (
        REVISION_SYSTEM_PROMPT
    )
    assert "missing must be exactly one of" in REVISION_SYSTEM_PROMPT
