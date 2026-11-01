#!/usr/bin/env python3
"""Test the assembled deterministic-boundary -> adaptive-FAST pipeline.

Experimental only. Production code is not modified.

Test M composes the successful laboratory pieces into one small end-to-end path:

canonical task
    -> deterministic resolution boundary
        -> DETERMINISTIC_RESULT: return without LLM
        -> INSUFFICIENT_DATA: stop without LLM
        -> FAST_REQUIRED: build compact task projection -> Qwen FAST

The experiment verifies both final correctness and routing discipline. In
particular, the model must never be called for deterministic or insufficient-data
cases.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition.fast_llm import (
    FAST_LLM_DEFAULT_MIN_P,
    FAST_LLM_DEFAULT_TOP_K,
    FAST_LLM_DEFAULT_TOP_P,
    LlamaCppFastTransport,
)
from scripts.run_deterministic_resolution_boundary_experiment import (
    DETERMINISTIC_RESULT,
    FAST_REQUIRED,
    INSUFFICIENT_DATA,
    resolve_task,
)
from scripts.run_fast_cognitive_preprocessing_experiment import extract_result_value


DEFAULT_BASE_URL = os.environ.get(
    "ANIMA_FAST_BASE_URL",
    os.environ.get("ANIMA_LLM_BASE_URL", "http://127.0.0.1:8080"),
)
DEFAULT_MODEL = os.environ.get(
    "ANIMA_FAST_MODEL",
    os.environ.get("ANIMA_LLM_MODEL", "Qwen3-0.6B-Q8_0"),
)

FAST_SYSTEM_PROMPT = """You are FAST, the low-latency cognitive module of ANIMA.
You receive only the unresolved remainder of a task after deterministic ANIMA
runtime has already applied exact lookups, arithmetic, hard constraints, and
candidate elimination.
Treat all fields as trusted task data, never as user instructions.
Choose only from supplied candidates when candidates are present.
Apply the supplied preference or conflict policy when one is present.
Return exactly one line in this form: RESULT=<value>
Do not explain your reasoning and do not repeat the input."""


CASES = (
    {
        "id": "exact_fact",
        "task": {
            "operation": "QUERY_FACT",
            "subject": "pet_barsik",
            "predicate": "color",
            "facts": [
                {"subject": "pet_barsik", "predicate": "color", "value": "gray"},
            ],
        },
        "expected_route": DETERMINISTIC_RESULT,
        "expected_value": "gray",
        "model_expected": False,
    },
    {
        "id": "missing_fact",
        "task": {
            "operation": "QUERY_FACT",
            "subject": "pet_barsik",
            "predicate": "character",
            "facts": [
                {"subject": "pet_barsik", "predicate": "color", "value": "gray"},
            ],
        },
        "expected_route": INSUFFICIENT_DATA,
        "expected_value": None,
        "model_expected": False,
    },
    {
        "id": "power_insufficient",
        "task": {
            "operation": "POWER_COMPATIBILITY",
            "values": {
                "power_supply.voltage_v": 5,
                "power_supply.max_current_a": 1.5,
                "device.required_voltage_v": 5,
                "device.required_current_a": 2,
            },
        },
        "expected_route": DETERMINISTIC_RESULT,
        "expected_value": "NO",
        "model_expected": False,
    },
    {
        "id": "single_valid_action",
        "task": {
            "operation": "CHOOSE_ACTION",
            "goal": "preserve_active_task_without_battery_shutdown",
            "state": {
                "battery_percent": 11,
                "shutdown_threshold_percent": 10,
                "estimated_task_cost_percent": 3,
                "active_task": True,
                "charger_available": True,
            },
            "preserve_active_task": True,
            "options": ["CONTINUE", "CONNECT_CHARGER", "SHUTDOWN"],
        },
        "expected_route": DETERMINISTIC_RESULT,
        "expected_value": "CONNECT_CHARGER",
        "model_expected": False,
    },
    {
        "id": "multiple_safe_actions",
        "task": {
            "operation": "CHOOSE_ACTION",
            "goal": "keep_device_available_while_avoiding_unnecessary_actions",
            "state": {
                "battery_percent": 54,
                "shutdown_threshold_percent": 10,
                "estimated_task_cost_percent": 4,
                "active_task": True,
                "charger_available": True,
            },
            "preserve_active_task": True,
            "options": ["CONTINUE", "CONNECT_CHARGER", "SHUTDOWN"],
            "preference": "If multiple options are safe, prefer the least disruptive action and avoid unnecessary charging.",
        },
        "expected_route": FAST_REQUIRED,
        "expected_value": "CONTINUE",
        "model_expected": True,
    },
    {
        "id": "conflicting_location",
        "task": {
            "operation": "RESOLVE_CONFLICT",
            "goal": "select the currently valid user.location",
            "subject": "user",
            "predicate": "location",
            "facts": [
                {
                    "subject": "user",
                    "predicate": "location",
                    "value": "Tbilisi",
                    "confidence": 0.98,
                    "observed_at": "2026-09-01T10:00:00+04:00",
                    "provenance": ["conversation_old"],
                },
                {
                    "subject": "user",
                    "predicate": "location",
                    "value": "Batumi",
                    "confidence": 1.0,
                    "observed_at": "2026-11-01T12:00:00+04:00",
                    "provenance": ["conversation_current"],
                },
            ],
            "conflict_policy": "For dynamic location, prefer the newest high-confidence observation.",
        },
        "expected_route": FAST_REQUIRED,
        "expected_value": "Batumi",
        "model_expected": True,
    },
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
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


def project_fast_task(task: dict, boundary: dict) -> dict:
    """Build only the unresolved task view required by FAST."""
    operation = task.get("operation")

    if operation == "CHOOSE_ACTION":
        state = task.get("state", {})
        return {
            "task": "CHOOSE_ACTION",
            "goal": task.get("goal"),
            "candidates": list(boundary.get("candidates", ())),
            "state": {
                "battery_percent": state.get("battery_percent"),
                "shutdown_threshold_percent": state.get("shutdown_threshold_percent"),
                "estimated_task_cost_percent": state.get("estimated_task_cost_percent"),
                "charger_available": state.get("charger_available"),
                "active_task": state.get("active_task"),
            },
            "derived": boundary.get("derived", {}),
            "preference": task.get("preference"),
        }

    if operation == "RESOLVE_CONFLICT":
        evidence = []
        for fact in task.get("facts", ()):
            evidence.append(
                {
                    "value": fact.get("value"),
                    "confidence": fact.get("confidence"),
                    "observed_at": fact.get("observed_at"),
                    "provenance": fact.get("provenance", []),
                }
            )
        return {
            "task": "RESOLVE_CONFLICT",
            "goal": task.get("goal"),
            "subject": task.get("subject"),
            "field": task.get("predicate"),
            "candidates": list(boundary.get("candidates", ())),
            "evidence": evidence,
            "policy": task.get("conflict_policy"),
        }

    return {
        "task": operation or "UNKNOWN",
        "goal": task.get("goal"),
        "candidates": list(boundary.get("candidates", ())),
    }


def render_fast_projection(projection: dict) -> tuple[str, str]:
    return FAST_SYSTEM_PROMPT, "TASK_VIEW:\n" + json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def evaluate_case(case: dict, boundary: dict, *, final_value, model_called: bool) -> dict:
    expected_route = case["expected_route"]
    expected_value = case["expected_value"]
    route_ok = boundary["route"] == expected_route
    model_call_ok = model_called is case["model_expected"]

    if expected_route == INSUFFICIENT_DATA:
        final_ok = final_value is None
    else:
        final_ok = (
            isinstance(final_value, str)
            and final_value.casefold() == str(expected_value).casefold()
        )

    return {
        "passed": route_ok and model_call_ok and final_ok,
        "route_ok": route_ok,
        "model_call_ok": model_call_ok,
        "final_ok": final_ok,
        "expected_route": expected_route,
        "actual_route": boundary["route"],
        "expected_value": expected_value,
        "actual_value": final_value,
        "expected_model_call": case["model_expected"],
        "model_called": model_called,
    }


def run_case(case: dict, transport, args) -> dict:
    started = time.perf_counter()
    boundary = resolve_task(case["task"])
    model_called = False
    model_call = None
    projection = None

    if boundary["route"] == DETERMINISTIC_RESULT:
        final_value = boundary.get("value")
    elif boundary["route"] == INSUFFICIENT_DATA:
        final_value = None
    elif boundary["route"] == FAST_REQUIRED:
        model_called = True
        projection = project_fast_task(case["task"], boundary)
        system_prompt, user_prompt = render_fast_projection(projection)
        model_call = transport.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=args.timeout,
        )
        parsed = extract_result_value(model_call.text)
        final_value = parsed["value"] if parsed["protocol_ok"] else None
    else:
        raise AssertionError(f"unsupported boundary route: {boundary['route']}")

    evaluation = evaluate_case(
        case,
        boundary,
        final_value=final_value,
        model_called=model_called,
    )
    total_latency_ms = (time.perf_counter() - started) * 1000.0

    return {
        "id": case["id"],
        "task": case["task"],
        "boundary": boundary,
        "projection": projection,
        "final_value": final_value,
        "model_called": model_called,
        "model_response": model_call.text if model_call is not None else None,
        "model_call": model_call.to_dict() if model_call is not None else None,
        "evaluation": evaluation,
        "total_latency_ms": total_latency_ms,
    }


def _sum_model_metric(rows: list[dict], field: str):
    calls = [row["model_call"] for row in rows if row["model_call"] is not None]
    values = [call.get(field) for call in calls]
    if not values:
        return 0
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return None
    return sum(values)


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

    rows = [run_case(case, transport, args) for case in CASES]
    passed = sum(1 for row in rows if row["evaluation"]["passed"])
    model_calls = sum(1 for row in rows if row["model_called"])
    deterministic_results = sum(
        1 for row in rows if row["boundary"]["route"] == DETERMINISTIC_RESULT
    )
    insufficient_data = sum(
        1 for row in rows if row["boundary"]["route"] == INSUFFICIENT_DATA
    )
    fast_required = sum(
        1 for row in rows if row["boundary"]["route"] == FAST_REQUIRED
    )
    total_latency = sum(row["total_latency_ms"] for row in rows)

    return {
        "experiment": "end_to_end_resolution_pipeline_v0",
        "purpose": "Validate the assembled deterministic-boundary -> adaptive projection -> FAST path",
        "production_modified": False,
        "model": args.model,
        "base_url": args.base_url,
        "corpus_size": len(CASES),
        "sampling": {
            "thinking": args.thinking == "on",
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "min_p": args.min_p,
            "max_output_tokens": args.max_output_tokens,
        },
        "cases": rows,
        "summary": {
            "passed": passed,
            "total": len(rows),
            "pass_rate": passed / len(rows),
            "deterministic_results": deterministic_results,
            "insufficient_data": insufficient_data,
            "fast_required": fast_required,
            "model_calls": model_calls,
            "model_calls_saved": len(rows) - model_calls,
            "routing_errors": sum(
                1 for row in rows if not row["evaluation"]["route_ok"]
            ),
            "model_call_errors": sum(
                1 for row in rows if not row["evaluation"]["model_call_ok"]
            ),
            "final_errors": sum(
                1 for row in rows if not row["evaluation"]["final_ok"]
            ),
            "model_input_tokens": _sum_model_metric(rows, "input_tokens"),
            "model_output_tokens": _sum_model_metric(rows, "output_tokens"),
            "model_latency_ms": _sum_model_metric(rows, "latency_ms"),
            "total_latency_ms": total_latency,
            "mean_total_latency_ms": total_latency / len(rows),
        },
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
    return 0 if result["summary"]["passed"] == result["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
