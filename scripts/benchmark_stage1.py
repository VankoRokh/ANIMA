#!/usr/bin/env python3
"""Reproducible Stage 1 performance baseline over synthetic 1k/10k/100k datasets.

The benchmark intentionally separates synthetic batch seeding from measured
production API operations. It uses only the Python standard library and ANIMA code.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


BENCHMARK_VERSION = 1
DEFAULT_SIZES = (1_000, 10_000, 100_000)
DEFAULT_SAMPLES = 7
DEFAULT_BATCH_COUNT = 3
SEED_TIMESTAMP = "2026-01-01T00:00:00+00:00"
CHUNK_SIZE = 5_000
API_ID_BASE = 1_000_000_000
BATCH_EVENT_BASE = 2_000_000_000


def public_id(prefix, number):
    """Return a deterministic valid UUIDv4 with the requested ANIMA prefix."""
    if not isinstance(number, int) or number < 0 or number > 0xFFFFFFFF:
        raise ValueError("Synthetic public ID number must fit 32 bits")
    raw = (
        f"{number:08x}-0000-4000-8000-"
        f"{number:012x}"
    )
    return f"{prefix}{raw}"


def event_id(number):
    return public_id("ev_", number)


def memory_id(number):
    return public_id("mem_", number)


def knowledge_id(number):
    return public_id("kn_", number)


def entity_id(number):
    return public_id("ent_", number)


def relation_id(number):
    return public_id("rel_", number)


def synthetic_text(index, entity_count):
    topic = index % entity_count
    return (
        f"Benchmark topic {topic} synthetic memory record {index} "
        "sqlite project baseline."
    )


def synthetic_event(index, entity_count):
    return Event(
        "conversation.user",
        {"text": synthetic_text(index, entity_count)},
        source="benchmark",
        session_id=f"session_{((index - 1) // 100) + 1:08d}",
        event_id=event_id(index),
        timestamp=SEED_TIMESTAMP,
    )


def chunks(total, chunk_size=CHUNK_SIZE):
    start = 1
    while start <= total:
        stop = min(total + 1, start + chunk_size)
        yield range(start, stop)
        start = stop


def mb(byte_count):
    return round(byte_count / (1024 * 1024), 3)


def file_size(path):
    path = Path(path)
    return path.stat().st_size if path.exists() else 0


def directory_size(path):
    path = Path(path)
    return sum(
        item.stat().st_size
        for item in path.rglob("*")
        if item.is_file()
    )


def peak_rss_mb():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(value / (1024 * 1024), 3)
    return round(value / 1024, 3)


def percentile(values, fraction):
    ordered = sorted(values)
    position = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[position]


def latency_summary(durations):
    milliseconds = [value * 1000 for value in durations]
    return {
        "samples": len(milliseconds),
        "p50_ms": round(statistics.median(milliseconds), 4),
        "p95_ms": round(percentile(milliseconds, 0.95), 4),
        "min_ms": round(min(milliseconds), 4),
        "max_ms": round(max(milliseconds), 4),
    }


def measure_calls(operation, count):
    durations = []
    outputs = []
    for index in range(count):
        started = time.perf_counter()
        outputs.append(operation(index))
        durations.append(time.perf_counter() - started)
    return latency_summary(durations), outputs


def append_seed_events(event_log, size, entity_count):
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    for index in range(1, size + 1):
        event_log.write(synthetic_event(index, entity_count))
    wall = time.perf_counter() - wall_started
    cpu = time.process_time() - cpu_started
    return {
        "events": size,
        "wall_s": round(wall, 4),
        "cpu_s": round(cpu, 4),
        "events_per_s": round(size / wall, 2) if wall else None,
    }


def seed_sqlite(store, size, entity_count):
    """Populate a realistic searchable dataset in one setup transaction.

    This is benchmark setup, not the measured MemoryStore.create_memory path.
    FTS triggers and indexes remain active, so the resulting DB is representative
    for read-path measurements and storage scaling.
    """
    knowledge_count = max(1, size // 20)
    relation_number = 1
    wall_started = time.perf_counter()
    cpu_started = time.process_time()

    with store.transaction() as connection:
        connection.executemany(
            """
            INSERT INTO entities(public_id, type, canonical_name, status)
            VALUES (?, 'concept', ?, 'active')
            """,
            [
                (entity_id(index), f"Benchmark Entity {index}")
                for index in range(entity_count)
            ],
        )
        connection.executemany(
            "INSERT INTO entity_aliases(entity_id, alias) VALUES (?, ?)",
            [
                (entity_id(index), f"topic-{index}")
                for index in range(entity_count)
            ],
        )

        for batch in chunks(size):
            memory_rows = []
            source_rows = []
            relation_rows = []
            for index in batch:
                topic = index % entity_count
                memory_rows.append(
                    (
                        memory_id(index),
                        "episodic",
                        "project",
                        "open",
                        synthetic_text(index, entity_count),
                        index % 4,
                        SEED_TIMESTAMP,
                        SEED_TIMESTAMP,
                    )
                )
                source_rows.append((memory_id(index), event_id(index)))
                relation_rows.append(
                    (
                        relation_id(relation_number),
                        "memory",
                        memory_id(index),
                        "about",
                        "entity",
                        entity_id(topic),
                        SEED_TIMESTAMP,
                        memory_id(index),
                    )
                )
                relation_number += 1

            connection.executemany(
                """
                INSERT INTO memories(
                    public_id, type, domain, status, content, importance,
                    created_at, updated_at, closed_at, merged_into
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                memory_rows,
            )
            connection.executemany(
                "INSERT INTO memory_sources(memory_id, event_id) VALUES (?, ?)",
                source_rows,
            )
            connection.executemany(
                """
                INSERT INTO relations(
                    public_id, source_kind, source_id, relation_type,
                    target_kind, target_id, created_at, valid_until,
                    source_memory_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                relation_rows,
            )

        for start in range(0, knowledge_count, CHUNK_SIZE):
            stop = min(knowledge_count, start + CHUNK_SIZE)
            knowledge_rows = []
            relation_rows = []
            for index in range(start, stop):
                source_index = (index * 20) + 1
                topic = index % entity_count
                knowledge_rows.append(
                    (
                        knowledge_id(index),
                        "project",
                        (
                            f"Benchmark topic {topic} confirmed knowledge "
                            f"record {index} sqlite project baseline."
                        ),
                        "confirmed",
                        SEED_TIMESTAMP,
                        SEED_TIMESTAMP,
                    )
                )
                relation_rows.append(
                    (
                        relation_id(relation_number),
                        "memory",
                        memory_id(source_index),
                        "supports",
                        "knowledge",
                        knowledge_id(index),
                        SEED_TIMESTAMP,
                        memory_id(source_index),
                    )
                )
                relation_number += 1
                relation_rows.append(
                    (
                        relation_id(relation_number),
                        "knowledge",
                        knowledge_id(index),
                        "about",
                        "entity",
                        entity_id(topic),
                        SEED_TIMESTAMP,
                        memory_id(source_index),
                    )
                )
                relation_number += 1

            connection.executemany(
                """
                INSERT INTO knowledge(
                    public_id, domain, statement, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                knowledge_rows,
            )
            connection.executemany(
                """
                INSERT INTO relations(
                    public_id, source_kind, source_id, relation_type,
                    target_kind, target_id, created_at, valid_until,
                    source_memory_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                relation_rows,
            )

    wall = time.perf_counter() - wall_started
    cpu = time.process_time() - cpu_started
    inserted_rows = size + entity_count + entity_count + knowledge_count + relation_number - 1
    return {
        "memories": size,
        "knowledge": knowledge_count,
        "entities": entity_count,
        "relations": relation_number - 1,
        "setup_rows": inserted_rows,
        "wall_s": round(wall, 4),
        "cpu_s": round(cpu, 4),
        "rows_per_s": round(inserted_rows / wall, 2) if wall else None,
    }


def batch_timestamp(index):
    timestamp = datetime(2026, 2, 1, tzinfo=timezone.utc) + timedelta(seconds=index)
    return timestamp.isoformat(timespec="seconds")


def measure_batch_processing(event_log, coordinator, size, batch_count):
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    actions = []
    for index in range(batch_count):
        number = BATCH_EVENT_BASE + (size * 10) + index
        event = Event(
            "conversation.user",
            {
                "text": (
                    f"quartz{size}_{index} zephyr{size}_{index} "
                    f"cobalt{size}_{index}"
                )
            },
            source="benchmark",
            session_id="session_benchmark_batch",
            event_id=event_id(number),
            timestamp=batch_timestamp(index),
        )
        event_log.write(event)
        actions.append(coordinator.process(event)["action"])
    wall = time.perf_counter() - wall_started
    cpu = time.process_time() - cpu_started
    return {
        "events": batch_count,
        "actions": actions,
        "wall_s": round(wall, 4),
        "cpu_s": round(cpu, 4),
        "events_per_s": round(batch_count / wall, 2) if wall else None,
    }


def storage_snapshot(data_dir):
    data_dir = Path(data_dir)
    database = data_dir / "memory.db"
    event_log = data_dir / "events.jsonl"
    return {
        "memory_db_mb": mb(file_size(database)),
        "events_jsonl_mb": mb(file_size(event_log)),
        "data_total_mb": mb(directory_size(data_dir)),
    }


def run_dataset(size, *, samples=DEFAULT_SAMPLES, batch_count=DEFAULT_BATCH_COUNT, workdir=None):
    if not isinstance(size, int) or size < 1:
        raise ValueError("Benchmark size must be a positive integer")
    if not isinstance(samples, int) or samples < 1:
        raise ValueError("Benchmark samples must be a positive integer")
    if not isinstance(batch_count, int) or not 1 <= batch_count <= 30:
        raise ValueError("Benchmark batch_count must be from 1 to 30")

    owned_temp = None
    if workdir is None:
        owned_temp = tempfile.TemporaryDirectory(prefix=f"anima-stage1-{size}-")
        data_dir = Path(owned_temp.name)
    else:
        data_dir = Path(workdir)
        data_dir.mkdir(parents=True, exist_ok=True)

    overall_wall = time.perf_counter()
    overall_cpu = time.process_time()
    entity_count = min(100, size)
    probe = min(42, entity_count - 1)
    probe_memory_index = probe if probe > 0 else 1

    event_log = EventLog(data_dir / "events.jsonl")
    event_append = append_seed_events(event_log, size, entity_count)

    store = MemoryStore(data_dir / "memory.db")
    synthetic_seed = seed_sqlite(store, size, entity_count)
    seed_storage = storage_snapshot(data_dir)

    links = LinkStore(store)
    knowledge = KnowledgeLayer(memory_store=store)
    provenance = ProvenanceResolver(store, links, event_log)
    retrieval = RetrievalEngine(memory_store=store, link_store=links)
    context = ContextBuilder(retrieval=retrieval, provenance=provenance)
    processor = MemoryProcessor(
        memory_store=store,
        event_log=event_log,
        link_store=links,
    )
    coordinator = EventProcessingCoordinator(
        memory_store=store,
        memory_processor=processor,
        event_log=event_log,
    )

    api_ids = []

    def create_memory_sample(index):
        number = API_ID_BASE + (size * 100) + index
        public = memory_id(number)
        result = store.create_memory(
            memory_type="episodic",
            domain="project",
            content=f"API memory create sample {size} {index}",
            status="open",
            importance=1,
            created_at=SEED_TIMESTAMP,
            public_id=public,
        )
        api_ids.append(result["id"])
        return result

    memory_create, _ = measure_calls(create_memory_sample, samples)

    def update_memory_sample(index):
        public = api_ids[index % len(api_ids)]
        return store.update_memory(
            public,
            content=f"API memory update sample {size} {index}",
            updated_at=SEED_TIMESTAMP,
        )

    memory_update, _ = measure_calls(update_memory_sample, samples)

    entity_lookup, entity_outputs = measure_calls(
        lambda _: links.resolve_entity(f"topic-{probe}"),
        samples,
    )
    if any(result is None for result in entity_outputs):
        raise RuntimeError("Entity lookup probe was not found")

    knowledge_probe = min(42, synthetic_seed["knowledge"] - 1)
    knowledge_lookup, knowledge_outputs = measure_calls(
        lambda _: knowledge.get(knowledge_id(knowledge_probe)),
        samples,
    )
    if any(result is None for result in knowledge_outputs):
        raise RuntimeError("Knowledge lookup probe was not found")

    fts_query = f'"benchmark" AND "topic" AND "{probe}"'
    fts_memory, fts_outputs = measure_calls(
        lambda _: store.search_memories(fts_query, limit=10),
        samples,
    )
    if any(not result for result in fts_outputs):
        raise RuntimeError("FTS benchmark probe returned no results")

    relation_1hop, relation_outputs = measure_calls(
        lambda _: links.relations_for(
            "memory",
            memory_id(probe_memory_index),
            direction="both",
        ),
        samples,
    )
    if any(not result for result in relation_outputs):
        raise RuntimeError("Relation benchmark probe returned no results")

    query = f"benchmark topic {probe}"
    retrieval_latency, retrieval_outputs = measure_calls(
        lambda _: retrieval.retrieve(query, top_k=10, relation_hops=1),
        samples,
    )
    if any(not result["results"] for result in retrieval_outputs):
        raise RuntimeError("Retrieval benchmark probe returned no results")

    fast_context, fast_outputs = measure_calls(
        lambda _: context.build(
            query,
            consumer="FAST",
            max_items=6,
            max_chars=1200,
        ),
        samples,
    )
    if any(result["selection_stats"]["items_used"] == 0 for result in fast_outputs):
        raise RuntimeError("FAST Context benchmark returned an empty bundle")

    expensive_samples = min(3, samples)
    deep_context, deep_outputs = measure_calls(
        lambda _: context.build(
            query,
            consumer="DEEP",
            max_items=16,
            max_chars=4000,
        ),
        expensive_samples,
    )
    if any(result["selection_stats"]["items_used"] == 0 for result in deep_outputs):
        raise RuntimeError("DEEP Context benchmark returned an empty bundle")

    batch_processing = measure_batch_processing(
        event_log,
        coordinator,
        size,
        batch_count,
    )

    final_storage = storage_snapshot(data_dir)
    total_wall = time.perf_counter() - overall_wall
    total_cpu = time.process_time() - overall_cpu

    result = {
        "size": size,
        "samples": samples,
        "expensive_samples": expensive_samples,
        "batch_count": batch_count,
        "event_append": event_append,
        "synthetic_seed": synthetic_seed,
        "latency": {
            "memory_create": memory_create,
            "memory_update": memory_update,
            "entity_lookup": entity_lookup,
            "knowledge_lookup": knowledge_lookup,
            "fts_memory": fts_memory,
            "relation_1hop": relation_1hop,
            "retrieval": retrieval_latency,
            "context_fast": fast_context,
            "context_deep": deep_context,
        },
        "batch_processing": batch_processing,
        "storage_after_seed": seed_storage,
        "storage_final": final_storage,
        "total": {
            "wall_s": round(total_wall, 4),
            "cpu_s": round(total_cpu, 4),
            "peak_rss_mb": peak_rss_mb(),
        },
    }

    if owned_temp is not None:
        owned_temp.cleanup()
    return result


def git_head():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def environment_record():
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
    }


def format_number(value, digits=2):
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def print_report(report):
    print("\nStage 1 Performance Baseline")
    print(f"snapshot: {report['snapshot']}")
    print(f"python: {report['environment']['python']}")
    print("\nScale / throughput")
    print(
        "size | event append/s | seed rows/s | batch events/s | wall s | cpu s | "
        "peak RSS MB | DB MB | data MB"
    )
    print("---:|---:|---:|---:|---:|---:|---:|---:|---:")
    for item in report["results"]:
        print(
            f"{item['size']} | "
            f"{format_number(item['event_append']['events_per_s'])} | "
            f"{format_number(item['synthetic_seed']['rows_per_s'])} | "
            f"{format_number(item['batch_processing']['events_per_s'])} | "
            f"{format_number(item['total']['wall_s'])} | "
            f"{format_number(item['total']['cpu_s'])} | "
            f"{format_number(item['total']['peak_rss_mb'])} | "
            f"{format_number(item['storage_after_seed']['memory_db_mb'])} | "
            f"{format_number(item['storage_after_seed']['data_total_mb'])}"
        )

    print("\nLatency p50 / p95 (ms)")
    print(
        "size | mem create | mem update | entity lookup | knowledge lookup | FTS | "
        "1-hop | retrieval | FAST ctx | DEEP ctx"
    )
    print("---:|---:|---:|---:|---:|---:|---:|---:|---:|---:")
    for item in report["results"]:
        latency = item["latency"]
        def pair(name):
            metric = latency[name]
            return f"{metric['p50_ms']:.3f}/{metric['p95_ms']:.3f}"
        print(
            f"{item['size']} | {pair('memory_create')} | {pair('memory_update')} | "
            f"{pair('entity_lookup')} | {pair('knowledge_lookup')} | "
            f"{pair('fts_memory')} | {pair('relation_1hop')} | {pair('retrieval')} | "
            f"{pair('context_fast')} | {pair('context_deep')}"
        )


def worker_command(size, samples, batch_count):
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-size",
        str(size),
        "--samples",
        str(samples),
        "--batch-count",
        str(batch_count),
    ]


def run_parent(sizes, *, samples, batch_count, output):
    results = []
    for size in sizes:
        print(f"[benchmark] dataset={size}: start", file=sys.stderr, flush=True)
        completed = subprocess.run(
            worker_command(size, samples, batch_count),
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Benchmark worker failed for size {size}")
        payload = completed.stdout.strip().splitlines()
        if not payload:
            raise RuntimeError(f"Benchmark worker returned no result for size {size}")
        result = json.loads(payload[-1])
        results.append(result)
        print(
            f"[benchmark] dataset={size}: done "
            f"wall={result['total']['wall_s']}s "
            f"rss={result['total']['peak_rss_mb']}MB",
            file=sys.stderr,
            flush=True,
        )

    report = {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot": git_head(),
        "environment": environment_record(),
        "sizes": list(sizes),
        "samples": samples,
        "batch_count": batch_count,
        "results": results,
    }

    output = Path(output)
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print_report(report)
    print(f"\nJSON: {output.relative_to(PROJECT_ROOT) if output.is_relative_to(PROJECT_ROOT) else output}")
    return report


def parse_sizes(values):
    sizes = []
    for value in values:
        size = int(value)
        if size < 1:
            raise ValueError("Benchmark sizes must be positive integers")
        if size not in sizes:
            sizes.append(size)
    return sizes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        nargs="+",
        default=[str(value) for value in DEFAULT_SIZES],
        help="Synthetic dataset sizes; default: 1000 10000 100000",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLES,
        help="Latency samples for cheap operations; DEEP Context uses at most 3",
    )
    parser.add_argument(
        "--batch-count",
        type=int,
        default=DEFAULT_BATCH_COUNT,
        help="Number of full EventProcessingCoordinator operations per dataset",
    )
    parser.add_argument(
        "--output",
        default=".benchmarks/stage1-performance.json",
        help="JSON report path",
    )
    parser.add_argument("--worker-size", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        if args.worker_size is not None:
            result = run_dataset(
                args.worker_size,
                samples=args.samples,
                batch_count=args.batch_count,
            )
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0

        sizes = parse_sizes(args.sizes)
        run_parent(
            sizes,
            samples=args.samples,
            batch_count=args.batch_count,
            output=args.output,
        )
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
