"""ANIMA v0.2 H5.3: reproducible, isolated endurance measurement.

Runs only in tempfile.TemporaryDirectory; NEVER opens real ANIMA instances.
Each scenario is a fresh worker process so OS peak RSS is not polluted by
previous scenarios. Timing metrics are measured, not pass/fail SLOs.

Usage from repository root:
    PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_performance \
      --events 160 640 --output /tmp/anima-h5-performance.json

A separate existing benchmark measures H1.3 1k/10k/50k prefix verification:
    PYTHONPATH="$PWD" .venv/bin/python \
      tests/bench_v02_h1_3_index_prefix.py --events 1000 10000 50000

This is a deterministic synthetic workload, NOT representative production
traffic and NOT an assessment of semantic association accuracy or power-loss
durability. Run with a clean Git snapshot and disclose hardware/storage.
"""

import argparse
import json
import math
import os
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter_ns
from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.event_retrieval import EventRetrieval
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


SCHEMA = "anima.v02.h5.performance/0.1"
ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-11-17T12:00:00+00:00"
QUERY = "h53perf"
QUERY_SAMPLES = 5


def percentile_nearest_rank(samples, percentile):
    """Nearest-rank percentile; no interpolation and no hidden smoothing."""
    if not samples:
        raise ValueError("At least one sample required")
    if not 0 < percentile <= 100:
        raise ValueError("Percentile must be in (0, 100]")
    ordered = sorted(samples)
    index = math.ceil(percentile * len(ordered) / 100) - 1
    return ordered[index]


def latency_summary(samples_ns):
    """Return milliseconds; p95 is nearest-rank (one slow sample matters)."""
    if not samples_ns:
        raise ValueError("No latency samples")
    ms = [x / 1_000_000 for x in samples_ns]
    return {
        "samples": len(ms),
        "p50_ms": round(median(ms), 4),
        "p95_ms": round(percentile_nearest_rank(ms, 95), 4),
        "max_ms": round(max(ms), 4),
    }


def _event(number):
    return Event(
        "conversation.user",
        {
            "text": (
                f"{QUERY} sensor batch{number % 8} "
                f"reading{number:06d} calibration status verified "
                "on synthetic rig"
            )
        },
        source="user",
        session_id="session_00000001",
        event_id="ev_" + str(UUID(int=(4 << 76) | (2 << 62) | number)),
        timestamp=STAMP,
    )


def _stack(root):
    store = MemoryStore(root / "memory.db")
    raw = EventLog(root / "events.jsonl")
    links = LinkStore(store)
    coordinator = EventProcessingCoordinator(
        memory_store=store,
        memory_processor=MemoryProcessor(
            memory_store=store, event_log=raw, link_store=links,
        ),
        event_log=raw,
    )
    return store, raw, links, coordinator


def _timed(fn):
    began = perf_counter_ns()
    value = fn()
    return perf_counter_ns() - began, value


def _query_latency(fn, *, minimum_results=1):
    elapsed = []
    # Warm up each read path; do not report first-call cold timings as steady.
    fn()
    for _ in range(QUERY_SAMPLES):
        interval, response = _timed(fn)
        if len(response["results"]) < minimum_results:
            raise RuntimeError("Synthetic query returned insufficient evidence")
        elapsed.append(interval)
    return latency_summary(elapsed)


def _peak_rss_mib():
    """Per-worker OS maximum RSS; Linux ru_maxrss uses KiB."""
    if sys.platform != "linux":
        return None
    import resource

    return round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        3,
    )


def run_case(event_count):
    """Execute synthetic end-to-end memory flow in one disposable directory."""
    if type(event_count) is not int or not 8 <= event_count <= 5000:
        raise ValueError("event_count must be in 8..5000")

    with TemporaryDirectory(prefix="anima-h53-perf-") as tmp:
        root = Path(tmp)
        store, raw, links, coordinator = _stack(root)
        append_ns = []
        process_ns = []
        actions = {}
        total_start = perf_counter_ns()

        for number in range(1, event_count + 1):
            ev = _event(number)
            append_elapsed, _ = _timed(lambda: raw.write(ev))
            process_elapsed, result = _timed(
                lambda: coordinator.process(ev)
            )
            append_ns.append(append_elapsed)
            process_ns.append(process_elapsed)
            action = result["action"]
            actions[action] = actions.get(action, 0) + 1
            if action not in {"create", "create_related", "update"}:
                raise RuntimeError(f"Unexpected ingested action: {action}")
        ingest_ns = perf_counter_ns() - total_start

        if coordinator.finalized_count() != event_count:
            raise RuntimeError("Processing ledger count does not match Raw")
        if len(raw.load_events()) != event_count:
            raise RuntimeError("Raw EventLog count mismatch")
        with store.transaction() as conn:
            source_count = conn.execute(
                "SELECT COUNT(*) FROM memory_sources"
            ).fetchone()[0]
        if source_count != event_count:
            raise RuntimeError("Not all synthetic Events have Memory provenance")

        reopen_ns, (reopened_store, reopened_raw, reopened_links, reopened) = (
            _timed(lambda: _stack(root))
        )
        first_recovery_ns, first_recovery = _timed(reopened.recover)
        second_recovery_ns, second_recovery = _timed(reopened.recover)
        if (
            first_recovery["retried"]
            or first_recovery["adopted"]
            or second_recovery["retried"]
            or second_recovery["adopted"]
            or second_recovery["finalized"] != event_count
        ):
            raise RuntimeError("Reopen/recovery was not idempotent")

        init_index_ns, index = _timed(
            lambda: EventRetrieval(
                reopened_raw,
                root / "event_index.db",
                memory_store=reopened_store,
            )
        )
        build_index_ns, index_status = _timed(
            lambda: index.sync(
                max_events=100_000, max_bytes=100_000_000,
            )
        )
        if (
            index_status["status"] != "complete"
            or index_status["indexed_events"] != event_count
        ):
            raise RuntimeError("Derived Event index did not converge")
        indexed_repeat_ns, repeat = _timed(index.sync)
        if repeat["indexed_now"] != 0 or repeat["status"] != "complete":
            raise RuntimeError("Unchanged Event index unexpectedly advanced")

        retrieval = RetrievalEngine(
            memory_store=reopened_store,
            link_store=reopened_links,
        )
        context = ContextBuilder(
            retrieval=retrieval,
            provenance=ProvenanceResolver(
                reopened_store, reopened_links, reopened_raw,
                event_retrieval=index,
            ),
        )

        event_search = _query_latency(
            lambda: index.search(QUERY, top_k=5)
        )
        memory_search = _query_latency(
            lambda: retrieval.retrieve(
                QUERY, kinds=("memory",),
                relation_hops=0, top_k=5,
            )
        )
        def build_context():
            return context.build(
                QUERY, consumer="FAST",
                max_items=4, max_chars=900,
                retrieval_options={"kinds": ("memory",)},
            )

        # Context bundles do not share the top-level "results" shape.
        context_ns = []
        for _ in range(QUERY_SAMPLES):
            elapsed, bundle = _timed(build_context)
            if not isinstance(bundle, dict):
                raise RuntimeError("ContextBuilder returned no bundle")
            context_ns.append(elapsed)

        quartile = max(1, event_count // 4)
        start_median = median(process_ns[:quartile])
        end_median = median(process_ns[-quartile:])
        delta_ratio = end_median / max(start_median, 1)
        files = {
            name: (root / name).stat().st_size
            for name in ("events.jsonl", "memory.db", "event_index.db")
        }

        return {
            "schema": SCHEMA,
            "event_count": event_count,
            "memory_count": reopened_store.count(),
            "source_links": source_count,
            "processing_actions": actions,
            "processing_finalized": coordinator.finalized_count(),
            "ingest_wall_s": round(ingest_ns / 1e9, 4),
            "throughput_events_s": round(event_count / (ingest_ns / 1e9), 3),
            "append": latency_summary(append_ns),
            "process": latency_summary(process_ns),
            "process_early_quartile_p50_ms": round(
                start_median / 1e6, 4
            ),
            "process_late_quartile_p50_ms": round(
                end_median / 1e6, 4
            ),
            "process_late_over_early_p50_ratio": round(
                delta_ratio, 4
            ),
            "reopen_ms": round(reopen_ns / 1e6, 4),
            "recovery_first_ms": round(first_recovery_ns / 1e6, 4),
            "recovery_repeat_ms": round(second_recovery_ns / 1e6, 4),
            "index_initialize_ms": round(init_index_ns / 1e6, 4),
            "index_initial_sync_ms": round(build_index_ns / 1e6, 4),
            "index_unchanged_sync_ms": round(indexed_repeat_ns / 1e6, 4),
            "event_search": event_search,
            "memory_search": memory_search,
            "context_build": latency_summary(context_ns),
            "storage_bytes": files,
            "peak_rss_mib": _peak_rss_mib(),
            "memory_note": (
                "ru_maxrss is whole isolated worker-process peak on Linux, "
                "not the instantaneous memory used only by ANIMA objects"
            ),
        }


def _run_worker(event_count, timeout):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    cmd = [
        sys.executable, "-B", "-m", "labs.v02_h5_performance",
        "--worker-events", str(event_count),
    ]
    result = subprocess.run(
        cmd, cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Benchmark worker {event_count} failed with "
            f"exit={result.returncode}: {result.stderr[-2500:]}"
        )
    try:
        record = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Benchmark worker did not return JSON") from error
    if record["event_count"] != event_count:
        raise RuntimeError("Worker returned wrong event count")
    return record


def _git_snapshot():
    def git(*args):
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True,
            text=True, timeout=10, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "dirty": git("status", "--porcelain") not in {"", None},
    }


def build_report(event_counts, *, timeout=900):
    if not event_counts or any(
        type(size) is not int or not 8 <= size <= 5000
        for size in event_counts
    ):
        raise ValueError("Event counts must be integers in 8..5000")
    if len(set(event_counts)) != len(event_counts):
        raise ValueError("Event counts must be distinct")
    if not 1 <= timeout <= 3600:
        raise ValueError("Timeout must be 1..3600 seconds")
    results = [_run_worker(count, timeout) for count in event_counts]
    by_count = sorted(results, key=lambda result: result["event_count"])
    growth = []
    for smaller, larger in zip(by_count, by_count[1:]):
        growth.append({
            "from_events": smaller["event_count"],
            "to_events": larger["event_count"],
            "size_ratio": round(
                larger["event_count"] / smaller["event_count"], 4
            ),
            "process_p95_ratio": round(
                larger["process"]["p95_ms"]
                / max(smaller["process"]["p95_ms"], 1e-9),
                4,
            ),
            "recovery_first_ratio": round(
                larger["recovery_first_ms"]
                / max(smaller["recovery_first_ms"], 1e-9),
                4,
            ),
        })
    return {
        "schema": SCHEMA,
        "measurement_status": "MEASURED_NO_RELEASE_SLO",
        "git": _git_snapshot(),
        "environment": {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "system": platform.system(),
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
        },
        "workload": {
            "synthetic": True,
            "query": QUERY,
            "query_repetitions": QUERY_SAMPLES,
            "ingest_mode": "Raw append then EventProcessingCoordinator.process",
            "storage": "fresh isolated temporary directory per event_count",
        },
        "scenarios": results,
        "growth": growth,
        "limits": [
            "No release latency thresholds have been approved or asserted.",
            "One timed synthetic run per event_count: measure again for variance.",
            "The 160/640 cases are not the 1k/10k/50k H1.3 verification probe.",
            "Process crash durability, real power loss, and semantic accuracy "
            "are NOT measured.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events", type=int, nargs="+", default=[160, 640],
        help="Per-worker synthetic Raw Event counts; default: 160 640",
    )
    parser.add_argument(
        "--timeout", type=int, default=900,
        help="Per-scenario worker timeout in seconds",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Write JSON to a new path (refuses to overwrite an existing file)",
    )
    parser.add_argument(
        "--worker-events", type=int, default=None, help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.worker_events is not None:
        print(json.dumps(run_case(args.worker_events), sort_keys=True))
        return 0
    try:
        report = build_report(args.events, timeout=args.timeout)
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.error(str(error))
    payload = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            file.write(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
