"""EXP-009 E1: compare legacy MemoryProcessor with raw-source shadow episodes.

Fixed 20 synthetic user Events, 2 composition budgets, one independent
gold labeling. Nothing is inserted into production memory. Output raw
per-Event decisions and pairwise boundary errors; no LLM and no refitting.
"""

import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import tempfile
from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.composer import RuleBasedComposer
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.memory.shadow_encoding import ShadowEpisodeEncoder


ENT_CPU_A = "ent_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ENT_CPU_B = "ent_bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ENT_CPU_C = "ent_cccccccc-cccc-4ccc-8ccc-cccccccccccc"
BASE_DATE = "2026-11-11"
NEXT_DATE = "2026-11-12"
S1 = "session_00000001"
S2 = "session_00000002"
S3 = "session_00000003"


def event_id(i):
    return "ev_" + str(UUID(int=(4 << 76) | (2 << 62) | (i + 1)))


# (group, minute offset, session, message, entity, UTC day)
# Deliberate interleaving, repeated topic later, entity collision, punctuation,
# isolated noise and unrelated topics for explicit boundary evaluation.
CORPUS = (
    ("cpu_a", 0, S1, "CPU cooling temperature 82 high", ENT_CPU_A, BASE_DATE),
    ("network_a", 1, S1, "network router connection down", None, BASE_DATE),
    ("cpu_a", 3, S1, "CPU cooling temperature 91 alarm", ENT_CPU_A, BASE_DATE),
    ("network_a", 4, S1, "network router connection restored", None, BASE_DATE),
    ("cpu_a", 6, S1, "CPU cooling fan repaired", ENT_CPU_A, BASE_DATE),
    ("cpu_a", 8, S1, "CPU cooling temperature 65 stable", ENT_CPU_A, BASE_DATE),
    ("cpu_b", 0, S2, "CPU cooling temperature 82 high", ENT_CPU_B, NEXT_DATE),
    ("cpu_b", 2, S2, "CPU cooling temperature 65 stable", ENT_CPU_B, NEXT_DATE),
    ("cpu_c", 3, S2, "CPU cooling temperature 82 high", ENT_CPU_C, NEXT_DATE),
    ("cpu_c", 6, S2, "CPU cooling temperature 65 stable", ENT_CPU_C, NEXT_DATE),
    ("cpu_schedule", 7, S2, "CPU scheduling inventory review", ENT_CPU_B, NEXT_DATE),
    ("one_off", 8, S2, "unrelated travel tickets status", None, NEXT_DATE),
    ("db_a", 10, S2, "Database storage checkpoint verified", None, NEXT_DATE),
    ("db_a", 11, S2, "Database, storage: checkpoint verified!", None, NEXT_DATE),
    ("db_b", 12, S3, "Database storage checkpoint verified", None, NEXT_DATE),
    ("noise_1", 13, S3, "Hello", None, NEXT_DATE),
    ("noise_2", 14, S3, "???!", None, NEXT_DATE),
    ("screws", 15, S3, "Need screw parts stocked", None, NEXT_DATE),
    ("screws", 16, S3, "Screw parts arrived", None, NEXT_DATE),
    ("another", 17, S3, "memory algorithm raw event comparison", None, NEXT_DATE),
)


def fixture():
    events = []
    gold = {}
    for i, (group, minute, session, text, entity, day) in enumerate(CORPUS):
        stamp = f"{day}T12:{minute:02d}:00+00:00"
        refs = [{"kind": "entity", "id": entity}] if entity else []
        item = Event(
            "conversation.user", {"text": text}, source="user",
            session_id=session, references=refs, event_id=event_id(i),
            timestamp=stamp,
        )
        events.append(item)
        gold[item.event_id] = group
    return events, gold


def _register_entities(links):
    for entity_id, name in (
        (ENT_CPU_A, "CPU A"), (ENT_CPU_B, "CPU B"), (ENT_CPU_C, "CPU C")
    ):
        links.create_entity(
            entity_type="technology", canonical_name=name,
            public_id=entity_id,
        )


def _legacy(root, events, *, composition_budget):
    root.mkdir(parents=True, exist_ok=True)
    log = EventLog(root / "events.jsonl")
    store = MemoryStore(root / "memory.db")
    links = LinkStore(store)
    _register_entities(links)
    processor = MemoryProcessor(
        memory_store=store, event_log=log, link_store=links,
        composer=RuleBasedComposer(max_chars=composition_budget),
    )
    turns = []
    for event in events:
        log.write(event)
        outcome = processor.process_event(event)
        turns.append({
            "event_id": event.event_id, "action": outcome["action"],
            "memory_id": outcome["memory_id"],
            "candidate_id": outcome["candidate_id"],
            "score": outcome["score"],
            "reasons": outcome["reasons"],
        })
    memories = store.list_memories()
    assignments = {}
    for memory in memories:
        for source_id in store.source_events(memory["id"]):
            if source_id in assignments:
                raise AssertionError("A source Event belongs to multiple memories")
            assignments[source_id] = memory["id"]
    if len(assignments) != len(events):
        raise AssertionError("Not all user Events are assigned to Memory")
    return {
        "composition_budget": composition_budget,
        "turns": turns,
        "memories": memories,
        "assignments": assignments,
        "memory_sources": {
            m["id"]: store.source_events(m["id"]) for m in memories
        },
        "_log": log, "_store": store, "_links": links,
    }


def pairwise_metrics(assignments, gold):
    ids = sorted(gold)
    target_pairs = {
        (left, right) for left, right in combinations(ids, 2)
        if gold[left] == gold[right]
    }
    pred_pairs = {
        (left, right) for left, right in combinations(ids, 2)
        if assignments.get(left) is not None
        and assignments[left] == assignments.get(right)
    }
    tp = target_pairs & pred_pairs
    merges = sorted(pred_pairs - target_pairs)
    splits = sorted(target_pairs - pred_pairs)
    return {
        "true_positive_pairs": len(tp),
        "predicted_same_episode_pairs": len(pred_pairs),
        "gold_same_episode_pairs": len(target_pairs),
        "false_merge_pairs": len(merges),
        "false_split_pairs": len(splits),
        "precision": len(tp) / len(pred_pairs) if pred_pairs else None,
        "recall": len(tp) / len(target_pairs) if target_pairs else None,
        "false_merge_examples": [list(pair) for pair in merges[:15]],
        "false_split_examples": [list(pair) for pair in splits[:15]],
    }


def run_shadow(root, *, report_path=None):
    root = Path(root)
    if root.exists():
        raise ValueError("Lab root must not already exist")
    events, gold = fixture()

    old_64 = _legacy(root / "legacy_64", events, composition_budget=64)
    old_512 = _legacy(root / "legacy_512", events, composition_budget=512)
    # Shadow Entity IDs are resolved through the *real* EntityStore, but no
    # Memory/Relation/Knowledge rows are changed by shadow operations.
    before_memory = old_512["_store"].list_memories()
    before_raw = old_512["_log"].load_events()
    encoder = ShadowEpisodeEncoder(link_store=old_512["_links"])
    shadow_turns = [encoder.accept(event) for event in events]
    after_memory = old_512["_store"].list_memories()
    after_raw = old_512["_log"].load_events()
    if before_memory != after_memory or before_raw != after_raw:
        raise AssertionError("Shadow changed source stores")
    assert len(encoder.event_assignments()) == len(events)

    def public_legacy(data):
        return {
            "composition_budget": data["composition_budget"],
            "turns": data["turns"], "memories": data["memories"],
            "assignments": data["assignments"],
            "memory_sources": data["memory_sources"],
            "metrics": pairwise_metrics(data["assignments"], gold),
        }

    result = {
        "type": "exp009.memory_encoding.shadow/0.1",
        "scope": "synthetic conversation.user, deterministic, read-only shadow",
        "gold": gold,
        "input_events": [event.to_dict() for event in events],
        "legacy_64": public_legacy(old_64),
        "legacy_512": public_legacy(old_512),
        "shadow": {
            "turns": shadow_turns, "episodes": encoder.episodes(),
            "assignments": encoder.event_assignments(),
            "metrics": pairwise_metrics(encoder.event_assignments(), gold),
        },
        "invariants": {
            "raw_event_count": len(events),
            "legacy_eventlog_unchanged": before_raw == after_raw,
            "legacy_memories_unchanged": before_memory == after_memory,
            "shadow_source_coverage": len(encoder.event_assignments()),
            "no_llm": True,
        },
        "caveat": (
            "Synthetic example corpus and handcrafted lexical rule only; "
            "pairwise metrics do not prove real-world semantic grouping or "
            "replacement safety. New runtime routing is not enabled."
        ),
    }
    if report_path is not None:
        report = Path(report_path)
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False,
                      sort_keys=True, indent=2)
            stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anima-encoding-shadow-") as td:
        report_path = args.report_dir / "memory_encoding_shadow.json"
        result = run_shadow(Path(td) / "work", report_path=report_path)
    for label in ("legacy_64", "legacy_512", "shadow"):
        metrics = result[label]["metrics"]
        print(
            f"{label}: pair_precision={metrics['precision']}, "
            f"pair_recall={metrics['recall']}, "
            f"false_merge={metrics['false_merge_pairs']}, "
            f"false_split={metrics['false_split_pairs']}"
        )
    print("Raw report:", report_path)


if __name__ == "__main__":
    main()
