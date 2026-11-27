"""R9.2 laboratory cognitive result: deterministic basis, not a Core gate.

Trusted in-process coordinator/report only; imported verdicts, model prose
and hidden fixture answers are not sources of authority. No new research
reads, inference, persistence or execution. Verification may re-read Raw.
"""
from .turn_status import valid_turn_status
from copy import deepcopy

from .claim_verification import ObservationClaim, ObservationClaimVerifier
from .completion import CompletionRequirement, evaluate_completion
from .coordinator import E25LabCognitiveCoordinator
from .source_binding import admitted_source_rows
from .result_reasoning import build_reasoning
from .model_claims import evaluate_model_claims


SCHEMA = "anima.lab.cognitive_result/0.1"


def _bound_records(coordinator, report):
    if type(coordinator) is not E25LabCognitiveCoordinator:
        raise TypeError("trusted lab coordinator required")
    if (report["schema"] != "anima.lab.cognitive_turn/0.1"
            or not valid_turn_status(report)
            or report["lab_admission_only"] is not True
            or report["model_executive_authority"] is not False):
        raise ValueError("trusted laboratory turn report required")
    records = coordinator.decision_records(report["turn_id"])
    if len(records) != len(report["outcomes"]):
        raise ValueError("incomplete decision trace")
    for index, (record, outcome) in enumerate(zip(records, report["outcomes"])):
        if (record["turn_id"] != report["turn_id"]
                or record["step_index"] != index
                or record["context_snapshot"]["context_snapshot_id"] != report["context_snapshot_id"]
                or record["outcome"] != outcome
                or outcome["step_index"] != index):
            raise ValueError("decision trace does not bind result")
    return records


def build_cognitive_result(coordinator, report, *, requirement=None,
                           research_calls=(), claim_phase=None):
    """Produce a detached, bounded result from a trusted completed turn.

    Requirement-directed observation claims only in this version. The
    requirement is a question/scope, not an asserted answer. With no
    requirement there is no completeness or claim-coverage assessment.
    Facts retain captured-sample scope even if a later observation exists.
    A report with no journal entries is trusted in-process metadata only.
    """
    if requirement is not None and type(requirement) is not CompletionRequirement:
        raise TypeError("trusted completion requirement required")
    records = _bound_records(coordinator, report)
    return _project_result(
        report, records, requirement=requirement, research_calls=research_calls,
        claim_phase=claim_phase, verify=ObservationClaimVerifier(coordinator).verify,
        evaluate_claims=lambda calls: evaluate_model_claims(coordinator, report, calls),
    )


def _project_result(report, records, *, requirement, research_calls, claim_phase,
                    verify, evaluate_claims):
    """Internal shared projection over already checked sources and records."""
    operations = []
    searches = []
    sources = {}
    candidates = {}
    conflicts = set()
    ctx = records[0]["context_snapshot"] if records else None
    for record in records:
        outcome, proposal = record["outcome"], record["proposal"]
        operations.append({
            "step_index": record["step_index"],
            "proposal_id": outcome["proposal_id"],
            "operation_kind": outcome.get("operation_kind"),
            "admission": record["admission"],
            "status": outcome["status"],
            "reason_code": outcome["reason_code"],
        })
        if (record["admission"] == "ADMITTED" and outcome["status"] == "COMPLETED"
                and proposal and proposal["operation_kind"] == "retrieve_memory"):
            result = outcome["result"]
            searches.append({
                "step_index": record["step_index"],
                "proposal_id": proposal["proposal_id"],
                "arguments": deepcopy(proposal["arguments"]),
                "memory_enabled": result["memory_enabled"],
                "strategy": result["strategy"],
                "returned": result["returned"],
                "possible_matches": result["possible_matches"],
                "truncated": result["truncated"],
                "scope": "BOUNDED_MEMORY_SEARCH_NOT_WORLD_ABSENCE",
            })
        for row in admitted_source_rows(record):
            event = row["event_id"]
            if event in sources and sources[event]["row"] != row:
                conflicts.add(event)
            if event not in sources:
                sources[event] = {"row": deepcopy(row), "step_indices": []}
            sources[event]["step_indices"].append(record["step_index"])
            if requirement is None or requirement.kind not in (
                    "verified_observation", "historical_and_latest_observation"):
                continue
            temporal = requirement.kind == "historical_and_latest_observation"
            latest = row["sample_id"] == record["context_snapshot"]["latest_sample_id"]
            if not temporal and proposal["operation_kind"] != "lookup_raw_evidence":
                continue  # match the existing verified_observation requirement
            for entity in requirement.entities:
                observed = entity in row["entities_observed"]
                if not observed and not (temporal and latest):
                    continue
                scope = "latest_captured_sample" if temporal and latest else "source_sample"
                claim = ObservationClaim(entity, "observed_in_sample", observed,
                                         event, row["sample_id"], scope)
                candidates[(entity, event, scope)] = claim

    completion = evaluate_completion(requirement, report, records) if requirement else None
    facts, verdicts = [], []
    for key in sorted(candidates):
        claim = candidates[key]
        verdict = verify(report["turn_id"], claim)
        entry = {"origin": "DETERMINISTIC_HOST", "verdict": verdict}
        verdicts.append(entry)
        if verdict["status"] == "VERIFIED" and claim.event_id not in conflicts:
            facts.append(deepcopy(entry))

    integrity = ("INCONSISTENT_SOURCE_READS" if conflicts else
                 "VERIFICATION_FAILED" if any(e["verdict"]["status"] != "VERIFIED"
                                               for e in verdicts) else
                 "VERIFIED" if verdicts else "NO_CLAIMS")
    # Do not publish facts from a result with an integrity failure. Keep
    # diagnostic verdicts and the original operation/completion record.
    if integrity in ("INCONSISTENT_SOURCE_READS", "VERIFICATION_FAILED"):
        facts = []
    verified_entities = {e["verdict"]["claim"]["entity_ref"] for e in facts}
    coverage = "NOT_ASSESSED"
    if requirement is not None:
        if requirement.kind == "verified_observation":
            coverage = ("COMPLETE" if set(requirement.entities) <= verified_entities
                        else "INCOMPLETE")
        elif requirement.kind == "historical_and_latest_observation":
            from .model_claims import temporal_claim_coverage
            # Reuse the same temporal coverage predicate as other consumers.
            coverage = ("COMPLETE" if temporal_claim_coverage(completion, {
                "format_status": "VALID", "verdicts": [e["verdict"] for e in facts],
            }) else "INCOMPLETE")
        else:
            coverage = "NOT_APPLICABLE"
    reasoning, model_claims, presentation = build_reasoning(
        report, completion, research_calls=research_calls,
        claim_phase=claim_phase, evaluate_claims=evaluate_claims,
    )
    result = {
        "schema": SCHEMA,
        "identity": {
            "turn_id": report["turn_id"],
            "context_snapshot_id": report["context_snapshot_id"],
            "journal_binding": "BOUND" if records else "NO_JOURNAL_ENTRIES",
            "latest_captured_sample_id": ctx["latest_sample_id"] if ctx else None,
            "memory_enabled": ctx["memory_enabled"] if ctx else None,
        },
        "execution": {
            "turn_status": report["status"],
            "operations": operations,
            "resource_budget": deepcopy(report.get("resource_budget")),
            "model_calls_used": report.get("model_calls_used"),
            "task_completion": "NOT_ESTABLISHED",
        },
        "information": {
            "status": ("NOT_ASSESSED" if completion is None else
                       "SATISFIED" if completion["information_requirement_satisfied"] else
                       "INCOMPLETE"),
            "completion": deepcopy(completion),
            "search_outcomes": searches,
        },
        "evidence": {
            "source_references": [
                {"event_id": event, "sample_id": data["row"]["sample_id"],
                 "sample_seq": data["row"]["sample_seq"],
                 "raw_sha256": data["row"]["raw_sha256"],
                 "source_ref": data["row"]["source_ref"],
                 "step_indices": sorted(set(data["step_indices"])),
                 "scope": "ADMITTED_SOURCE_REFERENCE"}
                for event, data in sorted(sources.items())
            ],
            "facts": facts,
            "model_claims": model_claims,
            "verdicts": deepcopy(verdicts),
            "integrity_status": integrity,
            "claim_coverage": coverage,
            "world_truth_authority": False,
            "knowledge_write": False,
        },
        "reasoning": reasoning,
        "presentation": presentation,
    }

    if report.get('control',{}).get('profile') == 'r945/0.1':
        from .verified_presentation import project_verified_presentation
        result['consumer_view'] = project_verified_presentation(result)
    return result


__all__ = ["SCHEMA", "build_cognitive_result"]
