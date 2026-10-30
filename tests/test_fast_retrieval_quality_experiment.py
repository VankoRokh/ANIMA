from scripts.run_fast_retrieval_quality_experiment import (
    RETRIEVAL_CORPUS,
    evaluate_selected,
    summarize,
)


def _case(case_id):
    return next(case for case in RETRIEVAL_CORPUS if case["id"] == case_id)


def test_evaluator_accepts_expected_context():
    result = evaluate_selected(
        [{"text": "Пользователь предпочитает кофе эспрессо."}],
        _case("direct_recall"),
    )

    assert result["passed"] is True
    assert result["false_context_injection"] is False


def test_evaluator_rejects_misleading_neighbour_fact():
    result = evaluate_selected(
        [{"text": "Кота пользователя зовут Барсик."}],
        _case("missing_information"),
    )

    assert result["passed"] is False
    assert result["false_context_injection"] is True


def test_empty_context_is_valid_for_unknown_fact():
    result = evaluate_selected([], _case("unrelated_topic"))

    assert result["passed"] is True
    assert result["selected_count"] == 0


def test_summary_counts_passes_and_false_injections():
    cases = [
        {
            "latency_ms": 1.0,
            "evaluation": {
                "passed": True,
                "false_context_injection": False,
                "selected_count": 1,
            },
        },
        {
            "latency_ms": 3.0,
            "evaluation": {
                "passed": False,
                "false_context_injection": True,
                "selected_count": 2,
            },
        },
    ]

    summary = summarize(cases)

    assert summary["passed"] == 1
    assert summary["total"] == 2
    assert summary["false_context_injections"] == 1
    assert summary["mean_latency_ms"] == 2.0
    assert summary["selected_context_items"] == 3
