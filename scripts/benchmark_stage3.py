#!/usr/bin/env python3
"""Reproducible Stage 3 Sleep performance baseline.

Measured production paths:
- selection: SleepSelector over 1k/10k/100k existing WorkItems;
- checkpoint: checkpoint commit/latest/history with a scaled sleep.db;
- provenance: DerivedResultRepository.commit_final_result with a scaled sleep.db;
- large_source: interrupted/resumed 10 GiB synthetic Asset execution.

Synthetic dataset seeding is setup and is reported separately from measured latency.
No SLA or pass/fail threshold is encoded here; this script records a baseline.
"""

import argparse
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from anima.sleep.contracts import SourceRef, SourceRegistry
from anima.sleep.derived import DerivedResultRepository
from anima.sleep.execution import SleepChunkExecutor
from anima.sleep.large_data import (
    GIB,
    MIB,
    SyntheticLargeAssetProcessor,
    SyntheticLargeSource,
)
from anima.sleep.processors import FinalizeResult, ProcessorRegistry
from anima.sleep.selection import SelectionBudget, SelectionCandidate, SleepSelector
from anima.sleep.store import SleepStore


BENCHMARK_VERSION = 1
DEFAULT_SIZES = (1_000, 10_000, 100_000)
DEFAULT_SAMPLES = 5
DEFAULT_HISTORY_DEPTH = 128
DEFAULT_LARGE_LOGICAL_SIZE = 10 * GIB
DEFAULT_LARGE_CHUNK_SIZE = 5 * MIB
DEFAULT_LARGE_INTERRUPT_AFTER = 512
MODES = ("selection", "checkpoint", "provenance")
SEED_TIMESTAMP = "2026-01-01T00:00:00+00:00"
PROCESSOR_NAME = "synthetic-large-asset"
PROCESSOR_VERSION = "1"
COST_HINTS = ("cheap", "normal", "expensive")
SEED_BATCH = 5_000


def public_id(prefix, number):
    if not isinstance(number, int) or isinstance(number, bool) or number < 0:
        raise ValueError("Synthetic ID number must be a non-negative integer")
    if number > 0xFFFFFFFF:
        raise ValueError("Synthetic ID number must fit 32 bits")
    raw = f"{number:08x}-0000-4000-8000-{number:012x}"
    return f"{prefix}{raw}"


def asset_id(number):
    return public_id("asset_", number)


def work_item_id(number):
    return public_id("wi_", number)


def job_id(number=1):
    return public_id("sj_", number)


def percentile(values, fraction):
    ordered = sorted(values)
    position = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[position]


def duration_summary_ns(values):
    milliseconds = [value / 1_000_000 for value in values]
    return {
        "samples": len(milliseconds),
        "p50_ms": round(statistics.median(milliseconds), 6),
        "p95_ms": round(percentile(milliseconds, 0.95), 6),
        "min_ms": round(min(milliseconds), 6),
        "max_ms": round(max(milliseconds), 6),
    }


def peak_rss_mb():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(value / (1024 * 1024), 3)
    return round(value / 1024, 3)


def current_rss_mb():
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    kib = int(line.split()[1])
                    return round(kib / 1024, 3)
        except (OSError, ValueError, IndexError):
            pass
    return None


def total_memory_mb():
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    kib = int(line.split()[1])
                    return round(kib / 1024, 3)
        except (OSError, ValueError, IndexError):
            pass
    return None


def git_head():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "not-recorded"
    return result.stdout.strip() or "not-recorded"


def environment_record():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "total_memory_mb": total_memory_mb(),
    }


def file_bytes(path):
    path = Path(path)
    return path.stat().st_size if path.exists() else 0


def storage_snapshot(database_file):
    database_file = Path(database_file)
    main = file_bytes(database_file)
    wal = file_bytes(str(database_file) + "-wal")
    shm = file_bytes(str(database_file) + "-shm")
    total = main + wal + shm
    return {
        "sleep_db_mb": round(main / (1024 * 1024), 3),
        "wal_mb": round(wal / (1024 * 1024), 3),
        "shm_mb": round(shm / (1024 * 1024), 3),
        "total_mb": round(total / (1024 * 1024), 3),
    }


def _validate_size(size):
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ValueError("Benchmark size must be a positive integer")


def _validate_samples(samples):
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
        raise ValueError("Benchmark samples must be a positive integer")


def source_registry():
    return SourceRegistry().register(
        "asset",
        lambda source_id: isinstance(source_id, str) and source_id.startswith("asset_"),
    )


def metadata_for(index):
    return {
        "priority": (index * 7) % 17,
        "cost_hint": COST_HINTS[index % len(COST_HINTS)],
    }


def candidate_set(size):
    _validate_size(size)
    values = []
    for index in range(1, size + 1):
        metadata = metadata_for(index)
        values.append(
            SelectionCandidate(
                source_ref=SourceRef("asset", asset_id(index)),
                priority=metadata["priority"],
                cost_hint=metadata["cost_hint"],
            )
        )
    return tuple(values)


def _batched_indexes(size):
    start = 1
    while start <= size:
        stop = min(size + 1, start + SEED_BATCH)
        yield range(start, stop)
        start = stop


def seed_work_items(store, public_job_id, size):
    _validate_size(size)
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    with store.transaction() as connection:
        for batch in _batched_indexes(size):
            rows = []
            for index in batch:
                metadata = metadata_for(index)
                rows.append(
                    (
                        work_item_id(index),
                        public_job_id,
                        asset_id(index),
                        PROCESSOR_NAME,
                        PROCESSOR_VERSION,
                        metadata["priority"],
                        metadata["cost_hint"],
                        SEED_TIMESTAMP,
                        SEED_TIMESTAMP,
                    )
                )
            connection.executemany(
                """
                INSERT INTO work_items(
                    public_id, job_id, work_kind, source_kind, source_id,
                    processor, processor_version, priority, cost_hint,
                    status, attempts, checkpoint_ref, created_at, updated_at
                ) VALUES (?, ?, 'CONSOLIDATE', 'asset', ?, ?, ?, ?, ?,
                          'queued', 0, NULL, ?, ?)
                """,
                rows,
            )
    wall = time.perf_counter() - wall_started
    cpu = time.process_time() - cpu_started
    return {
        "work_items": size,
        "wall_s": round(wall, 6),
        "cpu_s": round(cpu, 6),
        "rows_per_s": round(size / wall, 2) if wall else None,
    }


def setup_dataset(workdir, size):
    _validate_size(size)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    store = SleepStore(workdir / "sleep.db")
    job = store.create_job(
        public_id=job_id(),
        created_at=SEED_TIMESTAMP,
        reason="Stage 3 benchmark setup",
    )
    setup = seed_work_items(store, job["id"], size)
    return store, job, source_registry(), setup


def measure_repeated(operation, samples):
    _validate_samples(samples)
    wall_ns = []
    cpu_ns = []
    output = None
    for index in range(samples):
        wall_started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        output = operation(index)
        cpu_ns.append(time.process_time_ns() - cpu_started)
        wall_ns.append(time.perf_counter_ns() - wall_started)
    return duration_summary_ns(wall_ns), duration_summary_ns(cpu_ns), output


def _base_case(mode, size, setup, store, latency, cpu, throughput_per_s, details):
    return {
        "mode": mode,
        "work_item_count": size,
        "setup": setup,
        "latency": latency,
        "cpu": cpu,
        "throughput_per_s": round(throughput_per_s, 3) if throughput_per_s is not None else None,
        "memory": {
            "current_rss_mb": current_rss_mb(),
            "process_peak_rss_mb": peak_rss_mb(),
        },
        "storage": storage_snapshot(store.database_file),
        "details": details,
    }


def run_selection_case(size, *, samples=DEFAULT_SAMPLES, workdir=None):
    _validate_size(size)
    _validate_samples(samples)
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix=f"anima-stage3-selection-{size}-") as temp_dir:
            return run_selection_case(size, samples=samples, workdir=temp_dir)

    store, job, sources, setup = setup_dataset(workdir, size)
    selector = SleepSelector(sleep_store=store, source_registry=sources)
    candidates = candidate_set(size)
    budget = SelectionBudget(max_items=size, max_cost_units=4 * size)

    def operation(_):
        return selector.select(
            job_id=job["id"],
            candidates=candidates,
            processor=PROCESSOR_NAME,
            processor_version=PROCESSOR_VERSION,
            budget=budget,
        )

    latency, cpu, result = measure_repeated(operation, samples)
    if len(result.work_items) != size or result.reused != size:
        raise RuntimeError("Selection benchmark did not reuse the complete seeded queue")
    p50_s = latency["p50_ms"] / 1000
    throughput = size / p50_s if p50_s else None
    return _base_case(
        "selection",
        size,
        setup,
        store,
        latency,
        cpu,
        throughput,
        {
            "selected": len(result.work_items),
            "reused": result.reused,
            "considered": result.considered,
            "total_cost_units": result.total_cost_units,
        },
    )


def _checkpoint_payload(sequence):
    return {
        "sequence": sequence,
        "cursor": sequence + 1,
        "rolling": f"benchmark-{sequence:08d}",
    }


def run_checkpoint_case(
    size,
    *,
    samples=DEFAULT_SAMPLES,
    history_depth=DEFAULT_HISTORY_DEPTH,
    workdir=None,
):
    _validate_size(size)
    _validate_samples(samples)
    if not isinstance(history_depth, int) or isinstance(history_depth, bool) or history_depth < 0:
        raise ValueError("history_depth must be a non-negative integer")
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix=f"anima-stage3-checkpoint-{size}-") as temp_dir:
            return run_checkpoint_case(
                size,
                samples=samples,
                history_depth=history_depth,
                workdir=temp_dir,
            )

    store, _, _, setup = setup_dataset(workdir, size)
    target = work_item_id(1)
    store.begin_work_item(target)
    for sequence in range(history_depth):
        store.commit_work_item_chunk(
            target,
            sequence=sequence,
            checkpoint=_checkpoint_payload(sequence),
            local_result={"sequence": sequence},
        )

    storage_before = storage_snapshot(store.database_file)

    def commit_operation(index):
        sequence = history_depth + index
        return store.commit_work_item_chunk(
            target,
            sequence=sequence,
            checkpoint=_checkpoint_payload(sequence),
            local_result={"sequence": sequence},
        )

    commit_latency, commit_cpu, latest = measure_repeated(commit_operation, samples)
    expected_last = history_depth + samples - 1
    if latest["sequence"] != expected_last:
        raise RuntimeError("Checkpoint benchmark sequence mismatch")

    latest_latency, latest_cpu, latest_lookup = measure_repeated(
        lambda _: store.get_latest_checkpoint(target),
        samples,
    )
    history_latency, history_cpu, history = measure_repeated(
        lambda _: store.list_checkpoints(target),
        samples,
    )
    expected_history = history_depth + samples
    if latest_lookup["sequence"] != expected_last or len(history) != expected_history:
        raise RuntimeError("Checkpoint benchmark history mismatch")

    p50_s = commit_latency["p50_ms"] / 1000
    throughput = 1 / p50_s if p50_s else None
    return _base_case(
        "checkpoint",
        size,
        setup,
        store,
        commit_latency,
        commit_cpu,
        throughput,
        {
            "history_depth_before": history_depth,
            "history_depth_after": expected_history,
            "latest_lookup_latency": latest_latency,
            "latest_lookup_cpu": latest_cpu,
            "history_list_latency": history_latency,
            "history_list_cpu": history_cpu,
            "storage_before": storage_before,
        },
    )


def run_provenance_case(size, *, samples=DEFAULT_SAMPLES, workdir=None):
    _validate_size(size)
    _validate_samples(samples)
    if samples > size:
        raise ValueError("provenance samples must not exceed work item count")
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix=f"anima-stage3-provenance-{size}-") as temp_dir:
            return run_provenance_case(size, samples=samples, workdir=temp_dir)

    store, job, sources, setup = setup_dataset(workdir, size)
    repository = DerivedResultRepository(store)
    prepared = []
    for index in range(1, samples + 1):
        item = store.begin_work_item(work_item_id(index))
        store.commit_work_item_chunk(
            item.public_id,
            sequence=0,
            checkpoint={"processed": 1, "sequence": 0},
            local_result={"sequence": 0},
        )
        prepared.append(item)

    def operation(index):
        item = prepared[index]
        final = FinalizeResult.create(
            work_item=item,
            output={
                "kind": "stage3_performance_probe",
                "dataset_size": size,
                "sample": index,
            },
        )
        return repository.commit_final_result(
            item.public_id,
            final,
            source_registry=sources,
        )

    latency, cpu, last_result = measure_repeated(operation, samples)
    if last_result.authority != "derived":
        raise RuntimeError("Provenance benchmark did not produce a derived result")
    results = repository.list_results(job_id=job["id"])
    if len(results) != samples:
        raise RuntimeError("Provenance benchmark result count mismatch")

    p50_s = latency["p50_ms"] / 1000
    throughput = 1 / p50_s if p50_s else None
    return _base_case(
        "provenance",
        size,
        setup,
        store,
        latency,
        cpu,
        throughput,
        {
            "derived_results": len(results),
            "sources_per_result": len(last_result.source_refs),
            "transformation_steps": len(last_result.transformation_history),
        },
    )


def run_large_source_case(
    *,
    logical_size_bytes=DEFAULT_LARGE_LOGICAL_SIZE,
    chunk_size_bytes=DEFAULT_LARGE_CHUNK_SIZE,
    interrupt_after=DEFAULT_LARGE_INTERRUPT_AFTER,
    workdir=None,
):
    for value, label in (
        (logical_size_bytes, "logical_size_bytes"),
        (chunk_size_bytes, "chunk_size_bytes"),
        (interrupt_after, "interrupt_after"),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{label} must be a positive integer")
    chunk_count = math.ceil(logical_size_bytes / chunk_size_bytes)
    if interrupt_after >= chunk_count:
        raise ValueError("interrupt_after must be smaller than chunk count")
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="anima-stage3-large-") as temp_dir:
            return run_large_source_case(
                logical_size_bytes=logical_size_bytes,
                chunk_size_bytes=chunk_size_bytes,
                interrupt_after=interrupt_after,
                workdir=temp_dir,
            )

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    store = SleepStore(workdir / "sleep.db")
    job = store.create_job(created_at=SEED_TIMESTAMP, reason="Stage 3 large benchmark")
    source_ref = SourceRef("asset", asset_id(0xF0000000))
    sources = SourceRegistry().register(
        "asset",
        lambda source_id: source_id == source_ref.source_id,
    )
    from anima.sleep.contracts import WorkItem

    item = WorkItem.create(
        job_id=job["id"],
        source_ref=source_ref,
        processor=PROCESSOR_NAME,
        processor_version=PROCESSOR_VERSION,
        cost_hint="expensive",
    )
    item = store.create_work_item(item, source_registry=sources, created_at=SEED_TIMESTAMP)
    executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=ProcessorRegistry().register(SyntheticLargeAssetProcessor()),
        source_registry=sources,
    )
    source = SyntheticLargeSource(
        source_ref=source_ref,
        logical_size_bytes=logical_size_bytes,
        chunk_size_bytes=chunk_size_bytes,
    )

    first_wall = time.perf_counter_ns()
    first_cpu = time.process_time_ns()
    interrupted = executor.run(
        item.public_id,
        source,
        interrupt_after_new_chunks=interrupt_after,
    )
    first_cpu_elapsed = time.process_time_ns() - first_cpu
    first_wall_elapsed = time.perf_counter_ns() - first_wall
    if interrupted.status != "checkpointed":
        raise RuntimeError("Large-source benchmark did not checkpoint at interruption")

    reopened = SleepStore(store.database_file)
    resumed_executor = SleepChunkExecutor(
        sleep_store=reopened,
        processor_registry=ProcessorRegistry().register(SyntheticLargeAssetProcessor()),
        source_registry=sources,
    )
    resumed_source = SyntheticLargeSource(
        source_ref=source_ref,
        logical_size_bytes=logical_size_bytes,
        chunk_size_bytes=chunk_size_bytes,
    )
    second_wall = time.perf_counter_ns()
    second_cpu = time.process_time_ns()
    completed = resumed_executor.run(item.public_id, resumed_source)
    second_cpu_elapsed = time.process_time_ns() - second_cpu
    second_wall_elapsed = time.perf_counter_ns() - second_wall
    if completed.status != "completed":
        raise RuntimeError("Large-source benchmark did not complete after resume")
    if completed.resumed_from_sequence != interrupt_after:
        raise RuntimeError("Large-source benchmark resumed from the wrong chunk")
    if resumed_source.iter_starts != (interrupt_after,):
        raise RuntimeError("Large-source benchmark did not use direct resume")

    total_wall = first_wall_elapsed + second_wall_elapsed
    total_cpu = first_cpu_elapsed + second_cpu_elapsed
    total_seconds = total_wall / 1_000_000_000
    latency = duration_summary_ns([total_wall])
    cpu = duration_summary_ns([total_cpu])
    return {
        "mode": "large_source",
        "work_item_count": 1,
        "setup": {"work_items": 1},
        "latency": latency,
        "cpu": cpu,
        "throughput_per_s": round(chunk_count / total_seconds, 3) if total_seconds else None,
        "memory": {
            "current_rss_mb": current_rss_mb(),
            "process_peak_rss_mb": peak_rss_mb(),
        },
        "storage": storage_snapshot(reopened.database_file),
        "details": {
            "logical_size_bytes": logical_size_bytes,
            "logical_gib": round(logical_size_bytes / GIB, 6),
            "chunk_size_bytes": chunk_size_bytes,
            "chunk_count": chunk_count,
            "interrupt_after": interrupt_after,
            "first_run": {
                "latency": duration_summary_ns([first_wall_elapsed]),
                "cpu": duration_summary_ns([first_cpu_elapsed]),
                "processed_chunks": interrupted.processed_chunks,
            },
            "resume": {
                "latency": duration_summary_ns([second_wall_elapsed]),
                "cpu": duration_summary_ns([second_cpu_elapsed]),
                "processed_chunks": completed.processed_chunks,
                "resumed_from_sequence": completed.resumed_from_sequence,
            },
            "logical_gib_per_s": round((logical_size_bytes / GIB) / total_seconds, 6)
            if total_seconds
            else None,
        },
    }


def run_case(size, mode, *, samples=DEFAULT_SAMPLES, history_depth=DEFAULT_HISTORY_DEPTH, workdir=None):
    if mode == "selection":
        return run_selection_case(size, samples=samples, workdir=workdir)
    if mode == "checkpoint":
        return run_checkpoint_case(
            size,
            samples=samples,
            history_depth=history_depth,
            workdir=workdir,
        )
    if mode == "provenance":
        return run_provenance_case(size, samples=samples, workdir=workdir)
    raise ValueError(f"Unknown benchmark mode: {mode!r}")


def parse_sizes(values):
    sizes = []
    for raw in values:
        size = int(raw)
        _validate_size(size)
        if size not in sizes:
            sizes.append(size)
    return sizes


def worker_command(size, mode, samples, history_depth):
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-size",
        str(size),
        "--worker-mode",
        mode,
        "--samples",
        str(samples),
        "--history-depth",
        str(history_depth),
    ]


def large_worker_command():
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-large-source",
    ]


def _run_worker(command, label):
    print(f"[benchmark] {label}: start", file=sys.stderr, flush=True)
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Benchmark worker failed: {label}")
    lines = completed.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError(f"Benchmark worker returned no result: {label}")
    result = json.loads(lines[-1])
    print(
        f"[benchmark] {label}: p95={result['latency']['p95_ms']}ms "
        f"rss={result['memory']['process_peak_rss_mb']}MB "
        f"storage={result['storage']['total_mb']}MB",
        file=sys.stderr,
        flush=True,
    )
    return result


def run_parent(sizes, *, samples, history_depth, output):
    results = []
    for size in sizes:
        for mode in MODES:
            results.append(
                _run_worker(
                    worker_command(size, mode, samples, history_depth),
                    f"size={size} mode={mode}",
                )
            )
    results.append(_run_worker(large_worker_command(), "large_source=10GiB"))

    report = {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot": git_head(),
        "environment": environment_record(),
        "sizes": list(sizes),
        "samples": samples,
        "history_depth": history_depth,
        "modes": list(MODES) + ["large_source"],
        "results": results,
    }

    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print_report(report)
    label = output_path.relative_to(PROJECT_ROOT) if output_path.is_relative_to(PROJECT_ROOT) else output_path
    print(f"\nJSON: {label}")
    return report


def print_report(report):
    print("\nStage 3 Sleep Performance baseline")
    print(
        "WorkItems | Mode         | p50 ms     | p95 ms     | CPU p95 ms | "
        "Throughput/s | Peak RSS MB | Storage MB"
    )
    print("-" * 105)
    for result in report["results"]:
        count = result["work_item_count"]
        print(
            f"{count:>9} | "
            f"{result['mode']:<12} | "
            f"{result['latency']['p50_ms']:>10.4f} | "
            f"{result['latency']['p95_ms']:>10.4f} | "
            f"{result['cpu']['p95_ms']:>10.4f} | "
            f"{(result['throughput_per_s'] or 0):>12.2f} | "
            f"{result['memory']['process_peak_rss_mb']:>11.3f} | "
            f"{result['storage']['total_mb']:>10.3f}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", default=[str(value) for value in DEFAULT_SIZES])
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--history-depth", type=int, default=DEFAULT_HISTORY_DEPTH)
    parser.add_argument("--output", default=".benchmarks/stage3-performance.json")
    parser.add_argument("--worker-size", type=int)
    parser.add_argument("--worker-mode", choices=MODES)
    parser.add_argument("--worker-large-source", action="store_true")
    args = parser.parse_args()

    if args.worker_large_source:
        print(json.dumps(run_large_source_case(), ensure_ascii=False))
        return 0

    if args.worker_size is not None or args.worker_mode is not None:
        if args.worker_size is None or args.worker_mode is None:
            parser.error("--worker-size and --worker-mode must be used together")
        result = run_case(
            args.worker_size,
            args.worker_mode,
            samples=args.samples,
            history_depth=args.history_depth,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0

    sizes = parse_sizes(args.sizes)
    run_parent(
        sizes,
        samples=args.samples,
        history_depth=args.history_depth,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
