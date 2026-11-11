"""EXP-009 C2-C/F: forensic observation of Runtime Memory content retention.

This is an external, read-only observer of production Memory interfaces. It
does not modify Core, Runtime, Composer, Retrieval or ContextBuilder. Each
variant uses a fresh temporary Core instance and the same C2-C corpus.
"""

import argparse
import json
import tempfile
from pathlib import Path

from anima.core.assembly import build_core
from anima.memory.composer import DEFAULT_CONTENT_BUDGET
from anima.memory.context_builder import ContextBuilder
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine
from labs.exp009.c2_memory_observe import MATCHED, corpus


VARIANTS = ("plain", "sentence_delimited")
CONTEXT_ITEM_BUDGETS = (3, 5, 10)
CONTEXT_CHAR_BUDGETS = (256, 1200)
PROBES = (
    ("early_marker", "exp009case000", ("exp009case000",)),
    ("incident_marker", "exp009case004", ("exp009case004",)),
    ("late_marker", "exp009case018", ("exp009case018",)),
    ("incident_query", "previous overheating incident",
     tuple(f"exp009case{i:03d}" for i in range(5))),
    ("temperature_normalized", "temperature normalized",
     ("exp009case004",)),
    ("thermal_query", "processor temperature",
     tuple(f"exp009case{i:03d}" for i in (0, 1, 2, 4, 6, 12, 18, 24))),
)


def _input_text(row, variant):
    if variant == "plain":
        return row["text"]
    if variant == "sentence_delimited":
        return row["text"] + "."
    raise ValueError(f"Unknown forensic variant: {variant!r}")


def _source_marker(event, marker_set):
    if event is None:
        return None
    payload = event.get("payload") or {}
    text = payload.get("text", "")
    if not isinstance(text, str):
        return None
    # Markers are synthetic immutable fixture labels, not model-generated tags.
    return next((marker for marker in marker_set if marker in text), None)


def _memory_snapshot(core, input_rows):
    events = core.event_log.load_events()
    by_id = {item["id"]: item for item in events}
    markers = [row["marker"] for row in input_rows]
    result = []
    for memory in core.memory_store.list_memories():
        source_ids = core.memory_store.source_events(memory["id"])
        linked_events = [by_id.get(source_id) for source_id in source_ids]
        source_markers = sorted(set(
            marker for marker in (
                _source_marker(event, markers) for event in linked_events
            ) if marker is not None
        ))
        content_markers = sorted(
            marker for marker in markers if marker in memory["content"]
        )
        result.append({
            "memory": memory,
            "source_event_ids": source_ids,
            "missing_source_event_ids": [
                source_id for source_id in source_ids
                if source_id not in by_id
            ],
            "linked_events": linked_events,
            "source_markers": source_markers,
            "content_markers": content_markers,
            "source_markers_absent_from_content": sorted(
                set(source_markers) - set(content_markers)
            ),
            "content_chars": len(memory["content"]),
        })
    return result


def _marker_lookups(core, input_rows):
    retrieval = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store
    )
    marker_set = {row["marker"] for row in input_rows}
    observations = []
    for marker in sorted(marker_set):
        found = retrieval.retrieve(
            marker, kinds={"memory"}, relation_hops=0, top_k=10
        )
        selected = found["results"]
        # Distinguish a text match from an indirect provenance link.
        selected_source_ids = [
            source_id for item in selected
            for source_id in core.memory_store.source_events(item["id"])
        ]
        events = {e["id"]: e for e in core.event_log.load_events()}
        source_markers = {
            _source_marker(events.get(event_id), marker_set)
            for event_id in selected_source_ids
        }
        observations.append({
            "marker": marker,
            "retrieval": found,
            "found_by_text": any(
                marker in item["record"]["content"] for item in selected
            ),
            "linked_through_retrieval": marker in source_markers,
        })
    return observations


def _context_probes(core):
    provenance = ProvenanceResolver(
        core.memory_store, core.link_store, core.event_log
    )
    retrieval = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store
    )
    builder = ContextBuilder(retrieval=retrieval, provenance=provenance)
    records = []
    for probe_id, query, target_markers in PROBES:
        raw_retrieval = retrieval.retrieve(
            query, kinds={"memory"}, relation_hops=0, top_k=10
        )
        for max_items in CONTEXT_ITEM_BUDGETS:
            for max_chars in CONTEXT_CHAR_BUDGETS:
                for consumer in ("FAST", "DEEP"):
                    bundle = builder.build(
                        query,
                        consumer=consumer,
                        max_items=max_items,
                        max_chars=max_chars,
                        retrieval_options={"kinds": {"memory"}},
                    )
                    included_memory_text = " ".join(
                        entry["record"]["content"]
                        for entry in bundle["memories"]
                    )
                    included_event_text = " ".join(
                        str((entry["record"].get("payload") or {}).get("text", ""))
                        for entry in bundle["events"]
                    )
                    records.append({
                        "type": "context_probe",
                        "probe_id": probe_id,
                        "query": query,
                        "target_markers": list(target_markers),
                        "consumer": consumer,
                        "max_items": max_items,
                        "max_chars": max_chars,
                        "retrieval": raw_retrieval,
                        "context": bundle,
                        "targets_in_memory_content": [
                            marker for marker in target_markers
                            if marker in included_memory_text
                        ],
                        "targets_in_event_content": [
                            marker for marker in target_markers
                            if marker in included_event_text
                        ],
                        "limitations": (
                            "Marker presence is literal and not semantic comprehension. "
                            "Context is selected by existing FAST/DEEP policy."
                        ),
                    })
    return records


def _save_jsonl(path, records):
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Existing raw results are immutable; require a new report name.
    with target.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True, allow_nan=False
            ) + "\n")


def run_c2_cf(root, *, variant="plain", report_path=None):
    """Run F1/F2/F3 against real Runtime and Memory, return raw JSONL entries."""
    if variant not in VARIANTS:
        raise ValueError(f"Unsupported forensic variant: {variant}")
    rows = corpus(MATCHED)
    core = build_core(root)
    core.runtime.wake()
    records = [{
        "type": "experiment",
        "format": "exp009.c2cf.raw-jsonl/0.1",
        "variant": variant,
        "input_count": len(rows),
        "composer_limit": DEFAULT_CONTENT_BUDGET,
        "context_item_budgets": list(CONTEXT_ITEM_BUDGETS),
        "context_char_budgets": list(CONTEXT_CHAR_BUDGETS),
        "probe_ids": [item[0] for item in PROBES],
        "fixture": "C2-C MATCHED; synthetic conversation.user only",
    }]
    first_absence = {}
    for ordinal, row in enumerate(rows, start=1):
        before = {
            entry["memory"]["id"]: entry
            for entry in _memory_snapshot(core, rows[:ordinal-1])
        }
        before_event_ids = {
            item["id"] for item in core.event_log.load_events()
        }
        text = _input_text(row, variant)
        processed = core.runtime.user_input(text)
        new_user = [
            item for item in processed
            if item.event_type == "conversation.user"
        ]
        if len(new_user) != 1:
            raise AssertionError("Expected one Runtime conversation.user event")
        event_id = new_user[0].event_id
        event = next(
            item for item in core.event_log.load_events()
            if item["id"] == event_id
        )
        snapshot = _memory_snapshot(core, rows[:ordinal])
        linked = [
            entry for entry in snapshot
            if event_id in entry["source_event_ids"]
        ]
        if len(linked) != 1:
            raise AssertionError("New Runtime event must have exactly one Memory owner")

        current = linked[0]
        previous = before.get(current["memory"]["id"])
        if previous is None:
            preview = core.memory_composer.compose_create(text)
            operation = "create_or_create_related"
        else:
            preview = core.memory_composer.compose_update(
                previous["memory"]["content"], text
            )
            operation = "update"

        # These calculations are observer-only; they do not feed production
        # Memory or influence the next event.
        missing = sorted(set(
            marker for entry in snapshot
            for marker in entry["source_markers_absent_from_content"]
        ))
        for marker in missing:
            first_absence.setdefault(marker, ordinal)
        lookups = _marker_lookups(core, rows[:ordinal])
        records.append({
            "type": "step",
            "variant": variant,
            "ordinal": ordinal,
            "input": {**row, "submitted_text": text},
            "original_event": event,
            "processing_ledger": core.event_processing.get(event_id),
            "new_event_ids": [
                item["id"] for item in core.event_log.load_events()
                if item["id"] not in before_event_ids
            ],
            "operation_inferred_from_sources": operation,
            "composer_preview": preview,
            "composer_preview_matches_stored": (
                preview["content"] == current["memory"]["content"]
            ),
            "prior_content_chars": (
                previous["content_chars"] if previous else None
            ),
            "pre_composition_chars": (
                len(previous["memory"]["content"]) + 1 + len(text)
                if previous else len(text)
            ),
            "current_memory_id": current["memory"]["id"],
            "memory_snapshot": snapshot,
            "source_markers_absent_from_content": missing,
            "marker_retrieval": lookups,
        })
    records.extend(_context_probes(core))
    final_snapshot = _memory_snapshot(core, rows)
    all_events = core.event_log.load_events()
    final = {
        "type": "final",
        "variant": variant,
        "input_count": len(rows),
        "memory_count": core.memory_store.count(),
        "event_count": len(all_events),
        "all_events": all_events,
        "memory_snapshot": final_snapshot,
        "first_absence_step_by_marker": first_absence,
        "source_markers": sorted(row["marker"] for row in rows),
        "visible_markers": sorted({
            marker for entry in final_snapshot
            for marker in entry["content_markers"]
        }),
        "raw_source_event_ids": sorted({
            source_id for entry in final_snapshot
            for source_id in entry["source_event_ids"]
        }),
        "original_input_event_ids": [
            entry["original_event"]["id"] for entry in records
            if entry["type"] == "step"
        ],
        "limits": [
            "Synthetic conversation.user is not a sensor observation.",
            "Source marker visibility is a lexical signal, not semantic truth.",
            "Composer preview is observation of current rules, not a new policy.",
            "DEEP does not guarantee restoration of missing events.",
            "Equal-second event timestamps may leave UUID as sorting tie-breaker.",
        ],
    }
    records.append(final)
    _save_jsonl(report_path, records)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("both", *VARIANTS), default="both")
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--show-steps", action="store_true")
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    variants = VARIANTS if args.variant == "both" else (args.variant,)
    with tempfile.TemporaryDirectory(prefix="anima-exp009-c2cf-") as tempdir:
        for variant in variants:
            report = args.report_dir / f"{variant}.jsonl"
            entries = run_c2_cf(
                Path(tempdir) / variant,
                variant=variant,
                report_path=report,
            )
            final = entries[-1]
            missing = sorted(
                set(final["source_markers"]) - set(final["visible_markers"])
            )
            print(
                f"{variant}: inputs={final['input_count']} "
                f"memories={final['memory_count']} "
                f"visible_markers={len(final['visible_markers'])} "
                f"missing_markers={missing} "
                f"first_absence={final['first_absence_step_by_marker']} "
                f"report={report}"
            )
            if args.show_steps:
                for step in (r for r in entries if r["type"] == "step"):
                    print(
                        f"  step={step['ordinal']:02d} "
                        f"marker={step['input']['marker']} "
                        f"action={step['operation_inferred_from_sources']} "
                        f"prev_chars={step['prior_content_chars']} "
                        f"candidate_chars={step['pre_composition_chars']} "
                        f"actual_chars={next(x['content_chars'] for x in step['memory_snapshot'] if x['memory']['id'] == step['current_memory_id'])} "
                        f"composer_truncated={step['composer_preview']['truncated']} "
                        f"absent={step['source_markers_absent_from_content']}"
                    )


if __name__ == "__main__":
    main()
