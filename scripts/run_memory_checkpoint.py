#!/usr/bin/env python3
"""Read-only-infrastructure memory characterization on disposable synthetic data.

Core v0.1 and production stores are untouched. This is a characterization
experiment, not a claim that Sleep autonomously revises Knowledge.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine

BASE_TIME = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
# (minute offset, type, content, session number). All names and observations
# are synthetic. "conversation.user" represents reported text, NOT a sensor.
CORPUS = (
    (0, "system.wake", None, 1),
    (1, "conversation.user", "Door hinge metallic clicks near hallway", 1),
    (4, "conversation.user", "Door hinge metallic clicks again near hallway", 1),
    (5, "sensor.audio", "Metallic clicks detected near hallway", 1),
    (7, "conversation.user", "CM5 battery voltage dropped overnight", 1),
    (11, "conversation.user", "CM5 battery voltage dropped and power unstable", 1),
    (13, "conversation.user", "Kitchen fan makes constant low humming noise", 1),
    (14, "conversation.user", "Kitchen fan makes constant low humming noise", 1),
    (15, "sensor.audio", "Constant low humming noise in kitchen", 1),
    (18, "conversation.user", "Door hinge metallic clicks may indicate loose hardware", 1),
    (21, "conversation.user", "CM5 battery voltage recovered after adapter change", 1),
    (25, "conversation.user", "Hallway door was closed at midday", 1),
    (28, "conversation.user", "Kitchen fan now makes sharper rattling noise", 1),
    (30, "conversation.user", "Fan was switched off and rattling stopped", 1),
    (31, "system.sleep", None, 1),
    (1441, "system.wake", None, 2),
    (1443, "conversation.user", "Door hinge metallic clicks returned next day", 2),
    (1445, "conversation.user", "CM5 battery voltage declined after reboot", 2),
    (1449, "sensor.audio", "Metallic clicks detected near hallway", 2),
    (1452, "conversation.user", "Hallway door was closed at midday", 2),
    (1455, "conversation.user", "Faint buzzing sound occurs near kitchen fan", 2),
    (1456, "conversation.user", "Kitchen fan makes constant low humming noise", 2),
)
QUERIES = ("door hinge metallic", "CM5 battery voltage", "kitchen fan humming")


def _event(index, entry):
    minute, kind, text, session = entry
    event_id = f"ev_{index:08x}-1111-4111-8111-{index:012x}"
    payload = {"text": text} if kind == "conversation.user" else (
        None if kind.startswith("system.") else {"transcript_hint": text}
    )
    return Event(
        kind,
        payload,
        source=("user" if kind == "conversation.user" else (
            "runtime" if kind.startswith("system.") else "synthetic.sensor"
        )),
        event_id=event_id,
        timestamp=(BASE_TIME + timedelta(minutes=minute)).isoformat(),
        session_id=f"session_{session:08d}",
    )


def _run(root: Path):
    event_log = EventLog(root / "events.jsonl")
    store = MemoryStore(root / "memory.db")
    links = LinkStore(store)
    processor = MemoryProcessor(
        memory_store=store, event_log=event_log, link_store=links
    )
    retrieval = RetrievalEngine(memory_store=store, link_store=links)
    provenance = ProvenanceResolver(store, links, event_log)
    lifecycle = MemoryLifecycle(memory_store=store)
    knowledge = KnowledgeLayer(memory_store=store)

    observed, latencies = [], []
    print("MEMORY_CHECKPOINT base=Core_v0.1 events=" + str(len(CORPUS)))
    for i, entry in enumerate(CORPUS, start=1):
        event = _event(i, entry)
        event_log.write(event)
        start = time.perf_counter()
        result = processor.process_event(event)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)
        observed.append({"number": i, "kind": event.event_type,
                         "action": result["action"],
                         "memory_id": result["memory_id"],
                         "candidate_id": result["candidate_id"],
                         "score": result["score"],
                         "reasons": result["reasons"],
                         "elapsed_ms": round(elapsed_ms, 3)})
        print(f"EVENT {i:02d} {event.event_type:<18} "
              f"{result['action']:<14} score={result['score']:<2} "
              f"{elapsed_ms:.2f}ms")

    actions = Counter(record["action"] for record in observed)
    memories = store.list_memories()
    if len(event_log.load_events()) != len(CORPUS):
        raise AssertionError("raw event log lost synthetic events")
    if actions["skip"] != sum(
        1 for x in CORPUS if x[1] != "conversation.user"
    ):
        raise AssertionError("unexpected memory selection policy")
    created_ids = {
        item["memory_id"] for item in observed if item["memory_id"] is not None
    }
    if len(created_ids) != len(memories):
        raise AssertionError("memory actions disagree with persisted memory IDs")

    query_results = {}
    for query in QUERIES:
        response = retrieval.retrieve(query, top_k=3, relation_hops=0)
        records = [
            {"kind": item["kind"], "id": item["id"],
             "score": item["score"], "content": (
                 item["record"].get("content")
                 or item["record"].get("statement")
             ), "reasons": item["reasons"]}
            for item in response["results"]
        ]
        query_results[query] = records
        print("RETRIEVE " + query)
        for item in records:
            print(f"  score={item['score']:<3} {item['kind']}: "
                  f"{str(item['content'])[:105]}")

    first_id = observed[1]["memory_id"]
    if first_id is None:
        raise AssertionError("first user event failed to produce memory")
    chain = provenance.memory(first_id)
    source_ids = store.source_events(first_id)
    if [record["id"] for record in chain["events"]] != source_ids:
        raise AssertionError("memory provenance differs from source links")
    print("PROVENANCE first_memory_events=" + str(len(source_ids)))

    # An explicitly invoked lifecycle demonstration. It is NOT autonomous
    # Sleep consolidation, belief revision or inferred world knowledge.
    closed = lifecycle.close(
        first_id, closed_at="2026-11-04T12:00:00+00:00"
    )
    candidate = knowledge.create_candidate(
        domain="user",
        statement="A metallic clicking sound was reported near the hallway door.",
        source_memory_id=first_id,
        created_at="2026-11-04T12:05:00+00:00",
    )
    if closed["status"] != "closed" or candidate["knowledge"]["status"] != "provisional":
        raise AssertionError("explicit memory->knowledge lifecycle failed")
    resolved = provenance.knowledge(candidate["knowledge"]["id"])
    if not resolved["sources"]:
        raise AssertionError("knowledge candidate lost supporting source")
    print("EXPLICIT_KNOWLEDGE_PROPOSAL provisional=1 (manual API invocation)")

    reopened_store = MemoryStore(root / "memory.db")
    reopened_links = LinkStore(reopened_store)
    reopened_retrieval = RetrievalEngine(
        memory_store=reopened_store, link_store=reopened_links
    )
    if reopened_store.count() != len(memories):
        raise AssertionError("memory count changed on cold reopen")
    if reopened_links.get_knowledge(candidate["knowledge"]["id"]) is None:
        raise AssertionError("knowledge candidate absent on cold reopen")
    if not reopened_retrieval.retrieve("door hinge", top_k=3)["results"]:
        raise AssertionError("retrieval failed after cold reopen")
    print("COLD_REOPEN_PASS")

    p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
    result = {
        "schema": "anima.memory-checkpoint/0.1",
        "scope": "isolated MemoryProcessor, Retrieval, Knowledge APIs",
        "events": len(CORPUS),
        "memory_count": len(memories),
        "actions": dict(sorted(actions.items())),
        "processed": observed,
        "retrieval": query_results,
        "provenance_event_ids": source_ids,
        "manual_knowledge_status": candidate["knowledge"]["status"],
        "manual_knowledge_id": candidate["knowledge"]["id"],
        "cold_reopen_pass": True,
        "mean_ms": round(statistics.mean(latencies), 3),
        "p95_ms": round(p95, 3),
    }
    print(f"MEMORY_CHECKPOINT_PASS memories={len(memories)} "
          f"actions={dict(actions)} mean={result['mean_ms']}ms "
          f"p95={result['p95_ms']}ms")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="anima-memory-checkpoint-") as temp:
        report = _run(Path(temp))
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("MEMORY_CHECKPOINT_REPORT " + str(args.report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
