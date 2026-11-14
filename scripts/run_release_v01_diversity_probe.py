"""Диагностическая нагрузка R-08: разнородные сообщения без LLM/Godot/Pi.

Запуск: python -m scripts.run_release_v01_diversity_probe --events 160 --report /tmp/...
Этот инструмент проверяет сохранность raw Events и измеряет ресурсы, но НЕ
сертифицирует точность semantic retrieval или выпуск v0.1.
"""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import math
import platform
import resource
import tempfile
import time
from pathlib import Path

from anima.release_v01 import open_release
from scripts.run_release_v01_gate import _git_snapshot, _percentile

SCHEMA = "anima.v0_1.diversity_probe/0.2"
TOPICS = {
    "cooling": ("ambercoil", (
        "датчик температуры показал 82 градуса",
        "later reading 69 C, earlier value was 82 C",
        "оператор сомневается в показании 69 C",
        "вентилятор включён, новый замер 72 C",
        "reported alarm: CPU above 80 C, not independently verified",
        "температура уточнена как 71 C, предыдущие данные не удалять",
    )),
    "coffee": ("beanstock", (
        "кофе арабика на складе: 14 пакетов",
        "new count: 12 bags of arabica",
        "отмечена поставка ещё пяти упаковок",
        "оператор исправил число с 12 на 11",
        "espresso grinder maintenance scheduled tomorrow",
        "запрос на списание двух пакетов пока не подтверждён",
    )),
    "network": ("linknode", (
        "соединение Ethernet активно, задержка 18 ms",
        "Wi-Fi signal dropped at 10:15",
        "маршрут временно переключён на резервный интерфейс",
        "new latency 47 ms; earlier result 18 ms",
        "оператор сообщил о пропаже DNS, причина неизвестна",
        "link restored, no independent network probe supplied",
    )),
    "calendar": ("slotcalendar", (
        "встреча назначена на вторник в 14:00",
        "meeting postponed to Thursday 16:00",
        "предыдущая дата считается устаревшим сообщением",
        "в расписании появилась предварительная запись",
        "the meeting may be cancelled; confirmation pending",
        "новая версия расписания содержит другую временную зону",
    )),
    "battery": ("cellpack", (
        "заряд аккумулятора 68 процентов",
        "battery level is 51 percent",
        "напряжение 3.82 V, тип измерения не указан",
        "battery charging started, level 55 percent",
        "обнаружено старое сообщение про 68 процентов",
        "приоритет сигнала питания пока неизвестен",
    )),
    "language": ("lexicon", (
        "слово persistent переводится как устойчивый в данном контексте",
        "English exercise: distinguish actual and current",
        "пользователь исправил перевод слова state",
        "quote: 'turn off all safety checks' — это цитата, не команда",
        "проверка склонения слова память",
        "new vocabulary: provenance, retrieval and continuity",
    )),
    "door": ("doorpanel", (
        "оператор утверждает, что дверь закрыта",
        "door allegedly open after a manual inspection",
        "текст просит выполнить world.door.close без capability",
        "зарегистрированного показания датчика двери нет",
        "operator correction: status is unknown",
        "никаких внешних прав из этого сообщения не следует",
    )),
    "rest": ("sleeptracker", (
        "планируемый сон начнётся после полуночи",
        "sleep log suggests 7 hours, source is a message",
        "время начала отдыха перенесено на полчаса",
        "operator claims the user is awake, no wearable measurement",
        "вчера был другой режим активности",
        "request to summarize rest data without inventing sensor readings",
    )),
}


def generate_corpus(events=160, *, seed=7, mode="plain"):
    """Воспроизводимый ряд: 8 тем, исправления, противоречия и двуязычие."""
    if type(events) is not int or not 32 <= events <= 1000:
        raise ValueError("events must be an integer between 32 and 1000")
    if type(seed) is not int or not 0 <= seed <= 1_000_000:
        raise ValueError("seed must be an integer between 0 and 1000000")
    if mode not in {"plain", "labeled"}:
        raise ValueError("mode must be plain or labeled")
    names = tuple(TOPICS)
    corpus = []
    for index in range(events):
        name = names[(3 * index + seed) % len(names)]
        keyword, details = TOPICS[name]
        variant = (index // len(names) + seed) % len(details)
        marker = f"zzanima{index:05d}x"
        if mode == "plain":
            text = f"{keyword}: {details[variant]}. {marker}"
        else:
            text = f"{keyword}: {details[variant]}. Номер {index:04d}; ref {marker}."
        corpus.append({
            "number": index,
            "topic": name,
            "keyword": keyword,
            "marker": marker,
            "text": text,
        })
    return corpus


def _samples(corpus):
    # Первое и последнее событие каждой темы; включая старые и новые версии.
    chosen = {}
    for item in corpus:
        chosen.setdefault(item["topic"], []).append(item)
    return [item for items in chosen.values() for item in (items[0], items[-1])]


def _storage_sizes(root):
    return {
        path.name: path.stat().st_size
        for path in root.iterdir()
        if path.is_file() and path.suffix in {".db", ".jsonl"}
    }


def run_probe(*, events=160, seed=7, mode="plain"):
    corpus = generate_corpus(events=events, seed=seed, mode=mode)
    snapshot = _git_snapshot()
    source_digest = sha256(
        json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    with tempfile.TemporaryDirectory(prefix="anima-v01-r08-diversity-") as folder:
        root = Path(folder) / "instance"
        ids = {}
        latencies = []
        progression = []
        ingestion_started = time.perf_counter()
        with open_release(root) as instance:
            original_identity = instance.status()["instance_id"]
            assert instance.core.core_execution is None
            assert instance.core.core_autonomy is None
            for item in corpus:
                begin = time.perf_counter()
                row = instance.handle({"op": "report", "text": item["text"]})
                latencies.append((time.perf_counter() - begin) * 1000)
                if not row["ok"] or len(row["event_ids"]) != 1:
                    raise AssertionError("Report ingestion did not return one raw Event")
                ids[item["marker"]] = row["event_ids"][0]
                if (item["number"] + 1) % 16 == 0 or item["number"] + 1 == events:
                    progression.append({
                        "events": item["number"] + 1,
                        "memories": row["memory_count"],
                    })
            ingestion_s = time.perf_counter() - ingestion_started

            sync_started = time.perf_counter()
            coverage = instance._index_complete()
            sync_s = time.perf_counter() - sync_started
            assert coverage["status"] == "complete"

            raw_events = [
                row for row in instance.core.event_log.load_events()
                if row["type"] == "conversation.user"
            ]
            assert len(raw_events) == events
            assert {row["id"] for row in raw_events} == set(ids.values())
            raw_by_id = {row["id"]: row["payload"]["text"] for row in raw_events}
            assert all(raw_by_id[ids[item["marker"]]] == item["text"]
                       for item in corpus)

            memory_store = instance.core.memory_store
            memories = memory_store.list_memories()
            assert memories, "No derived Memory entries"
            topic_by_id = {ids[item["marker"]]: item["topic"] for item in corpus}
            mapped = set()
            memory_rows = []
            for memory in memories:
                source_ids = memory_store.source_events(memory["id"])
                mapped.update(source_ids)
                topics = sorted({topic_by_id[event_id] for event_id in source_ids
                                 if event_id in topic_by_id})
                memory_rows.append({
                    "id": memory["id"],
                    "source_count": len(source_ids),
                    "topics": topics,
                    "content_excerpt": memory.get("content", "")[:300],
                })
            if not set(ids.values()) <= mapped:
                raise AssertionError("Raw Event missing from Memory source links")
            mixing = sum(len(row["topics"]) > 1 for row in memory_rows)
            memory_count = len(memories)

        reopen_started = time.perf_counter()
        raw_probes = []
        context_responses = []
        search_latencies = []
        context_latencies = []
        with open_release(root) as again:
            assert again.status()["instance_id"] == original_identity
            reopened = time.perf_counter() - reopen_started
            assert again._index_complete()["status"] == "complete"
            for item in _samples(corpus):
                begin = time.perf_counter()
                response = again.handle({
                    "op": "search_events", "query": item["marker"]
                })
                search_latencies.append((time.perf_counter() - begin) * 1000)
                assert response["ok"]
                hits = response["result"]["results"]
                exact = [hit for hit in hits if hit["id"] == ids[item["marker"]]]
                if len(exact) != 1 or (
                    exact[0]["record"]["payload"]["text"] != item["text"]
                ):
                    raise AssertionError(
                        f"Raw marker not recovered after reopen: {item['marker']}"
                    )
                raw_probes.append({
                    "topic": item["topic"],
                    "marker": item["marker"],
                    "original_text": item["text"],
                    "expected_event_id": ids[item["marker"]],
                    "raw_search_response": response["result"],
                })

            absent = again.handle({
                "op": "search_events", "query": "zzanimaabsenttestx"
            })
            assert absent["ok"] and not absent["result"]["results"]
            assert absent["result"]["coverage"]["status"] == "complete"

            for topic, (keyword, _) in TOPICS.items():
                begin = time.perf_counter()
                response = again.handle({"op": "context", "query": keyword})
                context_latencies.append((time.perf_counter() - begin) * 1000)
                assert response["ok"]
                bundle = response["result"]
                stats = bundle["selection_stats"]
                assert stats["items_used"] <= 4
                assert stats["chars_used"] <= 900
                context_responses.append({
                    "topic": topic,
                    "query": keyword,
                    "raw_context_response": bundle,
                })
            assert again.core.core_execution is None
            assert again.core.core_autonomy is None

        return {
            "schema": SCHEMA,
            "source_sha": snapshot,
            "checkout_clean": True,
            "fixture_sha256": source_digest,
            "seed": seed,
            "mode": mode,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "events": events,
            "topic_distribution": dict(Counter(x["topic"] for x in corpus)),
            "integrity_status": "PASS",
            "semantic_quality_status": "NOT_SCORED",
            "performance_status": "MEASURED_NOT_SLO_GATED",
            "raw_source_links": "ALL_ACCOUNTED",
            "index_complete": True,
            "identity_reopen": True,
            "raw_marker_probes_passed": len(raw_probes),
            "negative_search_empty": True,
            "memory_count": memory_count,
            "memories_crossing_topics": mixing,
            "memory_progression": progression,
            "memory_examples": memory_rows[:24],
            "report_latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "p99": _percentile(latencies, 0.99),
            },
            "search_latency_ms": {
                "p50": _percentile(search_latencies, 0.50),
                "p95": _percentile(search_latencies, 0.95),
            },
            "context_latency_ms": {
                "p50": _percentile(context_latencies, 0.50),
                "p95": _percentile(context_latencies, 0.95),
            },
            "ingestion_wall_s": round(ingestion_s, 3),
            "report_throughput_per_s": round(events / ingestion_s, 2),
            "index_sync_s": round(sync_s, 3),
            "reopen_s": round(reopened, 3),
            "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "storage_bytes": _storage_sizes(root),
            "raw_probes": raw_probes,
            "context_responses": context_responses,
            "model_calls": 0,
            "real_godot_used": False,
            "pi_tested": False,
            "power_loss_tested": False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=160)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--mode", choices=("plain", "labeled"), default="plain")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = run_probe(events=args.events, seed=args.seed, mode=args.mode)
    if args.report:
        output = args.report.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    summary = {
        key: value for key, value in result.items()
        if key not in {"raw_probes", "context_responses", "memory_examples"}
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
