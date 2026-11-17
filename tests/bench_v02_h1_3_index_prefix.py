"""Synthetic H1.3 index-prefix verification cost benchmark.

Not collected by pytest. Runs only on disposable temporary JSONL/SQLite files.
Compare each checked incremental sync with the same implementation where the
new prefix verifier is disabled on this benchmark *instance only*.
The latter is a timing baseline, NOT a release-safe operational mode.

Usage:
    PYTHONPATH="$PWD" .venv/bin/python \
      tests/bench_v02_h1_3_index_prefix.py --events 1000 10000 50000
"""

import argparse
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_retrieval import EventRetrieval


STAMP = "2026-11-17T12:00:00+00:00"


def make_event(number):
    return Event(
        "conversation.user",
        {"text": f"benchmark event {number:08d} " + ("x" * 192)},
        source="user", session_id="session_00000001",
        timestamp=STAMP,
        event_id=f"ev_{UUID(int=(4 << 76) | (2 << 62) | number)}",
    )


def measure(fn):
    start = perf_counter()
    result = fn()
    return round(1000 * (perf_counter() - start), 3), result


def one_size(count, repeats):
    with TemporaryDirectory(prefix="anima-v02-h13-bench-") as temporary:
        root = Path(temporary)
        log = EventLog(root / "events.jsonl")
        index = EventRetrieval(log, root / "event_index.db")
        for i in range(1, count + 1):
            log.write(make_event(i))

        initial_ms, initial = measure(
            lambda: index.sync(max_events=100_000, max_bytes=100_000_000)
        )
        if initial["status"] != "complete" or initial["indexed_events"] != count:
            raise RuntimeError("Initial benchmark index did not converge")

        # In-memory override on this disposable benchmark instance only.
        # The prior verified hasher is trusted without checking the changed
        # file identity. This is NOT an operationally safe production mode.
        baseline_hasher = index._prefix_cache[0].copy()
        index._cached_prefix_hasher = (
            lambda _cursor, _stat: baseline_hasher.copy()
        )
        log.write(make_event(count + 1))
        try:
            unchecked_ms, unchecked = measure(index.sync)
        finally:
            del index._cached_prefix_hasher
        if unchecked["status"] != "complete":
            raise RuntimeError("Unchecked benchmark append failed")

        verified = []
        for i in range(repeats):
            log.write(make_event(count + 2 + i))
            elapsed, result = measure(index.sync)
            if result["status"] != "complete" or result["indexed_now"] != 1:
                raise RuntimeError("Verified benchmark append failed")
            verified.append(elapsed)

        return {
            "event_count": count,
            "source_bytes": log.log_file.stat().st_size,
            "initial_index_ms": initial_ms,
            "unchecked_append_sync_ms": unchecked_ms,
            "verified_append_sync_median_ms": round(median(verified), 3),
            "verified_append_sync_samples_ms": verified,
            "median_verification_overhead_ms": round(median(verified) - unchecked_ms, 3),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 20:
        parser.error("--repeats must be 1..20")
    for count in args.events:
        if count < 10 or count >= 1_000_000:
            parser.error("--events values must be in 10..999999")
        print(json.dumps(one_size(count, args.repeats), sort_keys=True))


if __name__ == "__main__":
    main()
