"""ANIMA v0.1 Integrated — opt-in M0 Core→Memory→Retrieval→FAST read gate.

No production code changes, LLM calls, external effects, E4 alias authority or
automatic Knowledge writes. The driver launches seed and verify in distinct
Python interpreters over one temporary directory. Synthetic facts are reports,
not verified facts about the world.
"""
import argparse
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from anima.cognition.fast import FastCognition, FastResult
from anima.core.assembly import build_core
from anima.memory.context_builder import ContextBuilder
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine

SCHEMA = "anima.memory_v1.integrated_read_m0/0.1"
MARKER_EARLY = "oldheatstamp"
MARKER_LATE = "newcoolstamp"
EARLY_REPORT = (
    "Unit ambercoil thermal report: earlier reading exactly 82 C; "
    "source marker oldheatstamp."
)
LATE_REPORT = (
    "Unit ambercoil thermal report: later reading exactly 69 C; "
    "source marker newcoolstamp."
)
QUERY = "What does the memory say about unit ambercoil temperature?"
ABSENT = "zzpocketquartzabsent"
MANIFEST = "m0_fixture_manifest.json"


class _ReadOnlyProbeBackend:
    def __init__(self):
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return FastResult(response_text="M0 probe completed; no factual answer generated.")


def _sync_to_end(index):
    for _ in range(32):
        result = index.sync(max_events=32)
        if result["status"] == "complete":
            return result
    raise AssertionError("Event index failed to converge within fixed sync budget")


def _source_mapping(core, event_ids):
    refs = {event_id: [] for event_id in event_ids}
    for memory in core.memory_store.list_memories():
        sources = core.memory_store.source_events(memory["id"])
        for event_id in event_ids:
            if event_id in sources:
                refs[event_id].append(memory["id"])
    for event_id, selected in refs.items():
        if not selected:
            raise AssertionError(f"Raw report has no persisted Memory link: {event_id}")
    return {eid: sorted(ids) for eid, ids in refs.items()}


def _require_partial(index):
    assert index.status()["status"] == "partial", index.status()
    try:
        index.search(ABSENT)
    except RuntimeError as exc:
        assert "partial" in str(exc), str(exc)
    else:
        raise AssertionError("Partial source index silently claimed no matching Events")


def _knowledge_count(core):
    with sqlite3.connect(core.memory_store.database_file) as connection:
        return connection.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]


def seed(root):
    root.mkdir(parents=True, exist_ok=True)
    if (root / MANIFEST).exists():
        raise FileExistsError("Seed manifest already exists; use a fresh directory")
    core = build_core(root, enable_event_retrieval=True)
    assert core.core_execution is None and core.core_autonomy is None
    core.runtime.wake()
    early = core.runtime.user_input(EARLY_REPORT)
    late = core.runtime.user_input(LATE_REPORT)
    assert len(early) == len(late) == 1
    first, second = early[0], late[0]
    assert first.event_id != second.event_id
    assert first.event_type == second.event_type == "conversation.user"

    source_map = _source_mapping(core, [first.event_id, second.event_id])
    assert core.memory_store.count() >= 1
    assert _knowledge_count(core) == 0
    core.runtime.sleep()
    _require_partial(core.event_retrieval)
    indexed = _sync_to_end(core.event_retrieval)
    assert indexed["indexed_events"] >= 4  # wake, two reports, sleep
    assert core.event_retrieval.get(first.event_id)["payload"]["text"] == EARLY_REPORT
    assert core.event_retrieval.get(second.event_id)["payload"]["text"] == LATE_REPORT
    manifest = {
        "schema": SCHEMA,
        "early_id": first.event_id,
        "late_id": second.event_id,
        "source_memories": source_map,
        "seed_indexed_events": indexed["indexed_events"],
    }
    with (root / MANIFEST).open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    return {
        "phase": "seed", "status": "M0_SEED_PASS",
        "source_event_count": 2,
        "memory_count": core.memory_store.count(),
        "index_status": indexed["status"],
        "source_memories": source_map,
        "knowledge_count": 0,
    }


def verify(root):
    with (root / MANIFEST).open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    assert manifest["schema"] == SCHEMA
    first, second = manifest["early_id"], manifest["late_id"]
    assert first != second

    # A genuinely new interpreter reassembles Core on the same persistent store.
    core = build_core(root, enable_event_retrieval=True)
    assert core.core_decision is None and core.core_execution is None
    assert core.core_autonomy is None
    core.runtime.wake()
    _require_partial(core.event_retrieval)
    _sync_to_end(core.event_retrieval)
    assert core.event_retrieval.get(first)["payload"]["text"] == EARLY_REPORT
    assert core.event_retrieval.get(second)["payload"]["text"] == LATE_REPORT

    for event_id, unique_word in ((first, MARKER_EARLY), (second, MARKER_LATE)):
        hits = core.event_retrieval.search(unique_word, top_k=4)
        assert hits["coverage"]["status"] == "complete"
        assert [hit["id"] for hit in hits["results"]] == [event_id]
        assert hits["results"][0]["provenance"]["raw_sha256"]

    source_map = _source_mapping(core, [first, second])
    assert source_map == manifest["source_memories"], "Source links changed after restart"

    provenance = ProvenanceResolver(
        core.memory_store, core.link_store, core.event_log,
        event_retrieval=core.event_retrieval,
    )
    for event_id, memory_ids in source_map.items():
        for memory_id in memory_ids:
            proof = provenance.memory(memory_id)
            assert event_id in {item["id"] for item in proof["events"]}
            assert {row["id"] for row in proof["events"]} == set(
                core.memory_store.source_events(memory_id))

    retrieval = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store)
    context_builder = ContextBuilder(retrieval=retrieval, provenance=provenance)
    backend = _ReadOnlyProbeBackend()
    fast = FastCognition(context_builder=context_builder, backend=backend)

    # A real second-run Runtime user Event is fed into the existing FAST bridge.
    query_events = core.runtime.user_input(QUERY)
    assert len(query_events) == 1
    turn = fast.process(query_events[0])
    assert len(backend.requests) == 1
    bundle = turn.request.context_bundle
    assert bundle["consumer"] == "FAST"
    assert bundle["budget"] == {"max_items": 6, "max_chars": 1200}
    assert bundle["events"] == []  # FAST policy: source IDs remain resolvable
    assert bundle["knowledge"] == []
    assert 0 < len(bundle["memories"]) <= 6
    assert bundle["selection_stats"]["items_used"] <= 6
    assert bundle["selection_stats"]["chars_used"] <= 1200
    selected = {row["record"]["id"] for row in bundle["memories"]}
    originally_linked = set(source_map[first]) | set(source_map[second])
    assert selected & originally_linked
    assert turn.request.input_event_id == query_events[0].event_id

    # The query itself generated a raw Event, so coverage must change to partial.
    _require_partial(core.event_retrieval)
    indexed = _sync_to_end(core.event_retrieval)
    assert indexed["status"] == "complete"
    absence = core.event_retrieval.search(ABSENT)
    assert absence["results"] == []
    empty_memory = retrieval.retrieve(ABSENT, kinds=("memory",), relation_hops=0)
    assert empty_memory["results"] == []
    assert _knowledge_count(core) == 0

    # Replay/recovery must not invent duplicate raw events or Memory sources.
    before = {m["id"]: core.memory_store.source_events(m["id"])
              for m in core.memory_store.list_memories()}
    total_memories = core.memory_store.count()
    core.event_processing.recover()
    assert core.memory_store.count() == total_memories
    assert before == {m["id"]: core.memory_store.source_events(m["id"])
                      for m in core.memory_store.list_memories()}
    assert core.event_retrieval.sync()["indexed_now"] == 0
    assert core.event_retrieval.get(first)["payload"]["text"] == EARLY_REPORT

    return {
        "phase": "verify", "status": "M0_INTEGRATED_READ_PASS",
        "schema": SCHEMA,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "raw_event_count": len(core.event_log.load_events()),
        "memory_count": total_memories,
        "knowledge_count": _knowledge_count(core),
        "raw_source_ids": [first, second],
        "source_memories": source_map,
        "fast_selected_memories": sorted(selected),
        "fast_items": bundle["selection_stats"]["items_used"],
        "fast_chars": bundle["selection_stats"]["chars_used"],
        "index_status": indexed["status"],
        "absent_marker_results": len(absence["results"]),
        "independent_process_reopen": True,
        "real_sigkill_tested": False,
        "llm_used": False,
        "actions_executed": False,
        "production_code_changed": False,
    }


def _worker(phase, root):
    command = [
        sys.executable, "-m", "scripts.run_memory_v1_integrated_read_gate",
        "--internal-phase", phase, "--root", str(root),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise AssertionError(
            f"M0 {phase} child failed ({proc.returncode}): "
            f"stdout={proc.stdout[-3000:]!r}; stderr={proc.stderr[-5000:]!r}"
        )
    return json.loads(proc.stdout)


def run_gate():
    """Public driver: two child interpreters, one ephemeral filesystem."""
    with tempfile.TemporaryDirectory(prefix="anima-m0-integrated-") as folder:
        root = Path(folder)
        seeded = _worker("seed", root)
        verified = _worker("verify", root)
        assert seeded["status"] == "M0_SEED_PASS"
        assert verified["status"] == "M0_INTEGRATED_READ_PASS"
        assert seeded["source_memories"] == verified["source_memories"]
        return verified


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-phase", choices=("seed", "verify"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.internal_phase:
        if args.root is None or args.report is not None:
            parser.error("--internal-phase requires --root, without --report")
        result = seed(args.root) if args.internal_phase == "seed" else verify(args.root)
    else:
        if args.root is not None:
            parser.error("--root is only available for internal test phases")
        result = run_gate()
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as stream:
            stream.write(output)
    print(output, end="")


if __name__ == "__main__":
    main()
