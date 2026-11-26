"""Offline reconstruction of the laboratory Cognitive Result.

Only called on a verified Raw fixture and journal/model-call chain.
Reconstruction establishes consistency, not live backend or DB attestation.
No coordinator impersonation, service dispatch, database writes or inference.
"""
import json

from anima.agent.native_tools import canonical
from ..cognition.claim_verification import _verify_captured_claim
from ..cognition.cognitive_result import SCHEMA, _project_result
from ..cognition.model_claims import _evaluate_model_claims
from .egocentric import EgocentricView


def verify_exported_result(fixture, raw_fixture, *, scenario=None, variant=None,
                           required=False):
    aggregate = fixture.get("result")
    if type(aggregate) is not dict or "cognitive_result" not in aggregate:
        if required:
            raise ValueError("required cognitive result missing")
        return
    # The existing suite owns its explicit information requirements.
    # Import lazily to avoid a runner/reproducibility module cycle.
    from .e26b_cognitive_suite import CASES, information_requirement
    case = next((c for c in CASES if c["id"] == fixture["case"]), None)
    if case is None:
        raise ValueError("unknown cognitive result scenario")
    if scenario is not None and any(
            key in scenario and canonical(scenario[key]) != canonical(case[key])
            for key in ("id", "task", "enabled", "kind", "targets", "query")
            if key in case):
        raise ValueError("cognitive result scenario mismatch")
    profile = aggregate["variant"]
    if variant is not None and profile != variant:
        raise ValueError("cognitive result variant mismatch")
    if (aggregate["case"] != case["id"] or aggregate["seed"] != fixture["world_seed"]
            or aggregate["memory_enabled"] is not case["enabled"]
            or aggregate["task"] != case["task"]):
        raise ValueError("cognitive result case identity mismatch")
    requirement = information_requirement(case, temporal_completion=profile == "temporal_completion")
    phase = ("research" if profile == "claims" else
             "claim_projection" if profile in (
                 "claims_separated", "temporal_sources", "temporal_completion") else None)
    report = fixture["turn"]
    records = fixture["trace"]
    research = [c for c in fixture["model_calls"] if c.get("phase", "research") == "research"]
    raw_by_sample = {row["sample_id"]: row for row in raw_fixture["samples"]}

    def load_view(claim):
        row = raw_by_sample.get(claim.sample_id)
        if row is None or row["event_id"] != claim.event_id:
            return None, "RAW_EVENT_BINDING_MISMATCH"
        return EgocentricView(json.loads(row["raw_json"])), None

    def verify(turn, claim):
        return _verify_captured_claim(turn, claim, records, load_view)

    expected = _project_result(
        report, records, requirement=requirement, research_calls=research,
        claim_phase=phase, verify=verify,
        evaluate_claims=lambda calls: _evaluate_model_claims(
            report, calls, lambda: records, verify),
    )
    if canonical(aggregate["cognitive_result"]) != canonical(expected):
        raise ValueError("cognitive result reconstruction mismatch")
    if canonical(aggregate["information_completion"]) != canonical(expected["information"]["completion"]):
        raise ValueError("cognitive result completion metric mismatch")
    if phase is not None and canonical(aggregate["model_claims"]) != canonical(
            expected["evidence"]["model_claims"]["evaluation"]):
        raise ValueError("cognitive result model metric mismatch")
