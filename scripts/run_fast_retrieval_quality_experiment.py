#!/usr/bin/env python3
"""Measure FAST ContextBuilder retrieval quality without calling an LLM.

The experiment seeds a tiny temporary Memory corpus for every case, asks the
existing FAST ContextBuilder to build a bounded context bundle, and evaluates
whether the selected context contains the facts that should be injected while
rejecting misleading neighbour facts.

Normal ANIMA data is never touched.
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

from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


RETRIEVAL_CORPUS = (
    {
        "id": "direct_recall",
        "description": "Выбрать один точный личный факт",
        "memories": ("Пользователь предпочитает кофе эспрессо.",),
        "query": "Какой кофе я предпочитаю?",
        "required_any": ("эспрессо",),
        "forbidden_any": (),
    },
    {
        "id": "missing_information",
        "description": "Не подмешивать факт о коте в вопрос про собаку",
        "memories": ("Кота пользователя зовут Барсик.",),
        "query": "Как зовут мою собаку?",
        "required_any": (),
        "forbidden_any": ("барсик", "кота пользователя"),
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
        "description": "Найти факт при простой семантической переформулировке",
        "memories": ("Пользователь предпочитает работать по вечерам.",),
        "query": "В какое время суток мне обычно нравится работать?",
        "required_any": ("вечерам",),
        "forbidden_any": (),
    },
    {
        "id": "related_facts",
        "description": "Сохранить полезные связанные факты",
        "memories": (
            "Кота пользователя зовут Барсик.",
            "Кот Барсик серого цвета.",
        ),
        "query": "Какого цвета кот Барсик?",
        "required_any": ("серого цвета",),
        "forbidden_any": (),
    },
    {
        "id": "unrelated_topic",
        "description": "Не подмешивать кофе в неизвестный вопрос про чай",
        "memories": ("Пользователь предпочитает кофе эспрессо.",),
        "query": "Какой чай я предпочитаю?",
        "required_any": (),
        "forbidden_any": ("эспрессо", "кофе"),
    },
)


def _build_case_stack(case_dir: Path, case: dict) -> ContextBuilder:
    store = MemoryStore(case_dir / "memory.db")
    links = LinkStore(store)
    log = EventLog(case_dir / "events.jsonl")

    for index, content in enumerate(case["memories"]):
        timestamp = f"2026-10-30T10:{index:02d}:00+00:00"
        event = Event(
            "conversation.user",
            {"text": content},
            source="user",
            session_id="session_retrieval_quality",
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
    return ContextBuilder(retrieval=retrieval, provenance=provenance)


def selected_context(bundle: dict) -> list[dict]:
    selected: list[dict] = []
    for entry in bundle.get("knowledge", ()):
        record = entry["record"]
        selected.append(
            {
                "kind": "knowledge",
                "id": record["id"],
                "text": record["statement"],
                "score": entry.get("score"),
                "selection_reason": list(entry.get("selection_reason", ())),
            }
        )
    for entry in bundle.get("memories", ()):
        record = entry["record"]
        selected.append(
            {
                "kind": "memory",
                "id": record["id"],
                "text": record["content"],
                "score": entry.get("score"),
                "selection_reason": list(entry.get("selection_reason", ())),
            }
        )
    return selected


def evaluate_selected(selected: list[dict], case: dict) -> dict:
    corpus = "\n".join(item["text"] for item in selected).casefold()
    required = tuple(token.casefold() for token in case["required_any"])
    forbidden = tuple(token.casefold() for token in case["forbidden_any"])

    required_ok = not required or any(token in corpus for token in required)
    forbidden_ok = not any(token in corpus for token in forbidden)
    false_context_injection = not forbidden_ok

    return {
        "passed": required_ok and forbidden_ok,
        "required_any": list(case["required_any"]),
        "required_ok": required_ok,
        "forbidden_any": list(case["forbidden_any"]),
        "forbidden_ok": forbidden_ok,
        "false_context_injection": false_context_injection,
        "selected_count": len(selected),
    }


def run_case(root: Path, case: dict) -> dict:
    case_dir = root / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    builder = _build_case_stack(case_dir, case)

    started = time.perf_counter()
    bundle = builder.build(case["query"], consumer="FAST")
    latency_ms = (time.perf_counter() - started) * 1000.0

    selected = selected_context(bundle)
    evaluation = evaluate_selected(selected, case)
    return {
        "id": case["id"],
        "description": case["description"],
        "query": case["query"],
        "source_memories": list(case["memories"]),
        "selected_context": selected,
        "context_budget": bundle["budget"],
        "context_stats": bundle["selection_stats"],
        "truncated": bundle["truncated"],
        "latency_ms": latency_ms,
        "evaluation": evaluation,
    }


def summarize(cases: list[dict]) -> dict:
    passed = sum(1 for case in cases if case["evaluation"]["passed"])
    false_injections = sum(
        1 for case in cases if case["evaluation"]["false_context_injection"]
    )
    latency_total = sum(case["latency_ms"] for case in cases)
    selected_total = sum(
        case["evaluation"]["selected_count"] for case in cases
    )
    return {
        "passed": passed,
        "total": len(cases),
        "pass_rate": passed / len(cases),
        "false_context_injections": false_injections,
        "latency_ms": latency_total,
        "mean_latency_ms": latency_total / len(cases),
        "selected_context_items": selected_total,
    }


def run_experiment() -> dict:
    with tempfile.TemporaryDirectory(prefix="anima-fast-retrieval-quality-") as temp:
        root = Path(temp)
        cases = [run_case(root, case) for case in RETRIEVAL_CORPUS]

    return {
        "experiment": "fast_retrieval_quality_v0",
        "purpose": "Measure ContextBuilder retrieval quality without an LLM",
        "consumer": "FAST",
        "llm_enabled": False,
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
