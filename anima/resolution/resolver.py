"""Pure machine-checkable resolution over explicit task data; no LLM dependency."""

import operator

from anima.ir import CanonicalTask, ConstraintRule
from .contracts import DeterministicOutcome, ResolutionResult, ResolutionRoute
from .policy import evaluate_policies
from .numeric import decimal_result, is_number, rational

D = ResolutionRoute.DETERMINISTIC_RESULT
I = ResolutionRoute.INSUFFICIENT_DATA
C = ResolutionRoute.COGNITIVE_REQUIRED

_ARITHMETIC = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}
_COMPARISON = {"==": operator.eq, "!=": operator.ne, ">": operator.gt,
               ">=": operator.ge, "<": operator.lt, "<=": operator.le}


def _value(value, reason, **context):
    return ResolutionResult(D, reason, value=value, outcome=DeterministicOutcome.VALUE, **context)


def _missing(fields, **context):
    return ResolutionResult(I, "missing_requirements", missing=tuple(fields), **context)


def _numeric(task):
    args = task.arguments
    required = ("left", "right", "operator")
    missing = [key for key in required if key not in args]
    if missing:
        return _missing(missing)
    operations = _ARITHMETIC if task.operation == "CALCULATE" else _COMPARISON
    op = args["operator"]
    if not isinstance(op, str) or op not in operations:
        return ResolutionResult(C, "unsupported_numeric_operator")
    if not all(is_number(args[key]) for key in ("left", "right")):
        return ResolutionResult(C, "invalid_numeric_operands")
    if args.get("left_unit") != args.get("right_unit"):
        return ResolutionResult(C, "incompatible_units")
    if task.operation == "CALCULATE" and op in ("*", "/") and args.get("left_unit") is not None:
        return ResolutionResult(C, "unsupported_unit_arithmetic")
    try:
        result = operations[op](rational(args["left"]), rational(args["right"]))
        if task.operation == "COMPARE":
            return _value("YES" if result else "NO", "formal_comparison")
        result = decimal_result(result)
    except (ArithmeticError, ValueError):
        return ResolutionResult(C, "invalid_arithmetic")
    return _value(result, "formal_arithmetic")


def _power(task):
    keys = ("power_supply.voltage_v", "power_supply.max_current_a",
            "device.required_voltage_v", "device.required_current_a")
    missing = [key for key in keys if key not in task.arguments]
    if missing:
        return _missing(missing)
    if not all(is_number(task.arguments[key]) and task.arguments[key] >= 0 for key in keys):
        return ResolutionResult(C, "invalid_electrical_inputs")
    voltage, current, required_voltage, required_current = [rational(task.arguments[key]) for key in keys]
    derived = {"voltage_match": voltage == required_voltage,
               "current_sufficient": current >= required_current,
               "current_margin_a": decimal_result(current - required_current)}
    return _value("YES" if derived["voltage_match"] and derived["current_sufficient"] else "NO",
                  "formal_electrical_constraints", derived=derived)


_REQUIREMENTS = {
    ConstraintRule.PRESERVE_ACTIVE_TASK: ("active_task", "preserve_active_task"),
    ConstraintRule.CHARGER_AVAILABLE: ("charger_available",),
    ConstraintRule.BATTERY_ABOVE_THRESHOLD: (
        "battery_percent", "shutdown_threshold_percent", "estimated_task_cost_percent"),
}


def _actions(task):
    state = task.state
    missing = ["candidates"] if task.candidates is None else []
    unsupported = set()
    for constraint in task.constraints:
        if constraint.rule not in _REQUIREMENTS:
            unsupported.add(constraint.candidate_id)
            continue
        missing.extend(key for key in _REQUIREMENTS[constraint.rule] if key not in state)
    # Discover all known requirements before unsupported rules or policies can defer.
    if missing:
        return _missing(dict.fromkeys(missing))

    rejected = {}
    derived = {}
    invalid = set()
    for constraint in task.constraints:
        if constraint.rule not in _REQUIREMENTS:
            continue
        fields = _REQUIREMENTS[constraint.rule]
        if constraint.rule == ConstraintRule.BATTERY_ABOVE_THRESHOLD:
            if not all(is_number(state[key]) and 0 <= rational(state[key]) <= 100 for key in fields):
                invalid.add(constraint.candidate_id)
                continue
            battery, threshold, cost = (rational(state[key]) for key in fields)
            after = battery - cost
            derived["projected_battery_after_task_percent"] = decimal_result(after)
            allowed = min(battery, after) > threshold
        else:
            if not all(type(state[key]) is bool for key in fields):
                invalid.add(constraint.candidate_id)
                continue
            if constraint.rule == ConstraintRule.PRESERVE_ACTIVE_TASK:
                allowed = not (state["active_task"] and state["preserve_active_task"])
            else:
                allowed = state["charger_available"]
        if not allowed:
            rejected.setdefault(constraint.candidate_id, []).append(constraint.constraint_id)
    unverified = tuple(item for item in task.candidates
                       if item in (unsupported | invalid) and item not in rejected)
    remaining = tuple(item for item in task.candidates if item not in rejected and item not in unverified)
    context = dict(remaining=remaining, unverified=unverified, rejected=rejected, derived=derived)
    if unverified:
        reason = "unsupported_hard_constraint" if any(item in unsupported for item in unverified) else "invalid_constraint_inputs"
        return ResolutionResult(C, reason, **context)
    if not remaining:
        return ResolutionResult(D, "no_admissible_action", outcome=DeterministicOutcome.NO_ADMISSIBLE_ACTION,
                                **context)
    if len(remaining) == 1:
        return _value(remaining[0], "single_action_survives_hard_constraints", **context)
    evaluations = evaluate_policies(task.policies, remaining)
    context["policies"] = evaluations
    if not evaluations:
        return ResolutionResult(C, "multiple_actions_without_policy", **context)
    if not all(item.valid for item in evaluations):
        return ResolutionResult(C, "malformed_or_incomplete_policy", **context)
    winners = {item.winner for item in evaluations}
    if len(winners) != 1:
        return ResolutionResult(C, "formal_policy_conflict", **context)
    return _value(next(iter(winners)), "formal_policies_agree", **context)


def resolve(task):
    if not isinstance(task, CanonicalTask):
        raise TypeError("Resolver requires CanonicalTask")
    if task.output_contract == "candidate" and task.candidates is None and task.operation != "CHOOSE_ACTION":
        return _missing(("candidates",))
    if task.operation == "QUERY_FACT":
        matches = [item for item in task.evidence
                   if item.subject == task.subject and item.predicate == task.predicate]
        if not matches:
            return ResolutionResult(I, "exact_fact_absent", missing=(f"{task.subject}.{task.predicate}",),
                                    next_source="structured_evidence")
        if len(matches) == 1:
            return _value(matches[0].value, "single_exact_structured_fact",
                          derived={"evidence_ids": [matches[0].evidence_id]})
        return ResolutionResult(C, "conflicting_or_multiple_facts")
    if task.operation in ("CALCULATE", "COMPARE"):
        return _numeric(task)
    if task.operation == "POWER_COMPATIBILITY":
        return _power(task)
    if task.operation == "CHOOSE_ACTION":
        return _actions(task)
    return ResolutionResult(C, "unsupported_or_open_operation")
