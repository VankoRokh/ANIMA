from scripts.run_fast_epistemic_guard_stress_experiment import (
    ALLOW_FAST,
    AMBIGUOUS,
    BLOCK_UNGROUNDED,
    CONTEXT_REQUIRED,
    OPEN_KNOWLEDGE,
    RESOLVE_WITH_CONTEXT,
    STRESS_CORPUS,
    classify_scope_v1,
    guard_decision_v1,
    run_experiment,
)


def test_stress_corpus_v1_classification():
    for case_id, query, expected_scope in STRESS_CORPUS:
        result = classify_scope_v1(query)
        assert result["scope"] == expected_scope, case_id


def test_context_required_missing_is_blocked():
    result = guard_decision_v1(CONTEXT_REQUIRED, "NOT_FOUND")
    assert result["action"] == BLOCK_UNGROUNDED


def test_open_knowledge_missing_is_allowed():
    result = guard_decision_v1(OPEN_KNOWLEDGE, "NOT_FOUND")
    assert result["action"] == ALLOW_FAST


def test_ambiguous_requires_resolution_even_when_memory_exists():
    assert guard_decision_v1(AMBIGUOUS, "NOT_FOUND")["action"] == RESOLVE_WITH_CONTEXT
    assert guard_decision_v1(AMBIGUOUS, "FOUND")["action"] == RESOLVE_WITH_CONTEXT


def test_experiment_reports_full_v1_pass_and_v0_risk():
    result = run_experiment()
    summary = result["summary"]
    assert summary["passed"] == summary["total"] == len(STRESS_CORPUS)
    assert summary["guard_matrix_passed"] == summary["guard_matrix_total"] == 6
    assert summary["v0_unsafe_false_negatives"] > 0
    assert summary["v0_ambiguity_collapses"] > 0
