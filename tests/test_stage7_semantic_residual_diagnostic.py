import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anima.semantic import EvaluationPlan, evaluate_document, parse_and_validate_request
from anima.semantic.residual import ResidualModelError
from anima.semantic.residual_diagnostic import (
    DIAGNOSTIC_SYSTEM_PROMPT,
    DiagnosticBackend,
    complete_with_diagnostic,
    parse_diagnostic_proposal,
)


ROOT = Path(__file__).parent / "fixtures" / "stage7" / "classify_relation_0_1"
CASE_PATHS = {
    "CR-028": ROOT / "block_c" / "CR-028",
    "CR-032": ROOT / "block_c" / "CR-032",
    "CR-030-M": ROOT / "model_residual" / "CR-030-M",
    "CR-050-M": ROOT / "model_residual" / "CR-050-M",
}


def _case(case_id):
    case_dir = CASE_PATHS[case_id]
    raw = (case_dir / "request.json").read_text(encoding="utf-8")
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    request = parse_and_validate_request(raw)
    plan = evaluate_document(raw)
    assert isinstance(plan, EvaluationPlan)
    assert plan.residual_facets == ("revision",)
    return request, plan, expected


class FakeTransport:
    def __init__(self, proposal):
        self.text = json.dumps(proposal, separators=(",", ":"))
        self.calls = []

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        self.calls.append((system_prompt, user_prompt, timeout_seconds))
        return SimpleNamespace(text=self.text, model="fake")


def _run(case_id, proposal):
    request, plan, expected = _case(case_id)
    backend = DiagnosticBackend(FakeTransport(proposal))
    result = complete_with_diagnostic(request, plan, backend)
    return result, expected, backend


def test_factorized_explicit_correction_translates_to_canonical_revision():
    result, expected, backend = _run(
        "CR-028",
        {
            "signal": "present",
            "intent": "explicit",
            "replacement_claim_ref": "c2",
            "replaced_claim_ref": "c1",
            "declaration_evidence_ref": "e2",
        },
    )
    assert result.assessment == expected
    assert result.backend_calls == 1
    assert len(backend.call_history) == 1


def test_factorized_ambiguous_correction_translates_to_insufficient():
    result, expected, _ = _run(
        "CR-032",
        {
            "signal": "present",
            "intent": "ambiguous",
            "missing": "correction_intent",
            "evidence_ref": "e1",
        },
    )
    assert result.assessment == expected


@pytest.mark.parametrize("case_id", ["CR-030-M", "CR-050-M"])
def test_factorized_no_signal_translates_to_no_declaration(case_id):
    request, _, expected = _case(case_id)
    refs = [item["ref"] for item in request["evidence"]]
    result, _, _ = _run(case_id, {"signal": "none", "evidence_refs": refs})
    assert result.assessment == expected


def test_diagnostic_prompt_factorizes_signal_before_intent_and_excludes_coverage():
    request, plan, _ = _case("CR-032")
    transport = FakeTransport(
        {
            "signal": "present",
            "intent": "ambiguous",
            "missing": "correction_intent",
            "evidence_ref": "e1",
        }
    )
    backend = DiagnosticBackend(transport)
    complete_with_diagnostic(request, plan, backend)
    system_prompt, user_prompt, _ = transport.calls[0]
    assert system_prompt == DIAGNOSTIC_SYSTEM_PROMPT
    assert "Step 1" in system_prompt
    assert "Step 2" in system_prompt
    assert '"coverage"' not in user_prompt
    assert "maybe I was wrong" in user_prompt.lower()


def test_diagnostic_output_cannot_add_authority_fields():
    request, _, _ = _case("CR-028")
    proposal = {
        "signal": "present",
        "intent": "explicit",
        "replacement_claim_ref": "c2",
        "replaced_claim_ref": "c1",
        "declaration_evidence_ref": "e2",
        "write_knowledge": True,
    }
    with pytest.raises(ResidualModelError, match="unknown/missing fields"):
        parse_diagnostic_proposal(json.dumps(proposal), request)


def test_diagnostic_signal_none_still_requires_system_owned_complete_coverage():
    request, _, _ = _case("CR-032")
    request = json.loads(json.dumps(request))
    request["coverage"]["completeness"] = "partial"
    with pytest.raises(ResidualModelError, match="complete declared-scope coverage"):
        parse_diagnostic_proposal(
            '{"signal":"none","evidence_refs":["e1"]}', request
        )
