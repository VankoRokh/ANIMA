#!/usr/bin/env python3
"""Evaluate a small deterministic relevance gate above FAST retrieval.

This is an experiment only. It does not modify RetrievalEngine or ContextBuilder.
The gate receives already-selected context items and rejects candidates that have
no shared content-bearing lexical anchor with the query.

The purpose is to test one architectural hypothesis: can a cheap deterministic
filter remove obvious false context injection before Working Context reaches FAST?
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_fast_retrieval_quality_experiment import (
    RETRIEVAL_CORPUS,
    _build_case_stack,
    evaluate_selected,
    selected_context,
)


TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)

# Small, deliberately conservative lexical stop set for the v0 experiment.
# These words may describe question form, ownership, or a generic relation, but
# they do not identify what entity/topic the answer must be about.
LOW_INFORMATION_TOKENS = {
    "в",
    "во",
    "по",
    "и",
    "а",
    "но",
    "как",
    "какой",
    "какая",
    "какое",
    "какие",
    "кого",
    "что",
    "где",
    "когда",
    "мне",
    "мой",
    "моя",
    "моё",
    "мое",
    "мои",
    "моего",
    "мою",
    "я",
    "пользователь",
    "пользователя",
    "зовут",
    "предпочитаю",
    "предпочитает",
    "нравится",
    "обычно",
}


def lexical_anchors(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_PATTERN.findall(text)
        if len(token) >= 2 and token.casefold() not in LOW_INFORMATION_TOKENS
    }


def apply_relevance_gate(query: str, selected: list[dict]) -> tuple[list[dict], list[dict]]:
    query_anchors = lexical_anchors(query)
    accepted: list[dict] = []
    decisions: list[dict] = []

    for item in selected:
        item_anchors = lexical_anchors(item["text"])
        shared = sorted(query_anchors & item_anchors)
        keep = bool(shared)

        decisions.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "text": item["text"],
                "query_anchors": sorted(query_anchors),
                "item_anchors": sorted(item_anchors),
                "shared_anchors": shared,
                "accepted": keep,
                "reason": (
                    "shared_content_anchor"
                    if keep
                    else "no_shared_content_anchor"
                ),
            }
        )
        if keep:
            accepted.append(item)

    return accepted, decisions


def run_case(root: Path, case: dict) -> dict:
    case_dir = root / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    builder = _build_case_stack(case_dir, case)

    started = time.perf_counter()
    bundle = builder.build(case["query"], consumer="FAST")
    retrieved = selected_context(bundle)
    accepted, gate_decisions = apply_relevance_gate(case["query"], retrieved)
    latency_ms = (time.perf_counter() - started) * 1000.0

    evaluation = evaluate_selected(accepted, case)
    return {
        "id": case["id"],
        "description": case["description"],
        "query": case["query"],
        "source_memories": list(case["memories"]),
        "retrieved_context": retrieved,
        "accepted_context": accepted,
        "gate_decisions": gate_decisions,
        "retrieved_count": len(retrieved),
        "accepted_count": len(accepted),
        "rejected_count": len(retrieved) - len(accepted),
        "latency_ms": latency_ms,
        "evaluation": evaluation,
    }


def summarize(cases: list[dict]) -> dict:
    passed = sum(1 for case in cases if case["evaluation"]["passed"])
    false_injections = sum(
        1 for case in cases if case["evaluation"]["false_context_injection"]
    )
    latency_total = sum(case["latency_ms"] for case in cases)
    return {
        "passed": passed,
        "total": len(cases),
        "pass_rate": passed / len(cases),
        "false_context_injections": false_injections,
        "retrieved_context_items": sum(case["retrieved_count"] for case in cases),
        "accepted_context_items": sum(case["accepted_count"] for case in cases),
        "rejected_context_items": sum(case["rejected_count"] for case in cases),
        "latency_ms": latency_total,
        "mean_latency_ms": latency_total / len(cases),
    }


def run_experiment() -> dict:
    with tempfile.TemporaryDirectory(prefix="anima-fast-relevance-gate-") as temp:
        root = Path(temp)
        cases = [run_case(root, case) for case in RETRIEVAL_CORPUS]

    return {
        "experiment": "fast_relevance_gate_v0",
        "purpose": "Test a cheap deterministic relevance gate above existing FAST retrieval",
        "consumer": "FAST",
        "llm_enabled": False,
        "retrieval_modified": False,
        "gate": {
            "type": "lexical_anchor_overlap",
            "minimum_shared_anchors": 1,
        },
        "corpus_size": len(RETRIEVAL_CORPUS),
        "summary": summarize(cases),
        "cases": cases,
    }


def main() -> int:
    result = run_experiment()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["summary"]["passed"] == result["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
