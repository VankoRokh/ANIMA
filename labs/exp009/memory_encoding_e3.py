"""EXP-009 E3: explicit review-readiness without Memory/Knowledge authority.

Produces raw shadow candidate transitions and a deliberately false bridge:
review-ready does not mean verified relatedness.
"""

import argparse
import json
from pathlib import Path
import tempfile

from anima.core.event_bus import Event
from labs.exp009.episode_link_triage import EpisodeLinkTriage
from labs.exp009.memory_encoding_e2 import run_e2, GOLD_RELATED
from labs.exp009.memory_encoding_shadow import (
    ENT_CPU_A, ENT_CPU_B, S1, S2, event_id,
)

KNOWN_ENTITIES = frozenset({ENT_CPU_A, ENT_CPU_B})


def bridge(n, text, *, session=S1, source="user", entity=ENT_CPU_A,
           timestamp=None):
    return Event(
        "conversation.user", {"text": text}, source=source,
        session_id=session,
        timestamp=timestamp or f"2026-11-12T12:0{n}:00+00:00",
        event_id=event_id(400 + n),
        references=(
            [{"kind": "entity", "id": entity}] if entity else []
        ),
    )


def _named(snapshot, decisions):
    reverse = {
        row["decision"]["episode_id"]: name
        for name, row in decisions.items()
    }
    result = {}
    for row in snapshot["candidates"]:
        names = tuple(sorted(reverse[ep] for ep in row["episode_ids"]))
        result[names] = row
    return result


def _metrics(candidates):
    truth = {tuple(sorted(pair)) for pair in GOLD_RELATED}
    ready = {
        pair for pair, row in candidates.items()
        if row["review_state"] == "review_ready"
    }
    return {
        "ready_pairs": [list(x) for x in sorted(ready)],
        "ready_true_positive_pairs": [list(x) for x in sorted(ready & truth)],
        "ready_false_positive_pairs": [list(x) for x in sorted(ready - truth)],
        "true_pairs_not_ready": [list(x) for x in sorted(truth - ready)],
        "review_ready_precision": len(ready & truth) / len(ready) if ready else None,
        "review_ready_recall": len(ready & truth) / len(truth) if truth else None,
    }


def run_e3(root, *, report_path=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    e2 = run_e2(root / "e2")
    decisions = e2["decisions"]
    book = EpisodeLinkTriage(decisions, known_entities=KNOWN_ENTITIES)
    initial = book.snapshot()

    true_bridge = bridge(3, "Copper calibration decision new hardware supply")
    after_true = book.observe(true_bridge)
    # An unrelated task can also have an apparently persuasive lexical bridge.
    # This should raise review priority, not silently create a real relation.
    false_bridge = bridge(4, "Copper calibration baseline Office inventory meeting")
    after_false = book.observe(false_bridge)
    if book.observe(false_bridge) != after_false:
        raise AssertionError("Duplicate delivery changed candidate review")
    no_entity = bridge(5, "Copper calibration decision new hardware supply", entity=None)
    after_no_entity = book.observe(no_entity)
    if after_no_entity["candidates"] != after_false["candidates"]:
        raise AssertionError("Unverified Entity-free trigger changed candidates")
    unrelated_session = bridge(
        6, "Copper calibration decision new hardware supply", session=S2,
    )
    book.observe(unrelated_session)
    old_time = bridge(
        7, "Copper calibration decision new hardware supply",
        timestamp="2026-11-12T13:07:00+00:00",
    )
    book.observe(old_time)
    final = book.snapshot()

    # Every step is independently auditable; no source or authority writes.
    report = {
        "format": "exp009.memory_encoding.e3/0.1",
        "source_snapshot_sha256": initial["source_snapshot_sha256"],
        "initial": initial,
        "after_true_bridge": after_true,
        "after_false_bridge": after_false,
        "final": final,
        "metrics_after_true": _metrics(_named(after_true, decisions)),
        "metrics_after_false": _metrics(_named(after_false, decisions)),
        "production_mutations": 0,
        "caveat": (
            "Small synthetic examples deliberately include a false bridge. "
            "review_ready is NOT a Knowledge/Memory relation, verified fact, "
            "causal claim or independent witness."
        ),
    }
    if report_path is not None:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anima-e3-") as td:
        path = args.report_dir / "memory_encoding_e3_review.json"
        report = run_e3(Path(td) / "work", report_path=path)
    for key in ("metrics_after_true", "metrics_after_false"):
        row = report[key]
        print(
            f"{key}: ready={len(row['ready_pairs'])} "
            f"precision={row['review_ready_precision']} "
            f"recall={row['review_ready_recall']}"
        )
    print("Raw report:", path)


if __name__ == "__main__":
    main()
