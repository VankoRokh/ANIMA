from scripts.run_fast_relevance_gate_experiment import (
    apply_relevance_gate,
    lexical_anchors,
    run_experiment,
)


def _item(text, item_id="mem_test"):
    return {
        "kind": "memory",
        "id": item_id,
        "text": text,
        "score": 35,
        "selection_reason": ["test"],
    }


def test_lexical_anchors_remove_generic_relation_words():
    anchors = lexical_anchors("Как зовут мою собаку?")

    assert "собаку" in anchors
    assert "зовут" not in anchors
    assert "мою" not in anchors


def test_gate_rejects_cat_fact_for_dog_question():
    accepted, decisions = apply_relevance_gate(
        "Как зовут мою собаку?",
        [_item("Кота пользователя зовут Барсик.")],
    )

    assert accepted == []
    assert decisions[0]["accepted"] is False
    assert decisions[0]["shared_anchors"] == []


def test_gate_keeps_coffee_fact_for_coffee_question():
    item = _item("Пользователь предпочитает кофе эспрессо.")
    accepted, decisions = apply_relevance_gate(
        "Какой кофе я предпочитаю?",
        [item],
    )

    assert accepted == [item]
    assert decisions[0]["accepted"] is True
    assert "кофе" in decisions[0]["shared_anchors"]


def test_gate_keeps_semantic_paraphrase_with_shared_work_anchor():
    item = _item("Пользователь предпочитает работать по вечерам.")
    accepted, decisions = apply_relevance_gate(
        "В какое время суток мне обычно нравится работать?",
        [item],
    )

    assert accepted == [item]
    assert "работать" in decisions[0]["shared_anchors"]


def test_gate_experiment_passes_current_six_case_corpus():
    result = run_experiment()

    assert result["summary"]["passed"] == 6
    assert result["summary"]["total"] == 6
    assert result["summary"]["false_context_injections"] == 0
