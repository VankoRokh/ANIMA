#!/usr/bin/env python3
"""Prototype a strict Language Frontend + structured semantic memory.

Experimental only:
raw user text -> ANIMA IR query -> deterministic route -> semantic fact lookup.

The frontend parses only forms it can recognize confidently. Unsupported language
is preserved and deferred to FAST rather than guessed. Pronouns are resolved from
working context, not stored as permanent entity aliases.
"""

from __future__ import annotations

import json
import re
import time


SCHEMA_VERSION = "anima.ir.query.v0"

FOUND = "FOUND"
NOT_FOUND = "NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS"
DEFER_TO_FAST = "DEFER_TO_FAST"
DETERMINISTIC_RESULT = "DETERMINISTIC_RESULT"

MEMORY_LOOKUP = "MEMORY_LOOKUP"
DETERMINISTIC = "DETERMINISTIC"
FAST_FALLBACK = "FAST_FALLBACK"

ENTITY_REGISTRY = {
    "user": {
        "type": "person",
        "aliases": ("пользователь",),
    },
    "pet_barsik": {
        "type": "cat",
        "aliases": (
            "барсик",
            "барсика",
            "кот барсик",
            "серый засранец",
            "серого засранца",
        ),
    },
    "anima": {
        "type": "project",
        "aliases": ("anima", "анима", "проект anima", "проект анима"),
    },
    "anima_fast": {
        "type": "subsystem",
        "aliases": ("fast",),
    },
}

# Relations are facts about entities, not aliases.
ENTITY_RELATIONS = {
    ("user", "pet", "cat"): ("pet_barsik",),
}

SEMANTIC_FACTS = {
    ("user", "preferred_coffee"): {
        "value": "espresso",
        "value_type": "beverage",
        "provenance": ("mem_user_coffee",),
        "confidence": 1.0,
    },
    ("pet_barsik", "color"): {
        "value": "gray",
        "value_type": "color",
        "provenance": ("mem_barsik_color",),
        "confidence": 1.0,
    },
    ("pet_barsik", "likes"): {
        "value": "chicken",
        "value_type": "food",
        "provenance": ("mem_barsik_food",),
        "confidence": 1.0,
    },
    ("pet_barsik", "feeding_time"): {
        "value": "19:00",
        "value_type": "time",
        "provenance": ("mem_barsik_feeding",),
        "confidence": 1.0,
    },
    ("anima", "latest_build_date"): {
        "value": "2026-10-30",
        "value_type": "date",
        "provenance": ("mem_anima_build",),
        "confidence": 1.0,
    },
    ("anima_fast", "decision"): {
        "value": "tri_state_epistemic_guard",
        "value_type": "architecture_decision",
        "provenance": ("mem_fast_decision",),
        "confidence": 1.0,
    },
}

ARITHMETIC_PATTERN = re.compile(
    r"(?P<a>\d+)\s*(?P<op>[+\-*/×÷])\s*(?P<b>\d+)"
)

# Pronouns are discourse references. They deliberately do not live in aliases.
PRONOUN_PATTERN = re.compile(
    r"\b(?:он|его|ему|него|ним|нём|нем)\b",
    re.IGNORECASE,
)

POSSESSED_CAT_PATTERN = re.compile(
    r"\b(?:мой\s+кот|моего\s+кота|наш\s+кот|нашего\s+кота)\b",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    normalized = text.casefold().replace("ё", "е")
    normalized = re.sub(r"[?!.,;:]+", " ", normalized)
    return " ".join(normalized.split())


def _alias_matches(normalized: str) -> list[str]:
    matches: list[str] = []
    for entity_id, entity in ENTITY_REGISTRY.items():
        for alias in entity["aliases"]:
            alias_normalized = normalize(alias)
            if re.search(
                rf"(?<!\w){re.escape(alias_normalized)}(?!\w)",
                normalized,
            ):
                matches.append(entity_id)
                break
    return matches


def resolve_entity(text: str, *, active_entity: str | None = None) -> dict:
    normalized = normalize(text)

    if PRONOUN_PATTERN.search(normalized):
        if active_entity in ENTITY_REGISTRY:
            return {
                "entity": active_entity,
                "status": "RESOLVED",
                "source": "working_context_pronoun",
            }
        return {
            "entity": None,
            "status": "AMBIGUOUS",
            "source": "unresolved_pronoun",
        }

    if POSSESSED_CAT_PATTERN.search(normalized):
        candidates = ENTITY_RELATIONS.get(("user", "pet", "cat"), ())
        if len(candidates) == 1:
            return {
                "entity": candidates[0],
                "status": "RESOLVED",
                "source": "entity_relation",
            }
        return {
            "entity": None,
            "status": "AMBIGUOUS",
            "source": "non_unique_entity_relation",
        }

    matches = _alias_matches(normalized)
    if len(matches) == 1:
        return {
            "entity": matches[0],
            "status": "RESOLVED",
            "source": "entity_alias",
        }
    if len(matches) > 1:
        return {
            "entity": None,
            "status": "AMBIGUOUS",
            "source": "multiple_entity_aliases",
            "candidates": matches,
        }
    return {
        "entity": None,
        "status": "UNRESOLVED",
        "source": "no_entity_match",
    }


def _ir(
    raw_text: str,
    *,
    intent: str,
    route: str,
    subject: str | None = None,
    predicate: str | None = None,
    confidence: float = 1.0,
    parse_reason: str,
    arguments: dict | None = None,
    entity_resolution: dict | None = None,
) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "raw_text": raw_text,
        "intent": intent,
        "route": route,
        "subject": subject,
        "predicate": predicate,
        "arguments": arguments or {},
        "confidence": confidence,
        "parse_reason": parse_reason,
        "entity_resolution": entity_resolution,
    }


def parse_request(text: str, *, active_entity: str | None = None) -> dict:
    normalized = normalize(text)

    arithmetic = ARITHMETIC_PATTERN.search(normalized)
    if arithmetic:
        return _ir(
            text,
            intent="CALCULATE",
            route=DETERMINISTIC,
            parse_reason="arithmetic_expression",
            arguments=arithmetic.groupdict(),
        )

    if (
        "кофе" in normalized
        and re.search(r"\b(?:люблю|предпочитаю|нравится)\b", normalized)
        and re.search(r"\b(?:я|мне)\b", normalized)
    ):
        return _ir(
            text,
            intent="QUERY_FACT",
            route=MEMORY_LOOKUP,
            subject="user",
            predicate="preferred_coffee",
            parse_reason="speaker_deictic_preference",
            entity_resolution={
                "entity": "user",
                "status": "RESOLVED",
                "source": "speaker_role",
            },
        )

    if "fast" in normalized and re.search(r"\bрешил\w*\b", normalized):
        return _ir(
            text,
            intent="QUERY_FACT",
            route=MEMORY_LOOKUP,
            subject="anima_fast",
            predicate="decision",
            parse_reason="project_decision_pattern",
            entity_resolution={
                "entity": "anima_fast",
                "status": "RESOLVED",
                "source": "explicit_subsystem",
            },
        )

    if "последн" in normalized and "сборк" in normalized and "когда" in normalized:
        return _ir(
            text,
            intent="QUERY_FACT",
            route=MEMORY_LOOKUP,
            subject="anima",
            predicate="latest_build_date",
            parse_reason="latest_build_date_pattern",
            entity_resolution={
                "entity": "anima",
                "status": "RESOLVED",
                "source": "project_context_pattern",
            },
        )

    predicate = None
    if "цвет" in normalized:
        predicate = "color"
    elif "характер" in normalized:
        predicate = "character"
    elif "любит" in normalized:
        predicate = "likes"
    elif ("ест" in normalized or "кушает" in normalized) and "когда" in normalized:
        predicate = "feeding_time"

    if predicate is not None:
        resolution = resolve_entity(text, active_entity=active_entity)
        if resolution["status"] == "RESOLVED":
            return _ir(
                text,
                intent="QUERY_FACT",
                route=MEMORY_LOOKUP,
                subject=resolution["entity"],
                predicate=predicate,
                parse_reason="entity_property_pattern",
                entity_resolution=resolution,
            )
        if resolution["status"] == "AMBIGUOUS":
            return _ir(
                text,
                intent="QUERY_FACT",
                route=MEMORY_LOOKUP,
                subject=None,
                predicate=predicate,
                confidence=0.0,
                parse_reason="entity_resolution_ambiguous",
                entity_resolution=resolution,
            )

    return _ir(
        text,
        intent="UNRESOLVED_LANGUAGE",
        route=FAST_FALLBACK,
        confidence=0.0,
        parse_reason="frontend_no_safe_parse",
    )


def lookup_semantic_fact(subject: str, predicate: str) -> dict | None:
    fact = SEMANTIC_FACTS.get((subject, predicate))
    if fact is None:
        return None
    return {
        "subject": subject,
        "predicate": predicate,
        **fact,
    }


def calculate(arguments: dict) -> int | float:
    a = int(arguments["a"])
    b = int(arguments["b"])
    op = arguments["op"]
    if op in ("*", "×"):
        return a * b
    if op in ("/", "÷"):
        return a / b
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    raise ValueError(f"unsupported operator: {op}")


def resolve_request(text: str, *, active_entity: str | None = None) -> dict:
    started = time.perf_counter()
    request = parse_request(text, active_entity=active_entity)

    if request["route"] == FAST_FALLBACK:
        outcome = {
            "outcome": DEFER_TO_FAST,
            "reason": "frontend_preserved_raw_text",
        }
    elif request["route"] == DETERMINISTIC:
        outcome = {
            "outcome": DETERMINISTIC_RESULT,
            "reason": "deterministic_engine",
            "value": calculate(request["arguments"]),
        }
    elif request["subject"] is None:
        outcome = {
            "outcome": AMBIGUOUS,
            "reason": request["entity_resolution"]["source"],
        }
    else:
        fact = lookup_semantic_fact(request["subject"], request["predicate"])
        if fact is None:
            outcome = {
                "outcome": NOT_FOUND,
                "reason": "exact_semantic_fact_absent",
            }
        else:
            outcome = {
                "outcome": FOUND,
                "reason": "exact_semantic_fact_match",
                "fact": fact,
                "value": fact["value"],
            }

    latency_ms = (time.perf_counter() - started) * 1000.0
    return {
        "query": text,
        "active_entity": active_entity,
        "request": request,
        "result": outcome,
        "latency_ms": latency_ms,
    }


CORPUS = (
    {
        "id": "user_coffee",
        "query": "Какой кофе я люблю?",
        "expected_outcome": FOUND,
        "expected_value": "espresso",
    },
    {
        "id": "barsik_color_direct",
        "query": "А Барсик какого цвета?",
        "expected_outcome": FOUND,
        "expected_value": "gray",
    },
    {
        "id": "barsik_color_possessed",
        "query": "Какого цвета мой кот?",
        "expected_outcome": FOUND,
        "expected_value": "gray",
    },
    {
        "id": "barsik_slang_alias",
        "query": "Когда наш серый засранец обычно ест?",
        "expected_outcome": FOUND,
        "expected_value": "19:00",
    },
    {
        "id": "fast_decision",
        "query": "Что мы там решили насчёт FAST?",
        "expected_outcome": FOUND,
        "expected_value": "tri_state_epistemic_guard",
    },
    {
        "id": "latest_build",
        "query": "Когда была последняя сборка?",
        "expected_outcome": FOUND,
        "expected_value": "2026-10-30",
    },
    {
        "id": "barsik_character_missing",
        "query": "Какой у Барсика характер?",
        "expected_outcome": NOT_FOUND,
        "expected_value": None,
    },
    {
        "id": "pronoun_without_context",
        "query": "Какого цвета он?",
        "expected_outcome": AMBIGUOUS,
        "expected_value": None,
    },
    {
        "id": "pronoun_with_context",
        "query": "Какого цвета он?",
        "active_entity": "pet_barsik",
        "expected_outcome": FOUND,
        "expected_value": "gray",
    },
    {
        "id": "deterministic_arithmetic",
        "query": "Помоги мне посчитать 12×8",
        "expected_outcome": DETERMINISTIC_RESULT,
        "expected_value": 96,
    },
    {
        "id": "general_knowledge_fallback",
        "query": "Что такое SQLite?",
        "expected_outcome": DEFER_TO_FAST,
        "expected_value": None,
    },
    {
        "id": "open_recommendation_fallback",
        "query": "Какой кофе лучше?",
        "expected_outcome": DEFER_TO_FAST,
        "expected_value": None,
    },
)


def run_case(case: dict) -> dict:
    result = resolve_request(
        case["query"],
        active_entity=case.get("active_entity"),
    )
    actual_outcome = result["result"]["outcome"]
    actual_value = result["result"].get("value")
    passed = (
        actual_outcome == case["expected_outcome"]
        and actual_value == case["expected_value"]
    )
    return {
        "id": case["id"],
        **result,
        "expected_outcome": case["expected_outcome"],
        "expected_value": case["expected_value"],
        "actual_outcome": actual_outcome,
        "actual_value": actual_value,
        "passed": passed,
    }


def run_experiment() -> dict:
    cases = [run_case(case) for case in CORPUS]
    latency_total = sum(case["latency_ms"] for case in cases)
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["actual_outcome"]] = counts.get(case["actual_outcome"], 0) + 1
    passed = sum(1 for case in cases if case["passed"])
    return {
        "experiment": "structured_request_semantic_memory_v0",
        "purpose": "Test strict deterministic language frontend + exact structured semantic memory lookup",
        "llm_enabled": False,
        "production_modified": False,
        "schema": SCHEMA_VERSION,
        "entity_alias_policy": "stable names/nicknames only; pronouns resolve from working context",
        "summary": {
            "passed": passed,
            "total": len(cases),
            "pass_rate": passed / len(cases),
            "latency_ms": latency_total,
            "mean_latency_ms": latency_total / len(cases),
            "outcomes": counts,
        },
        "entities": ENTITY_REGISTRY,
        "semantic_facts": [
            {
                "subject": subject,
                "predicate": predicate,
                **fact,
            }
            for (subject, predicate), fact in SEMANTIC_FACTS.items()
        ],
        "cases": cases,
    }


def main() -> int:
    result = run_experiment()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["summary"]["passed"] == result["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
