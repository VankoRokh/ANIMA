#!/usr/bin/env python3
"""Test a deterministic epistemic guard before FAST generation.

The guard answers one narrow question: does the user request a fact that must be
supported by ANIMA's private/current context, or may FAST answer from general
knowledge/reasoning without Memory?

This experiment does not call an LLM and does not modify production code.
"""

from __future__ import annotations

import json
import re
import time


CONTEXT_REQUIRED = "CONTEXT_REQUIRED"
OPEN_KNOWLEDGE = "OPEN_KNOWLEDGE"

BLOCK_UNGROUNDED = "BLOCK_UNGROUNDED"
ALLOW_FAST = "ALLOW_FAST"

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
NUMBER_PATTERN = re.compile(r"\d")
ARITHMETIC_OPERATOR_PATTERN = re.compile(r"(?:\d\s*[+\-*/×÷]\s*\d)")

ACTION_PREFIXES = (
    "помоги",
    "объясни",
    "расскажи как",
    "покажи как",
    "как починить",
    "как настроить",
    "как установить",
    "как сделать",
    "как приготовить",
    "как выбрать",
    "как использовать",
    "переведи",
)

CALCULATION_WORDS = {
    "посчитать",
    "посчитай",
    "вычислить",
    "вычисли",
    "умножить",
    "разделить",
    "сложить",
    "вычесть",
}

PERSONAL_FACT_PATTERNS = (
    re.compile(r"\bкак\s+зовут\s+(?:мо(?:ю|его|ю|и|й)|у\s+меня)\b", re.IGNORECASE),
    re.compile(r"\bсколько\s+мне\b", re.IGNORECASE),
    re.compile(r"\bгде\s+я\b", re.IGNORECASE),
    re.compile(r"\bкогда\s+я\b", re.IGNORECASE),
    re.compile(r"\bкакой\s+у\s+меня\b", re.IGNORECASE),
    re.compile(r"\bкакая\s+у\s+меня\b", re.IGNORECASE),
    re.compile(r"\bкакое\s+у\s+меня\b", re.IGNORECASE),
    re.compile(r"\bкакие\s+у\s+меня\b", re.IGNORECASE),
    re.compile(
        r"\b(?:какой|какая|какое|какие|что)\b.*\bя\s+"
        r"(?:предпочитаю|люблю|выбрал|выбрала|использую|считаю)\b",
        re.IGNORECASE,
    ),
)

POSSESSIVE_FACT_PATTERN = re.compile(
    r"^(?:какой|какая|какое|какие|как|где|когда|сколько|что)\b.*\b"
    r"(?:мой|моя|моё|мое|мои|моего|мою|моих|моём|моем)\b",
    re.IGNORECASE,
)

PROJECT_CONTEXT_PATTERNS = (
    re.compile(r"\bна\s+чем\s+мы\s+остановились\b", re.IGNORECASE),
    re.compile(r"\b(?:текущий|текущая|текущее|сейчас)\b.*\b(?:anima|анима|проект)\b", re.IGNORECASE),
    re.compile(r"\b(?:приоритет|цель|состояние|этап|статус)\b.*\b(?:anima|анима|проекта)\b", re.IGNORECASE),
)


CORPUS = (
    ("personal_coffee", "Какой кофе я предпочитаю?", CONTEXT_REQUIRED),
    ("personal_dog", "Как зовут мою собаку?", CONTEXT_REQUIRED),
    ("personal_age", "Сколько мне лет?", CONTEXT_REQUIRED),
    ("personal_location", "Где я живу?", CONTEXT_REQUIRED),
    ("personal_laptop", "Какой у меня ноутбук?", CONTEXT_REQUIRED),
    ("project_resume", "На чем мы остановились в проекте ANIMA?", CONTEXT_REQUIRED),
    ("project_priority", "Какой сейчас приоритет проекта ANIMA?", CONTEXT_REQUIRED),
    ("project_state", "Какое текущее состояние ANIMA?", CONTEXT_REQUIRED),
    ("arithmetic", "Сколько будет 12 умножить на 8?", OPEN_KNOWLEDGE),
    ("arithmetic_with_me", "Помоги мне посчитать 12×8", OPEN_KNOWLEDGE),
    ("general_capital", "Какая столица Франции?", OPEN_KNOWLEDGE),
    ("general_sqlite", "Что такое SQLite?", OPEN_KNOWLEDGE),
    ("explain_to_me", "Объясни мне, как работает FTS", OPEN_KNOWLEDGE),
    ("repair_my_device", "Как починить мой ноутбук, если он не включается?", OPEN_KNOWLEDGE),
    ("translate_for_me", "Переведи мне слово memory", OPEN_KNOWLEDGE),
    ("recipe", "Как приготовить эспрессо?", OPEN_KNOWLEDGE),
    ("open_recommendation", "Какой ноутбук лучше купить?", OPEN_KNOWLEDGE),
    ("open_coffee", "Какой кофе лучше?", OPEN_KNOWLEDGE),
)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


def _tokens(text: str) -> set[str]:
    return {token.casefold().replace("ё", "е") for token in TOKEN_PATTERN.findall(text)}


def classify_scope(text: str) -> dict:
    normalized = _normalize(text)
    tokens = _tokens(normalized)

    # Explicit calculations win over personal pronouns such as "мне".
    if ARITHMETIC_OPERATOR_PATTERN.search(normalized) or (
        NUMBER_PATTERN.search(normalized) and tokens & CALCULATION_WORDS
    ):
        return {
            "scope": OPEN_KNOWLEDGE,
            "reason": "calculation_override",
        }

    # Imperative/help requests are tasks, not assertions about private facts.
    if any(normalized.startswith(prefix) for prefix in ACTION_PREFIXES):
        return {
            "scope": OPEN_KNOWLEDGE,
            "reason": "action_request_override",
        }

    for pattern in PROJECT_CONTEXT_PATTERNS:
        if pattern.search(normalized):
            return {
                "scope": CONTEXT_REQUIRED,
                "reason": "project_or_current_context_fact",
            }

    for pattern in PERSONAL_FACT_PATTERNS:
        if pattern.search(normalized):
            return {
                "scope": CONTEXT_REQUIRED,
                "reason": "personal_fact_pattern",
            }

    if POSSESSIVE_FACT_PATTERN.search(normalized):
        return {
            "scope": CONTEXT_REQUIRED,
            "reason": "possessive_fact_question",
        }

    return {
        "scope": OPEN_KNOWLEDGE,
        "reason": "default_open_knowledge",
    }


def guard_decision(scope: str, memory_status: str) -> dict:
    if scope == CONTEXT_REQUIRED and memory_status == "NOT_FOUND":
        return {
            "action": BLOCK_UNGROUNDED,
            "reason": "context_required_but_not_found",
        }
    return {
        "action": ALLOW_FAST,
        "reason": "grounding_available_or_not_required",
    }


def run_case(case_id: str, text: str, expected_scope: str) -> dict:
    started = time.perf_counter()
    classification = classify_scope(text)
    latency_ms = (time.perf_counter() - started) * 1000.0
    passed = classification["scope"] == expected_scope
    return {
        "id": case_id,
        "query": text,
        "expected_scope": expected_scope,
        "actual_scope": classification["scope"],
        "reason": classification["reason"],
        "passed": passed,
        "latency_ms": latency_ms,
    }


def run_guard_matrix() -> list[dict]:
    matrix = (
        (CONTEXT_REQUIRED, "NOT_FOUND", BLOCK_UNGROUNDED),
        (CONTEXT_REQUIRED, "FOUND", ALLOW_FAST),
        (OPEN_KNOWLEDGE, "NOT_FOUND", ALLOW_FAST),
        (OPEN_KNOWLEDGE, "FOUND", ALLOW_FAST),
    )
    rows = []
    for scope, memory_status, expected_action in matrix:
        decision = guard_decision(scope, memory_status)
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
    cases = [run_case(*case) for case in CORPUS]
    guard_matrix = run_guard_matrix()
    latency_total = sum(case["latency_ms"] for case in cases)
    passed = sum(1 for case in cases if case["passed"])
    guard_passed = sum(1 for row in guard_matrix if row["passed"])
    return {
        "experiment": "fast_epistemic_guard_v0",
        "purpose": "Classify whether FAST may answer without private/current context and block unsupported contextual facts",
        "llm_enabled": False,
        "classifier": "deterministic rule-based v0",
        "corpus_size": len(cases),
        "summary": {
            "passed": passed,
            "total": len(cases),
            "pass_rate": passed / len(cases),
            "latency_ms": latency_total,
            "mean_latency_ms": latency_total / len(cases),
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
