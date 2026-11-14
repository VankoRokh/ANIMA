#!/usr/bin/env python3
"""Opt-in comparative FAST/DEEP baseline audit before Stage 7 semantic integration.

Default mode runs the current practical pair with aligned deterministic generation:
Qwen3-0.6B as FAST and SmolLM3-3B as DEEP. --factorial additionally runs both
roles on both models, separating model-size effects from role/prompt effects.

This script never changes production routing and is not executed by normal pytest.
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

from scripts.workspace_paths import models_root, llama_server_binary

from anima.cognition.deep_llm import DeepLLMProfile, build_llama_cpp_deep_backend
from anima.cognition.fast_llm import FastLLMBackend, LlamaCppFastTransport
from anima.cognition.proposals import ProjectedFastProposalAdapter
from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit import (
    AUDIT_VERSION,
    AuditDifficulty,
    default_audit_corpus,
    run_case,
    summarize_results,
)
from anima.ir import plain
from scripts.benchmark_stage5_v2 import MODELS, model_server


MODEL_ORDER = ("Qwen3-0.6B-Q8_0", "SmolLM3-3B-Q8_0")
ALIGNED = {
    "thinking": False,
    "temperature": 0.0,
    "top_k": 40,
    "top_p": 0.8,
    "min_p": 0.05,
    "max_output_tokens": 64,
}


def build_fast(base_url, model, timeout):
    transport = LlamaCppFastTransport(
        base_url=base_url,
        model=model,
        thinking=ALIGNED["thinking"],
        temperature=ALIGNED["temperature"],
        top_k=ALIGNED["top_k"],
        top_p=ALIGNED["top_p"],
        min_p=ALIGNED["min_p"],
        max_output_tokens=ALIGNED["max_output_tokens"],
    )
    return ProjectedFastProposalAdapter(
        FastLLMBackend(transport, timeout_seconds=timeout)
    )


def build_deep(base_url, model, timeout):
    profile = DeepLLMProfile(
        model=model,
        thinking=ALIGNED["thinking"],
        temperature=ALIGNED["temperature"],
        top_k=ALIGNED["top_k"],
        top_p=ALIGNED["top_p"],
        min_p=ALIGNED["min_p"],
        max_output_tokens=ALIGNED["max_output_tokens"],
    )
    return build_llama_cpp_deep_backend(
        base_url=base_url,
        profile=profile,
        timeout_seconds=timeout,
    )


def selected_cases(difficulty):
    corpus = default_audit_corpus()
    if difficulty == "all":
        return corpus
    wanted = AuditDifficulty(difficulty)
    return tuple(case for case in corpus if case.difficulty == wanted)


def run_arm(*, model, role, backend, cases):
    results = [
        run_case(case, role=role, backend=backend)
        for case in cases
    ]
    return {
        "arm": f"{model}:{role.value}",
        "model": model,
        "role": role.value,
        "summary": summarize_results(results),
        "cases": [item.to_dict() for item in results],
    }


def write_markdown(output, arms):
    lines = [
        "# DEEP Baseline Comparative Audit",
        "",
        f"Audit contract: `{AUDIT_VERSION}`. Generation settings are aligned and deterministic.",
        "",
        "| Arm | PASS | Simple | Intermediate | Hard | Abstention | Mean ms | Tokens in/out |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in arms:
        summary = arm["summary"]
        by = summary["by_difficulty"]

        def cell(name):
            item = by[name]
            return f"{item['passes']}/{item['total']}"

        mean = summary["mean_latency_ms"]
        mean_text = f"{mean:.1f}" if isinstance(mean, (int, float)) else "—"
        lines.append(
            f"| {arm['model']} / {arm['role']} | "
            f"{summary['passes']}/{summary['total']} | "
            f"{cell('simple')} | {cell('intermediate')} | {cell('hard')} | "
            f"{summary['abstention_passes']}/{summary['abstention_total']} | "
            f"{mean_text} | {summary['input_tokens']}/{summary['output_tokens']} |"
        )
    lines += [
        "",
        "Interpretation rule: this benchmark is evidence, not an automatic routing change.",
        "A larger model must show a meaningful quality gain on the harder/abstention subsets to justify its additional latency.",
        "Use `--factorial` to separate model effects from FAST/DEEP role-prompt effects.",
    ]
    (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models-root",
        type=Path,
        default=models_root(),
    )
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
        help="Run all 30 cases or one 10-case tier.",
    )
    parser.add_argument(
        "--factorial",
        action="store_true",
        help="Run FAST and DEEP on both models instead of only the practical pair.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".benchmarks" / "deep-baseline-v0"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
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
        relative = MODELS[model_name]
        model_path = args.models_root / relative
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
            else (
                (CognitiveRole.FAST,)
                if model_name == "Qwen3-0.6B-Q8_0"
                else (CognitiveRole.DEEP,)
            )
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
                    print(f"  {role.value}: {len(cases)} cases", flush=True)
                    arm = run_arm(
                        model=model_name,
                        role=role,
                        backend=backend,
                        cases=cases,
                    )
                    arms.append(arm)
                    summary = arm["summary"]
                    mean = summary["mean_latency_ms"]
                    mean_text = (
                        f"{mean:.1f} ms"
                        if isinstance(mean, (int, float))
                        else "n/a"
                    )
                    print(
                        f"  {summary['passes']}/{summary['total']} PASS; "
                        f"abstention {summary['abstention_passes']}/"
                        f"{summary['abstention_total']}; "
                        f"mean {mean_text}; errors {summary['errors']}",
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
        "notes": [
            "Ground truth is fixed before inference.",
            "FAST and DEEP receive the same semantic payload; only consumer/role prompt changes.",
            "No benchmark result changes production routing automatically.",
        ],
    }
    (output / "evidence.json").write_text(
        json.dumps(plain(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_markdown(output, arms)
    print(f"Evidence: {output}", flush=True)
    if setup_errors:
        print(json.dumps(setup_errors, ensure_ascii=False, indent=2), file=sys.stderr)
    runtime_errors = any(arm["summary"]["errors"] for arm in arms)
    return int(bool(setup_errors) or runtime_errors)


if __name__ == "__main__":
    raise SystemExit(main())
