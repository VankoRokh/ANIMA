#!/usr/bin/env python3
"""Stress-test Epistemic Guard false negatives with a tri-state v1 classifier.

This experiment compares the existing binary Guard v0 against an experimental
tri-state classifier:

- CONTEXT_REQUIRED: answer must be grounded in private/current context;
- OPEN_KNOWLEDGE: FAST may answer without Memory;
- AMBIGUOUS: lexical form alone is insufficient, so runtime must resolve with
  entity/retrieval evidence before generation is allowed.

No LLM is called and production code is not modified.
"""

from __future__ import annotations

import json
import re
import time

from scripts.run_fast_epistemic_guard_experiment import (
    ACTION_PREFIXES,
    ARITHMETIC_OPERATOR_PATTERN,
    CALCULATION_WORDS,
    NUMBER_PATTERN,
    CONTEXT_REQUIRED,
    OPEN_KNOWLEDGE,
    _normalize,
    _tokens,
    classify_scope as classify_scope_v0,
)

AMBIGUOUS = "AMBIGUOUS"

BLOCK_UNGROUNDED = "BLOCK_UNGROUNDED"
ALLOW_FAST = "ALLOW_FAST"
RESOLVE_WITH_CONTEXT = "RESOLVE_WITH_CONTEXT"

OPEN_KNOWLEDGE_PREFIXES = (
    "что такое",
    "как устроен",
    "как устроена",
    "как устроено",
    "как работает",
    "как определить",
    "какие бывают",
    "какого цвета бывают",
    "что обычно пьют",
)

PERSONAL_HISTORY_OR_HABIT = re.compile(
    r"\b(?:я|мне|мы)\b.*\b(?:обычно|предпочита\w*|люб\w*|выбрал\w*|"
    r"говорил\w*|решил\w*|жив\w*|работа\w*|лож\w*|пью|использ\w*)\b",
    re.IGNORECASE,
)

PERSONAL_POSSESSIVE = re.compile(
    r"\b(?:мой|моя|моё|мое|мои|моего|мою|моих|моём|моем)\b",
    re.IGNORECASE,
)

PROJECT_HISTORY = (
    re.compile(r"\bчто\s+мы\s+решили\b", re.IGNORECASE),
    re.compile(r"\bкакой\s+вариант\s+мы\s+выбрали\b", re.IGNORECASE),
    re.compile(r"\bна\s+каком\s+этапе\s+сейчас\s+(?:anima|анима)\b", re.IGNORECASE),
    re.compile(r"\bчто\s+я\s+говорил\b", re.IGNORECASE),
    re.compile(r"\bчто\s+я\s+выбрал\b", re.IGNORECASE),
)

# Proper-name/property questions may refer to a private entity (for example a pet)
# or to a public entity. v1 therefore refuses to guess and marks them AMBIGUOUS.
NAMED_ENTITY_PROPERTY = (
    re.compile(r"^какого\s+цвета\s+[А-ЯA-Z][\w-]+\??$"),
    re.compile(r"^что\s+любит\s+[А-ЯA-Z][\w-]+\??$"),
    re.compile(r"^когда\s+[А-ЯA-Z][\w-]+\s+обычно\s+ест\??$"),
    re.compile(r"^какой\s+у\s+[А-ЯA-Z][\w-]+\s+характер\??$"),
)

VAGUE_CONTEXT_REFERENCE = (
    re.compile(r"\bпоследн(?:яя|ий|ее)\s+(?:сборка|решение|вариант|версия)\b", re.IGNORECASE),
    re.compile(r"\bэт(?:от|а|о)\s+(?:проект|устройство|вариант)\b", re.IGNORECASE),
)


STRESS_CORPUS = (
    # Clearly private/current context.
    ("personal_worktime", "В какое время суток мне обычно нравится работать?", CONTEXT_REQUIRED),
    ("personal_work_habit", "Когда я обычно работаю?", CONTEXT_REQUIRED),
    ("personal_sleep", "Во сколько я обычно ложусь?", CONTEXT_REQUIRED),
    ("personal_morning_drink", "Что я обычно пью утром?", CONTEXT_REQUIRED),
    ("personal_pet_color", "Какого цвета мой кот?", CONTEXT_REQUIRED),
    ("project_decision", "Что мы решили насчёт FAST?", CONTEXT_REQUIRED),
    ("project_stage", "На каком этапе сейчас ANIMA?", CONTEXT_REQUIRED),
    ("personal_previous_choice", "Что я выбрал в прошлый раз?", CONTEXT_REQUIRED),
    ("personal_prior_statement", "Что я говорил про Raspberry Pi?", CONTEXT_REQUIRED),
    ("shared_previous_choice", "Какой вариант мы выбрали?", CONTEXT_REQUIRED),

    # Clearly answerable without private/current context.
    ("general_bar_worktime", "В какое время суток обычно работают бары?", OPEN_KNOWLEDGE),
    ("general_cat_colors", "Какого цвета бывают британские коты?", OPEN_KNOWLEDGE),
    ("general_morning_drinks", "Что обычно пьют утром?", OPEN_KNOWLEDGE),
    ("general_fast", "Что такое FAST?", OPEN_KNOWLEDGE),
    ("general_raspberry", "Как устроен Raspberry Pi?", OPEN_KNOWLEDGE),
    ("general_coat", "Как определить цвет шерсти кота?", OPEN_KNOWLEDGE),
    ("repair_my_device", "Как починить мой ноутбук, если он не включается?", OPEN_KNOWLEDGE),
    ("calculate_for_me", "Помоги мне посчитать 12×8", OPEN_KNOWLEDGE),
    ("explain_for_me", "Объясни мне, как работает FTS", OPEN_KNOWLEDGE),
    ("recommend_laptop", "Какой ноутбук лучше купить?", OPEN_KNOWLEDGE),

    # Lexically ambiguous without entity/current-context evidence.
    ("barsik_color", "Какого цвета Барсик?", AMBIGUOUS),
    ("barsik_likes", "Что любит Барсик?", AMBIGUOUS),
    ("barsik_food_time", "Когда Барсик обычно ест?", AMBIGUOUS),
    ("barsik_character", "Какой у Барсика характер?", AMBIGUOUS),
    ("last_build", "Когда была последняя сборка?", AMBIGUOUS),
    ("this_project", "Когда начался этот проект?", AMBIGUOUS),
)


def classify_scope_v1(text: str) -> dict:
    normalized = _normalize(text)
    tokens = _tokens(normalized)

    # Keep the safe v0 overrides first: arithmetic and explicit task requests
    # must not become private-context requests merely because they contain "мне"/"мой".
    if ARITHMETIC_OPERATOR_PATTERN.search(normalized) or (
        NUMBER_PATTERN.search(normalized) and tokens & CALCULATION_WORDS
    ):
        return {"scope": OPEN_KNOWLEDGE, "reason": "calculation_override"}

    if any(normalized.startswith(prefix) for prefix in ACTION_PREFIXES):
        return {"scope": OPEN_KNOWLEDGE, "reason": "action_request_override"}

    if any(normalized.startswith(prefix) for prefix in OPEN_KNOWLEDGE_PREFIXES):
        return {"scope": OPEN_KNOWLEDGE, "reason": "open_knowledge_form"}

    for pattern in PROJECT_HISTORY:
        if pattern.search(normalized):
            return {"scope": CONTEXT_REQUIRED, "reason": "project_or_history_context"}

    if PERSONAL_HISTORY_OR_HABIT.search(normalized):
        return {"scope": CONTEXT_REQUIRED, "reason": "personal_history_or_habit"}

    if PERSONAL_POSSESSIVE.search(normalized):
        return {"scope": CONTEXT_REQUIRED, "reason": "personal_possessive_fact"}

    # Reuse v0 only when it already detects a contextual query.
    v0 = classify_scope_v0(text)
    if v0["scope"] == CONTEXT_REQUIRED:
        return {"scope": CONTEXT_REQUIRED, "reason": f"v0:{v0['reason']}"}

    for pattern in NAMED_ENTITY_PROPERTY:
        if pattern.match(text.strip()):
            return {"scope": AMBIGUOUS, "reason": "named_entity_requires_resolution"}

    for pattern in VAGUE_CONTEXT_REFERENCE:
        if pattern.search(normalized):
            return {"scope": AMBIGUOUS, "reason": "vague_context_reference"}

    return {"scope": OPEN_KNOWLEDGE, "reason": "default_open_knowledge"}


def guard_decision_v1(scope: str, memory_status: str) -> dict:
    if scope == CONTEXT_REQUIRED and memory_status == "NOT_FOUND":
        return {"action": BLOCK_UNGROUNDED, "reason": "required_context_missing"}
    if scope == AMBIGUOUS:
        return {"action": RESOLVE_WITH_CONTEXT, "reason": "scope_ambiguous"}
    return {"action": ALLOW_FAST, "reason": "generation_allowed"}


def _v0_risk(expected_scope: str, v0_scope: str) -> str:
    if expected_scope == CONTEXT_REQUIRED and v0_scope == OPEN_KNOWLEDGE:
        return "unsafe_false_negative"
    if expected_scope == AMBIGUOUS and v0_scope == OPEN_KNOWLEDGE:
        return "unsafe_ambiguity_collapse"
    if expected_scope == OPEN_KNOWLEDGE and v0_scope == CONTEXT_REQUIRED:
        return "overblocking"
    return "none"


def run_case(case_id: str, query: str, expected_scope: str) -> dict:
    started = time.perf_counter()
    v1 = classify_scope_v1(query)
    latency_ms = (time.perf_counter() - started) * 1000.0
    v0 = classify_scope_v0(query)
    return {
        "id": case_id,
        "query": query,
        "expected_scope": expected_scope,
        "v0_scope": v0["scope"],
        "v0_reason": v0["reason"],
        "v0_risk": _v0_risk(expected_scope, v0["scope"]),
        "v1_scope": v1["scope"],
        "v1_reason": v1["reason"],
        "passed": v1["scope"] == expected_scope,
        "latency_ms": latency_ms,
    }


def run_guard_matrix() -> list[dict]:
    matrix = (
        (CONTEXT_REQUIRED, "NOT_FOUND", BLOCK_UNGROUNDED),
        (CONTEXT_REQUIRED, "FOUND", ALLOW_FAST),
        (OPEN_KNOWLEDGE, "NOT_FOUND", ALLOW_FAST),
        (OPEN_KNOWLEDGE, "FOUND", ALLOW_FAST),
        (AMBIGUOUS, "NOT_FOUND", RESOLVE_WITH_CONTEXT),
        (AMBIGUOUS, "FOUND", RESOLVE_WITH_CONTEXT),
    )
    rows = []
    for scope, memory_status, expected_action in matrix:
        decision = guard_decision_v1(scope, memory_status)
        rows.append(
            {
                "scope": scope,
                "memory_status": memory_status,
                "expected_action": expected_action,
                "actual_action": decision["action"],
                "reason": decision["reason"],
                "passed": decision["action"] == expected_action,
            }
        )
    return rows


def run_experiment() -> dict:
    cases = [run_case(*case) for case in STRESS_CORPUS]
    guard_matrix = run_guard_matrix()
    passed = sum(1 for case in cases if case["passed"])
    latency_total = sum(case["latency_ms"] for case in cases)
    v0_unsafe_false_negatives = sum(
        1 for case in cases if case["v0_risk"] == "unsafe_false_negative"
    )
    v0_ambiguity_collapses = sum(
        1 for case in cases if case["v0_risk"] == "unsafe_ambiguity_collapse"
    )
    v0_overblocking = sum(1 for case in cases if case["v0_risk"] == "overblocking")
    guard_passed = sum(1 for row in guard_matrix if row["passed"])
    return {
        "experiment": "fast_epistemic_guard_stress_v1",
        "purpose": "Stress-test false negatives and evaluate tri-state epistemic classification",
        "llm_enabled": False,
        "production_modified": False,
        "classifier_v0": "deterministic binary rule-based",
        "classifier_v1": "experimental deterministic tri-state",
        "corpus_size": len(cases),
        "summary": {
            "passed": passed,
            "total": len(cases),
            "pass_rate": passed / len(cases),
            "latency_ms": latency_total,
            "mean_latency_ms": latency_total / len(cases),
            "v0_unsafe_false_negatives": v0_unsafe_false_negatives,
            "v0_ambiguity_collapses": v0_ambiguity_collapses,
            "v0_overblocking": v0_overblocking,
            "guard_matrix_passed": guard_passed,
            "guard_matrix_total": len(guard_matrix),
        },
        "cases": cases,
        "guard_matrix": guard_matrix,
    }


def main() -> int:
    result = run_experiment()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    ok = (
        result["summary"]["passed"] == result["summary"]["total"]
        and result["summary"]["guard_matrix_passed"]
        == result["summary"]["guard_matrix_total"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
