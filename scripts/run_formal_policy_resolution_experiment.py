#!/usr/bin/env python3
"""Test formal policy resolution after hard action constraints.

Experimental only. Production code is not modified.

Test M1 closes the last routing gap exposed by Test M: when several actions
survive hard constraints, ANIMA should not send an already-formalized preference
to FAST as natural language. A machine-readable policy may resolve the choice
deterministically; absent or conflicting policies must leave the choice to FAST.
"""

from __future__ import annotations

import json
import time

from scripts.run_deterministic_resolution_boundary_experiment import (
    DETERMINISTIC_RESULT,
    FAST_REQUIRED,
    _filter_actions,
)


POLICY_ACTION_PRIORITY = "ACTION_PRIORITY"


def _result(route: str, *, value=None, reason: str, candidates=None, derived=None):
    return {
        "route": route,
        "value": value,
        "reason": reason,
        "candidates": list(candidates or ()),
        "derived": derived or {},
    }


def _priority_policy_winner(policy: dict, candidates: list[str]) -> str | None:
    """Return a unique winner only for a complete, well-formed priority policy."""
    if policy.get("type") != POLICY_ACTION_PRIORITY:
        return None

    priority = policy.get("priority")
    if not isinstance(priority, list) or not priority:
        return None
    if not all(isinstance(item, str) and item for item in priority):
        return None
    if len(priority) != len(set(priority)):
        return None

    candidate_set = set(candidates)
    priority_set = set(priority)
    if not candidate_set.issubset(priority_set):
        return None

    for action in priority:
        if action in candidate_set:
            return action
    return None


def resolve_formal_action_policy(task: dict) -> dict:
    """Resolve multiple valid actions only when formal policies agree uniquely."""
    started = time.perf_counter()
    valid, constraint_derived = _filter_actions(task)

    if len(valid) <= 1:
        # M1 is specifically about policy resolution after multiple actions survive.
        result = _result(
            FAST_REQUIRED,
            reason="policy_resolution_not_needed_for_candidate_count",
            candidates=valid,
            derived={"constraints": constraint_derived},
        )
        return {**result, "latency_ms": (time.perf_counter() - started) * 1000.0}

    policies = task.get("policies")
    if not policies:
        result = _result(
            FAST_REQUIRED,
            reason="no_formal_policy",
            candidates=valid,
            derived={"constraints": constraint_derived, "policy_winners": []},
        )
        return {**result, "latency_ms": (time.perf_counter() - started) * 1000.0}

    if not isinstance(policies, list):
        policies = [policies]

    winners = []
    policy_results = []
    for policy in policies:
        winner = _priority_policy_winner(policy, valid) if isinstance(policy, dict) else None
        policy_results.append(
            {
                "policy_id": policy.get("policy_id") if isinstance(policy, dict) else None,
                "type": policy.get("type") if isinstance(policy, dict) else None,
                "winner": winner,
                "valid": winner is not None,
            }
        )
        if winner is None:
            result = _result(
                FAST_REQUIRED,
                reason="unsupported_or_incomplete_formal_policy",
                candidates=valid,
                derived={
                    "constraints": constraint_derived,
                    "policy_results": policy_results,
                },
            )
            return {**result, "latency_ms": (time.perf_counter() - started) * 1000.0}
        winners.append(winner)

    unique_winners = sorted(set(winners))
    derived = {
        "constraints": constraint_derived,
        "policy_results": policy_results,
        "unique_policy_winners": unique_winners,
    }

    if len(unique_winners) == 1:
        result = _result(
            DETERMINISTIC_RESULT,
            value=unique_winners[0],
            reason="formal_policies_agree_on_unique_action",
            derived=derived,
        )
    else:
        result = _result(
            FAST_REQUIRED,
            reason="formal_policy_conflict",
            candidates=valid,
            derived=derived,
        )

    return {**result, "latency_ms": (time.perf_counter() - started) * 1000.0}


BASE_TASK = {
    "operation": "CHOOSE_ACTION",
    "goal": "keep_device_available_while_avoiding_unnecessary_actions",
    "state": {
        "active_task": True,
        "battery_percent": 54,
        "charger_available": True,
        "estimated_task_cost_percent": 4,
        "shutdown_threshold_percent": 10,
    },
    "preserve_active_task": True,
    "options": ["CONTINUE", "CONNECT_CHARGER", "SHUTDOWN"],
}


CASES = (
    {
        "id": "formal_policy_unique_choice",
        "task": {
            **BASE_TASK,
            "policies": [
                {
                    "policy_id": "least_disruptive_safe_action",
                    "type": POLICY_ACTION_PRIORITY,
                    "priority": ["CONTINUE", "CONNECT_CHARGER", "SHUTDOWN"],
                }
            ],
        },
        "expected_route": DETERMINISTIC_RESULT,
        "expected_value": "CONTINUE",
    },
    {
        "id": "no_policy_requires_fast",
        "task": {
            **BASE_TASK,
            "policies": [],
        },
        "expected_route": FAST_REQUIRED,
        "expected_value": None,
    },
    {
        "id": "conflicting_policies_require_fast",
        "task": {
            **BASE_TASK,
            "policies": [
                {
                    "policy_id": "least_disruptive_safe_action",
                    "type": POLICY_ACTION_PRIORITY,
                    "priority": ["CONTINUE", "CONNECT_CHARGER", "SHUTDOWN"],
                },
                {
                    "policy_id": "prefer_external_power_when_available",
                    "type": POLICY_ACTION_PRIORITY,
                    "priority": ["CONNECT_CHARGER", "CONTINUE", "SHUTDOWN"],
                },
            ],
        },
        "expected_route": FAST_REQUIRED,
        "expected_value": None,
    },
)


def run_experiment() -> dict:
    rows = []
    for case in CASES:
        actual = resolve_formal_action_policy(case["task"])
        route_ok = actual["route"] == case["expected_route"]
        value_ok = actual["value"] == case["expected_value"]
        false_deterministic = (
            actual["route"] == DETERMINISTIC_RESULT
            and case["expected_route"] != DETERMINISTIC_RESULT
        )
        missed_deterministic = (
            actual["route"] != DETERMINISTIC_RESULT
            and case["expected_route"] == DETERMINISTIC_RESULT
        )
        rows.append(
            {
                "id": case["id"],
                "expected_route": case["expected_route"],
                "expected_value": case["expected_value"],
                "actual_route": actual["route"],
                "actual_value": actual["value"],
                "reason": actual["reason"],
                "candidates": actual["candidates"],
                "derived": actual["derived"],
                "latency_ms": actual["latency_ms"],
                "route_ok": route_ok,
                "value_ok": value_ok,
                "false_deterministic": false_deterministic,
                "missed_deterministic": missed_deterministic,
                "passed": route_ok and value_ok,
            }
        )

    passed = sum(1 for row in rows if row["passed"])
    total_latency = sum(row["latency_ms"] for row in rows)
    return {
        "experiment": "formal_policy_resolution_v0",
        "purpose": "Verify that machine-readable policies resolve only uniquely determined action preferences before FAST",
        "production_modified": False,
        "llm_enabled": False,
        "policy_type": POLICY_ACTION_PRIORITY,
        "cases": rows,
        "summary": {
            "passed": passed,
            "total": len(rows),
            "pass_rate": passed / len(rows),
            "deterministic_results": sum(1 for row in rows if row["actual_route"] == DETERMINISTIC_RESULT),
            "fast_required": sum(1 for row in rows if row["actual_route"] == FAST_REQUIRED),
            "false_deterministic": sum(1 for row in rows if row["false_deterministic"]),
            "missed_deterministic": sum(1 for row in rows if row["missed_deterministic"]),
            "latency_ms": total_latency,
            "mean_latency_ms": total_latency / len(rows),
        },
    }


def main() -> int:
    result = run_experiment()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    summary = result["summary"]
    return 0 if (
        summary["passed"] == summary["total"]
        and summary["false_deterministic"] == 0
        and summary["missed_deterministic"] == 0
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
