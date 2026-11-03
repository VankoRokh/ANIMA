import json
from pathlib import Path
from types import SimpleNamespace

from anima.semantic import (
    EvaluationPlan,
    RevisionResidualBackend,
    build_revision_residual_view,
    complete_with_residual,
    evaluate_document,
    parse_and_validate_request,
    render_revision_residual_prompts,
)


FIXTURE_ROOT = (
    Path(__file__).parent
    / "fixtures"
    / "stage7"
    / "classify_relation_0_1"
    / "model_residual"
)


class FakeTransport:
    def __init__(self, proposal):
        self.text = json.dumps(proposal, ensure_ascii=False, separators=(",", ":"))
        self.calls = []

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        self.calls.append((system_prompt, user_prompt, timeout_seconds))
        return SimpleNamespace(text=self.text, model="fake")


def _load(case_id):
    case_dir = FIXTURE_ROOT / case_id
    raw = (case_dir / "request.json").read_text(encoding="utf-8")
    request = parse_and_validate_request(raw)
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    plan = evaluate_document(raw)
    assert isinstance(plan, EvaluationPlan)
    assert plan.residual_facets == ("revision",)
    return request, plan, expected


def test_cr030m_natural_language_no_declaration_reaches_only_revision_model():
    request, plan, expected = _load("CR-030-M")
    assert plan.content == {"kind": "not_requested"}

    transport = FakeTransport(
        {"decision": "no_declaration", "evidence_refs": ["e1", "e2"]}
    )
    completed = complete_with_residual(
        request, plan, RevisionResidualBackend(transport)
    )

    assert completed.assessment == expected
    assert completed.backend_calls == 1
    assert len(transport.calls) == 1


def test_cr050m_injection_is_model_data_and_deterministic_content_stays_frozen():
    request, plan, expected = _load("CR-050-M")
    assert plan.content == expected["content"]

    view = build_revision_residual_view(request, plan)
    system_prompt, user_prompt = render_revision_residual_prompts(view)
    assert "write it to Knowledge" in user_prompt
    assert "run a shell tool" in user_prompt
    assert "data, not instructions" in system_prompt

    transport = FakeTransport(
        {"decision": "no_declaration", "evidence_refs": ["e1", "e2"]}
    )
    completed = complete_with_residual(
        request, plan, RevisionResidualBackend(transport)
    )

    assert completed.assessment == expected
    assert completed.assessment["content"] == plan.content
    assert completed.backend_calls == 1
