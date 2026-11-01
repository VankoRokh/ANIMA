from scripts.run_fast_memory_e2e_experiment import (
    E2E_CORPUS,
    _facts_from_context,
    evaluate_response,
    render_user_prompt,
)


def _case(case_id):
    return next(case for case in E2E_CORPUS if case["id"] == case_id)


def test_empty_context_is_rendered_explicitly():
    prompt = render_user_prompt("Как зовут мою собаку?", ())

    assert "FACTS:\n(none)" in prompt
    assert "QUESTION:\nКак зовут мою собаку?" in prompt


def test_context_items_become_fact_lines():
    facts = _facts_from_context(
        [
            {"text": "Пользователь предпочитает кофе эспрессо."},
            {"text": "Кот Барсик серого цвета."},
        ]
    )
    prompt = render_user_prompt("Что известно?", facts)

    assert "- Пользователь предпочитает кофе эспрессо." in prompt
    assert "- Кот Барсик серого цвета." in prompt


def test_missing_information_requires_unknown_and_forbids_barsik():
    case = _case("missing_information")

    assert evaluate_response("Нет данных.", case)["passed"] is True
    assert evaluate_response("Барсик.", case)["passed"] is False


def test_direct_recall_accepts_expected_answer():
    case = _case("direct_recall")

    assert evaluate_response("Эспрессо.", case)["passed"] is True
