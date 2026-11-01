"""Adaptive selection only. Resolution owns computations and decisions."""

from anima.ir import CanonicalTask, plain
from anima.resolution.contracts import ResolutionResult, ResolutionRoute
from .contracts import CognitiveView


def _evidence(item, *, conflict):
    data = {"value": plain(item.value)}
    if item.subject is not None:
        data.update(subject=item.subject, predicate=item.predicate)
    if conflict:
        if item.confidence is not None:
            data["confidence"] = item.confidence
        if item.observed_at is not None:
            data["observed_at"] = item.observed_at
        data["provenance"] = list(item.provenance)
    return data


def project(task, resolution, *, consumer="FAST"):
    if not isinstance(task, CanonicalTask) or not isinstance(resolution, ResolutionResult):
        raise TypeError("Projection requires CanonicalTask and ResolutionResult")
    if resolution.route != ResolutionRoute.COGNITIVE_REQUIRED:
        raise ValueError("Projection requires COGNITIVE_REQUIRED")
    data = {"operation": task.operation, "output_contract": task.output_contract}
    if task.raw_input is not None:
        data["input"] = task.raw_input
    if task.goal:
        data["goal"] = task.goal
    if task.preference:
        data["preference"] = task.preference
    if task.operation == "CHOOSE_ACTION":
        data["candidates"] = list(resolution.remaining)
        # An unsupported constraint must remain visible; it was not silently applied.
        data["constraints"] = [
            {"candidate": item.candidate_id, "rule": item.rule}
            for item in task.constraints
            if item.candidate_id in resolution.remaining or item.candidate_id in resolution.unverified
        ]
        if resolution.unverified:
            data["unverified_candidates"] = list(resolution.unverified)
        data["state"] = plain(task.state)
        data["unresolved_reason"] = resolution.reason
        if task.evidence:
            data["evidence"] = [_evidence(item, conflict=False) for item in task.evidence]
        if resolution.derived:
            data["derived"] = plain(resolution.derived)
        if task.policies:
            data["policies"] = [
                {"policy_id": item.policy_id, "type": item.type, "priority": plain(item.priority)}
                for item in task.policies
            ]
    else:
        conflict = task.operation in ("QUERY_FACT", "RESOLVE_CONFLICT")
        selected = task.evidence
        if task.subject is not None and task.predicate is not None:
            data.update(subject=task.subject, predicate=task.predicate)
            if conflict:
                selected = tuple(item for item in selected if item.subject is None or (
                    item.subject == task.subject and item.predicate == task.predicate))
        if selected:
            data["evidence"] = [_evidence(item, conflict=conflict) for item in selected]
        if task.arguments:
            data["arguments"] = plain(task.arguments)
        if task.candidates is not None:
            data["candidates"] = list(task.candidates)
        if task.state:
            data["state"] = plain(task.state)
    return CognitiveView(consumer, data)
