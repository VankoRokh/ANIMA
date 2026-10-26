#!/usr/bin/env python3
"""Measure Stage 2 Choice performance for 2/10/100 Candidates.

The benchmark separates three costs:
- base: base-score ranking only;
- state_modifiers: bounded Internal State scoring without diagnostic trace;
- full_trace_history: production ChoiceEngine.choose() plus bounded history read.

Setup and synthetic state/history seeding are outside measured operations.
"""

import argparse
import gc
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
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from anima.internal_state.choice_engine import Candidate, ChoiceEngine
from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore
from anima.internal_state.variables import StateName


BENCHMARK_VERSION = 1
DEFAULT_CANDIDATE_COUNTS = (2, 10, 100)
DEFAULT_SAMPLES = 100
DEFAULT_WARMUP = 10
HISTORY_LIMIT = 20
MODES = ("base", "state_modifiers", "full_trace_history")
SEED_TIMESTAMP = "2026-01-01T00:00:00+00:00"


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
    }


def candidate_set(count):
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("Candidate count must be a positive integer")

    candidates = []
    for index in range(count):
        ratio_a = ((index * 17 + 3) % 101) / 100.0
        ratio_b = ((index * 29 + 11) % 101) / 100.0
        ratio_c = ((index * 43 + 7) % 101) / 100.0
        ratio_d = ((index * 61 + 19) % 101) / 100.0
        ratio_e = ((index * 73 + 23) % 101) / 100.0
        ratio_f = ((index * 89 + 31) % 101) / 100.0

        candidates.append(
            Candidate(
                candidate_id=f"candidate_{index:04d}",
                base_score=0.15 + (0.75 * ratio_a),
                effort_cost=ratio_b,
                information_gain=ratio_c,
                irreversible_risk=ratio_d,
                repeated_failure=ratio_e,
                alternative_value=ratio_f,
                verified_continuation=ratio_a,
            )
        )
    return tuple(candidates)


def _seed_state(store):
    values = {
        "fatigue": 0.60,
        "uncertainty": 0.70,
        "frustration": 0.50,
        "satisfaction": 0.40,
    }
    for state_name, value in values.items():
        store.apply_state_transition(
            state_name=state_name,
            delta=value,
            cause_type="benchmark_setup",
            source_id=f"benchmark_seed_{state_name}",
            rule_id=f"benchmark.seed.{state_name}",
            reason="seed non-neutral Stage 2 decision benchmark state",
            timestamp=SEED_TIMESTAMP,
        )

    remaining = HISTORY_LIMIT - len(values)
    for index in range(remaining):
        store.apply_state_transition(
            state_name="fatigue",
            delta=0.0,
            cause_type="benchmark_setup",
            source_id=f"benchmark_history_{index:02d}",
            rule_id="benchmark.history",
            reason="seed bounded diagnostic history",
            timestamp=SEED_TIMESTAMP,
        )


def _setup(workdir):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    store = InternalStateStore(workdir / "internal_state.db")
    goals = GoalStore(store)
    _seed_state(store)
    goal = goals.create_goal(
        source="benchmark",
        priority=1.0,
        description="Stage 2 decision performance goal",
        success_criterion="benchmark completes",
        reason="benchmark setup",
        timestamp=SEED_TIMESTAMP,
    )
    engine = ChoiceEngine(store, goal_store=goals)
    return store, engine, goal["id"]


def base_evaluate(candidates):
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            -float(candidate.base_score),
            candidate.candidate_id,
        ),
    )
    return {
        "selected_candidate_id": ranked[0].candidate_id,
        "scores": tuple(
            (candidate.candidate_id, float(candidate.base_score))
            for candidate in ranked
        ),
    }


def _activation(engine, state_name, snapshot):
    definition = engine.registry.get(state_name)
    baseline = float(definition.baseline)
    maximum = float(definition.maximum)
    value = float(snapshot[state_name.value])
    if value <= baseline or maximum <= baseline:
        return 0.0
    return (value - baseline) / (maximum - baseline)


def modifier_evaluate(engine, candidates, snapshot):
    weights = engine.rules["weights"]
    activations = {
        state_name: _activation(engine, state_name, snapshot)
        for state_name in StateName
    }

    evaluations = []
    for candidate in candidates:
        modifier_total = (
            -activations[StateName.FATIGUE]
            * candidate.effort_cost
            * float(weights["fatigue_effort"])
            + activations[StateName.UNCERTAINTY]
            * candidate.information_gain
            * float(weights["uncertainty_information_gain"])
            - activations[StateName.UNCERTAINTY]
            * candidate.irreversible_risk
            * float(weights["uncertainty_irreversible_risk"])
            - activations[StateName.FRUSTRATION]
            * candidate.repeated_failure
            * float(weights["frustration_repeated_failure"])
            + activations[StateName.FRUSTRATION]
            * candidate.alternative_value
            * float(weights["frustration_alternative"])
            + activations[StateName.SATISFACTION]
            * candidate.verified_continuation
            * float(weights["satisfaction_verified_continuation"])
        )
        unclamped = float(candidate.base_score) + modifier_total
        final_score = min(
            float(engine.rules["score_maximum"]),
            max(float(engine.rules["score_minimum"]), unclamped),
        )
        evaluations.append(
            (
                candidate.candidate_id,
                final_score,
                float(candidate.base_score),
            )
        )

    ranked = sorted(
        evaluations,
        key=lambda item: (-item[1], -item[2], item[0]),
    )
    return {
        "selected_candidate_id": ranked[0][0],
        "scores": tuple((item[0], item[1]) for item in ranked),
    }


def full_evaluate(store, engine, goal_id, candidates):
    choice = engine.choose(goal_id, candidates)
    history = store.list_state_transitions(limit=HISTORY_LIMIT)
    return {
        "selected_candidate_id": choice["selected_candidate_id"],
        "choice": choice,
        "history_count": len(history),
    }


def _operation(mode, store, engine, goal_id, candidates):
    if mode == "base":
        return lambda: base_evaluate(candidates)
    if mode == "state_modifiers":
        snapshot = engine._state_snapshot()
        return lambda: modifier_evaluate(engine, candidates, snapshot)
    if mode == "full_trace_history":
        return lambda: full_evaluate(store, engine, goal_id, candidates)
    raise ValueError(f"Unknown benchmark mode: {mode!r}")


def measure_operation(operation, *, samples, warmup):
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
        raise ValueError("Benchmark samples must be a positive integer")
    if not isinstance(warmup, int) or isinstance(warmup, bool) or warmup < 0:
        raise ValueError("Benchmark warmup must be a non-negative integer")

    for _ in range(warmup):
        operation()

    wall_ns = []
    cpu_ns = []
    output = None
    for _ in range(samples):
        wall_started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        output = operation()
        cpu_ns.append(time.process_time_ns() - cpu_started)
        wall_ns.append(time.perf_counter_ns() - wall_started)

    gc.collect()
    tracemalloc.start()
    operation()
    _, allocation_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "latency": duration_summary_ns(wall_ns),
        "cpu": duration_summary_ns(cpu_ns),
        "memory": {
            "python_allocation_peak_kib": round(allocation_peak / 1024, 3),
            "process_peak_rss_mb": peak_rss_mb(),
        },
        "output": output,
    }


def run_case(
    candidate_count,
    mode,
    *,
    samples=DEFAULT_SAMPLES,
    warmup=DEFAULT_WARMUP,
    workdir=None,
):
    if mode not in MODES:
        raise ValueError(f"Unknown benchmark mode: {mode!r}")

    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="anima-stage2-benchmark-") as temp_dir:
            return run_case(
                candidate_count,
                mode,
                samples=samples,
                warmup=warmup,
                workdir=temp_dir,
            )

    candidates = candidate_set(candidate_count)
    store, engine, goal_id = _setup(workdir)
    operation = _operation(mode, store, engine, goal_id, candidates)
    measured = measure_operation(
        operation,
        samples=samples,
        warmup=warmup,
    )
    output = measured.pop("output")

    return {
        "candidate_count": candidate_count,
        "mode": mode,
        "samples": samples,
        "warmup": warmup,
        "selected_candidate_id": output["selected_candidate_id"],
        "history_limit": HISTORY_LIMIT if mode == "full_trace_history" else 0,
        "history_records": output.get("history_count", 0),
        **measured,
    }


def run_matrix(
    candidate_counts,
    *,
    samples=DEFAULT_SAMPLES,
    warmup=DEFAULT_WARMUP,
    workdir,
):
    root = Path(workdir)
    results = []
    for candidate_count in candidate_counts:
        candidate_set(candidate_count)
        for mode in MODES:
            results.append(
                run_case(
                    candidate_count,
                    mode,
                    samples=samples,
                    warmup=warmup,
                    workdir=root / f"{candidate_count}-{mode}",
                )
            )
    return results


def worker_command(candidate_count, mode, samples, warmup):
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-count",
        str(candidate_count),
        "--worker-mode",
        mode,
        "--samples",
        str(samples),
        "--warmup",
        str(warmup),
    ]


def run_parent(candidate_counts, *, samples, warmup, output):
    results = []
    for candidate_count in candidate_counts:
        for mode in MODES:
            print(
                f"[benchmark] candidates={candidate_count} mode={mode}: start",
                file=sys.stderr,
                flush=True,
            )
            completed = subprocess.run(
                worker_command(candidate_count, mode, samples, warmup),
                cwd=PROJECT_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Benchmark worker failed: candidates={candidate_count} mode={mode}"
                )
            lines = completed.stdout.strip().splitlines()
            if not lines:
                raise RuntimeError("Benchmark worker returned no result")
            result = json.loads(lines[-1])
            results.append(result)
            print(
                f"[benchmark] candidates={candidate_count} mode={mode}: "
                f"p95={result['latency']['p95_ms']}ms "
                f"rss={result['memory']['process_peak_rss_mb']}MB",
                file=sys.stderr,
                flush=True,
            )

    report = {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot": git_head(),
        "environment": environment_record(),
        "candidate_counts": list(candidate_counts),
        "modes": list(MODES),
        "samples": samples,
        "warmup": warmup,
        "history_limit": HISTORY_LIMIT,
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
    label = (
        output_path.relative_to(PROJECT_ROOT)
        if output_path.is_relative_to(PROJECT_ROOT)
        else output_path
    )
    print(f"\nJSON: {label}")
    return report


def print_report(report):
    print("\nStage 2 Decision Performance baseline")
    print(
        "Candidates | Mode               | p50 ms   | p95 ms   | "
        "CPU p95 ms | Alloc KiB | Peak RSS MB"
    )
    print("-" * 91)
    for result in report["results"]:
        print(
            f"{result['candidate_count']:>10} | "
            f"{result['mode']:<18} | "
            f"{result['latency']['p50_ms']:>8.4f} | "
            f"{result['latency']['p95_ms']:>8.4f} | "
            f"{result['cpu']['p95_ms']:>10.4f} | "
            f"{result['memory']['python_allocation_peak_kib']:>9.3f} | "
            f"{result['memory']['process_peak_rss_mb']:>11.3f}"
        )


def parse_candidate_counts(values):
    counts = []
    for value in values:
        count = int(value)
        if count < 1:
            raise ValueError("Candidate counts must be positive integers")
        if count not in counts:
            counts.append(count)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-counts",
        nargs="+",
        default=[str(value) for value in DEFAULT_CANDIDATE_COUNTS],
        help="Candidate counts; default: 2 10 100",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLES,
        help=f"Measured iterations per case; default: {DEFAULT_SAMPLES}",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=DEFAULT_WARMUP,
        help=f"Warmup iterations per case; default: {DEFAULT_WARMUP}",
    )
    parser.add_argument(
        "--output",
        default=".benchmarks/stage2-decision-performance.json",
        help="JSON report path",
    )
    parser.add_argument("--worker-count", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker-mode", choices=MODES, help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        if args.worker_count is not None or args.worker_mode is not None:
            if args.worker_count is None or args.worker_mode is None:
                raise ValueError(
                    "Benchmark worker requires both --worker-count and --worker-mode"
                )
            result = run_case(
                args.worker_count,
                args.worker_mode,
                samples=args.samples,
                warmup=args.warmup,
            )
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0

        candidate_counts = parse_candidate_counts(args.candidate_counts)
        run_parent(
            candidate_counts,
            samples=args.samples,
            warmup=args.warmup,
            output=args.output,
        )
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
