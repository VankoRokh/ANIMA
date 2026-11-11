"""EXP-009 E2: ambiguous episode continuation without lexical overlap.

This is a deliberate adversarial *candidate triage* test, not a production
relation writer. Gold labels are explicit and are not passed to the encoder.
"""

import argparse
import json
from pathlib import Path
import tempfile

from anima.core.event_bus import Event
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.shadow_encoding import ShadowEpisodeEncoder
from labs.exp009.memory_encoding_shadow import (
    ENT_CPU_A, ENT_CPU_B, S1, S2, event_id,
)


# (name, minute, session, text, entity) — frozen gold before model execution.
CASES = (
    ("baseline", 0, S1, "Copper calibration baseline", ENT_CPU_A),
    ("decision", 1, S1, "Decision selected new supply hardware", ENT_CPU_A),
    ("distractor", 2, S1, "Office inventory meeting", ENT_CPU_A),
    ("different_entity", 3, S1, "Copper calibration baseline", ENT_CPU_B),
    ("different_session", 4, S2, "Decision selected new supply hardware", ENT_CPU_A),
    ("time_boundary", 45, S1, "Copper calibration resumed", ENT_CPU_A),
    ("no_entity_paraphrase", 46, S1, "A technical adjustment was approved", None),
)
# A candidate's "related" label refers ONLY to episode provenance, not truth.
GOLD_RELATED = {("decision", "baseline")}


def make_event(position, row):
    _, minutes, session, text, entity_id = row
    refs = [{"kind": "entity", "id": entity_id}] if entity_id else []
    return Event(
        "conversation.user", {"text": text}, source="user",
        timestamp=f"2026-11-12T12:{minutes:02d}:00+00:00",
        session_id=session, references=refs,
        event_id=event_id(position + 200),
    )


def run_e2(root, *, report_path=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    store = MemoryStore(root / "memory.db")
    links = LinkStore(store)
    for entity_id, name in ((ENT_CPU_A, "CPU A"), (ENT_CPU_B, "CPU B")):
        links.create_entity(
            entity_type="technology", canonical_name=name,
            public_id=entity_id,
        )
    encoder = ShadowEpisodeEncoder(link_store=links)
    memory_before = store.list_memories()
    events = [make_event(i, row) for i, row in enumerate(CASES)]
    results = {}
    event_by_ep = {}
    suggested_pairs = set()

    for row, event in zip(CASES, events):
        name = row[0]
        outcome = encoder.accept(event)
        if outcome["action"] != "new_episode":
            raise AssertionError("E2 cases must remain separate episodes")
        for candidate in outcome["possible_related"]:
            parent_name = event_by_ep.get(candidate["episode_id"])
            if parent_name is None:
                raise AssertionError("Candidate has no frozen source episode")
            suggested_pairs.add((name, parent_name))
        results[name] = {
            "event_id": event.event_id, "raw": event.to_dict(),
            "decision": outcome,
        }
        event_by_ep[outcome["episode_id"]] = name

    if store.list_memories() != memory_before:
        raise AssertionError("Shadow mutated authoritative MemoryStore")
    if len(encoder.episodes()) != len(events):
        raise AssertionError("Shadow inadvertently merged E2 episodes")

    hits = sorted(GOLD_RELATED & suggested_pairs)
    false_candidates = sorted(suggested_pairs - GOLD_RELATED)
    missed = sorted(GOLD_RELATED - suggested_pairs)
    report = {
        "type": "exp009.shadow-encoding.e2/0.1",
        "cases": [row[0] for row in CASES],
        "gold_related": [list(p) for p in sorted(GOLD_RELATED)],
        "suggested_pairs": [list(p) for p in sorted(suggested_pairs)],
        "hits": [list(p) for p in hits],
        "false_candidates": [list(p) for p in false_candidates],
        "missed": [list(p) for p in missed],
        "candidate_precision": (
            len(hits) / len(suggested_pairs) if suggested_pairs else None
        ),
        "candidate_recall": len(hits) / len(GOLD_RELATED),
        "decisions": results, "episode_count": len(encoder.episodes()),
        "memory_unchanged": True,
        "constraint": (
            "All related candidates are unverified. Candidate membership "
            "does not create evidence, links, Knowledge or an episode merge."
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
    with tempfile.TemporaryDirectory(prefix="anima-e2-") as td:
        report_file = args.report_dir / "memory_encoding_e2_candidates.json"
        result = run_e2(Path(td) / "work", report_path=report_file)
    print(
        "E2: candidates=%s hits=%s false=%s missed=%s precision=%s recall=%s"
        % (
            len(result["suggested_pairs"]), len(result["hits"]),
            len(result["false_candidates"]), len(result["missed"]),
            result["candidate_precision"], result["candidate_recall"],
        )
    )
    print("Raw report:", report_file)


if __name__ == "__main__":
    main()
