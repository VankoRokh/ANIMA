#!/usr/bin/env python3
"""Neutral model-only control for the cognitive baseline audit.

Both models receive the same evidence and the same role-neutral semantic
classification prompt. No ordered candidate list is supplied. Taxonomy definition
order is counterbalanced across cases so a fixed first-label preference cannot
dominate the corpus. Production routing is unchanged.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.workspace_paths import models_root, llama_server_binary

from anima.cognition.llm_transport import LlamaCppTransport
from anima.experiments.deep_audit import AuditDifficulty
from anima.experiments.deep_audit_v02 import (
    RELATION_LABELS,
    RESOLUTION_LABELS,
    default_audit_corpus,
)
from anima.ir import plain
from scripts.benchmark_deep_baseline import ALIGNED, MODEL_ORDER, MODELS, model_server


CONTROL_VERSION = "deep-baseline-v0.2-neutral-control"

_RELATION_DEFINITIONS = {
    "SUPPORT": "compatible evidence supports the same claim",
    "TEMPORAL_CHANGE": "different values are compatible at different validity times",
    "CORRECTION": "evidence explicitly shows an earlier claim was wrong for its claimed period",
    "CONTRADICTION": "incompatible evidence applies to the same entity, predicate and time",
    "INSUFFICIENT": "evidence does not safely establish any of the other relations",
}
_RESOLUTION_DEFINITIONS = {
    "RESOLVED": "the semantic relationship is sufficiently established",
    "UNRESOLVED": "the evidence is insufficient to resolve the semantic relationship",
}

_NEUTRAL_SYSTEM = (
    "You are a bounded semantic evidence classifier with no authority over persistent "
    "system state. Use only the supplied evidence. Do not invent facts and do not "
    "decide by source name, confidence, recency, or source count alone. Return only "
    "the requested final classification, without explanation."
)

_OUTPUT_RE = re.compile(
    r"^\s*RELATION\s*=\s*(SUPPORT|TEMPORAL_CHANGE|CORRECTION|CONTRADICTION|INSUFFICIENT)\s*;\s*"
    r"RESOLUTION\s*=\s*(RESOLVED|UNRESOLVED)\s*[.!]?\s*$",
    re.IGNORECASE,
)


def taxonomy_order(case_index, *, reversed_order=False):
    relations = list(RELATION_LABELS)
    resolutions = list(RESOLUTION_LABELS)
    reverse = (case_index % 2 == 1) ^ bool(reversed_order)
    if reverse:
        relations.reverse()
        resolutions.reverse()
    return tuple(relations), tuple(resolutions)


def render_prompts(case, case_index, *, reversed_order=False):
    relations, resolutions = taxonomy_order(
        case_index, reversed_order=reversed_order
    )
    relation_text = "; ".join(
        f"{label}: {_RELATION_DEFINITIONS[label]}" for label in relations
    )
    resolution_text = "; ".join(
        f"{label}: {_RESOLUTION_DEFINITIONS[label]}" for label in resolutions
    )
    instruction = (
        "Classify two independent axes. "
        f"RELATION labels: {relation_text}. "
        f"RESOLUTION labels: {resolution_text}. "
        "Return exactly RELATION=<label>;RESOLUTION=<label>."
    )
    payload = {
        "operation": "CLASSIFY_SEMANTIC_EVIDENCE",
        "input": instruction,
        "audit_version": CONTROL_VERSION,
        "audit_case": case.case_id,
        "evidence": [plain(item) for item in case.evidence],
    }
    return _NEUTRAL_SYSTEM, "TASK_VIEW:\n" + json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _first_label(text, labels):
    if not isinstance(text, str):
        return None
    upper = text.upper()
    for label in labels:
        if re.search(
            rf"(?<![A-Z0-9_]){re.escape(label)}(?![A-Z0-9_])",
            upper,
        ):
            return label
    return None


def parse_output(text):
    if not isinstance(text, str):
        return None, None, False
    match = _OUTPUT_RE.match(text)
    if match:
        return match.group(1).upper(), match.group(2).upper(), True
    return (
        _first_label(text, RELATION_LABELS),
        _first_label(text, RESOLUTION_LABELS),
        False,
    )


def selected_cases(difficulty):
    corpus = default_audit_corpus()
    if difficulty == "all":
        return corpus
    wanted = AuditDifficulty(difficulty)
    return tuple(case for case in corpus if case.difficulty == wanted)


def build_transport(base_url, model):
    return LlamaCppTransport(
        base_url=base_url,
        model=model,
        thinking=ALIGNED["thinking"],
        temperature=ALIGNED["temperature"],
        top_k=ALIGNED["top_k"],
        top_p=ALIGNED["top_p"],
        min_p=ALIGNED["min_p"],
        max_output_tokens=ALIGNED["max_output_tokens"],
    )


def run_case(case, case_index, *, transport, timeout, reversed_order=False):
    system_prompt, user_prompt = render_prompts(
        case, case_index, reversed_order=reversed_order
    )
    started = time.perf_counter()
    error = None
    response = None
    call = None
    try:
        call = transport.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=timeout,
        )
        response = call.text
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - started) * 1000.0
    if call is not None and isinstance(call.latency_ms, (int, float)):
        latency_ms = float(call.latency_ms)

    relation, resolution, exact = parse_output(response)
    return {
        "case_id": case.case_id,
        "difficulty": case.difficulty.value,
        "category": case.category,
        "expected_relation": case.expected_relation,
        "expected_resolution": case.expected_resolution,
        "response": response,
        "parsed_relation": relation,
        "parsed_resolution": resolution,
        "relation_correct": error is None and relation == case.expected_relation,
        "resolution_correct": error is None and resolution == case.expected_resolution,
        "semantic_pair_correct": (
            error is None
            and relation == case.expected_relation
            and resolution == case.expected_resolution
        ),
        "exact_format": bool(exact),
        "latency_ms": latency_ms,
        "input_tokens": getattr(call, "input_tokens", None) if call else None,
        "output_tokens": getattr(call, "output_tokens", None) if call else None,
        "error": error,
    }


def summarize(rows):
    latencies = [row["latency_ms"] for row in rows if row["error"] is None]
    return {
        "total": len(rows),
        "relation_passes": sum(row["relation_correct"] for row in rows),
        "resolution_passes": sum(row["resolution_correct"] for row in rows),
        "semantic_pair_passes": sum(row["semantic_pair_correct"] for row in rows),
        "exact_format": sum(row["exact_format"] for row in rows),
        "errors": sum(row["error"] is not None for row in rows),
        "mean_latency_ms": statistics.mean(latencies) if latencies else None,
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "input_tokens": sum(row["input_tokens"] or 0 for row in rows),
        "output_tokens": sum(row["output_tokens"] or 0 for row in rows),
    }


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
        default="simple",
    )
    parser.add_argument(
        "--both-orders",
        action="store_true",
        help="Run each model twice with the counterbalance assignment inverted.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            ROOT / ".benchmarks" / "deep-baseline-v02-neutral-control"
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
        print(f"Starting {model_name} / NEUTRAL", flush=True)
        try:
            with model_server(
                args.server_binary,
                model_path,
                model_name,
                model_output,
                args.port,
            ) as server:
                transport = build_transport(server["base_url"], model_name)
                variants = (False, True) if args.both_orders else (False,)
                for reversed_order in variants:
                    rows = [
                        run_case(
                            case,
                            case_index,
                            transport=transport,
                            timeout=args.timeout,
                            reversed_order=reversed_order,
                        )
                        for case_index, case in enumerate(cases)
                    ]
                    summary = summarize(rows)
                    label = "counterbalance-B" if reversed_order else "counterbalance-A"
                    arms.append({
                        "arm": f"{model_name}:NEUTRAL:{label}",
                        "model": model_name,
                        "role": "NEUTRAL",
                        "counterbalance": label,
                        "summary": summary,
                        "cases": rows,
                    })
                    print(
                        f"  {label}: relation {summary['relation_passes']}/{summary['total']}; "
                        f"resolution {summary['resolution_passes']}/{summary['total']}; "
                        f"pair {summary['semantic_pair_passes']}/{summary['total']}; "
                        f"exact-format {summary['exact_format']}/{summary['total']}; "
                        f"mean {summary['mean_latency_ms']:.1f} ms; errors {summary['errors']}",
                        flush=True,
                    )
        except Exception as error:
            setup_errors.append({
                "model": model_name,
                "type": type(error).__name__,
                "message": str(error),
            })

    report = {
        "benchmark": "deep-baseline-neutral-model-control",
        "control_version": CONTROL_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "difficulty": args.difficulty,
        "both_orders": args.both_orders,
        "aligned_generation": dict(ALIGNED),
        "cases": len(cases),
        "arms": arms,
        "setup_errors": setup_errors,
        "notes": [
            "No cognitive role identity is present in the system prompt.",
            "No ordered candidate list is present in TASK_VIEW.",
            "Taxonomy definition order is counterbalanced across cases.",
        ],
    }
    (output / "evidence.json").write_text(
        json.dumps(plain(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Evidence: {output}", flush=True)
    return int(bool(setup_errors))


if __name__ == "__main__":
    raise SystemExit(main())
