"""EXP-009 C3: reproducible bounded EventRetrieval workload, not Core QA.

Usage: python -m labs.exp009.event_retrieval_c3 --events 10000 --report-dir /tmp/run
The measured workload is EventLog append + EventRetrieval index, get and FTS.
It does not model MemoryProcessor, Cognition or Raspberry Pi hardware.
"""

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import resource
import sqlite3
import tempfile
from time import perf_counter
from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_retrieval import EventRetrieval


STAMP = "2026-11-11T12:00:00+00:00"


def _event_id(i):
    # UUIDv4 with deterministic values; separate from real Core identities.
    value = UUID(int=(4 << 76) | (2 << 62) | (i + 1))
    return "ev_" + str(value)


def _p(samples, proportion):
    ordered = sorted(samples)
    if not ordered:
        return None
    return round(ordered[min(len(ordered) - 1,
                             math.ceil(len(ordered) * proportion) - 1)], 4)


def _stats(samples):
    return {
        "samples": len(samples), "p50_ms": _p(samples, 0.5),
        "p95_ms": _p(samples, 0.95), "p99_ms": _p(samples, 0.99),
        "max_ms": _p(samples, 1.0),
    }


def run_c3(root, *, events=1000, probe_count=100):
    if type(events) is not int or not 1 <= events <= 100_000:
        raise ValueError("Events count must be in 1..100000")
    if type(probe_count) is not int or not 1 <= probe_count <= 1000:
        raise ValueError("Probe count must be in 1..1000")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    log = EventLog(root / "events.jsonl")
    index = EventRetrieval(log, root / "event_index.db")
    started = perf_counter()
    for i in range(events):
        # Repeated terms and unrelated noise exercise ranking; unique case ID
        # is gold for the exact lexical Event discovery workload.
        category = ("thermal", "network", "door", "maintenance")[i % 4]
        text = f"case{i:06d} {category} telemetry sensor reading {i % 100}"
        log.write(Event(
            "conversation.user", {"text": text},
            source="synthetic.exp009.c3", timestamp=STAMP,
            event_id=_event_id(i),
        ))
    append_seconds = perf_counter() - started

    lag_samples = []
    sync_samples = []
    indexed = 0
    started = perf_counter()
    for _ in range(math.ceil(events / 500) + 2):
        t0 = perf_counter()
        turn = index.sync(max_events=500, max_bytes=2_000_000)
        sync_samples.append((perf_counter() - t0) * 1000)
        indexed += turn["indexed_now"]
        lag_samples.append(turn["pending_bytes"])
        if turn["status"] == "complete":
            break
        if not turn["indexed_now"]:
            raise AssertionError("Index stalled before complete EventLog")
    index_seconds = perf_counter() - started
    if indexed != events or turn["indexed_events"] != events:
        raise AssertionError("Event index missed source rows")

    # Cold object reconstruction, direct ID read, and common lexical lookups
    # are measured separately. No full EventLog scan is used for search.
    reopened = EventRetrieval(log, root / "event_index.db")
    count = min(events, probe_count)
    selected = [round(i * (events - 1) / max(1, count - 1))
                for i in range(count)]
    get_ms, fts_ms = [], []
    for i in selected:
        t0 = perf_counter()
        result = reopened.get(_event_id(i))
        get_ms.append((perf_counter() - t0) * 1000)
        if result["id"] != _event_id(i):
            raise AssertionError("Direct lookup ID mismatch")
        t0 = perf_counter()
        found = reopened.search(f"case{i:06d}", top_k=3)
        fts_ms.append((perf_counter() - t0) * 1000)
        if not any(item["id"] == _event_id(i) for item in found["results"]):
            raise AssertionError("Exact lexical query missed indexed Event")

    # As-of append and bounded catch-up should not rebuild whole history.
    late = Event(
        "conversation.user", {"text": f"latecase{events:06d} thermal"},
        source="synthetic.exp009.c3", timestamp=STAMP,
        event_id=_event_id(events),
    )
    log.write(late)
    before_late = reopened.status()
    t0 = perf_counter()
    delta = reopened.sync(max_events=1)
    delta_ms = (perf_counter() - t0) * 1000
    if before_late["status"] != "partial" or (
        delta["indexed_now"] != 1 or delta["status"] != "complete"
    ):
        raise AssertionError("Late Event append did not catch up")
    if reopened.get(late.event_id)["id"] != late.event_id:
        raise AssertionError("Late indexed Event is not accessible")

    db_bytes = (root / "event_index.db").stat().st_size
    source_bytes = log.log_file.stat().st_size
    return {
        "type": "exp009.c3.event_retrieval/0.1",
        "workload": "isolated EventLog append + EventRetrieval",
        "events": events, "indexed_after_late": events + 1,
        "source_sha256": sha256(log.log_file.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "append_seconds": round(append_seconds, 4),
        "initial_index_seconds": round(index_seconds, 4),
        "index_batches": len(sync_samples),
        "sync_batch": _stats(sync_samples),
        "max_pending_bytes": max(lag_samples),
        "get": _stats(get_ms),
        "fts_exact": _stats(fts_ms),
        "late_sync_ms": round(delta_ms, 4),
        "source_bytes": source_bytes, "index_bytes": db_bytes,
        "maxrss_kb_process": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "caveat": (
            "CI PC baseline only; synthetic text, no MemoryProcessor/LLM, "
            "no fsync/power-loss guarantee. ru_maxrss is process peak, "
            "not incremental EventRetrieval allocation."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, choices=(1000, 10000, 100000),
                        default=1000)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--probes", type=int, default=100)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anima-exp009-c3-") as folder:
        result = run_c3(Path(folder) / "work", events=args.events,
                        probe_count=args.probes)
    path = args.report_dir / f"event_retrieval_c3_{args.events}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    print(
        f"C3: events={args.events} append={result['append_seconds']}s "
        f"index={result['initial_index_seconds']}s "
        f"get_p95={result['get']['p95_ms']}ms "
        f"fts_p95={result['fts_exact']['p95_ms']}ms "
        f"rss_kb={result['maxrss_kb_process']} report={path}"
    )


if __name__ == "__main__":
    main()
