"""R9.4.1a offline host measurements, never an input to admission or inference.

Only an in-process checked journal is accepted. Prefixes use frozen Context
and the records/calls already reached, never final-result facts. Measurements
are proxies, not semantic utility or Task completion. Verification here is
NEW measurement work and is never charged as historical acquisition.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import re

from anima.agent.native_tools import canonical
from .cognitive_result import _bound_records
from .claim_verification import ObservationClaim, ObservationClaimVerifier, _verify_captured_claim
from .completion import CompletionRequirement, evaluate_completion
from .contracts import CognitiveStepProposal
from .model_claims import _evaluate_model_claims
from .source_binding import admitted_source_rows
from .source_policy import TurnSourcePolicy
from ..lifecycle.e26_reproducibility import digest
from ..lifecycle.e24_working_memory import E24MemoryError

SCHEMA = "anima.lab.observable_cognitive_state/0.1"
PHASES = ("research", "model_claim_projection", "host_projection", "result_construction", "verification")


def _hash(value):
    return digest(canonical(value))


def _scope(ctx):
    if ctx is None:
        return {"status": "UNKNOWN", "world_absence": False}
    return {k: deepcopy(ctx[k]) for k in ("world_instance_id", "epoch", "source_ref",
            "latest_sample_id", "memory_enabled", "context_snapshot_id")} | {"world_absence": False}


def source_identity(context, row):
    """Content equality is a separate proxy, never event identity."""
    return (context["world_instance_id"], context["epoch"], row["source_ref"],
            row["event_id"], row["sample_id"], row["raw_sha256"])


def availability(ctx, result=None, *, rejected_reason=None):
    scope = _scope(ctx)
    state, reason = "UNKNOWN", "NO_SOURCE_AVAILABILITY_OBSERVATION"
    if ctx is not None and ctx["memory_enabled"] is False:
        state, reason = "DISABLED_BY_POLICY", "HISTORY_DISABLED_LATEST_SCOPE_ONLY"
    elif result is not None and result.get("kind") == "working_world_memory_search":
        if result.get("truncated") is True:
            state, reason = "PARTIAL_OR_TRUNCATED", "BOUNDED_TOP_K_TRUNCATED"
        elif result.get("memory_enabled") is True and result.get("truncated") is False:
            state, reason = "AVAILABLE_IN_SCOPE", "BOUNDED_SEARCH_COMPLETED"
    elif result is not None:
        state, reason = "AVAILABLE_IN_SCOPE", "ADMITTED_SERVICE_READ_COMPLETED"
    if rejected_reason:
        # SERVICE_REJECTED intentionally collapses multiple old causes. Do not
        # retrospectively invent an outage or integrity diagnosis from it.
        state, reason = "UNKNOWN", rejected_reason
    return {"state": state, "reason_code": reason, "scope": scope}


class ControlledServiceUnavailable(RuntimeError):
    """Explicit adapter/fixture signal; E24MemoryError alone is NOT an outage."""
    def __init__(self, service, reason_code, scope):
        if (type(service) is not str or not re.fullmatch(r"[a-z_]{1,64}", service)
                or type(reason_code) is not str or not re.fullmatch(r"[A-Z_]{1,64}", reason_code)
                or type(scope) is not dict or len(canonical(scope).encode()) > 2048):
            raise ValueError("bounded controlled service diagnostic required")
        self.service, self.reason_code, self.scope = service, reason_code, deepcopy(scope)
        super().__init__(reason_code)


class MeasurementIntegrityError(ValueError):
    """Checked source rejection, separate from programming errors/outages."""


def diagnose_before_context(error, *, turn_id, case_id, baseline_sha):
    """Call at an external boundary; does not run/catch/alter the coordinator."""
    if type(error) not in (ControlledServiceUnavailable, E24MemoryError):
        raise TypeError("explicit controlled service or memory integrity failure required")
    controlled = type(error) is ControlledServiceUnavailable
    return {"schema": SCHEMA, "kind": "PRE_CONTEXT_DIAGNOSTIC",
            "baseline_sha": baseline_sha, "turn_id": turn_id, "case_id": case_id,
            "context_status": "NOT_FORMED", "model_facing_authority": False,
            "availability": {"state": "SERVICE_UNAVAILABLE" if controlled else "INTEGRITY_REJECTED",
                             "service": error.service if controlled else "working_memory",
                             "reason_code": error.reason_code if controlled else "WORKING_MEMORY_INTEGRITY_REJECTED",
                             "scope": deepcopy(error.scope) if controlled else {"status":"UNKNOWN"}}}


def _phase(call):
    phase = call.get("phase", "research")
    return "model_claim_projection" if phase == "claim_projection" else phase


def _resources(calls):
    out = {}
    for phase in PHASES:
        selected = [c for c in calls if _phase(c) == phase]
        item = {"calls": len(selected)}
        for key in ("input_tokens", "output_tokens", "latency_ms"):
            known = [c[key] for c in selected if type(c.get(key)) in (int, float)
                     and c[key] >= 0 and (key == "latency_ms" or type(c[key]) is int)]
            item["known_" + key] = sum(known)
            item["missing_" + key] = len(selected) - len(known)
        out[phase] = item
    return out


def _coverage(req, completion):
    if req is None:
        return {"status": "NOT_ASSESSED", "required": None, "covered": None,
                "ratio": None, "covered_units": [], "missing_units": []}
    if req.kind in ("verified_observation", "historical_and_latest_observation"):
        temporal = req.kind == "historical_and_latest_observation"
        prefix = "historical:" if temporal else "observation:"
        required = [prefix + e for e in req.entities] + (["latest_bound_sample"] if temporal else [])
        seen = completion["historical_sources_by_entity" if temporal else "verified_sources_by_entity"]
        covered = [prefix + e for e in req.entities if seen.get(e)]
        if temporal and completion["latest_source"] is not None:
            covered.append("latest_bound_sample")
    else:
        required = [req.kind + (":" + " ".join(req.query.casefold().split()) if req.query else "")]
        covered = required[:] if completion["information_requirement_satisfied"] else []
    return {"status": "ASSESSED", "required": len(required), "covered": len(covered),
            "ratio": len(covered) / len(required), "covered_units": covered,
            "missing_units": sorted(set(required) - set(covered))}


def _visible_ids(request):
    """Typed IDs only; arbitrary prose and substrings grant no exposure."""
    ids = set()
    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ("event_id", "last_seen_event_id", "previous_event_id", "current_event_id") and type(value) is str:
                    ids.add(value)
                elif key == "event_ids" and type(value) is list:
                    ids.update(x for x in value if type(x) is str)
                elif key == "content" and type(value) is str:
                    try:
                        import json
                        walk(json.loads(value))
                    except ValueError:
                        pass
                else:
                    walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)
    # Requests contain also assistant proposals. Restrict exposure to host messages.
    for msg in request.get("messages", []):
        if msg.get("role") in ("user", "tool"):
            walk(msg)
    return sorted(ids)


def _text_stop(call):
    raw = call.get("raw_response")
    choices = raw.get("choices") if type(raw) is dict else None
    return bool(type(choices) is list and len(choices) == 1
                and type(choices[0]) is dict and choices[0].get("finish_reason") == "stop")


def measure_turn(coordinator, report, *, baseline_sha, case_id, requirement=None,
                 calls=None, frozen_context=None, claim_phase=None):
    """Build a detached sidecar. Missing calls/context stay UNKNOWN.

    The original completion contract is recorded separately from availability.
    Raw validation uses the existing claim verifier with PREFIX records. A
    future conflict rejects the sidecar; it never removes earlier prefix gain.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", baseline_sha):
        raise ValueError("full baseline SHA required")
    if requirement is not None and type(requirement) is not CompletionRequirement:
        raise TypeError("trusted completion requirement required")
    if claim_phase not in (None,"research","claim_projection"):
        raise ValueError("explicit trusted claim phase required")
    records = _bound_records(coordinator, report)
    ctx = deepcopy(frozen_context if frozen_context is not None else
                   records[0]["context_snapshot"] if records else None)
    if ctx is not None:
        base = {k: v for k, v in ctx.items() if k != "context_snapshot_id"}
        if ("ctx_" + _hash(base) != report["context_snapshot_id"]
                or any(r["context_snapshot"] != ctx for r in records)):
            raise ValueError("frozen Context mismatch")
    calls_known = calls is not None
    calls = deepcopy(list(calls or ()))
    for i, call in enumerate(calls):
        if (_phase(call) not in PHASES
                or call.get("turn_id") != report["turn_id"]
                or call.get("context_snapshot_id") != report["context_snapshot_id"]
                or call.get("model_call_index", i) != i):
            raise ValueError("ordered calls do not bind turn/context")
    if calls_known:
        research_count = sum(_phase(c) == "research" for c in calls)
        if report.get("model_calls_used",research_count) != research_count:
            raise ValueError("research call count does not bind report")
        expected_projection = report.get("claim_projection",{}).get("call")
        projection_calls = [c for c in calls if _phase(c) == "model_claim_projection"]
        if expected_projection is not None and projection_calls != [expected_projection]:
            raise ValueError("projection call count does not bind report")
    # Native calls identify the operation proposed at that boundary. Stop calls
    # share step_index with the NEXT operation and must never pull it backward.
    boundaries = [(0, 0)]
    n = 0
    if calls_known:
        for i, call in enumerate(calls):
            if _phase(call) == "research" and n < len(records):
                record = records[n]
                if call.get("step_index") == n and (
                        call.get("proposal") is not None and call["proposal"] == record["proposal"]
                        or call.get("valid") is False and record["proposal"] is None):
                    n += 1
            boundaries.append((n, i + 1))
        if n != len(records):
            raise ValueError("unmapped journal records; cannot infer call boundary")
    else:
        boundaries += [(i, 0) for i in range(1, len(records) + 1)]
    loader = ObservationClaimVerifier(coordinator)
    io = {"raw_rereads": 0, "binding_checks": 0, "known_raw_bytes": 0, "failed_rereads": 0,
          "phase": "verification", "origin": "MEASUREMENT_ONLY",
          "context_integrity_io": "NOT_INSTRUMENTED", "claim_candidates": 0,
          "verdicts": {}, "source_checks": 0, "status": "NOT_ASSESSED"}
    def load(claim):
        io["binding_checks"] += 1
        view, failure = loader._load_view(claim)
        if failure != "RAW_EVENT_BINDING_MISMATCH":
            io["raw_rereads"] += 1
        if view is not None:
            io["known_raw_bytes"] += len(view.canonical_json.encode("utf-8"))
        if failure and failure != "RAW_EVENT_BINDING_MISMATCH":
            io["failed_rereads"] += 1
        return view, failure
    prefixes, first_sufficient = [], None
    model_fact_keys, model_assessments, model_seen_calls = set(), [], set()
    previous = dict(exposed_ids=0, evidence=0, verified_facts=0, covered_units=0,
                    search_outcomes=0, availability_state=0)
    for size, call_size in boundaries:
        prefix = records[:size]
        policy = TurnSourcePolicy(ctx) if ctx is not None else None
        exposed_initial = policy.exposed_bindings() if policy else {}
        evidence, by_event, by_sample, facts, searches = {}, {}, {}, set(), {}
        same = cross = occurrences = attempts = completed = rejected = 0
        counts, candidate_refs, verdict_counts = Counter(), [], Counter()
        avail = availability(ctx)
        for record in prefix:
            proposal, outcome = record["proposal"], record["outcome"]
            if proposal:
                attempts += 1
                counts[proposal["operation_kind"]] += 1
            if outcome["status"] == "REJECTED":
                rejected += 1
                avail = availability(ctx, rejected_reason=outcome["reason_code"])
                continue
            completed += 1
            kind, result = proposal["operation_kind"], outcome["result"]
            if kind == "lookup_raw_evidence" and not policy.permits(proposal["arguments"]["event_ids"]):
                raise MeasurementIntegrityError("INCONSISTENT_SOURCE: unexposed lookup")
            policy.check_result(kind, proposal["arguments"], result)
            policy.record_completed(kind, result)
            avail = availability(ctx, result)
            if kind == "retrieve_memory":
                candidate_refs += [r["last_seen_event_id"] for r in result["records"]]
                key = _hash({"query": " ".join(proposal["arguments"]["query"].casefold().split()),
                             "scope": _scope(ctx), "availability": avail, "result": result})
                searches[key] = {"query": proposal["arguments"]["query"],
                                 "returned": result["returned"], "truncated": result["truncated"],
                                 "result_sha256": _hash(result), "availability": avail}
            rows = admitted_source_rows(record)
            if kind in ("lookup_raw_evidence", "inspect_latest_observation") and len(rows) != len(result["records"]):
                raise MeasurementIntegrityError("INCONSISTENT_SOURCE: ineligible source row")
            for row in rows:
                event, sample = row["event_id"], row["sample_id"]
                if ((event in by_event and by_event[event] != row)
                        or sample in by_sample and by_sample[sample] != row):
                    raise MeasurementIntegrityError("INCONSISTENT_SOURCE_READS")
                by_event[event], by_sample[sample] = row, row
                identity = source_identity(ctx, row)
                occurrences += 1
                if identity in evidence:
                    if kind in evidence[identity]:
                        same += 1
                    else:
                        cross += 1
                    evidence[identity].add(kind)
                else:
                    entity = next(iter(row["entities_observed"]), "measurement.empty_sample")
                    check = ObservationClaim(entity, "observed_in_sample", bool(row["entities_observed"]), event, sample)
                    io["source_checks"] += 1
                    verdict = _verify_captured_claim(report["turn_id"], check, prefix, load)
                    if verdict["status"] != "VERIFIED":
                        raise MeasurementIntegrityError("INCONSISTENT_SOURCE: " + verdict["reason_code"])
                    evidence[identity] = {kind}
        journaled_attempts = attempts
        recorded_proposals = {canonical(r["proposal"]) for r in prefix if r["proposal"]}
        unrecorded = []
        for index, call in enumerate(calls[:call_size]):
            if _phase(call) != "research" or call.get("proposal") is None:
                continue
            proposal = CognitiveStepProposal(call["proposal"]).as_dict()
            if (proposal["turn_id"] != report["turn_id"]
                    or proposal["context_snapshot_id"] != report["context_snapshot_id"]):
                raise ValueError("generated proposal does not bind turn/context")
            if canonical(proposal) not in recorded_proposals:
                # ResourceBudget may reject the returned call BEFORE journal
                # admission. Count the observed proposal, never fabricate an
                # admission/outcome or a completed service operation for it.
                attempts += 1
                counts[proposal["operation_kind"]] += 1
                unrecorded.append({"call_index":index,"proposal_id":proposal["proposal_id"],
                    "operation_kind":proposal["operation_kind"],"admission":"NOT_RECORDED"})
        # Requirement-directed fact projection reuses the existing verifier, but
        # never its final-journal lookup. No future rows can satisfy a prefix.
        if requirement and requirement.kind in ("verified_observation", "historical_and_latest_observation"):
            temporal = requirement.kind == "historical_and_latest_observation"
            candidates = {}
            for record in prefix:
                if not temporal and (not record["proposal"] or record["proposal"]["operation_kind"] != "lookup_raw_evidence"):
                    continue
                for row in admitted_source_rows(record):
                    latest = temporal and row["sample_id"] == ctx["latest_sample_id"]
                    for entity in requirement.entities:
                        observed = entity in row["entities_observed"]
                        if observed or latest:
                            claim = ObservationClaim(entity, "observed_in_sample", observed,
                                row["event_id"], row["sample_id"], "latest_captured_sample" if latest else "source_sample")
                            candidates[canonical(asdict(claim))] = claim
            for key, claim in sorted(candidates.items()):
                verdict = _verify_captured_claim(report["turn_id"], claim, prefix, load)
                verdict_counts[("DETERMINISTIC_HOST", verdict["status"], verdict["reason_code"])] += 1
                io["claim_candidates"] += 1
                if verdict["status"] == "VERIFIED":
                    facts.add(key)
        deterministic_fact_count = len(facts)
        if call_size and claim_phase is not None:
            index = call_size - 1
            call = calls[index]
            selected_phase = "model_claim_projection" if claim_phase == "claim_projection" else "research"
            if index not in model_seen_calls and _phase(call) == selected_phase and _text_stop(call):
                model_seen_calls.add(index)
                # A typed candidate is checked only when it appears. A later
                # Raw acquisition must NEVER reverify an earlier unsupported
                # model claim retroactively. This ledger is prefix-owned.
                def verify_model(turn,claim):
                    return _verify_captured_claim(turn,claim,prefix,load)
                evaluation = _evaluate_model_claims(
                    {"status":"STOPPED","turn_id":report["turn_id"],
                     "context_snapshot_id":report["context_snapshot_id"]},
                    [call],lambda:prefix,verify_model)
                model_assessments.append({"call_index":index,"phase":claim_phase,
                    "format_status":evaluation["format_status"],"verdicts":deepcopy(evaluation["verdicts"])})
                for verdict in evaluation["verdicts"]:
                    io["claim_candidates"] += 1
                    verdict_counts[("MODEL_CANDIDATE",verdict["status"],verdict["reason_code"])] += 1
                    if verdict["status"] == "VERIFIED":
                        model_fact_keys.add(canonical(verdict["claim"]))
        facts.update(model_fact_keys)
        provisional = {"turn_id":report["turn_id"],"context_snapshot_id":report["context_snapshot_id"],
                       "status":"STEP_BUDGET_EXHAUSTED","outcomes":report["outcomes"][:size]}
        completion = evaluate_completion(requirement, provisional, prefix) if requirement else None
        if completion:
            completion = {k: v for k, v in completion.items() if k not in ("model_stopped", "turn_status")}
        coverage = _coverage(requirement, completion)
        metrics = {"exposed_ids": len(policy.exposed_bindings()) - len(exposed_initial) if policy else 0,
                   "evidence": len(evidence), "verified_facts": len(facts),
                   "covered_units": coverage["covered"] or 0, "search_outcomes": len(searches),
                   "availability_state": int(avail != availability(ctx))}
        gain = {k: metrics[k] - previous[k] for k in metrics}
        gain["availability_state"] = int(bool(prefixes) and avail != prefixes[-1]["availability"])
        previous = metrics
        if completion and completion["information_requirement_satisfied"] and first_sufficient is None:
            first_sufficient = (size, call_size)
        for key, value in verdict_counts.items():
            label = "|".join(key)
            io["verdicts"][label] = io["verdicts"].get(label, 0) + value
        io["status"] = "ASSESSED" if io["claim_candidates"] else "NOT_ASSESSED"
        prefixes.append({"operation_prefix": size, "call_prefix": call_size if calls_known else None,
            "record_indices": list(range(size)), "call_indices": list(range(call_size)),
            "acquisition": {"attempts": attempts, "completed": completed, "rejected": rejected,
                            "attempts_by_kind": dict(counts), "journaled_attempts":journaled_attempts,
                            "unrecorded_generated_proposals":unrecorded,
                            "untyped_rejections":sum(r["proposal"] is None for r in prefix),
                            "attempts_assessment":"PARTIAL" if any(r["proposal"] is None for r in prefix) else "COMPLETE"},
            "exposure": {"initial_host_bindings": exposed_initial,
                         "host_bindings": policy.exposed_bindings() if policy else None,
                         "candidate_references": candidate_refs,
                         "native_visible_ids": _visible_ids(calls[call_size-1]["request"]) if call_size else None},
            "evidence": {"identities": [list(e) for e in sorted(evidence)], "unique_sources": len(evidence),
                         "unique_event_ids": len(by_event), "unique_samples": len(by_sample),
                         "unique_content_hashes": len({r["raw_sha256"] for r in by_event.values()})},
            "legacy_repeated_proposals": journaled_attempts - len({canonical([r["proposal"]["operation_kind"],r["proposal"]["arguments"]]) for r in prefix if r["proposal"]}),
            "redundancy": {"eligible_rows": occurrences, "same_tool": same, "cross_tool": cross,
                           "ratio": (same + cross) / occurrences if occurrences else None},
            "verified_fact_count": len(facts), "verified_fact_keys": sorted(facts),
            "facts_by_origin":{"DETERMINISTIC_HOST":deterministic_fact_count,
                               "MODEL_CANDIDATE_VERIFIED":len(model_fact_keys) if claim_phase and calls_known else None},
            "model_claim_assessments":deepcopy(model_assessments) if claim_phase and calls_known else "NOT_ASSESSED",
            "verification": deepcopy(io), "coverage": coverage, "completion": completion,
            "availability": avail, "searches": list(searches.values()), "search_outcome_count": len(searches),
            "gain": gain, "no_gain_candidate": all(v == 0 for v in gain.values()) if ctx and not (call_size and _phase(calls[call_size-1]) == "model_claim_projection" and claim_phase is None) else None,
            "resources": _resources(calls[:call_size]) if calls_known else {"status": "UNKNOWN"}})
    final = prefixes[-1]
    continuation = []
    for decision in report.get("continuation_decisions", []):
        boundary = decision["model_calls_used"]
        before = next((p for p in prefixes if p["call_prefix"] == boundary), None)
        later = [p for p in prefixes if p["call_prefix"] is not None and p["call_prefix"] > boundary]
        productive = next((p for p in later if before and
            (p["coverage"]["covered"] or 0) > (before["coverage"]["covered"] or 0)), None)
        continuation.append({**deepcopy(decision), "productive": bool(productive) if before else None,
                             "calls_to_coverage_gain": productive["call_prefix"] - boundary if productive else None,
                             "metadata_gain": any(p["gain"]["search_outcomes"] > 0 or p["gain"]["exposed_ids"] > 0 for p in later) if before else None,
                             "eventual_completeness": final["completion"]["information_requirement_satisfied"] if final["completion"] else None})
    sufficient = next((p for p in prefixes if first_sufficient and
                       (p["operation_prefix"],p["call_prefix"] or 0) == first_sufficient),None)
    after = [c for c in calls[first_sufficient[1]:] if _phase(c) == "research"] if first_sufficient and calls_known else []
    assessed = requirement is not None
    sufficiency = {
        "status":"NOT_ASSESSED" if not assessed else "REACHED" if sufficient else "NOT_REACHED",
        "first_operation_prefix":first_sufficient[0] if first_sufficient else None,
        "first_call_prefix":first_sufficient[1] if first_sufficient and calls_known else None,
        "research_calls_after":sum(c.get("proposal") is not None for c in after) if assessed and calls_known else None,
        "research_model_calls_after":len(after) if assessed and calls_known else None,
        "presentation_calls_after":sum(_text_stop(c) for c in after) if assessed and calls_known else None,
        "service_reads_after":final["acquisition"]["completed"] - sufficient["acquisition"]["completed"] if sufficient else 0 if assessed else None,
        "remained_satisfied":all(p["completion"]["information_requirement_satisfied"] for p in prefixes
                                  if p["operation_prefix"] >= first_sufficient[0]) if sufficient else None,
    }
    return {"schema": SCHEMA, "baseline_sha": baseline_sha, "case_id": case_id,
            "turn_id": report["turn_id"], "context_snapshot_id": report["context_snapshot_id"],
            "inputs": {"context_sha256": _hash(ctx) if ctx else None, "journal_sha256": _hash(records),
                       "report_sha256": _hash(report), "calls_sha256": _hash(calls) if calls_known else None},
            "model_facing_authority": False, "semantic_utility": "NOT_ASSESSED", "model_claim_phase":claim_phase,
            "retrieval_relevance": "NOT_ASSESSED", "prefixes": prefixes, "continuation": continuation,
            "stop_attempts": sum(_text_stop(c) for c in calls if _phase(c) == "research") if calls_known else None,
            "eligible_continuation_opportunities": len(report.get("continuation_decisions", [])),
            "sufficiency": sufficiency,
            "premature_stop": {"incomplete_stop": report["status"] == "STOPPED" and not completion["information_requirement_satisfied"] if completion else None,
                               "recoverability": "UNKNOWN"},
            "historical_resource_budget": deepcopy(report.get("resource_budget"))}
