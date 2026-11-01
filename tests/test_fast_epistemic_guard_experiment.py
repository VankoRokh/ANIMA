from scripts.run_fast_epistemic_guard_experiment import (
    ALLOW_FAST,
    BLOCK_UNGROUNDED,
    CONTEXT_REQUIRED,
    OPEN_KNOWLEDGE,
    CORPUS,
    classify_scope,
    guard_decision,
    run_experiment,
)


def test_classifier_matches_full_experiment_corpus():
    for case_id, query, expected_scope in CORPUS:
        result = classify_scope(query)
        assert result["scope"] == expected_scope, (
            case_id,
            query,
            expected_scope,
            result,
        )


def test_calculation_with_personal_pronoun_stays_open():
    result = classify_scope("Помоги мне посчитать 12×8")
    assert result["scope"] == OPEN_KNOWLEDGE


def test_action_on_personal_device_is_not_treated_as_private_fact():
    result = classify_scope("Как починить мой ноутбук, если он не включается?")
    assert result["scope"] == OPEN_KNOWLEDGE


def test_unknown_personal_fact_is_blocked_before_fast():
    decision = guard_decision(CONTEXT_REQUIRED, "NOT_FOUND")
    assert decision["action"] == BLOCK_UNGROUNDED


def test_found_personal_fact_is_allowed_to_fast():
    decision = guard_decision(CONTEXT_REQUIRED, "FOUND")
    assert decision["action"] == ALLOW_FAST


def test_open_knowledge_without_memory_is_allowed_to_fast():
    decision = guard_decision(OPEN_KNOWLEDGE, "NOT_FOUND")
    assert decision["action"] == ALLOW_FAST


def test_experiment_summary_is_clean():
    result = run_experiment()
    assert result["summary"]["passed"] == result["summary"]["total"]
    assert result["summary"]["guard_matrix_passed"] == result["summary"]["guard_matrix_total"]
