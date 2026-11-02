#!/usr/bin/env python3
"""Run only the missing cross-role arms for the v0.2 FAST/DEEP audit.

Existing evidence already covers the practical pair:
- Qwen3-0.6B as FAST
- SmolLM3-3B as DEEP

This script adds the two missing role/model combinations on the same 10 simple
cases and runs each under both original and reversed candidate order:
- Qwen3-0.6B as DEEP
- SmolLM3-3B as FAST

Together with the existing practical-pair evidence, this separates model effects,
role-prompt effects and candidate-order sensitivity without rerunning all four arms.
Production routing is never changed.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit import AuditDifficulty
from anima.experiments.deep_audit_v02 import CANDIDATES, default_audit_corpus
from anima.ir import plain
from scripts.benchmark_deep_baseline import (
    ALIGNED,
    MODELS,
    build_deep,
    build_fast,
    model_server,
)
from scripts.benchmark_deep_order_probe import run_case
import scripts.benchmark_deep_baseline_v02 as v02


EXPERIMENT_VERSION = "deep-baseline-v0.2-cross-role-order"
CROSS_ARMS = (
    ("Qwen3-0.6B-Q8_0", CognitiveRole.DEEP),
    ("SmolLM3-3B-Q8_0", CognitiveRole.FAST),
)
ORDERS = {
    "original": tuple(CANDIDATES),
    "reverse": tuple(reversed(CANDIDATES)),
}


def selected_cases():
    return tuple(
        case
        for case in default_audit_corpus()
        if case.difficulty == AuditDifficulty.SIMPLE
    )


def response_counts(rows):
    counts = {}
    for row in rows:
        value = row.get("exact_candidate") or "<non-exact>"
        counts[value] = counts.get(value, 0) + 1
    return counts


def build_backend(role, *, base_url, model, timeout):
    if role == CognitiveRole.FAST:
        return build_fast(base_url, model, timeout)
    if role == CognitiveRole.DEEP:
        return build_deep(base_url, model, timeout)
    raise ValueError(f"unsupported cognitive role: {role}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models-root", type=Path, default=Path.home() / "Projects/models"
    )
    parser.add_argument(
        "--server-binary",
        type=Path,
        default=Path.home() / "Projects/llama.cpp/build/bin/llama-server",
    )
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            ROOT
            / ".benchmarks"
            / "deep-baseline-v02-cross-role-order"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ),
    )
    args = parser.parse_args(argv)

    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be positive and finite")
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    if not args.server_binary.is_file():
        parser.error(f"llama-server not found: {args.server_binary}")

    cases = selected_cases()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    arms = []
    setup_errors = []

    for index, (model_name, role) in enumerate(CROSS_ARMS, start=1):
        model_path = args.models_root / MODELS[model_name]
        model_output = output / f"{index:02d}-{model_name}-{role.value.lower()}"
        model_output.mkdir()
        if not model_path.is_file():
            setup_errors.append({
                "model": model_name,
                "role": role.value,
                "type": "FileNotFoundError",
                "message": f"model unavailable: {model_path}",
            })
            continue

        print(f"Starting {model_name} / {role.value}", flush=True)
        try:
            with model_server(
                args.server_binary,
                model_path,
                model_name,
                model_output,
                args.port,
            ) as server:
                for order_name, candidates in ORDERS.items():
                    backend = build_backend(
                        role,
                        base_url=server["base_url"],
                        model=model_name,
                        timeout=args.timeout,
                    )
                    rows = [
                        run_case(
                            case,
                            role=role,
                            backend=backend,
                            candidates=candidates,
                        )
                        for case in cases
                    ]
                    summary = v02.summarize(rows)
                    arm = {
                        "arm": f"{model_name}:{role.value}:{order_name}",
                        "model": model_name,
                        "role": role.value,
                        "order": order_name,
                        "candidate_order": list(candidates),
                        "summary": summary,
                        "response_counts": response_counts(rows),
                        "cases": rows,
                    }
                    arms.append(arm)
                    print(
                        f"  {order_name}: relation {summary['relation_passes']}/10; "
                        f"resolution {summary['resolution_passes']}/10; "
                        f"pair {summary['semantic_pair_passes']}/10; "
                        f"exact {summary['exact_passes']}/10; "
                        f"mean {summary['mean_latency_ms']:.1f} ms; "
                        f"errors {summary['errors']}",
                        flush=True,
                    )
                    print(
                        "  response counts:",
                        json.dumps(arm["response_counts"], ensure_ascii=False),
                        flush=True,
                    )
        except Exception as error:
            setup_errors.append({
                "model": model_name,
                "role": role.value,
                "type": type(error).__name__,
                "message": str(error),
            })

    report = {
        "benchmark": "deep-baseline-cross-role-order",
        "experiment_version": EXPERIMENT_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "aligned_generation": dict(ALIGNED),
        "cases": len(cases),
        "orders": {name: list(values) for name, values in ORDERS.items()},
        "arms": arms,
        "setup_errors": setup_errors,
        "interpretation": (
            "Combine with existing practical-pair v0.2 original and reverse evidence. "
            "This script intentionally runs only the two missing model/role combinations."
        ),
    }
    (output / "evidence.json").write_text(
        json.dumps(plain(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Evidence: {output}", flush=True)
    if setup_errors:
        print(json.dumps(setup_errors, ensure_ascii=False, indent=2), file=sys.stderr)
    return int(bool(setup_errors))


if __name__ == "__main__":
    raise SystemExit(main())
