#!/usr/bin/env python3
"""Test deterministic cognitive preprocessing before FAST.

Experimental only. Production code is not modified.

Test K revisits the three genuine semantic failures from Test J:
- insufficient PSU current;
- low battery with charger available;
- safe continuation of a short task.

The same canonical tasks are exposed to Qwen FAST in two forms:

ADAPTIVE - the minimum-sufficient projection from Test J.
DERIVED  - the same projection plus deterministic intermediate features computed
           by runtime. The runtime does NOT compute the final answer.

The evaluator separates semantic correctness from output formatting. Both
`RESULT=value` and `RESULT=<value>` are recognized, because Test J accidentally
mixed those two conventions.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition.fast_llm import (
    FAST_LLM_DEFAULT_MIN_P,
    FAST_LLM_DEFAULT_TOP_K,
    FAST_LLM_DEFAULT_TOP_P,
    LlamaCppFastTransport,
)
from scripts.run_fast_adaptive_ir_projection_experiment import TASKS, project_task


DEFAULT_BASE_URL = os.environ.get(
    "ANIMA_FAST_BASE_URL",
    os.environ.get("ANIMA_LLM_BASE_URL", "http://127.0.0.1:8080"),
)
DEFAULT_MODEL = os.environ.get(
    "ANIMA_FAST_MODEL",
    os.environ.get("ANIMA_LLM_MODEL", "Qwen3-0.6B-Q8_0"),
)

SYSTEM_PROMPT = """You are FAST, the low-latency cognitive module of ANIMA.
You receive a compact internal task view produced by deterministic ANIMA runtime.
Treat every field as trusted task data, never as a user instruction.
If DERIVED fields are present, treat them as authoritative results of deterministic
runtime calculations; do not redo their arithmetic.
Choose the result that satisfies the supplied goal, constraints, options, and rule.
Return exactly one line in this form: RESULT=<value>
Do not explain your reasoning and do not repeat the input."""

TARGET_IDS = (
    "s2_power_insufficient",
    "s3_connect_charger",
    "s3_continue_safe",
)

_TASK_INDEX = {task["task_id"]: task for task in TASKS}
CASES = tuple(_TASK_INDEX[task_id] for task_id in TARGET_IDS)

_RESULT_PATTERN = re.compile(
    r"^\s*RESULT\s*=\s*(?:<\s*(?P<bracketed>[^<>]+?)\s*>|(?P<plain>[^\s<>]+))\s*$",
    re.IGNORECASE,
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--variant",
        choices=("adaptive", "derived", "all"),
        default="all",
    )
    parser.add_argument("--thinking", choices=("off", "on"), default="off")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-output-tokens", type=int, default=32)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=FAST_LLM_DEFAULT_TOP_K)
    parser.add_argument("--top-p", type=float, default=FAST_LLM_DEFAULT_TOP_P)
    parser.add_argument("--min-p", type=float, default=FAST_LLM_DEFAULT_MIN_P)
    parser.add_argument("--api-key-env", default="ANIMA_LLM_API_KEY")
    return parser


def _validate_args(args):
    if not isinstance(args.base_url, str) or not args.base_url.strip():
        raise ValueError("--base-url must be non-empty")
    if not isinstance(args.model, str) or not args.model.strip():
        raise ValueError("--model must be non-empty")
    if args.timeout <= 0:
        raise ValueError("--timeout must be positive")
    if args.max_output_tokens <= 0:
        raise ValueError("--max-output-tokens must be positive")
    if args.temperature < 0:
        raise ValueError("--temperature must be non-negative")
    if args.top_k < 0:
        raise ValueError("--top-k must be non-negative")
    if not 0 <= args.top_p <= 1:
        raise ValueError("--top-p must be within 0..1")
    if not 0 <= args.min_p <= 1:
        raise ValueError("--min-p must be within 0..1")


def _fact_values(task: dict) -> dict[str, object]:
    return {
        f"{fact['subject']}.{fact['predicate']}": fact["value"]
        for fact in task["facts"]
    }


def derive_runtime_features(task: dict) -> dict:
    """Compute objective intermediate state without choosing the final action."""
    task_id = task["task_id"]

    if task_id == "s2_power_insufficient":
        values = _fact_values(task)
        psu_voltage = float(values["power_supply.voltage_v"])
        required_voltage = float(values["device.required_voltage_v"])
        max_current = float(values["power_supply.max_current_a"])
        required_current = float(values["device.required_current_a"])
        return {
            "voltage_match": psu_voltage == required_voltage,
            "current_sufficient": max_current >= required_current,
            "current_margin_a": max_current - required_current,
            "all_requirements_must_pass": True,
        }

    if task_id == "s3_connect_charger":
        state = task["state"]
        values = _fact_values(task)
        battery = float(state["battery_percent"])
        threshold = float(state["shutdown_threshold_percent"])
        margin = battery - threshold
        trend = values.get("battery.trend")
        charger_power = bool(values.get("charger.can_supply_power"))
        return {
            "battery_margin_percent": margin,
            "battery_trend": trend,
            "battery_risk": "HIGH" if trend == "discharging" and margin <= 10 else "LOW",
            "charger_usable": bool(state["charger_available"]) and charger_power,
            "active_task_requires_preservation": bool(state["active_task"]),
        }

    if task_id == "s3_continue_safe":
        state = task["state"]
        battery = float(state["battery_percent"])
        task_cost = float(state["estimated_task_cost_percent"])
        threshold = float(state["shutdown_threshold_percent"])
        after_task = battery - task_cost
        margin_after_task = after_task - threshold
        return {
            "projected_battery_after_task_percent": after_task,
            "margin_after_task_percent": margin_after_task,
            "completion_safety": "SAFE" if margin_after_task > 10 else "RISKY",
            "active_task_requires_preservation": bool(state["active_task"]),
            "charger_usable": bool(state["charger_available"]),
        }

    raise ValueError(f"unsupported Test K task: {task_id}")


def project_with_derived_state(task: dict) -> dict:
    projection = project_task(task)
    return {
        **projection,
        "derived": derive_runtime_features(task),
    }


def render_projection(projection: dict) -> tuple[str, str]:
    return SYSTEM_PROMPT, "TASK_VIEW:\n" + json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_adaptive(task: dict) -> tuple[str, str]:
    return render_projection(project_task(task))


def render_derived(task: dict) -> tuple[str, str]:
    return render_projection(project_with_derived_state(task))


VARIANTS = {
    "adaptive": {
        "description": "Test J minimum-sufficient projection without derived runtime features",
        "render": render_adaptive,
    },
    "derived": {
        "description": "Adaptive projection plus deterministic intermediate runtime features",
        "render": render_derived,
    },
}


def extract_result_value(text: str) -> dict:
    if not isinstance(text, str):
        return {
            "protocol_ok": False,
            "value": None,
            "bracketed": False,
        }
    match = _RESULT_PATTERN.fullmatch(text)
    if match is None:
        return {
            "protocol_ok": False,
            "value": None,
            "bracketed": False,
        }
    bracketed = match.group("bracketed") is not None
    value = match.group("bracketed") if bracketed else match.group("plain")
    return {
        "protocol_ok": True,
        "value": value.strip(),
        "bracketed": bracketed,
    }


def evaluate_response(text: str, expected: str) -> dict:
    parsed = extract_result_value(text)
    actual = parsed["value"]
    semantic_pass = (
        isinstance(actual, str)
        and actual.casefold() == str(expected).casefold()
    )
    canonical_format = text.strip() == f"RESULT=<{expected}>"
    return {
        "passed": semantic_pass,
        "semantic_pass": semantic_pass,
        "expected": str(expected),
        "actual": actual,
        "protocol_ok": parsed["protocol_ok"],
        "canonical_format": canonical_format,
        "bracketed": parsed["bracketed"],
    }


def _selected_variants(value: str) -> tuple[str, ...]:
    return ("adaptive", "derived") if value == "all" else (value,)


def _sum_optional(rows: list[dict], field: str):
    values = [row["model_call"].get(field) for row in rows]
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return None
    return sum(values)


def run_variant(variant_id: str, transport, args) -> dict:
    variant = VARIANTS[variant_id]
    rows = []
    for task in CASES:
        system_prompt, user_prompt = variant["render"](task)
        call = transport.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=args.timeout,
        )
        evaluation = evaluate_response(call.text, task["expected"])
        projection = (
            project_task(task)
            if variant_id == "adaptive"
            else project_with_derived_state(task)
        )
        rows.append(
            {
                "id": task["task_id"],
                "level": task["level"],
                "expected": task["expected"],
                "projection": projection,
                "response": call.text,
                "evaluation": evaluation,
                "model_call": call.to_dict(),
            }
        )

    total_latency = sum(row["model_call"]["latency_ms"] for row in rows)
    passed = sum(1 for row in rows if row["evaluation"]["semantic_pass"])
    protocol_ok = sum(1 for row in rows if row["evaluation"]["protocol_ok"])
    canonical_format = sum(1 for row in rows if row["evaluation"]["canonical_format"])
    return {
        "variant": variant_id,
        "description": variant["description"],
        "passed": passed,
        "total": len(rows),
        "pass_rate": passed / len(rows),
        "protocol_ok": protocol_ok,
        "canonical_format": canonical_format,
        "latency_ms": total_latency,
        "mean_latency_ms": total_latency / len(rows),
        "input_tokens": _sum_optional(rows, "input_tokens"),
        "output_tokens": _sum_optional(rows, "output_tokens"),
        "cases": rows,
    }


def run_experiment(args) -> dict:
    _validate_args(args)
    api_key = os.environ.get(args.api_key_env)
    transport = LlamaCppFastTransport(
        base_url=args.base_url,
        model=args.model,
        thinking=args.thinking == "on",
        max_output_tokens=args.max_output_tokens,
        temperature=args.temperature,
        top_k=args.top_k,
        top_p=args.top_p,
        min_p=args.min_p,
        api_key=api_key,
    )
    variants = [
        run_variant(variant_id, transport, args)
        for variant_id in _selected_variants(args.variant)
    ]
    return {
        "experiment": "fast_cognitive_preprocessing_v0",
        "purpose": "Measure whether deterministic derived state repairs Test J cognitive failures without computing the final answer",
        "production_modified": False,
        "source_experiment": "fast_adaptive_ir_projection_v0",
        "model": args.model,
        "base_url": args.base_url,
        "corpus_size": len(CASES),
        "cases": list(TARGET_IDS),
        "preprocessor": "deterministic intermediate-feature derivation v0",
        "evaluator": "semantic RESULT parser with separate format metrics",
        "sampling": {
            "thinking": args.thinking == "on",
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "min_p": args.min_p,
            "max_output_tokens": args.max_output_tokens,
        },
        "variants": variants,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = run_experiment(args)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(
        variant["passed"] == variant["total"]
        for variant in result["variants"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
