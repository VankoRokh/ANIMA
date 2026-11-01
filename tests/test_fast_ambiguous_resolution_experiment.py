from scripts.run_fast_ambiguous_resolution_experiment import (
    AMBIGUOUS_CORPUS,
    RESOLVED_CONTEXT,
    UNRESOLVED,
    resolve_ambiguous,
    run_experiment,
)


def _item(text: str, item_id: str = "mem_test") -> dict:
    return {
        "kind": "memory",
        "id": item_id,
        "text": text,
        "score": 35,
        "selection_reason": [],
    }


def test_entity_identity_alone_does_not_resolve_property():
    result = resolve_ambiguous(
        "Какого цвета Барсик?",
        [_item("Кота пользователя зовут Барсик.")],
    )
    assert result["resolution"] == UNRESOLVED
    assert result["strong_evidence"] == []


def test_matching_entity_and_property_resolve_context():
    result = resolve_ambiguous(
        "Какого цвета Барсик?",
        [_item("Кот Барсик серого цвета.")],
    )
    assert result["resolution"] == RESOLVED_CONTEXT
    assert result["strong_evidence"]
    assert "барсик" in result["strong_evidence"][0]["shared_anchors"]
    assert "цвета" in result["strong_evidence"][0]["shared_anchors"]


def test_vague_project_reference_needs_requested_event_anchor():
    unresolved = resolve_ambiguous(
        "Когда начался этот проект?",
        [_item("Этот проект использует Python.")],
    )
    resolved = resolve_ambiguous(
        "Когда начался этот проект?",
        [_item("Этот проект начался в 2026 году.")],
    )
    assert unresolved["resolution"] == UNRESOLVED
    assert resolved["resolution"] == RESOLVED_CONTEXT


def test_experiment_resolves_and_rejects_expected_cases():
    result = run_experiment()
    summary = result["summary"]
    assert summary["passed"] == summary["total"] == len(AMBIGUOUS_CORPUS)
    assert summary["false_resolutions"] == 0
    assert summary["resolved"] > 0
    assert summary["unresolved"] > 0
