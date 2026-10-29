"""Run the Stage 5.3 FAST corpus against a live llama.cpp model.

The runner creates a temporary Cognitive Memory for every case and never touches
the normal ANIMA data directory.  It can compare thinking OFF/ON on the same model
and the same Russian baseline corpus.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition import FastCognition
from anima.cognition.fast_llm import (
    FAST_LLM_DEFAULT_MAX_OUTPUT_TOKENS,
    FAST_LLM_DEFAULT_MIN_P,
    FAST_LLM_DEFAULT_TEMPERATURE,
    FAST_LLM_DEFAULT_TOP_K,
    FAST_LLM_DEFAULT_TOP_P,
    FastLLMBackend,
    LlamaCppFastTransport,
)
from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


DEFAULT_BASE_URL = os.environ.get(
    "ANIMA_FAST_BASE_URL",
    os.environ.get("ANIMA_LLM_BASE_URL", "http://127.0.0.1:8080"),
)
DEFAULT_MODEL = os.environ.get(
    "ANIMA_FAST_MODEL",
    os.environ.get("ANIMA_LLM_MODEL", "Qwen3-0.6B-Q8_0"),
)

BASELINE_CORPUS = (
    {
        "id": "direct_recall",
        "description": "Прямой recall одного релевантного факта",
        "memories": ("Пользователь предпочитает кофе эспрессо.",),
        "query": "Какой кофе я предпочитаю?",
        "required_any": ("эспрессо",),
        "forbidden_any": (),
    },
    {
        "id": "missing_information",
        "description": "Не подменять отсутствующий факт похожей памятью",
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
        "description": "Выбрать личный факт среди тематически похожего шума",
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
        "description": "Использовать память при простой переформулировке вопроса",
        "memories": ("Пользователь предпочитает работать по вечерам.",),
        "query": "В какое время суток мне обычно нравится работать?",
        "required_any": ("вечер",),
        "forbidden_any": (),
    },
    {
        "id": "related_facts",
        "description": "Ответить по связанному факту, не путая соседние сведения",
        "memories": (
            "Кота пользователя зовут Барсик.",
            "Кот Барсик серого цвета.",
        ),
        "query": "Какого цвета кот Барсик?",
        "required_any": ("сер",),
        "forbidden_any": (),
    },
)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run the Stage 5.3 FAST Russian baseline corpus against llama.cpp",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--thinking",
        choices=("off", "on", "both"),
        default="both",
        help="Compare Qwen thinking modes on the same corpus",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=FAST_LLM_DEFAULT_MAX_OUTPUT_TOKENS,
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=FAST_LLM_DEFAULT_TEMPERATURE,
    )
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


def _thinking_modes(value):
    if value == "both":
        return (False, True)
    return (value == "on",)


def _evaluate(text, case):
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


def _selected_context(bundle):
    selected = []
    for entry in bundle["knowledge"]:
        selected.append(
            {
                "kind": "knowledge",
                "id": entry["record"]["id"],
                "text": entry["record"]["statement"],
                "selection_reason": entry["selection_reason"],
            }
        )
    for entry in bundle["memories"]:
        selected.append(
            {
                "kind": "memory",
                "id": entry["record"]["id"],
                "text": entry["record"]["content"],
                "selection_reason": entry["selection_reason"],
            }
        )
    return selected


def _build_case_stack(case_dir, case):
    store = MemoryStore(case_dir / "memory.db")
    links = LinkStore(store)
    log = EventLog(case_dir / "events.jsonl")

    for index, content in enumerate(case["memories"]):
        timestamp = f"2026-10-29T12:{index:02d}:00+00:00"
        event = Event(
            "conversation.user",
            {"text": content},
            source="user",
            session_id="session_00000001",
            timestamp=timestamp,
        )
        log.write(event)
        store.create_memory(
            memory_type="episodic",
            domain="user",
            content=content,
            status="closed",
            importance=2 if index == 0 else 1,
            created_at=timestamp,
            source_event_id=event.event_id,
        )

    retrieval = RetrievalEngine(memory_store=store, link_store=links)
    provenance = ProvenanceResolver(store, links, log)
    context_builder = ContextBuilder(
        retrieval=retrieval,
        provenance=provenance,
    )
    return context_builder


def _run_case(root, case, backend, *, mode_name):
    case_dir = root / mode_name / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    context_builder = _build_case_stack(case_dir, case)
    cognition = FastCognition(
        context_builder=context_builder,
        backend=backend,
    )
    event = Event(
        "conversation.user",
        {"text": case["query"]},
        source="user",
        session_id="session_00000002",
    )

    before_calls = len(backend.call_history)
    turn = cognition.process(event)
    if len(backend.call_history) != before_calls + 1:
        raise RuntimeError("FAST live experiment expected exactly one model call")
    call = backend.call_history[-1]
    evaluation = _evaluate(turn.result.response_text, case)

    return {
        "id": case["id"],
        "description": case["description"],
        "query": case["query"],
        "selected_context": _selected_context(turn.request.context_bundle),
        "context_budget": turn.request.context_bundle["budget"],
        "context_stats": turn.request.context_bundle["selection_stats"],
        "response": turn.result.response_text,
        "evaluation": evaluation,
        "model_call": call.to_dict(),
    }


def run_experiment(args):
    _validate_args(args)
    api_key = os.environ.get(args.api_key_env)
    modes = []

    with tempfile.TemporaryDirectory(prefix="anima-stage5-fast-") as temp:
        root = Path(temp)
        for thinking in _thinking_modes(args.thinking):
            transport = LlamaCppFastTransport(
                base_url=args.base_url,
                model=args.model,
                thinking=thinking,
                max_output_tokens=args.max_output_tokens,
                temperature=args.temperature,
                top_k=args.top_k,
                top_p=args.top_p,
                min_p=args.min_p,
                api_key=api_key,
            )
            backend = FastLLMBackend(
                transport,
                timeout_seconds=args.timeout,
            )
            mode_name = "thinking_on" if thinking else "thinking_off"
            cases = [
                _run_case(root, case, backend, mode_name=mode_name)
                for case in BASELINE_CORPUS
            ]
            modes.append(
                {
                    "mode": mode_name,
                    "thinking": thinking,
                    "passed": sum(
                        1 for case in cases if case["evaluation"]["passed"]
                    ),
                    "total": len(cases),
                    "latency_ms": sum(
                        case["model_call"]["latency_ms"] for case in cases
                    ),
                    "input_tokens": (
                        sum(case["model_call"]["input_tokens"] for case in cases)
                        if all(
                            case["model_call"]["input_tokens"] is not None
                            for case in cases
                        )
                        else None
                    ),
                    "output_tokens": (
                        sum(case["model_call"]["output_tokens"] for case in cases)
                        if all(
                            case["model_call"]["output_tokens"] is not None
                            for case in cases
                        )
                        else None
                    ),
                    "reasoning_chars": sum(
                        case["model_call"]["reasoning_chars"] for case in cases
                    ),
                    "cases": cases,
                }
            )

    return {
        "stage": "5.3",
        "model": args.model,
        "base_url": args.base_url,
        "corpus_language": "ru",
        "corpus_size": len(BASELINE_CORPUS),
        "sampling": {
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "min_p": args.min_p,
            "max_output_tokens": args.max_output_tokens,
        },
        "modes": modes,
    }


def main():
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
    return 0 if all(mode["passed"] == mode["total"] for mode in result["modes"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
