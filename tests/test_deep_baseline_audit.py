from anima.cognition.llm_transport import LLMCallResult
from anima.cognition.proposals import CognitiveProposal
from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit import (
    ALLOWED_LABELS,
    AuditDifficulty,
    default_audit_corpus,
    make_request,
    normalize_response,
    run_case,
    summarize_results,
)


class GroundTruthBackend:
    def __init__(self, expected):
        self.expected = expected
        self.call_history = []

    def complete(self, request):
        case_id = request.view.to_dict()["audit_case"]
        text = self.expected[case_id]
        self.call_history.append(
            LLMCallResult(
                provider="stub",
                model="ground-truth",
                text=text,
                thinking=False,
                latency_ms=2.0,
                input_tokens=20,
                output_tokens=1,
                finish_reason="stop",
                raw_output_chars=len(text),
            )
        )
        return CognitiveProposal.respond(text)


class InvalidBackend:
    def __init__(self):
        self.call_history = []

    def complete(self, request):
        return CognitiveProposal.respond("I think the first source wins.")


def test_default_corpus_is_balanced_and_ground_truthed():
    corpus = default_audit_corpus()

    assert len(corpus) == 30
    assert len({case.case_id for case in corpus}) == 30
    assert {case.expected for case in corpus} <= set(ALLOWED_LABELS)
    assert sum(case.difficulty == AuditDifficulty.SIMPLE for case in corpus) == 10
    assert sum(case.difficulty == AuditDifficulty.INTERMEDIATE for case in corpus) == 10
    assert sum(case.difficulty == AuditDifficulty.HARD for case in corpus) == 10
    assert sum(case.expected == "UNRESOLVED" for case in corpus) >= 7


def test_same_case_payload_is_role_neutral_except_consumer():
    case = default_audit_corpus()[0]

    fast = make_request(case, CognitiveRole.FAST)
    deep = make_request(case, CognitiveRole.DEEP)

    assert fast.view.to_dict() == deep.view.to_dict()
    assert fast.view.consumer == "FAST"
    assert deep.view.consumer == "DEEP"
    assert fast.view.to_dict()["audit_case"] == case.case_id


def test_run_case_scores_exact_ground_truth_and_call_metrics():
    corpus = default_audit_corpus()
    expected = {case.case_id: case.expected for case in corpus}
    backend = GroundTruthBackend(expected)

    result = run_case(corpus[0], role=CognitiveRole.DEEP, backend=backend)

    assert result.correct is True
    assert result.format_valid is True
    assert result.latency_ms == 2.0
    assert result.input_tokens == 20
    assert result.output_tokens == 1
    assert result.error is None


def test_invalid_free_text_does_not_receive_subjective_partial_credit():
    case = default_audit_corpus()[0]
    result = run_case(case, role=CognitiveRole.DEEP, backend=InvalidBackend())

    assert result.correct is False
    assert result.format_valid is False
    assert result.normalized_response == "I THINK THE FIRST SOURCE WINS."


def test_normalization_allows_only_trivial_terminal_punctuation():
    assert normalize_response(" unresolved. ") == "UNRESOLVED"
    assert normalize_response("UNRESOLVED because evidence conflicts") not in ALLOWED_LABELS


def test_summary_reports_difficulty_and_abstention_quality():
    corpus = default_audit_corpus()
    expected = {case.case_id: case.expected for case in corpus}
    backend = GroundTruthBackend(expected)
    results = [
        run_case(case, role=CognitiveRole.DEEP, backend=backend)
        for case in corpus
    ]

    summary = summarize_results(results)

    assert summary["passes"] == 30
    assert summary["total"] == 30
    assert summary["format_valid"] == 30
    assert summary["errors"] == 0
    assert summary["abstention_passes"] == summary["abstention_total"]
    assert summary["by_difficulty"]["simple"] == {"passes": 10, "total": 10}
    assert summary["by_difficulty"]["intermediate"] == {"passes": 10, "total": 10}
    assert summary["by_difficulty"]["hard"] == {"passes": 10, "total": 10}
    assert summary["input_tokens"] == 600
    assert summary["output_tokens"] == 30
