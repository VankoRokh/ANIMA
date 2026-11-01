#!/usr/bin/env python3
"""Run FAST Memory -> Gate -> Epistemic Guard -> FAST end to end.

This experiment tests the first architecture that prevents unsupported personal/current
facts by construction instead of asking the LLM not to hallucinate.

Pipeline:
Memory -> RetrievalEngine -> ContextBuilder -> Relevance Gate
       -> Epistemic Guard
          -> BLOCK_UNGROUNDED: deterministic UNKNOWN, zero model calls
          -> ALLOW_FAST: compact FACTS -> FAST, one model call

Production code is not modified. Every case uses a temporary Memory corpus.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition.fast_llm import (
    FAST_LLM_DEFAULT_MIN_P,
    FAST_LLM_DEFAULT_TOP_K,
    FAST_LLM_DEFAULT_TOP_P,
    LlamaCppFastTransport,
)
from scripts.run_fast_context_grounding_experiment import A1_SYSTEM_PROMPT
from scripts.run_fast_epistemic_guard_experiment import (
    ALLOW_FAST,
    BLOCK_UNGROUNDED,
    classify_scope,
    guard_decision,
)
from scripts.run_fast_memory_e2e_experiment import evaluate_response, render_user_prompt
from scripts.run_fast_relevance_gate_experiment import apply_relevance_gate
from scripts.run_fast_retrieval_quality_experiment import _build_case_stack, selected_context

DEFAULT_BASE_URL = os.environ.get(
    "ANIMA_FAST_BASE_URL",
    os.environ.get("ANIMA_LLM_BASE_URL", "http://127.0.0.1:8080"),
)
DEFAULT_MODEL = os.environ.get(
    "ANIMA_FAST_MODEL",
    os.environ.get("ANIMA_LLM_MODEL", "Qwen3-0.6B-Q8_0"),
)

UNKNOWN_RESPONSE = "У меня нет этой информации."

GUARDED_E2E_CORPUS = (
    {
        "id": "direct_recall",
        "description": "Использовать найденный личный факт",
        "memories": ("Пользователь предпочитает кофе эспрессо.",),
        "query": "Какой кофе я предпочитаю?",
        "required_any": ("эспрессо",),
        "forbidden_any": (),
        "expected_action": ALLOW_FAST,
    },
    {
        "id": "missing_information",
        "description": "Блокировать неизвестный личный факт о собаке",
        "memories": ("Кота пользователя зовут Барсик.",),
        "query": "Как зовут мою собаку?",
        "required_any": ("нет этой информации",),
        "forbidden_any": ("барсик", "катя"),
        "expected_action": BLOCK_UNGROUNDED,
    },
    {
        "id": "relevant_among_noise",
        "description": "Использовать личный факт среди тематического шума",
        "memories": (
            "Пользователь предпочитает кофе эспрессо.",
            "В баре кофемашина используется для приготовления кофе.",
        ),
        "query": "Какой кофе я предпочитаю?",
        "required_any": ("эспрессо",),
        "forbidden_any": (),
        "expected_action": ALLOW_FAST,
    },
    {
        "id": "semantic_paraphrase",
        "description": "Использовать память при семантической переформулировке",
        "memories": ("Пользователь предпочитает работать по вечерам.",),
        "query": "В какое время суток мне обычно нравится работать?",
        "required_any": ("вечер",),
        "forbidden_any": (),
        "expected_action": ALLOW_FAST,
    },
    {
        "id": "related_facts",
        "description": "Ответить по связанным фактам",
        "memories": (
            "Кота пользователя зовут Барсик.",
            "Кот Барсик серого цвета.",
        ),
        "query": "Какого цвета кот Барсик?",
        "required_any": ("сер",),
        "forbidden_any": (),
        "expected_action": ALLOW_FAST,
    },
    {
        "id": "unknown_personal_tea",
        "description": "Блокировать неизвестное личное предпочтение",
        "memories": ("Пользователь предпочитает кофе эспрессо.",),
        "query": "Какой чай я предпочитаю?",
        "required_any": ("нет этой информации",),
        "forbidden_any": ("эспрессо", "розовой корицей"),
        "expected_action": BLOCK_UNGROUNDED,
    },
    {
        "id": "open_arithmetic",
        "description": "Не блокировать арифметику при пустой памяти",
        "memories": (),
        "query": "Сколько будет 12 умножить на 8?",
        "required_any": ("96",),
        "forbidden_any": ("нет этой информации",),
        "expected_action": ALLOW_FAST,
    },
    {
        "id": "open_general_knowledge",
        "description": "Не блокировать общие знания при пустой памяти",
        "memories": (),
        "query": "Какая столица Франции?",
        "required_any": ("париж",),
        "forbidden_any": ("нет этой информации",),
        "expected_action": ALLOW_FAST,
    },
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking", choices=("off", "on"), default="off")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-output-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=FAST_LLM_DEFAULT_TOP_K)
    parser.add_argument("--top-p", type=float, default=FAST_LLM_DEFAULT_TOP_P)
    parser.add_argument("--min-p", type=float, default=FAST_LLM_DEFAULT_MIN_P)
    parser.add_argument("--api-key-env", default="ANIMA_LLM_API_KEY")
    return parser


def _validate_args(args):
    if not isinstance(args.base_url, str) or not args.base_url.strip():
        raise ValueError("--base-url must be non-empty")
    if not isinstance(args.model, str) or not args.model.strip():
        raise ValueError("--model must be non-empty")
    if args.timeout <= 0:
        raise ValueError("--timeout must be positive")
    if args.max_output_tokens <= 0:
        raise ValueError("--max-output-tokens must be positive")
    if args.temperature < 0:
        raise ValueError("--temperature must be non-negative")
    if args.top_k < 0:
        raise ValueError("--top-k must be non-negative")
    if not 0 <= args.top_p <= 1:
        raise ValueError("--top-p must be within 0..1")
    if not 0 <= args.min_p <= 1:
        raise ValueError("--min-p must be within 0..1")


def run_case(root: Path, case: dict, transport, *, timeout_seconds: float) -> dict:
    case_dir = root / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    builder = _build_case_stack(case_dir, case)

    total_started = time.perf_counter()

    context_started = time.perf_counter()
    bundle = builder.build(case["query"], consumer="FAST")
    retrieved = selected_context(bundle)
    accepted, gate_decisions = apply_relevance_gate(case["query"], retrieved)
    memory_status = "FOUND" if accepted else "NOT_FOUND"
    classification = classify_scope(case["query"])
    decision = guard_decision(classification["scope"], memory_status)
    context_latency_ms = (time.perf_counter() - context_started) * 1000.0

    if decision["action"] == BLOCK_UNGROUNDED:
        response = UNKNOWN_RESPONSE
        model_call = None
        model_calls = 0
        model_latency_ms = 0.0
    else:
        facts = tuple(item["text"] for item in accepted)
        call = transport.complete(
            system_prompt=A1_SYSTEM_PROMPT,
            user_prompt=render_user_prompt(case["query"], facts),
            timeout_seconds=timeout_seconds,
        )
        response = call.text
        model_call = call.to_dict()
        model_calls = 1
        model_latency_ms = call.latency_ms

    total_latency_ms = (time.perf_counter() - total_started) * 1000.0
    evaluation = evaluate_response(response, case)
    action_ok = decision["action"] == case["expected_action"]
    evaluation["guard_action_ok"] = action_ok
    evaluation["passed"] = evaluation["passed"] and action_ok

    return {
        "id": case["id"],
        "description": case["description"],
        "query": case["query"],
        "source_memories": list(case["memories"]),
        "retrieved_context": retrieved,
        "accepted_context": accepted,
        "gate_decisions": gate_decisions,
        "memory_status": memory_status,
        "epistemic_scope": classification["scope"],
        "scope_reason": classification["reason"],
        "guard_action": decision["action"],
        "guard_reason": decision["reason"],
        "expected_action": case["expected_action"],
        "response": response,
        "evaluation": evaluation,
        "context_latency_ms": context_latency_ms,
        "model_latency_ms": model_latency_ms,
        "total_latency_ms": total_latency_ms,
        "model_calls": model_calls,
        "model_call": model_call,
    }


def summarize(cases: list[dict]) -> dict:
    passed = sum(1 for case in cases if case["evaluation"]["passed"])
    context_total = sum(case["context_latency_ms"] for case in cases)
    model_total = sum(case["model_latency_ms"] for case in cases)
    total_latency = sum(case["total_latency_ms"] for case in cases)
    blocked = sum(1 for case in cases if case["guard_action"] == BLOCK_UNGROUNDED)
    model_calls = sum(case["model_calls"] for case in cases)
    return {
        "passed": passed,
        "total": len(cases),
        "pass_rate": passed / len(cases),
        "blocked_ungrounded": blocked,
        "model_calls": model_calls,
        "model_calls_saved": len(cases) - model_calls,
        "context_latency_ms": context_total,
        "mean_context_latency_ms": context_total / len(cases),
        "model_latency_ms": model_total,
        "mean_model_latency_ms_per_call": model_total / model_calls if model_calls else 0.0,
        "total_latency_ms": total_latency,
        "mean_total_latency_ms_per_case": total_latency / len(cases),
    }


def run_experiment(args) -> dict:
    _validate_args(args)
    api_key = os.environ.get(args.api_key_env)
    transport = LlamaCppFastTransport(
        base_url=args.base_url,
        model=args.model,
        thinking=args.thinking == "on",
        max_output_tokens=args.max_output_tokens,
        temperature=args.temperature,
        top_k=args.top_k,
        top_p=args.top_p,
        min_p=args.min_p,
        api_key=api_key,
    )

    with tempfile.TemporaryDirectory(prefix="anima-fast-guarded-e2e-") as temp:
        root = Path(temp)
        cases = [
            run_case(root, case, transport, timeout_seconds=args.timeout)
            for case in GUARDED_E2E_CORPUS
        ]

    return {
        "experiment": "fast_memory_guarded_e2e_v1",
        "purpose": "Prevent unsupported contextual hallucinations by blocking generation when required grounding is absent",
        "model": args.model,
        "base_url": args.base_url,
        "corpus_language": "ru",
        "corpus_size": len(GUARDED_E2E_CORPUS),
        "retrieval": "existing ContextBuilder/RetrievalEngine",
        "relevance_gate": "experimental lexical_anchor_overlap v0",
        "epistemic_guard": "deterministic rule-based v0",
        "blocked_response": UNKNOWN_RESPONSE,
        "prompt_profile": "A1 explicit English grounding instructions for ALLOW_FAST cases",
        "sampling": {
            "thinking": args.thinking == "on",
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "min_p": args.min_p,
            "max_output_tokens": args.max_output_tokens,
        },
        "summary": summarize(cases),
        "cases": cases,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = run_experiment(args)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["summary"]["passed"] == result["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
