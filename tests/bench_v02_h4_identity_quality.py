"""Synthetic H4 pairwise-quality probe: false merges versus false splits.

Run from repository root:
    PYTHONPATH="$PWD" .venv/bin/python tests/bench_v02_h4_identity_quality.py

Every pair is generated in an isolated temporary database. This is a small,
explicitly synthetic *regression probe*, not a representative semantic-memory
benchmark or proof of accuracy on real multilingual streams.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor


T0 = "2026-11-17T12:00:00+00:00"
T1 = "2026-11-17T12:01:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def run_pair(case):
    with TemporaryDirectory(prefix="anima-h4-quality-") as tmp:
        root = Path(tmp)
        log = EventLog(root / "events.jsonl")
        store = MemoryStore(root / "memory.db")
        links = LinkStore(store)
        processor = MemoryProcessor(
            memory_store=store, event_log=log, link_store=links,
        )
        ids = {}
        for i, name in enumerate(["Vega", "Orion"], start=1):
            entity = links.create_entity(
                entity_type="object", canonical_name=name,
                public_id=uid("ent_", i),
            )
            ids[name] = entity["id"]
        memory_ids = []
        for step, item in enumerate(case["events"], start=1):
            refs = [
                {"kind": "entity", "id": ids[name]}
                for name in item["entities"]
            ]
            event = Event(
                "conversation.user", {"text": item["text"]},
                source="user", session_id="session_00000001",
                timestamp=T0 if step == 1 else T1,
                event_id=uid("ev_", step), references=refs,
            )
            log.write(event)
            memory_ids.append(processor.process_event(event)["memory_id"])
        predicted_same = memory_ids[0] == memory_ids[1]
        return {
            "name": case["name"],
            "expected_same": case["same"],
            "predicted_same": predicted_same,
            "correct": case["same"] == predicted_same,
            "result_memory_count": store.count(),
        }


def main():
    pairs = [
        {
            "name": "distinct_entity_same_boilerplate",
            "same": False,
            "events": [
                {"text": "Controller Vega reported overheating sensor",
                 "entities": ["Vega"]},
                {"text": "Controller Orion reported overheating sensor",
                 "entities": ["Orion"]},
            ],
        },
        {
            "name": "same_entity_strong_lexical_signal",
            "same": True,
            "events": [
                {"text": "Vega cooling system needs maintenance",
                 "entities": ["Vega"]},
                {"text": "Vega cooling system needs maintenance soon",
                 "entities": ["Vega"]},
            ],
        },
        {
            "name": "same_entity_no_shared_words",
            "same": True,
            "events": [
                {"text": "Storage baseline", "entities": ["Vega"]},
                {"text": "Database choice", "entities": ["Vega"]},
            ],
        },
        {
            "name": "multi_entity_claim_does_not_bridge_singleton",
            "same": False,
            "events": [
                {"text": "Controller Vega reported overheating sensor",
                 "entities": ["Vega"]},
                {"text": "Controller Vega Orion reported overheating sensor",
                 "entities": ["Vega", "Orion"]},
            ],
        },
    ]
    results = [run_pair(case) for case in pairs]
    tp = sum(x["expected_same"] and x["predicted_same"] for x in results)
    fp = sum(not x["expected_same"] and x["predicted_same"] for x in results)
    fn = sum(x["expected_same"] and not x["predicted_same"] for x in results)
    tn = sum(not x["expected_same"] and not x["predicted_same"]
             for x in results)
    summary = {
        "cases": len(results),
        "true_positive_pairs": tp,
        "false_merge_pairs": fp,
        "false_split_pairs": fn,
        "true_negative_pairs": tn,
        "pairwise_precision": tp / (tp + fp) if tp + fp else None,
        "pairwise_recall": tp / (tp + fn) if tp + fn else None,
        "cases_detail": results,
        "note": "Synthetic pairs only. No real-world recall guarantee.",
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if fp != 0 or fn != 1:
        raise SystemExit("H4 synthetic quality boundary changed; review required")


if __name__ == "__main__":
    main()
