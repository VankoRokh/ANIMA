"""E4 Level-0 read-only Shadow observation on frozen synthetic fixtures.

This is NOT an E4 conformance runner. Only existing ShadowEpisodeEncoder
behaviour is executed. Gold files are never opened. All control actions and
non-entity setup preconditions are reported unsupported, never simulated.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from anima.core.event_bus import Event
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.shadow_encoding import ShadowEpisodeEncoder

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "docs" / "TESTING" / "Fixtures"
FROZEN = "memory_e4_frozen_manifest_v0.json"
INPUT_FILES = {
    "positive": "memory_e4_inputs_v0.json",
    "negative": "memory_e4_negative_inputs_v0.json",
}
TRACE_SCHEMA = "anima.e4.shadow_observation_l0/0.1"


def _blob_sha(data):
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def _load_frozen_inputs(suite):
    if suite not in INPUT_FILES:
        raise ValueError("Unknown E4 suite")
    name = INPUT_FILES[suite]
    raw = (FIX / name).read_bytes()
    manifest = json.loads((FIX / FROZEN).read_text(encoding="utf-8"))
    if manifest["status"] != "FROZEN_DESIGN_BASELINE_V0":
        raise ValueError("E4 frozen manifest is not active")
    pinned = manifest["pinned_files"][f"docs/TESTING/Fixtures/{name}"]
    if len(raw) != pinned["bytes"] or _blob_sha(raw) != pinned["git_blob_sha1"]:
        raise ValueError("E4 frozen input checksum mismatch")
    dataset = json.loads(raw)
    if suite == "positive" and dataset["status"] != "FROZEN_DESIGN_INPUTS_V0":
        raise ValueError("Unexpected E4 positive fixture state")
    if suite == "negative" and dataset["status"] != "FROZEN_DEV_NEGATIVES_NOT_HOLDOUT":
        raise ValueError("Unexpected E4 negative fixture state")
    return dataset


def _make_event(raw):
    Event.validate_record(raw)
    return Event(
        raw["type"], raw["payload"], source=raw["source"],
        session_id=raw["session_id"], references=raw["references"],
        event_id=raw["id"], timestamp=raw["timestamp"],
    )


def run_case(case, *, entity_registry):
    """Observe one case in an isolated temporary SQLite lab store."""
    with tempfile.TemporaryDirectory(prefix="anima-e4-l0-") as directory:
        store = MemoryStore(Path(directory) / "memory.db")
        links = LinkStore(store)
        for name, entity_id in sorted(entity_registry.items()):
            links.create_entity(
                entity_type="object",
                canonical_name="fixture_" + name,
                public_id=entity_id,
            )
        encoder = ShadowEpisodeEncoder(link_store=links)
        before = store.list_memories()
        trace = []
        for entry in case["events"]:
            raw = entry["raw"]
            decision = encoder.accept(_make_event(raw))
            trace.append({
                "event_key": entry["key"],
                "event_id": raw["id"],
                "event_type": raw["type"],
                "source": raw["source"],
                "decision": decision,
            })
        after = store.list_memories()
        if before != after:
            raise RuntimeError("E4 L0 mutated authoritative MemoryStore")
        return {
            "case_id": case["id"],
            "track": case["track"],
            "observation_level": "L0_SHADOW_ONLY",
            "decisions": trace,
            "episodes": encoder.episodes(),
            "event_assignments": encoder.event_assignments(),
            "memory_store_unchanged": True,
            "ignored_setup_keys": sorted(case["setup"]),
            "unsupported_controls": [
                {"at": item["at"], "kind": item["kind"],
                 "reason": "not_supported_by_L0_shadow"}
                for item in case["controls"]
            ],
            "unsupported_capabilities": [
                "Story", "EntityResolution_learning",
                "UncertaintyRegistry", "GoalTask_research",
                "PeriodicScheduler", "CrashRecovery", "SLEEP_publication",
            ],
            "semantic_conformance": "NOT_ASSESSED",
        }


def run_suite(*, suite="positive", case_id=None):
    """Load frozen input only. No scoring, gold opening or control execution."""
    dataset = _load_frozen_inputs(suite)
    cases = dataset["cases"]
    if case_id is not None:
        cases = [case for case in cases if case["id"] == case_id]
        if not cases:
            raise ValueError("Unknown E4 case ID: " + case_id)
    return {
        "schema": TRACE_SCHEMA,
        "suite": suite,
        "status": "OBSERVATION_ONLY_NOT_CONFORMANCE",
        "cases": [run_case(case, entity_registry=dataset["entities"])
                  for case in cases],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=tuple(INPUT_FILES), default="positive")
    parser.add_argument("--case", dest="case_id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_suite(suite=args.suite, case_id=args.case_id)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)


if __name__ == "__main__":
    main()
