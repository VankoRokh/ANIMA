#!/usr/bin/env python3
"""Run the first single-inference FAST memory pipeline end to end.

Pipeline under test:

Memory -> RetrievalEngine -> ContextBuilder -> experimental Relevance Gate
       -> compact FACTS -> Qwen/FAST -> final answer

This is an experiment only. Production RetrievalEngine, ContextBuilder and FAST
runtime are not modified. Every case uses a temporary Memory corpus and exactly
one model call.
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
from scripts.run_fast_relevance_gate_experiment import apply_relevance_gate
from scripts.run_fast_retrieval_quality_experiment import (
    _build_case_stack,
    selected_context,
)


DEFAULT_BASE_URL = os.environ.get(
    "ANIMA_FAST_BASE_URL",
    os.environ.get("ANIMA_LLM_BASE_URL", "http://127.0.0.1:8080"),
)
DEFAULT_MODEL = os.environ.get(
    "ANIMA_FAST_MODEL",
    os.environ.get("ANIMA_LLM_MODEL", "Qwen3-0.6B-Q8_0"),
)


E2E_CORPUS = (
    {
        "id": "direct_recall",
        "description": "Прямой ответ из одного точного факта",
        "memories": ("Пользователь предпочитает кофе эспрессо.",),
        "query": "Какой кофе я предпочитаю?",
        "required_any": ("эспрессо",),
        "forbidden_any": (),
    },
    {
        "id": "missing_information",
        "description": "Не переносить факт о коте в вопрос про собаку",
        "memories": ("Кота пользователя зовут Барсик.",),
        "query": "Как зовут мою собаку?",
        "required_any": (
            "нет данных",
            "нет информации",
            "не знаю",
            "неизвест",
            "не указ",
            "не сообщ",
        ),
        "forbidden_any": ("барсик",),
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
    },
    {
        "id": "semantic_paraphrase",
        "description": "Использовать память при простой переформулировке",
        "memories": ("Пользователь предпочитает работать по вечерам.",),
        "query": "В какое время суток мне обычно нравится работать?",
        "required_any": ("вечер",),
        "forbidden_any": (),
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
    },
    {
        "id": "unrelated_topic",
        "description": "Честно сообщить об отсутствии неизвестного предпочтения",
        "memories": ("Пользователь предпочитает кофе эспрессо.",),
        "query": "Какой чай я предпочитаю?",
        "required_any": (
            "нет данных",
            "нет информации",
            "не знаю",
            "неизвест",
            "не указ",
            "не сообщ",
        ),
        "forbidden_any": ("эспрессо",),
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
    parser.add_argument(
        "--api-key-env",
        default="ANIMA_LLM_API_KEY",
        help="Optional environment variable used for a protected local endpoint",
    )
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


def _facts_from_context(items: list[dict]) -> tuple[str, ...]:
    return tuple(item["text"] for item in items)


def render_user_prompt(query: str, facts: tuple[str, ...]) -> str:
    facts_block = "\n".join(f"- {fact}" for fact in facts) if facts else "(none)"
    return (
        "FACTS:\n"
        f"{facts_block}\n\n"
        "QUESTION:\n"
        f"{query}"
    )


def evaluate_response(text: str, case: dict) -> dict:
    normalized = text.casefold()
    required = tuple(token.casefold() for token in case["required_any"])
    forbidden = tuple(token.casefold() for token in case["forbidden_any"])
    required_ok = not required or any(token in normalized for token in required)
    forbidden_ok = not any(token in normalized for token in forbidden)
    return {
        "passed": required_ok and forbidden_ok,
        "required_any": list(case["required_any"]),
        "required_ok": required_ok,
        "forbidden_any": list(case["forbidden_any"]),
        "forbidden_ok": forbidden_ok,
    }


def run_case(root: Path, case: dict, transport, *, timeout_seconds: float) -> dict:
    case_dir = root / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    builder = _build_case_stack(case_dir, case)

    pipeline_started = time.perf_counter()

    context_started = time.perf_counter()
    bundle = builder.build(case["query"], consumer="FAST")
    retrieved = selected_context(bundle)
    accepted, gate_decisions = apply_relevance_gate(case["query"], retrieved)
    context_latency_ms = (time.perf_counter() - context_started) * 1000.0

    facts = _facts_from_context(accepted)
    user_prompt = render_user_prompt(case["query"], facts)
    call = transport.complete(
        system_prompt=A1_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        timeout_seconds=timeout_seconds,
    )

    total_latency_ms = (time.perf_counter() - pipeline_started) * 1000.0
    evaluation = evaluate_response(call.text, case)

    return {
        "id": case["id"],
        "description": case["description"],
        "query": case["query"],
        "source_memories": list(case["memories"]),
        "retrieved_context": retrieved,
        "accepted_context": accepted,
        "gate_decisions": gate_decisions,
        "facts_given_to_fast": list(facts),
        "response": call.text,
        "evaluation": evaluation,
        "context_latency_ms": context_latency_ms,
        "model_latency_ms": call.latency_ms,
        "total_latency_ms": total_latency_ms,
        "model_call": call.to_dict(),
        "model_calls": 1,
    }


def _sum_optional(cases: list[dict], field: str):
    values = [case["model_call"].get(field) for case in cases]
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return None
    return sum(values)


def summarize(cases: list[dict]) -> dict:
    passed = sum(1 for case in cases if case["evaluation"]["passed"])
    context_total = sum(case["context_latency_ms"] for case in cases)
    model_total = sum(case["model_latency_ms"] for case in cases)
    total = sum(case["total_latency_ms"] for case in cases)
    return {
        "passed": passed,
        "total": len(cases),
        "pass_rate": passed / len(cases),
        "model_calls": sum(case["model_calls"] for case in cases),
        "context_latency_ms": context_total,
        "mean_context_latency_ms": context_total / len(cases),
        "model_latency_ms": model_total,
        "mean_model_latency_ms": model_total / len(cases),
        "total_latency_ms": total,
        "mean_total_latency_ms": total / len(cases),
        "input_tokens": _sum_optional(cases, "input_tokens"),
        "output_tokens": _sum_optional(cases, "output_tokens"),
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

    with tempfile.TemporaryDirectory(prefix="anima-fast-memory-e2e-") as temp:
        root = Path(temp)
        cases = [
            run_case(root, case, transport, timeout_seconds=args.timeout)
            for case in E2E_CORPUS
        ]

    return {
        "experiment": "fast_memory_e2e_v0",
        "purpose": "Test Memory -> Retrieval -> Gate -> Working Context -> FAST in one inference",
        "model": args.model,
        "base_url": args.base_url,
        "corpus_language": "ru",
        "corpus_size": len(E2E_CORPUS),
        "retrieval": "existing ContextBuilder/RetrievalEngine",
        "gate": "experimental lexical_anchor_overlap v0",
        "prompt_profile": "A1 explicit English grounding instructions",
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
