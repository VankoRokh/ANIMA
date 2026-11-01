from scripts.run_structured_request_semantic_memory_experiment import (
    AMBIGUOUS,
    CORPUS,
    DEFER_TO_FAST,
    DETERMINISTIC_RESULT,
    FOUND,
    NOT_FOUND,
    ENTITY_REGISTRY,
    parse_request,
    resolve_entity,
    resolve_request,
    run_experiment,
)


def test_full_corpus_passes():
    result = run_experiment()
    assert result["summary"]["passed"] == result["summary"]["total"] == len(CORPUS)


def test_known_fact_uses_exact_semantic_lookup():
    result = resolve_request("А Барсик какого цвета?")
    assert result["result"]["outcome"] == FOUND
    assert result["result"]["value"] == "gray"
    assert result["result"]["fact"]["subject"] == "pet_barsik"
    assert result["result"]["fact"]["predicate"] == "color"


def test_missing_property_is_not_invented():
    result = resolve_request("Какой у Барсика характер?")
    assert result["result"]["outcome"] == NOT_FOUND
    assert "value" not in result["result"]


def test_pronoun_is_not_a_permanent_alias():
    assert "он" not in ENTITY_REGISTRY["pet_barsik"]["aliases"]
    result = resolve_request("Какого цвета он?")
    assert result["result"]["outcome"] == AMBIGUOUS


def test_pronoun_can_resolve_from_working_context():
    result = resolve_request("Какого цвета он?", active_entity="pet_barsik")
    assert result["result"]["outcome"] == FOUND
    assert result["result"]["value"] == "gray"
    assert result["request"]["entity_resolution"]["source"] == "working_context_pronoun"


def test_possessed_entity_resolves_through_relation_not_alias():
    resolution = resolve_entity("Какого цвета мой кот?")
    assert resolution["entity"] == "pet_barsik"
    assert resolution["source"] == "entity_relation"


def test_arithmetic_is_handled_deterministically():
    result = resolve_request("Помоги мне посчитать 12×8")
    assert result["result"]["outcome"] == DETERMINISTIC_RESULT
    assert result["result"]["value"] == 96


def test_unknown_language_is_preserved_for_fast():
    parsed = parse_request("Что такое SQLite?")
    result = resolve_request("Что такое SQLite?")
    assert parsed["raw_text"] == "Что такое SQLite?"
    assert result["result"]["outcome"] == DEFER_TO_FAST
