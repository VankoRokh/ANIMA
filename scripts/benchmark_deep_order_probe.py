#!/usr/bin/env python3
"""Probe candidate-order sensitivity of FAST/DEEP on the v0.2 simple corpus.

This experiment changes only the order of the five allowed semantic candidates.
It does not change ground truth, evidence, model settings, role prompts, or
production routing. Default order is the exact reverse of v0.2.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition.contracts import CognitiveView
from anima.cognition.proposals import RoutedCognitiveRequest
from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit import AuditDifficulty
from anima.experiments.deep_audit_v02 import (
    AUDIT_VERSION,
    CANDIDATES,
    default_audit_corpus,
)
from anima.ir import plain
from scripts.benchmark_deep_baseline import (
    ALIGNED,
    MODEL_ORDER,
    MODELS,
    build_deep,
    build_fast,
    model_server,
)
import scripts.benchmark_deep_baseline_v02 as v02


PROBE_VERSION = "deep-baseline-v0.2-order-probe"


def ordered_request(case, role, candidates):
    payload = case.view_payload()
    payload["candidates"] = list(candidates)
    payload["audit_version"] = PROBE_VERSION
    return RoutedCognitiveRequest(
        persistent_task_id=f"task_order_{case.case_id}_{role.value}",
        canonical_task_id=f"ct_order_{case.case_id}_{role.value}",
        source_id=f"src_order_{case.case_id}_{role.value}",
        role=role,
        view=CognitiveView(role.value, payload),
    )


def run_case(case, *, role, backend, candidates):
    original = v02.make_request
    try:
        v02.make_request = lambda selected, selected_role: ordered_request(
            selected, selected_role, candidates
        )
        return v02.run_case(case, role=role, backend=backend)
    finally:
        v02.make_request = original


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
        "--order",
        choices=("reverse", "rotate"),
        default="reverse",
        help="reverse: exact reverse; rotate: move original first candidate to last",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            ROOT
            / ".benchmarks"
            / "deep-baseline-v02-order-probe"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ),
    )
    args = parser.parse_args(argv)

    candidates = (
        tuple(reversed(CANDIDATES))
        if args.order == "reverse"
        else tuple(CANDIDATES[1:]) + (CANDIDATES[0],)
    )
    cases = tuple(
        case
        for case in default_audit_corpus()
        if case.difficulty == AuditDifficulty.SIMPLE
    )
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    arms = []
    setup_errors = []

    print("Candidate order:", " -> ".join(candidates), flush=True)
    for index, model_name in enumerate(MODEL_ORDER, start=1):
        model_path = args.models_root / MODELS[model_name]
        model_output = output / f"{index:02d}-{model_name}"
        model_output.mkdir()
        if not model_path.is_file():
            setup_errors.append({
                "model": model_name,
                "type": "FileNotFoundError",
                "message": f"model unavailable: {model_path}",
            })
            continue
        role = (
            CognitiveRole.FAST
            if model_name.startswith("Qwen3")
            else CognitiveRole.DEEP
        )
        print(f"Starting {model_name} / {role.value}", flush=True)
        try:
            with model_server(
                args.server_binary,
                model_path,
                model_name,
                model_output,
                args.port,
            ) as server:
                backend = (
                    build_fast(server["base_url"], model_name, args.timeout)
                    if role == CognitiveRole.FAST
                    else build_deep(server["base_url"], model_name, args.timeout)
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
                arms.append({
                    "arm": f"{model_name}:{role.value}",
                    "model": model_name,
                    "role": role.value,
                    "summary": summary,
                    "cases": rows,
                })
                counts = {}
                for row in rows:
                    candidate = row.get("exact_candidate") or "<non-exact>"
                    counts[candidate] = counts.get(candidate, 0) + 1
                print(
                    f"  relation {summary['relation_passes']}/10; "
                    f"resolution {summary['resolution_passes']}/10; "
                    f"pair {summary['semantic_pair_passes']}/10; "
                    f"exact {summary['exact_passes']}/10; "
                    f"mean {summary['mean_latency_ms']:.1f} ms",
                    flush=True,
                )
                print("  exact response counts:", json.dumps(counts, ensure_ascii=False), flush=True)
        except Exception as error:
            setup_errors.append({
                "model": model_name,
                "type": type(error).__name__,
                "message": str(error),
            })

    report = {
        "benchmark": "deep-baseline-candidate-order-probe",
        "audit_version": AUDIT_VERSION,
        "probe_version": PROBE_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "order_mode": args.order,
        "candidate_order": list(candidates),
        "original_candidate_order": list(CANDIDATES),
        "aligned_generation": dict(ALIGNED),
        "cases": len(cases),
        "arms": arms,
        "setup_errors": setup_errors,
    }
    (output / "evidence.json").write_text(
        json.dumps(plain(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Evidence: {output}", flush=True)
    return int(bool(setup_errors))


if __name__ == "__main__":
    raise SystemExit(main())
