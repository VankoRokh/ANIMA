#!/usr/bin/env python3
"""Run the dual-axis FAST/DEEP baseline audit v0.2.

Default mode compares the current practical pair with aligned deterministic
generation. --factorial runs both FAST and DEEP role prompts on both models.
Production routing is never changed.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.workspace_paths import models_root, llama_server_binary

from anima.cognition.proposals import CognitiveProposal, ProposalKind
from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit import AuditDifficulty
from anima.experiments.deep_audit_v02 import (
    AUDIT_VERSION,
    CANDIDATES,
    default_audit_corpus,
    make_request,
    normalize_exact,
    parse_semantic_axes,
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


def _history(backend):
    history = getattr(backend, "call_history", None)
    if history is not None:
        return history
    wrapped = getattr(backend, "backend", None)
    return getattr(wrapped, "call_history", ())


def run_case(case, *, role, backend):
    request = make_request(case, role)
    history = _history(backend)
    before = len(history)
    started = time.perf_counter()
    response = None
    error = None
    try:
        proposal = backend.complete(request)
        if not isinstance(proposal, CognitiveProposal):
            raise TypeError("audit backend must return CognitiveProposal")
        if proposal.kind != ProposalKind.RESPOND:
            raise ValueError("audit backend must return RESPOND")
        payload = plain(proposal.payload)
        response = payload.get("text") if isinstance(payload, dict) else None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - started) * 1000.0
    input_tokens = None
    output_tokens = None
    history = _history(backend)
    if len(history) > before:
        call = history[-1]
        value = getattr(call, "latency_ms", None)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            latency_ms = float(value)
        input_tokens = getattr(call, "input_tokens", None)
        output_tokens = getattr(call, "output_tokens", None)

    exact = normalize_exact(response)
    relation, resolution = parse_semantic_axes(response)
    expected = case.expected_candidate
    return {
        "case_id": case.case_id,
        "difficulty": case.difficulty.value,
        "category": case.category,
        "expected_candidate": expected,
        "expected_relation": case.expected_relation,
        "expected_resolution": case.expected_resolution,
        "response": response,
        "exact_candidate": exact,
        "parsed_relation": relation,
        "parsed_resolution": resolution,
        "exact_correct": error is None and exact == expected,
        "relation_correct": error is None and relation == case.expected_relation,
        "resolution_correct": error is None and resolution == case.expected_resolution,
        "semantic_pair_correct": (
            error is None
            and relation == case.expected_relation
            and resolution == case.expected_resolution
        ),
        "format_valid": exact in CANDIDATES,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "error": error,
    }


def summarize(rows):
    by_difficulty = {}
    for difficulty in AuditDifficulty:
        selected = [row for row in rows if row["difficulty"] == difficulty.value]
        by_difficulty[difficulty.value] = {
            "relation": sum(row["relation_correct"] for row in selected),
            "resolution": sum(row["resolution_correct"] for row in selected),
            "pair": sum(row["semantic_pair_correct"] for row in selected),
            "exact": sum(row["exact_correct"] for row in selected),
            "total": len(selected),
        }
    valid = [row["latency_ms"] for row in rows if row["error"] is None]
    return {
        "total": len(rows),
        "exact_passes": sum(row["exact_correct"] for row in rows),
        "relation_passes": sum(row["relation_correct"] for row in rows),
        "resolution_passes": sum(row["resolution_correct"] for row in rows),
        "semantic_pair_passes": sum(row["semantic_pair_correct"] for row in rows),
        "format_valid": sum(row["format_valid"] for row in rows),
        "errors": sum(row["error"] is not None for row in rows),
        "mean_latency_ms": statistics.mean(valid) if valid else None,
        "median_latency_ms": statistics.median(valid) if valid else None,
        "input_tokens": sum(row["input_tokens"] or 0 for row in rows),
        "output_tokens": sum(row["output_tokens"] or 0 for row in rows),
        "by_difficulty": by_difficulty,
    }


def selected_cases(difficulty):
    corpus = default_audit_corpus()
    if difficulty == "all":
        return corpus
    wanted = AuditDifficulty(difficulty)
    return tuple(case for case in corpus if case.difficulty == wanted)


def run_arm(*, model, role, backend, cases):
    rows = [run_case(case, role=role, backend=backend) for case in cases]
    return {
        "arm": f"{model}:{role.value}",
        "model": model,
        "role": role.value,
        "summary": summarize(rows),
        "cases": rows,
    }


def write_markdown(output, arms):
    lines = [
        "# DEEP Baseline Comparative Audit v0.2",
        "",
        "Evidence relation and resolution state are scored independently.",
        "",
        "| Arm | Relation | Resolution | Semantic pair | Exact | Format | Mean ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in arms:
        s = arm["summary"]
        mean = s["mean_latency_ms"]
        lines.append(
            f"| {arm['arm']} | {s['relation_passes']}/{s['total']} | "
            f"{s['resolution_passes']}/{s['total']} | "
            f"{s['semantic_pair_passes']}/{s['total']} | "
            f"{s['exact_passes']}/{s['total']} | {s['format_valid']}/{s['total']} | "
            f"{mean:.1f} |"
        )
    lines += [
        "",
        "Exact output is a contract metric, not a substitute for semantic quality.",
        "No result from this experimental audit changes production routing automatically.",
    ]
    (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, default=models_root())
    parser.add_argument(
        "--server-binary",
        type=Path,
        default=llama_server_binary(),
    )
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--difficulty",
        choices=("all", "simple", "intermediate", "hard"),
        default="all",
    )
    parser.add_argument("--factorial", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            ROOT / ".benchmarks" / "deep-baseline-v02"
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

    cases = selected_cases(args.difficulty)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    arms = []
    setup_errors = []

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
        roles = (
            (CognitiveRole.FAST, CognitiveRole.DEEP)
            if args.factorial
            else ((CognitiveRole.FAST,) if model_name.startswith("Qwen3") else (CognitiveRole.DEEP,))
        )
        print(f"Starting {model_name}: {model_path}", flush=True)
        try:
            with model_server(
                args.server_binary,
                model_path,
                model_name,
                model_output,
                args.port,
            ) as server:
                for role in roles:
                    backend = (
                        build_fast(server["base_url"], model_name, args.timeout)
                        if role == CognitiveRole.FAST
                        else build_deep(server["base_url"], model_name, args.timeout)
                    )
                    arm = run_arm(model=model_name, role=role, backend=backend, cases=cases)
                    arms.append(arm)
                    s = arm["summary"]
                    print(
                        f"  {role.value}: relation {s['relation_passes']}/{s['total']}; "
                        f"resolution {s['resolution_passes']}/{s['total']}; "
                        f"pair {s['semantic_pair_passes']}/{s['total']}; "
                        f"exact {s['exact_passes']}/{s['total']}; "
                        f"mean {s['mean_latency_ms']:.1f} ms; errors {s['errors']}",
                        flush=True,
                    )
        except Exception as error:
            setup_errors.append({
                "model": model_name,
                "type": type(error).__name__,
                "message": str(error),
            })

    report = {
        "benchmark": "deep-baseline-comparative-audit",
        "audit_version": AUDIT_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "difficulty": args.difficulty,
        "factorial": args.factorial,
        "aligned_generation": dict(ALIGNED),
        "cases": len(cases),
        "arms": arms,
        "setup_errors": setup_errors,
    }
    (output / "evidence.json").write_text(
        json.dumps(plain(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_markdown(output, arms)
    print(f"Evidence: {output}", flush=True)
    if setup_errors:
        print(json.dumps(setup_errors, ensure_ascii=False, indent=2), file=sys.stderr)
    return int(bool(setup_errors))


if __name__ == "__main__":
    raise SystemExit(main())
