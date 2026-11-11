"""EXP-009 / C2-C: observe real Memory retrieval with bounded contexts.

Three independent stores:
  controlled_100: 100 synthetic Events + memories through MemoryStore API.
  controlled_20: 20 matched synthetic Events + memories through MemoryStore API.
  runtime_20: the SAME 20 texts as conversation.user via Runtime -> MemoryProcessor.

The lab generates inputs and reads public APIs, never injects query results,
edits MemoryProcessor, or treats simulated user reports as authorized sensors.
"""

import argparse
import json
import tempfile
from pathlib import Path
from uuid import UUID

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


STAMP = "2026-11-11T12:00:00+00:00"
TOTAL = 100
MATCHED = (
    0, 1, 2, 3, 4, 6, 12, 18, 24, 30, 36, 42, 48, 54,
    60, 66, 72, 78, 84, 90,
)
BUDGETS = (3, 5, 10)
MAX_CHARS = 1200


def _id(prefix, index):
    uid = UUID(int=(4 << 76) | (2 << 62) | (index + 1))
    return f"{prefix}{uid}"


def corpus_row(index):
    if not 0 <= index < TOTAL:
        raise ValueError("Corpus index outside EXP-009 fixture")
    marker = f"exp009case{index:03d}"
    if index < 5:
        details = (
            "cooling incident processor temperature 82 high",
            "cooling incident fan stopped processor temperature 91",
            "cooling incident alarm high processor temperature 94",
            "cooling incident fan repaired cooling restored",
            "cooling incident temperature normalized processor 65",
        )[index]
        topic = "cooling_incident"
    elif index < 25:
        details = f"thermal telemetry processor temperature {55 + index % 24} steady"
        topic = "temperature"
    elif index < 40:
        details = f"processor load telemetry {30 + index % 62} percent"
        topic = "load"
    elif index < 55:
        details = f"maintenance cooling fan inspected rotation {index % 3}"
        topic = "maintenance"
    elif index < 70:
        details = f"access door registry entry room {index % 6}"
        topic = "access"
    elif index < 85:
        details = f"network connection interface status port {index % 4}"
        topic = "network"
    else:
        details = f"unrelated scheduling inventory routine task {index}"
        topic = "noise"
    return {
        "index": index,
        "marker": marker,
        "topic": topic,
        "text": f"{marker} {details}",
    }


def corpus(indices):
    return [corpus_row(index) for index in indices]


def _access(core):
    provenance = ProvenanceResolver(
        core.memory_store, core.link_store, core.event_log
    )
    retrieval = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store
    )
    context = ContextBuilder(retrieval=retrieval, provenance=provenance)
    return retrieval, context, provenance


def _controlled(root, rows):
    core = build_core(root)
    inputs = []
    for row in rows:
        event = Event(
            "lab.fixture.memory_source",
            {"text": row["text"], "marker": row["marker"]},
            source="synthetic.exp009",
            timestamp=STAMP,
            event_id=_id("ev_", row["index"]),
        )
        core.event_log.write(event)
        memory = core.memory_store.create_memory(
            memory_type="episodic", domain="project", content=row["text"],
            status="closed", importance=1, created_at=STAMP,
            public_id=_id("mem_", row["index"]),
            source_event_id=event.event_id,
        )
        inputs.append({
            "type": "input", "path": "controlled_memory_api", **row,
            "source_event_id": event.event_id,
            "created_memory_id": memory["id"],
        })
    return core, inputs


def _runtime(root, rows):
    core = build_core(root)
    core.runtime.wake()
    inputs = []
    for row in rows:
        events_before = len(core.event_log.load_events())
        memory_before = core.memory_store.count()
        # This is a synthetic conversation.user message, NOT a Core world sensor.
        core.runtime.user_input(row["text"])
        new_events = core.event_log.load_events()[events_before:]
        conversation_ids = [
            record["id"] for record in new_events
            if record["type"] == "conversation.user"
        ]
        if len(conversation_ids) != 1:
            raise AssertionError("Runtime did not record exactly one user message")
        inputs.append({
            "type": "input", "path": "runtime_user_input", **row,
            "source_event_id": conversation_ids[0],
            "memory_count_before": memory_before,
            "memory_count_after": core.memory_store.count(),
            "processing": core.event_processing.get(conversation_ids[0]),
        })
    return core, inputs


# Query labels and gold topics are assigned before any Retrieval call.
# Gold denotes fixture membership, not a promise of semantic relevance.
QUERIES = (
    ("marker_first", "exp009case000", ("cooling_incident",)),
    ("marker_incident", "exp009case004", ("cooling_incident",)),
    ("marker_other", "exp009case060", ("access",)),
    ("cooling_failure", "cooling failure", ("cooling_incident",)),
    ("processor_temperature", "processor temperature", ("cooling_incident", "temperature")),
    ("fan_repaired", "fan repaired", ("cooling_incident",)),
    ("cooling_maintenance", "cooling maintenance", ("maintenance",)),
    ("processor_load", "processor load", ("load",)),
    ("door_access", "door access", ("access",)),
    ("network_connection", "network connection", ("network",)),
    ("inventory", "inventory routine", ("noise",)),
    ("past_incident", "previous overheating incident", ("cooling_incident",)),
    ("temperature_drop", "temperature normalized", ("cooling_incident",)),
    ("generic_telemetry", "telemetry", ("temperature", "load")),
    ("no_match", "nonexistentzzzxxyy", ()),
)


def _provenance_for(retrieval_result, provenance):
    # Raw retrieval records are preserved unmodified. This is an independent
    # provenance view, not an extra relevance signal.
    return [
        {
            "memory_id": item["id"],
            "source_events": provenance.memory(item["id"])["events"],
        }
        for item in retrieval_result["results"]
        if item["kind"] == "memory"
    ]


def _observations(core, mode, rows):
    retrieval, context, provenance = _access(core)
    event_by_id = {
        event["id"]: event for event in core.event_log.load_events()
    }
    marker_by_event = {}
    for event_id, event in event_by_id.items():
        payload = event["payload"] or {}  # system.wake has null payload
        marker = payload.get("marker")
        if marker is None:
            text = payload.get("text", "")
            marker = next(
                (row["marker"] for row in rows if row["marker"] in text),
                None,
            )
        if marker is not None:
            marker_by_event[event_id] = marker
    topic_by_marker = {row["marker"]: row["topic"] for row in rows}
    output = []
    for qid, query, topics in QUERIES:
        gold = sorted(
            row["marker"] for row in rows if row["topic"] in topics
        )
        for k in BUDGETS:
            found = retrieval.retrieve(
                query, kinds={"memory"}, relation_hops=0, top_k=k
            )
            selection = {}
            for consumer in ("FAST", "DEEP"):
                selection[consumer] = context.build(
                    query, consumer=consumer, max_items=k,
                    max_chars=MAX_CHARS,
                    retrieval_options={"kinds": {"memory"}},
                )

            selected_source_markers = set()
            for item in found["results"]:
                for event_id in core.memory_store.source_events(item["id"]):
                    marker = marker_by_event.get(event_id)
                    if marker:
                        selected_source_markers.add(marker)
            hits = sorted(set(gold) & selected_source_markers)
            output.append({
                "type": "query", "mode": mode, "query_id": qid,
                "query_text": query, "top_k": k,
                "fixture_gold_topics": list(topics),
                "fixture_gold_markers": gold,
                "retrieval": found,
                "context": selection,
                "selected_source_markers": sorted(selected_source_markers),
                "fixture_gold_found": hits,
                "fixture_source_recall": (
                    len(hits) / len(gold) if gold else None
                ),
                "provenance": _provenance_for(found, provenance),
                "caveat": "Gold measures tagged source coverage, not semantic correctness.",
            })
    return output


def _final(core, mode, rows, provenance):
    stored = core.memory_store.list_memories()
    event_log = core.event_log.load_events()
    source_links = [
        {"memory_id": memory["id"],
         "event_ids": core.memory_store.source_events(memory["id"])}
        for memory in stored
    ]
    # Only inspect a small sample with full provenance; ContextBuilder already
    # resolves source Events for each DEEP context.
    examples = [
        provenance.memory(memory["id"]) for memory in stored[:3]
    ]
    return {
        "type": "final", "mode": mode, "inputs": len(rows),
        "memory_count": core.memory_store.count(),
        "memories": stored,
        "source_links": source_links,
        "provenance_examples": examples,
        "events": event_log,
        "runtime_state": core.runtime.snapshot()["state"],
        "limitations": [
            "Controlled mode deliberately seeds Memory via public API.",
            "Runtime mode uses synthetic conversation.user messages, not sensors.",
            "Retrieval is FTS/filters/relations, not unconstrained semantic QA.",
            "No automatic sensor->Memory->Goal loop is exercised.",
            "Correlated fixture sources are not independent evidence.",
        ],
    }


def _dump(path, records):
    if path is None:
        return
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    # Never silently replace a previous experiment output.
    with file.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(
                record, sort_keys=True, ensure_ascii=False, allow_nan=False
            ) + "\n")


def run_c2_c(root, *, mode="controlled_100", report_path=None):
    if mode not in {"controlled_100", "controlled_20", "runtime_20"}:
        raise ValueError("Unsupported EXP-009 C2-C mode")
    rows = corpus(range(TOTAL) if mode == "controlled_100" else MATCHED)
    if mode == "runtime_20":
        core, inputs = _runtime(root, rows)
    else:
        core, inputs = _controlled(root, rows)
    retrieval, context, provenance = _access(core)
    records = [{
        "type": "experiment", "format": "exp009.c2c.raw-jsonl/0.1",
        "mode": mode, "row_count": len(rows),
        "matched_indices": list(MATCHED),
        "queries": len(QUERIES),
        "budgets": list(BUDGETS),
        "max_chars": MAX_CHARS,
    }]
    records.extend(inputs)
    records.extend(_observations(core, mode, rows))
    records.append(_final(core, mode, rows, provenance))
    _dump(report_path, records)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("all", "controlled_100", "controlled_20",
                          "runtime_20"), default="all"
    )
    parser.add_argument(
        "--report-dir", type=Path, required=True,
        help="New output directory outside tracked paths"
    )
    parser.add_argument(
        "--print-queries", action="store_true",
        help="Print each retrieval selection as compact text"
    )
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    modes = (
        ("controlled_100", "controlled_20", "runtime_20")
        if args.mode == "all" else (args.mode,)
    )
    with tempfile.TemporaryDirectory(prefix="anima-exp009-c2c-") as temp:
        for mode in modes:
            report_path = args.report_dir / f"{mode}.jsonl"
            records = run_c2_c(
                Path(temp) / mode, mode=mode, report_path=report_path
            )
            final = records[-1]
            print(
                f"{mode}: inputs={final['inputs']} "
                f"memories={final['memory_count']} "
                f"queries={sum(r['type'] == 'query' for r in records)} "
                f"report={report_path}"
            )
            if args.print_queries:
                for item in records:
                    if item["type"] != "query":
                        continue
                    ids = [r["id"] for r in item["retrieval"]["results"]]
                    fast = item["context"]["FAST"]["selection_stats"]
                    deep = item["context"]["DEEP"]["selection_stats"]
                    print(
                        f"  {item['query_id']} query={item['query_text']!r} "
                        f"k={item['top_k']} ids={ids} "
                        f"recall={item['fixture_source_recall']} "
                        f"FAST={fast['items_used']} DEEP={deep['items_used']}"
                    )
                    for rank, selected in enumerate(
                        item["retrieval"]["results"][:3], start=1
                    ):
                        print(
                            f"    [{rank}] score={selected['score']} "
                            f"text={selected['record']['content'][:120]!r} "
                            f"reasons={selected['reasons']}"
                        )


if __name__ == "__main__":
    main()
