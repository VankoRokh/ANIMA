"""H5.3b: isolate Raw scan / association cost on single vs grouped histories.

Read-only against ANIMA sources, writes only to disposable TemporaryDirectory.
No production algorithm changes. Every profile/repetition runs in its own
Python process and fresh instance; reported p95 uses nearest-rank as H5.3.

Usage:
    PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_scaling_diagnostics \
      --events 160 640 --streams 1 8 --repeats 3 \
      --output /tmp/anima-h53b-diagnostic.json

A stream is a synthetic anchored subject, not an authoritative Entity ID.
Grouping by explicit text anchors is a workload construction method, not
evidence of semantic identity or the real-world distribution of memory.
"""

import argparse
import json
import os
import platform
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter_ns
from uuid import UUID

from anima.core.event_bus import Event
from labs.v02_h5_performance import (
    ROOT, STAMP, _stack, latency_summary,
)

SCHEMA = "anima.v02.h5.scaling/0.1"
QUERY = "h53perf"
MAX_EVENTS = 5000


def synthetic_event(number, streams):
    """One predictable subject per group; all stream IDs are text-only."""
    if type(number) is not int or number < 1:
        raise ValueError("Event number must be positive")
    if type(streams) is not int or streams < 1:
        raise ValueError("streams must be positive")
    group = (number - 1) % streams
    # Single-stream mode is text-compatible with the first H5.3 probe.
    if streams == 1:
        text = (
            f"h53perf sensor batch{number % 8} "
            f"reading{number:06d} calibration status verified "
            "on synthetic rig"
        )
    else:
        text = (
            f"h53group{group:02d}: h53perf sensor calibration "
            f"status verified reading{number:06d} synthetic rig"
        )
    return Event(
        "conversation.user", {"text": text},
        source="user", session_id="session_00000001",
        event_id="ev_" + str(UUID(int=(4 << 76) | (2 << 62) | number)),
        timestamp=STAMP,
    )


def measure_case(count, streams):
    if type(count) is not int or not 8 <= count <= MAX_EVENTS:
        raise ValueError("count must be in 8..5000")
    if type(streams) is not int or not 1 <= streams <= min(count, 64):
        raise ValueError("streams must be in 1..min(count, 64)")

    with TemporaryDirectory(prefix="anima-h53b-") as temp:
        root = Path(temp)
        store, raw, _links, coordinator = _stack(root)
        processor = coordinator.memory_processor
        group_memories = defaultdict(set)
        memory_groups = defaultdict(set)

        measurements = defaultdict(list)
        raw_scan_count = 0
        original_load = raw.load_events
        original_guard = coordinator._require_raw_event
        original_best = processor._best_candidate

        def instrument_load_events():
            nonlocal raw_scan_count
            started = perf_counter_ns()
            try:
                return original_load()
            finally:
                raw_scan_count += 1
                measurements["raw_scan"].append(perf_counter_ns() - started)

        def instrument_guard(event):
            started = perf_counter_ns()
            try:
                return original_guard(event)
            finally:
                measurements["raw_guard"].append(perf_counter_ns() - started)

        def instrument_best(event, text, entity_ids):
            started = perf_counter_ns()
            try:
                return original_best(event, text, entity_ids)
            finally:
                measurements["association"].append(
                    perf_counter_ns() - started
                )

        raw.load_events = instrument_load_events
        coordinator._require_raw_event = instrument_guard
        processor._best_candidate = instrument_best

        began = perf_counter_ns()
        actions = defaultdict(int)
        for number in range(1, count + 1):
            ev = synthetic_event(number, streams)
            group = (number - 1) % streams
            raw.write(ev)
            before_scans = raw_scan_count
            started = perf_counter_ns()
            result = coordinator.process(ev)
            measurements["process"].append(perf_counter_ns() - started)
            measurements["scans_per_event"].append(
                raw_scan_count - before_scans
            )
            memory_id = result["memory_id"]
            if result["action"] not in {"create", "create_related", "update"}:
                raise RuntimeError(f"Unexpected action: {result['action']}")
            actions[result["action"]] += 1
            group_memories[group].add(memory_id)
            memory_groups[memory_id].add(group)
        elapsed_s = (perf_counter_ns() - began) / 1e9

        # The observer's integrity check never uses its untrusted grouping
        # labels to modify production data. It detects false merging only
        # on this synthetic corpus with uniquely anchored subjects.
        cross_group_memories = sorted(
            memory_id for memory_id, groups in memory_groups.items()
            if len(groups) > 1
        )
        fragments = sum(len(ids) - 1 for ids in group_memories.values())
        if coordinator.finalized_count() != count:
            raise RuntimeError("Finalized ledger count mismatch")

        # Avoid instrumenting recovery itself: first/repeated recovery should
        # be timed independently from the per-event instrumentation.
        store2, raw2, _links2, restarted = _stack(root)
        recover_started = perf_counter_ns()
        recovery = restarted.recover()
        recovery_ms = (perf_counter_ns() - recover_started) / 1e6
        if recovery["finalized"] != count or recovery["retried"]:
            raise RuntimeError("Recovered processing ledger is not finalized")
        if store2.count() != len(memory_groups):
            raise RuntimeError("Reopened Memory count differs")

        with store2.transaction() as conn:
            source_count = conn.execute(
                "SELECT COUNT(*) FROM memory_sources"
            ).fetchone()[0]
        if source_count != count:
            raise RuntimeError("Source provenance count mismatch")

        with raw2.log_file.open("rb") as stream:
            raw_bytes = stream.read()
        if raw_bytes.count(b"\n") != count:
            raise RuntimeError("Raw record newline count mismatch")

        quartile = max(1, count // 4)
        process = measurements["process"]
        first_med = median(process[:quartile]) / 1e6
        last_med = median(process[-quartile:]) / 1e6
        return {
            "count": count,
            "streams": streams,
            "memory_count": store2.count(),
            "source_links": source_count,
            "actions": dict(sorted(actions.items())),
            "false_cross_group_memory_count": len(cross_group_memories),
            "false_cross_group_memory_ids": cross_group_memories[:3],
            "extra_memory_fragments": fragments,
            "raw_bytes": len(raw_bytes),
            "throughput_events_s": round(count / elapsed_s, 3),
            "wall_s": round(elapsed_s, 4),
            "process": latency_summary(process),
            "raw_guard": latency_summary(measurements["raw_guard"]),
            "association": latency_summary(measurements["association"]),
            "raw_scan": latency_summary(measurements["raw_scan"]),
            "raw_scans_total": raw_scan_count,
            "raw_scans_per_event_p50": median(
                measurements["scans_per_event"]
            ),
            "process_early_p50_ms": round(first_med, 4),
            "process_late_p50_ms": round(last_med, 4),
            "process_late_over_early_ratio": round(
                last_med / max(first_med, 1e-9), 4,
            ),
            "recovery_ms": round(recovery_ms, 4),
            "notes": (
                "Association timings include nested EventLog scans. "
                "Do not add raw_scan to association to estimate total time."
            ),
        }


def _worker(count, streams, timeout=300):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    try:
        child = subprocess.run(
            [
                sys.executable, "-B", "-m",
                "labs.v02_h5_scaling_diagnostics",
                "--worker-count", str(count),
                "--worker-streams", str(streams),
            ],
            cwd=ROOT, env=env, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Scaling worker timed out: count={count} streams={streams}"
        ) from error
    if child.returncode:
        raise RuntimeError(
            f"Scaling worker failure count={count}, streams={streams}: "
            f"exit={child.returncode}, {child.stderr[-1600:]}"
        )
    try:
        row = json.loads(child.stdout)
    except ValueError as error:
        raise RuntimeError("Scaling worker did not return JSON") from error
    if row["count"] != count or row["streams"] != streams:
        raise RuntimeError("Scaling worker returned a mismatched scenario")
    return row


def _git_snapshot():
    def cmd(*args):
        result = subprocess.run(
            ["git", *args], cwd=ROOT,
            capture_output=True, text=True, timeout=10, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    return {
        "head": cmd("rev-parse", "HEAD"),
        "branch": cmd("branch", "--show-current"),
        "dirty": cmd("status", "--porcelain") not in {"", None},
    }


def build_report(counts, streams, repeats, *, timeout=300):
    if (
        not counts
        or not streams
        or any(type(x) is not int or not 8 <= x <= MAX_EVENTS for x in counts)
        or any(type(x) is not int or not 1 <= x <= 64 for x in streams)
        or any(s > c for s in streams for c in counts)
        or len(set(counts)) != len(counts)
        or len(set(streams)) != len(streams)
    ):
        raise ValueError("Invalid / duplicate count or stream scenario")
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("repeats must be in 1..5")
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be 1..3600 seconds")

    runs = []
    summaries = []
    for count in sorted(counts):
        for stream_count in sorted(streams):
            group = []
            for repeat in range(repeats):
                result = _worker(count, stream_count, timeout=timeout)
                result["repetition"] = repeat + 1
                runs.append(result)
                group.append(result)
            summaries.append({
                "count": count,
                "streams": stream_count,
                "repeats": repeats,
                "process_p95_ms": {
                    "min": min(x["process"]["p95_ms"] for x in group),
                    "median": median(
                        x["process"]["p95_ms"] for x in group
                    ),
                    "max": max(x["process"]["p95_ms"] for x in group),
                },
                "throughput_events_s_median": round(
                    median(x["throughput_events_s"] for x in group), 3
                ),
                "raw_guard_p95_ms_median": round(
                    median(x["raw_guard"]["p95_ms"] for x in group), 3
                ),
                "association_p95_ms_median": round(
                    median(x["association"]["p95_ms"] for x in group), 3
                ),
                "memory_count_range": [
                    min(x["memory_count"] for x in group),
                    max(x["memory_count"] for x in group),
                ],
                "cross_group_merges": max(
                    x["false_cross_group_memory_count"] for x in group
                ),
                "extra_fragments_max": max(
                    x["extra_memory_fragments"] for x in group
                ),
            })

    safety_alert = any(
        row["cross_group_merges"] > 0 for row in summaries
    )
    return {
        "schema": SCHEMA,
        "measurement_status": "MEASURED_NO_RELEASE_SLO",
        "synthetic_grouping_status": (
            "CROSS_GROUP_MERGE_OBSERVED" if safety_alert
            else "NO_CROSS_GROUP_MERGE_OBSERVED"
        ),
        "git": _git_snapshot(),
        "environment": {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
        },
        "workload": {
            "synthetic": True,
            "distribution": "round-robin anchored subjects",
            "repetitions": repeats,
            "phase_timings_nested": True,
        },
        "summary": summaries,
        "runs": runs,
        "limitations": [
            "Text anchors are synthetic, not verified Entity identities.",
            "Profiling wrappers add overhead; compare only within this tool.",
            "Nested timings overlap; raw_scan is a subset of other phases.",
            "No real-world semantic accuracy or physical durability proof.",
            "No performance threshold was approved before measurements.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, nargs="+", default=[160, 640])
    parser.add_argument("--streams", type=int, nargs="+", default=[1, 8])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-count", type=int, default=None,
                        help=argparse.SUPPRESS)
    parser.add_argument("--worker-streams", type=int, default=None,
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker_count is not None or args.worker_streams is not None:
        if args.worker_count is None or args.worker_streams is None:
            parser.error("Both worker-count and worker-streams are required")
        print(json.dumps(measure_case(
            args.worker_count, args.worker_streams,
        ), sort_keys=True))
        return 0
    result = build_report(
        args.events, args.streams, args.repeats, timeout=args.timeout,
    )
    json_report = json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as destination:
            destination.write(json_report + "\n")
    print(json_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
