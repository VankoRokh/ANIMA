#!/usr/bin/env python3
"""Test deterministic resolution for AMBIGUOUS epistemic queries.

Pipeline under test:

AMBIGUOUS query -> existing ContextBuilder/RetrievalEngine -> Relevance Gate v0
                -> deterministic ambiguity resolver

The resolver is deliberately stricter than the relevance gate. A single shared
entity/topic token is not enough to authorize generation. A candidate must share
at least two lexical anchors with the query and at least one of those anchors must
be content-bearing for the requested property/history, not only a vague reference.

No LLM is called and production code is not modified.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_fast_epistemic_guard_stress_experiment import (
    AMBIGUOUS,
    classify_scope_v1,
)
from scripts.run_fast_relevance_gate_experiment import (
    apply_relevance_gate,
    lexical_anchors,
)
from scripts.run_fast_retrieval_quality_experiment import (
    _build_case_stack,
    selected_context,
)


RESOLVED_CONTEXT = "RESOLVED_CONTEXT"
UNRESOLVED = "UNRESOLVED"
MIN_SHARED_ANCHORS = 2

# These anchors can identify a vague reference form, but by themselves they do
# not show that a memory contains the property/history requested by the query.
LOW_RESOLUTION_ANCHORS = {
    "этот",
    "эта",
    "это",
    "эти",
    "проект",
    "последняя",
    "последний",
    "последнее",
    "была",
    "был",
    "было",
    "есть",
}


AMBIGUOUS_CORPUS = (
    {
        "id": "barsik_color_resolved",
        "description": "Resolve a named private entity when the requested property is present",
        "memories": (
            "Кота пользователя зовут Барсик.",
            "Кот Барсик серого цвета.",
        ),
        "query": "Какого цвета Барсик?",
        "expected_resolution": RESOLVED_CONTEXT,
        "required_any": ("серого цвета",),
    },
    {
        "id": "barsik_color_entity_only",
        "description": "Do not resolve color from entity identity alone",
        "memories": ("Кота пользователя зовут Барсик.",),
        "query": "Какого цвета Барсик?",
        "expected_resolution": UNRESOLVED,
        "required_any": (),
    },
    {
        "id": "barsik_color_wrong_property",
        "description": "Do not resolve color from another fact about the same entity",
        "memories": (
            "Кота пользователя зовут Барсик.",
            "Барсик любит курицу.",
        ),
        "query": "Какого цвета Барсик?",
        "expected_resolution": UNRESOLVED,
        "required_any": (),
    },
    {
        "id": "barsik_likes_resolved",
        "description": "Resolve another named-entity property",
        "memories": ("Барсик любит курицу.",),
        "query": "Что любит Барсик?",
        "expected_resolution": RESOLVED_CONTEXT,
        "required_any": ("курицу",),
    },
    {
        "id": "barsik_food_time_resolved",
        "description": "Resolve a named-entity habitual event",
        "memories": ("Барсик обычно ест в 19:00.",),
        "query": "Когда Барсик обычно ест?",
        "expected_resolution": RESOLVED_CONTEXT,
        "required_any": ("19:00",),
    },
    {
        "id": "barsik_character_missing",
        "description": "Keep an unknown property unresolved even when entity exists",
        "memories": ("Кота пользователя зовут Барсик.",),
        "query": "Какой у Барсика характер?",
        "expected_resolution": UNRESOLVED,
        "required_any": (),
    },
    {
        "id": "last_build_resolved",
        "description": "Resolve a vague current-context reference when matching history exists",
        "memories": ("Последняя сборка ANIMA была 30 октября 2026 года.",),
        "query": "Когда была последняя сборка?",
        "expected_resolution": RESOLVED_CONTEXT,
        "required_any": ("30 октября 2026",),
    },
    {
        "id": "last_build_noise_only",
        "description": "Do not resolve last build from a merely recent-version fact",
        "memories": ("Последняя версия ANIMA использует Qwen3-0.6B.",),
        "query": "Когда была последняя сборка?",
        "expected_resolution": UNRESOLVED,
        "required_any": (),
    },
    {
        "id": "this_project_resolved",
        "description": "Resolve a vague project reference when the requested event is present",
        "memories": ("Этот проект начался в 2026 году.",),
        "query": "Когда начался этот проект?",
        "expected_resolution": RESOLVED_CONTEXT,
        "required_any": ("2026",),
    },
    {
        "id": "this_project_noise_only",
        "description": "Do not resolve a project start question from topical project context alone",
        "memories": ("Этот проект использует Python.",),
        "query": "Когда начался этот проект?",
        "expected_resolution": UNRESOLVED,
        "required_any": (),
    },
)


def resolve_ambiguous(query: str, accepted: list[dict]) -> dict:
    query_anchors = lexical_anchors(query)
    evidence = []

    for item in accepted:
        item_anchors = lexical_anchors(item["text"])
        shared = sorted(query_anchors & item_anchors)
        content_shared = sorted(set(shared) - LOW_RESOLUTION_ANCHORS)
        strong = (
            len(shared) >= MIN_SHARED_ANCHORS
            and bool(content_shared)
        )
        evidence.append(
            {
                "id": item["id"],
                "text": item["text"],
                "shared_anchors": shared,
                "content_shared_anchors": content_shared,
                "strong": strong,
            }
        )

    strong_evidence = [item for item in evidence if item["strong"]]
    if strong_evidence:
        return {
            "resolution": RESOLVED_CONTEXT,
            "reason": "strong_context_evidence",
            "query_anchors": sorted(query_anchors),
            "strong_evidence": strong_evidence,
            "evidence": evidence,
        }

    return {
        "resolution": UNRESOLVED,
        "reason": "insufficient_context_evidence",
        "query_anchors": sorted(query_anchors),
        "strong_evidence": [],
        "evidence": evidence,
    }


def evaluate_resolution(result: dict, case: dict) -> dict:
    resolution_ok = result["resolution"] == case["expected_resolution"]
    strong_text = "\n".join(
        item["text"] for item in result["strong_evidence"]
    ).casefold()
    required = tuple(token.casefold() for token in case["required_any"])
    required_ok = not required or any(token in strong_text for token in required)
    false_resolution = (
        case["expected_resolution"] == UNRESOLVED
        and result["resolution"] == RESOLVED_CONTEXT
    )
    return {
        "passed": resolution_ok and required_ok,
        "resolution_ok": resolution_ok,
        "required_any": list(case["required_any"]),
        "required_ok": required_ok,
        "false_resolution": false_resolution,
    }


def run_case(root: Path, case: dict) -> dict:
    classification = classify_scope_v1(case["query"])
    if classification["scope"] != AMBIGUOUS:
        raise RuntimeError(
            f"case {case['id']} is not AMBIGUOUS: {classification['scope']}"
        )

    case_dir = root / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    builder = _build_case_stack(case_dir, case)

    started = time.perf_counter()
    bundle = builder.build(case["query"], consumer="FAST")
    retrieved = selected_context(bundle)
    accepted, gate_decisions = apply_relevance_gate(case["query"], retrieved)
    resolution = resolve_ambiguous(case["query"], accepted)
    latency_ms = (time.perf_counter() - started) * 1000.0

    evaluation = evaluate_resolution(resolution, case)
    return {
        "id": case["id"],
        "description": case["description"],
        "query": case["query"],
        "source_memories": list(case["memories"]),
        "scope": classification["scope"],
        "scope_reason": classification["reason"],
        "retrieved_context": retrieved,
        "accepted_context": accepted,
        "gate_decisions": gate_decisions,
        "resolution": resolution,
        "expected_resolution": case["expected_resolution"],
        "latency_ms": latency_ms,
        "evaluation": evaluation,
    }


def summarize(cases: list[dict]) -> dict:
    passed = sum(1 for case in cases if case["evaluation"]["passed"])
    false_resolutions = sum(
        1 for case in cases if case["evaluation"]["false_resolution"]
    )
    resolved = sum(
        1 for case in cases
        if case["resolution"]["resolution"] == RESOLVED_CONTEXT
    )
    unresolved = len(cases) - resolved
    latency_total = sum(case["latency_ms"] for case in cases)
    return {
        "passed": passed,
        "total": len(cases),
        "pass_rate": passed / len(cases),
        "resolved": resolved,
        "unresolved": unresolved,
        "false_resolutions": false_resolutions,
        "latency_ms": latency_total,
        "mean_latency_ms": latency_total / len(cases),
    }


def run_experiment() -> dict:
    with tempfile.TemporaryDirectory(prefix="anima-fast-ambiguous-resolution-") as temp:
        root = Path(temp)
        cases = [run_case(root, case) for case in AMBIGUOUS_CORPUS]

    return {
        "experiment": "fast_ambiguous_resolution_v0",
        "purpose": "Resolve AMBIGUOUS queries with retrieval evidence before FAST generation",
        "llm_enabled": False,
        "production_modified": False,
        "classifier": "experimental epistemic tri-state v1",
        "retrieval": "existing ContextBuilder/RetrievalEngine",
        "relevance_gate": "experimental lexical_anchor_overlap v0",
        "resolver": {
            "type": "deterministic shared-anchor evidence v0",
            "minimum_shared_anchors": MIN_SHARED_ANCHORS,
            "requires_content_anchor": True,
        },
        "corpus_size": len(AMBIGUOUS_CORPUS),
        "summary": summarize(cases),
        "cases": cases,
    }


def main() -> int:
    result = run_experiment()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["summary"]["passed"] == result["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
