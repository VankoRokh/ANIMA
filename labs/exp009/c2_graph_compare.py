"""EXP-009 G1: matched Existing Memory vs lab-only graph retrieval.

Uses the exact same 20 Runtime inputs and final Memory/EventLog state.
A and B share input data; the graph is a *secondary index*, not a rewrite
of production Memory and not an autonomous semantic memory engine.
"""

import argparse
import json
import tempfile
from pathlib import Path

from anima.core.assembly import build_core
from anima.memory.context_builder import ContextBuilder
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine
from labs.exp009.c2_memory_forensics import PROBES
from labs.exp009.c2_memory_observe import MATCHED, corpus
from labs.exp009.graph_memory_probe import GraphMemoryProbe


QUERIES = (
    *PROBES,
    ("cooling_failure", "cooling failure",
     tuple(f"exp009case{i:03d}" for i in range(5))),
    ("no_match", "nonexistentzzzxxyy", ()),
)
DEPTHS = (0, 1, 2)
ITEM_BUDGETS = (3, 10)
CHAR_BUDGETS = (256, 1200)


def _raw_texts(bundle):
    return [
        entry["record"]["content"] for entry in bundle["memories"]
    ] + [
        str((entry["record"].get("payload") or {}).get("text", ""))
        for entry in bundle["events"]
    ]


def _literal_hits(texts, markers):
    combined = " ".join(texts)
    return [marker for marker in markers if marker in combined]


def _write_report(path, records):
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(
                record, sort_keys=True, ensure_ascii=False, allow_nan=False
            ) + "\n")


def run_g1(root, *, report_path=None):
    """Run paired observations; report content and provenance, never assert QA."""
    root = Path(root)
    core = build_core(root / "runtime")
    core.runtime.wake()
    rows = corpus(MATCHED)
    inputs = []
    for row in rows:
        processed = core.runtime.user_input(row["text"])
        messages = [
            event for event in processed
            if event.event_type == "conversation.user"
        ]
        if len(messages) != 1:
            raise AssertionError("One raw conversation Event per input required")
        inputs.append({
            **row, "source_event_id": messages[0].event_id,
            "processing": core.event_processing.get(messages[0].event_id),
        })

    original_memories = core.memory_store.list_memories()
    original_events = core.event_log.load_events()
    provenance = ProvenanceResolver(
        core.memory_store, core.link_store, core.event_log
    )
    graph = GraphMemoryProbe(root / "graph_projection.db")
    graph_before = graph.ingest_snapshot(core.event_log, core.memory_store)
    graph_after = graph.ingest_snapshot(core.event_log, core.memory_store)
    if graph_before != graph_after:
        raise AssertionError("Reindex of an unchanged snapshot must be idempotent")
    if (
        core.memory_store.list_memories() != original_memories
        or core.event_log.load_events() != original_events
    ):
        raise AssertionError("Indexing must not alter original ANIMA stores")

    retrieval = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store
    )
    context = ContextBuilder(retrieval=retrieval, provenance=provenance)
    marker_to_event = {
        row["marker"]: row["source_event_id"] for row in inputs
    }
    records = [{
        "type": "experiment",
        "format": "exp009.g1.raw-jsonl/0.1",
        "inputs": len(inputs), "queries": len(QUERIES),
        "depths": list(DEPTHS), "item_budgets": list(ITEM_BUDGETS),
        "char_budgets": list(CHAR_BUDGETS),
        "architecture_A": "existing Runtime Memory + Retrieval/ContextBuilder",
        "architecture_B": "lab SQLite raw Event/Memory graph projection",
        "known_asymmetry": (
            "Graph B explicitly indexes raw Events; A indexes Memory text. "
            "This is a test of reachability, not matched semantic ranking."
        ),
    }]
    records.extend({"type": "input", **item} for item in inputs)

    for query_id, query_text, targets in QUERIES:
        for max_items in ITEM_BUDGETS:
            for max_chars in CHAR_BUDGETS:
                baseline_found = retrieval.retrieve(
                    query_text, kinds={"memory"}, relation_hops=0,
                    top_k=max_items,
                )
                baseline_contexts = {
                    consumer: context.build(
                        query_text, consumer=consumer,
                        max_items=max_items, max_chars=max_chars,
                        retrieval_options={"kinds": {"memory"}},
                    )
                    for consumer in ("FAST", "DEEP")
                }
                baseline_hit_markers = {
                    consumer: _literal_hits(
                        _raw_texts(bundle), targets
                    )
                    for consumer, bundle in baseline_contexts.items()
                }
                for depth in DEPTHS:
                    found = graph.search(
                        query_text, max_depth=depth, max_items=max_items,
                        max_chars=max_chars, max_visits=40,
                    )
                    graph_selected_hits = _literal_hits(
                        [item["content"] for item in found["selected"]],
                        targets,
                    )
                    expected_source_ids = {
                        marker: marker_to_event[marker] for marker in targets
                        if marker in marker_to_event
                    }
                    graph_direct_event_hits = [
                        marker for marker, event_id in expected_source_ids.items()
                        if any(
                            node["kind"] == "event" and node["id"] == event_id
                            for node in found["selected"]
                        )
                    ]
                    records.append({
                        "type": "comparison",
                        "query_id": query_id,
                        "query": query_text,
                        "targets": list(targets),
                        "target_source_event_ids": expected_source_ids,
                        "max_depth": depth,
                        "max_items": max_items,
                        "max_chars": max_chars,
                        "baseline_retrieval": baseline_found,
                        "baseline_context": baseline_contexts,
                        "baseline_literal_hits": baseline_hit_markers,
                        "graph": found,
                        "graph_literal_hits": graph_selected_hits,
                        "graph_source_event_hits": graph_direct_event_hits,
                        "caveat": (
                            "Literal fixture markers measure availability, not "
                            "semantic correctness. Graph links represent existing "
                            "provenance, not inferred causal relationships."
                        ),
                    })
    final = {
        "type": "final",
        "input_count": len(inputs),
        "memory_count": len(original_memories),
        "raw_event_count": len(original_events),
        "inputs": inputs,
        "memories": original_memories,
        "event_log": original_events,
        "graph_snapshot": graph_after,
        "actual_source_links": [
            {
                "memory_id": memory["id"],
                "event_ids": core.memory_store.source_events(memory["id"]),
            }
            for memory in original_memories
        ],
        "limitations": [
            "Experiment G1 only tests a graph projection of a final snapshot.",
            "Neither semantic graph construction nor consolidation is implemented.",
            "No authority inference: text is synthetic conversation.user.",
            "No Meta-memory, route learning, DEEP planner, or SLEEP integration.",
            "All raw Event nodes are indexed by design: this gives Graph B "
            "an intentional retrieval advantage when A's summary lost text.",
            "Graph depth and context limits are separate; higher depth may "
            "return no additional selected evidence under a tight budget.",
        ],
    }
    records.append(final)
    _write_report(report_path, records)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-dir", required=True, type=Path
    )
    parser.add_argument(
        "--print-summary", action="store_true"
    )
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anima-exp009-g1-") as temp:
        report = args.report_dir / "graph_vs_existing.jsonl"
        records = run_g1(Path(temp), report_path=report)
        final = records[-1]
        print(
            f"G1: inputs={final['input_count']} "
            f"memories={final['memory_count']} "
            f"events={final['raw_event_count']} "
            f"graph_nodes={len(final['graph_snapshot']['nodes'])} "
            f"graph_edges={len(final['graph_snapshot']['edges'])} "
            f"comparisons={sum(r['type'] == 'comparison' for r in records)} "
            f"report={report}"
        )
        if args.print_summary:
            for item in records:
                if (
                    item["type"] != "comparison"
                    or item["max_items"] != 10
                    or item["max_chars"] != 1200
                ):
                    continue
                print(
                    f"  query={item['query_id']} depth={item['max_depth']} "
                    f"A_FAST={item['baseline_literal_hits']['FAST']} "
                    f"A_DEEP={item['baseline_literal_hits']['DEEP']} "
                    f"B={item['graph_literal_hits']} "
                    f"B_raw={item['graph_source_event_hits']} "
                    f"visited={item['graph']['stats']['visited']} "
                    f"selected={item['graph']['stats']['items_used']}"
                )


if __name__ == "__main__":
    main()
