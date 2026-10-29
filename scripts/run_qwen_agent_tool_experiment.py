#!/usr/bin/env python3
"""Live read-only Qwen-Agent tool-calling experiment for Qwen3-0.6B.

The experiment uses temporary ANIMA data. It never touches the normal data dir.
"""

import argparse
import json
from pathlib import Path
import tempfile
import time

from anima.cognition.qwen_agent_tools import (
    AnimaReadOnlyToolGateway,
    QwenAgentToolLoop,
    build_qwen_agent_chat_model,
)
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.retrieval import RetrievalEngine


T1 = "2026-10-29T12:00:00+00:00"
T2 = "2026-10-29T12:10:00+00:00"
T3 = "2026-10-29T12:20:00+00:00"

M_COFFEE = "mem_11111111-1111-4111-8111-111111111111"
M_CAT = "mem_22222222-2222-4222-8222-222222222222"
M_PROJECT = "mem_33333333-3333-4333-8333-333333333333"
E_COFFEE = "ev_44444444-4444-4444-8444-444444444444"
E_CAT = "ev_55555555-5555-4555-8555-555555555555"
E_PROJECT = "ev_66666666-6666-4666-8666-666666666666"


def seed_memory(store):
    store.create_memory(
        memory_type="episodic",
        domain="user",
        content="Пользователь предпочитает кофе эспрессо.",
        status="closed",
        importance=2,
        created_at=T1,
        public_id=M_COFFEE,
        source_event_id=E_COFFEE,
    )
    store.create_memory(
        memory_type="episodic",
        domain="user",
        content="Кота пользователя зовут Барсик.",
        status="closed",
        importance=2,
        created_at=T2,
        public_id=M_CAT,
        source_event_id=E_CAT,
    )
    store.create_memory(
        memory_type="episodic",
        domain="project",
        content="ANIMA использует SQLite для Cognitive Memory.",
        status="closed",
        importance=1,
        created_at=T3,
        public_id=M_PROJECT,
        source_event_id=E_PROJECT,
    )


def build_gateway(root):
    store = MemoryStore(root / "memory.db")
    links = LinkStore(store)
    seed_memory(store)
    retrieval = RetrievalEngine(memory_store=store, link_store=links)

    state_store = InternalStateStore(root / "internal_state.db")
    state_runtime = InternalStateRuntime(state_store)

    return AnimaReadOnlyToolGateway(
        retrieval=retrieval,
        internal_state_runtime=state_runtime,
    )


def contains_any(text, fragments):
    lowered = text.casefold()
    return any(fragment.casefold() in lowered for fragment in fragments)


def evaluate(case, turn):
    tools = [call.name for call in turn.tool_calls]
    response = turn.response_text
    checks = {}

    required_tools = case.get("required_tools", [])
    forbidden_tools = case.get("forbidden_tools", [])
    required_terms = case.get("required_terms", [])
    forbidden_terms = case.get("forbidden_terms", [])
    missing_terms = case.get("missing_terms", [])

    checks["required_tools"] = all(tool in tools for tool in required_tools)
    checks["forbidden_tools"] = all(tool not in tools for tool in forbidden_tools)
    checks["required_terms"] = all(
        term.casefold() in response.casefold() for term in required_terms
    )
    checks["forbidden_terms"] = all(
        term.casefold() not in response.casefold() for term in forbidden_terms
    )
    if missing_terms:
        checks["missing_information"] = contains_any(response, missing_terms)

    return {
        "passed": all(checks.values()),
        "checks": checks,
    }


def corpus():
    return [
        {
            "id": "memory_direct_recall",
            "query": "Какой кофе я предпочитаю?",
            "required_tools": ["memory_search"],
            "required_terms": ["эспрессо"],
        },
        {
            "id": "memory_missing_dog",
            "query": "Как зовут мою собаку?",
            "required_tools": ["memory_search"],
            "forbidden_terms": ["Барсик"],
            "missing_terms": [
                "нет информации",
                "информации нет",
                "не знаю",
                "неизвест",
                "нет данных",
                "данных нет",
            ],
        },
        {
            "id": "no_tool_arithmetic",
            "query": "Сколько будет 2 + 2?",
            "forbidden_tools": ["memory_search", "memory_get", "state_read"],
            "required_terms": ["4"],
        },
        {
            "id": "state_read",
            "query": "Каково твоё текущее внутреннее состояние ANIMA?",
            "required_tools": ["state_read"],
        },
        {
            "id": "memory_exact_get",
            "query": (
                "Прочитай объект памяти " + M_COFFEE + " и кратко скажи, что в нём записано."
            ),
            "required_tools": ["memory_get"],
            "required_terms": ["эспрессо"],
        },
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080/v1",
        help="OpenAI-compatible llama.cpp base URL",
    )
    parser.add_argument("--model", default="Qwen3-0.6B-Q8_0")
    parser.add_argument(
        "--thinking",
        choices=("off", "on"),
        default="off",
    )
    parser.add_argument("--max-tokens", type=int, default=256)
    args = parser.parse_args()

    llm = build_qwen_agent_chat_model(
        model=args.model,
        model_server=args.base_url,
        thinking=args.thinking == "on",
        max_tokens=args.max_tokens,
    )

    cases_output = []
    with tempfile.TemporaryDirectory(prefix="anima_qwen_agent_") as temp_dir:
        gateway = build_gateway(Path(temp_dir))
        loop = QwenAgentToolLoop(llm=llm, gateway=gateway)

        for case in corpus():
            started = time.perf_counter()
            try:
                turn = loop.run(case["query"])
                latency_ms = (time.perf_counter() - started) * 1000.0
                evaluation = evaluate(case, turn)
                result = {
                    "id": case["id"],
                    "query": case["query"],
                    "response": turn.response_text,
                    "tool_calls": [
                        {
                            "round": call.round_index,
                            "name": call.name,
                            "arguments": call.arguments,
                            "result": call.result,
                        }
                        for call in turn.tool_calls
                    ],
                    "rounds": turn.rounds,
                    "latency_ms": latency_ms,
                    "evaluation": evaluation,
                }
            except Exception as error:
                latency_ms = (time.perf_counter() - started) * 1000.0
                result = {
                    "id": case["id"],
                    "query": case["query"],
                    "latency_ms": latency_ms,
                    "evaluation": {"passed": False, "checks": {}},
                    "error": f"{type(error).__name__}: {error}",
                }
            cases_output.append(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))

    passed = sum(item["evaluation"]["passed"] for item in cases_output)
    summary = {
        "experiment": "qwen_agent_read_only_tools_v1",
        "model": args.model,
        "base_url": args.base_url,
        "thinking": args.thinking,
        "passed": passed,
        "total": len(cases_output),
        "total_latency_ms": sum(item["latency_ms"] for item in cases_output),
    }
    print("\nSUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
