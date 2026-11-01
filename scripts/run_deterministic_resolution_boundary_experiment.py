#!/usr/bin/env python3
"""Test the deterministic-resolution boundary before FAST.

Experimental only. Production code is not modified.

Test L asks one architectural question: after deterministic preprocessing, can
ANIMA decide whether a task has exactly one rule-derived result, or whether a
cognitive choice still remains for FAST?

The resolver is deliberately narrow. It resolves only task classes whose final
answer follows uniquely from explicit machine-checkable rules. If a task is
underspecified, contains a real preference/trade-off, or requires non-formal
interpretation, it returns FAST_REQUIRED instead of guessing.
"""

from __future__ import annotations

import json
import time


DETERMINISTIC_RESULT = "DETERMINISTIC_RESULT"
FAST_REQUIRED = "FAST_REQUIRED"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def _result(route: str, *, value=None, reason: str, candidates=None, derived=None):
    return {
        "route": route,
        "value": value,
        "reason": reason,
        "candidates": list(candidates or ()),
        "derived": derived or {},
    }


def resolve_exact_fact(task: dict) -> dict:
    facts = task.get("facts", ())
    subject = task.get("subject")
    predicate = task.get("predicate")
    matches = [
        fact for fact in facts
        if fact.get("subject") == subject and fact.get("predicate") == predicate
    ]
    if len(matches) == 1:
        return _result(
            DETERMINISTIC_RESULT,
            value=matches[0].get("value"),
            reason="single_exact_semantic_fact",
        )
    if not matches:
        return _result(
            INSUFFICIENT_DATA,
            reason="exact_semantic_fact_absent",
        )
    return _result(
        FAST_REQUIRED,
        reason="multiple_semantic_facts_require_resolution",
        candidates=[fact.get("value") for fact in matches],
    )


def resolve_power_compatibility(task: dict) -> dict:
    values = task.get("values", {})
    required_keys = (
        "power_supply.voltage_v",
        "power_supply.max_current_a",
        "device.required_voltage_v",
        "device.required_current_a",
    )
    if any(key not in values for key in required_keys):
        return _result(INSUFFICIENT_DATA, reason="missing_electrical_requirement")

    psu_voltage = float(values["power_supply.voltage_v"])
    max_current = float(values["power_supply.max_current_a"])
    required_voltage = float(values["device.required_voltage_v"])
    required_current = float(values["device.required_current_a"])
    derived = {
        "voltage_match": psu_voltage == required_voltage,
        "current_sufficient": max_current >= required_current,
        "current_margin_a": max_current - required_current,
    }
    compatible = derived["voltage_match"] and derived["current_sufficient"]
    return _result(
        DETERMINISTIC_RESULT,
        value="YES" if compatible else "NO",
        reason="formal_electrical_constraints",
        derived=derived,
    )


def _filter_actions(task: dict) -> tuple[list[str], dict]:
    state = task.get("state", {})
    options = list(task.get("options", ()))
    valid = []
    rejected = {}

    battery = state.get("battery_percent")
    threshold = state.get("shutdown_threshold_percent")
    task_cost = state.get("estimated_task_cost_percent")
    active_task = bool(state.get("active_task"))
    charger = bool(state.get("charger_available"))
    preserve_task = bool(task.get("preserve_active_task", False))

    projected_after = None
    if isinstance(battery, (int, float)) and isinstance(task_cost, (int, float)):
        projected_after = float(battery) - float(task_cost)

    for option in options:
        reasons = []
        if option == "SHUTDOWN" and active_task and preserve_task:
            reasons.append("violates_preserve_active_task")
        if option == "CONNECT_CHARGER" and not charger:
            reasons.append("charger_unavailable")
        if option == "CONTINUE":
            if isinstance(battery, (int, float)) and isinstance(threshold, (int, float)):
                if float(battery) <= float(threshold):
                    reasons.append("already_at_or_below_shutdown_threshold")
                elif projected_after is not None and projected_after <= float(threshold):
                    reasons.append("projected_below_shutdown_threshold")
        if reasons:
            rejected[option] = reasons
        else:
            valid.append(option)

    derived = {
        "projected_battery_after_task_percent": projected_after,
        "valid_options": valid,
        "rejected_options": rejected,
    }
    return valid, derived


def resolve_action_choice(task: dict) -> dict:
    valid, derived = _filter_actions(task)
    if not valid:
        return _result(
            INSUFFICIENT_DATA,
            reason="no_valid_action_after_hard_constraints",
            derived=derived,
        )
    if len(valid) == 1:
        return _result(
            DETERMINISTIC_RESULT,
            value=valid[0],
            reason="single_action_survives_hard_constraints",
            derived=derived,
        )

    # A formal dominance rule is allowed only when the task explicitly declares it.
    dominance = task.get("dominance_rule")
    if dominance == "prefer_continue_when_safe" and "CONTINUE" in valid:
        return _result(
            DETERMINISTIC_RESULT,
            value="CONTINUE",
            reason="explicit_dominance_rule",
            derived=derived,
        )

    return _result(
        FAST_REQUIRED,
        reason="multiple_valid_actions_require_preference_or_tradeoff",
        candidates=valid,
        derived=derived,
    )


def resolve_task(task: dict) -> dict:
    started = time.perf_counter()
    operation = task.get("operation")
    if operation == "QUERY_FACT":
        result = resolve_exact_fact(task)
    elif operation == "POWER_COMPATIBILITY":
        result = resolve_power_compatibility(task)
    elif operation == "CHOOSE_ACTION":
        result = resolve_action_choice(task)
    elif operation == "RESOLVE_CONFLICT":
        result = _result(
            FAST_REQUIRED,
            reason="conflict_policy_not_deterministic_in_test_l",
            candidates=[fact.get("value") for fact in task.get("facts", ())],
        )
    else:
        result = _result(
            FAST_REQUIRED,
            reason="unsupported_operation_requires_cognitive_route",
        )
    return {
        **result,
        "latency_ms": (time.perf_counter() - started) * 1000.0,
    }


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
    },
    {
        "id": "power_compatible",
        "task": {
            "operation": "POWER_COMPATIBILITY",
            "values": {
                "power_supply.voltage_v": 5,
                "power_supply.max_current_a": 3,
                "device.required_voltage_v": 5,
                "device.required_current_a": 2,
            },
        },
        "expected_route": DETERMINISTIC_RESULT,
        "expected_value": "YES",
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
    },
    {
        "id": "continue_safe_explicit_rule",
        "task": {
            "operation": "CHOOSE_ACTION",
            "state": {
                "battery_percent": 86,
                "shutdown_threshold_percent": 10,
                "estimated_task_cost_percent": 4,
                "active_task": True,
                "charger_available": False,
            },
            "preserve_active_task": True,
            "options": ["CONTINUE", "SHUTDOWN"],
            "dominance_rule": "prefer_continue_when_safe",
        },
        "expected_route": DETERMINISTIC_RESULT,
        "expected_value": "CONTINUE",
    },
    {
        "id": "single_valid_action",
        "task": {
            "operation": "CHOOSE_ACTION",
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
    },
    {
        "id": "multiple_safe_actions",
        "task": {
            "operation": "CHOOSE_ACTION",
            "state": {
                "battery_percent": 55,
                "shutdown_threshold_percent": 10,
                "estimated_task_cost_percent": 5,
                "active_task": False,
                "charger_available": True,
            },
            "preserve_active_task": False,
            "options": ["CONTINUE", "CONNECT_CHARGER"],
        },
        "expected_route": FAST_REQUIRED,
        "expected_value": None,
    },
    {
        "id": "conflicting_facts",
        "task": {
            "operation": "RESOLVE_CONFLICT",
            "facts": [
                {"subject": "device", "predicate": "status", "value": "online", "confidence": 0.99},
                {"subject": "device", "predicate": "status", "value": "offline", "confidence": 0.25},
            ],
        },
        "expected_route": FAST_REQUIRED,
        "expected_value": None,
    },
    {
        "id": "unsupported_open_task",
        "task": {
            "operation": "PLAN",
            "goal": "organize work efficiently",
        },
        "expected_route": FAST_REQUIRED,
        "expected_value": None,
    },
)


def run_case(case: dict) -> dict:
    result = resolve_task(case["task"])
    passed = (
        result["route"] == case["expected_route"]
        and result.get("value") == case["expected_value"]
    )
    false_deterministic = (
        result["route"] == DETERMINISTIC_RESULT
        and case["expected_route"] != DETERMINISTIC_RESULT
    )
    missed_deterministic = (
        result["route"] != DETERMINISTIC_RESULT
        and case["expected_route"] == DETERMINISTIC_RESULT
    )
    return {
        "id": case["id"],
        "expected_route": case["expected_route"],
        "expected_value": case["expected_value"],
        "actual_route": result["route"],
        "actual_value": result.get("value"),
        "reason": result["reason"],
        "candidates": result.get("candidates", []),
        "derived": result.get("derived", {}),
        "latency_ms": result["latency_ms"],
        "false_deterministic": false_deterministic,
        "missed_deterministic": missed_deterministic,
        "passed": passed,
    }


def run_experiment() -> dict:
    rows = [run_case(case) for case in CASES]
    total_latency = sum(row["latency_ms"] for row in rows)
    return {
        "experiment": "deterministic_resolution_boundary_v0",
        "purpose": "Test safe routing between deterministic resolution, insufficient data, and FAST-required tasks",
        "production_modified": False,
        "llm_enabled": False,
        "cases": rows,
        "summary": {
            "total": len(rows),
            "passed": sum(1 for row in rows if row["passed"]),
            "pass_rate": sum(1 for row in rows if row["passed"]) / len(rows),
            "false_deterministic": sum(1 for row in rows if row["false_deterministic"]),
            "missed_deterministic": sum(1 for row in rows if row["missed_deterministic"]),
            "deterministic_results": sum(1 for row in rows if row["actual_route"] == DETERMINISTIC_RESULT),
            "fast_required": sum(1 for row in rows if row["actual_route"] == FAST_REQUIRED),
            "insufficient_data": sum(1 for row in rows if row["actual_route"] == INSUFFICIENT_DATA),
            "latency_ms": total_latency,
            "mean_latency_ms": total_latency / len(rows),
        },
    }


def main() -> int:
    result = run_experiment()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["summary"]["passed"] == result["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
