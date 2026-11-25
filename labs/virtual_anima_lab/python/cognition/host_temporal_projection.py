"""Deterministic temporal assertions from already admitted same-turn evidence.

Not a model response, autonomous evidence acquisition, or Core completion.
The verifier re-reads only eligible canonical sources. No extra model call,
tool proposal, new observation, new permission, or Knowledge write.
"""
from .completion import CompletionRequirement, evaluate_completion
from .coordinator import E25LabCognitiveCoordinator, E25CognitionError, _json, _sha
from .claim_verification import ObservationClaim, ObservationClaimVerifier
from .model_claims import temporal_claim_coverage
from .source_binding import admitted_source_rows
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import E24MemoryError


def project_temporal_claims(coordinator, requirement, report, *, focus_refs=()):
    if type(coordinator) is not E25LabCognitiveCoordinator:
        raise TypeError("trusted lab coordinator required")
    if (type(requirement) is not CompletionRequirement
            or requirement.kind != "historical_and_latest_observation"):
        raise ValueError("temporal requirement required")
    result = {
        "schema": "anima.lab.host_temporal_projection/0.1",
        "origin": "DETERMINISTIC_HOST",
        "status": "INFORMATION_INCOMPLETE",
        "format_status": "NOT_GENERATED",
        "research_status": report["status"],
        "information_satisfied": False,
        "answer": None, "claims": [], "verdicts": [],
        "temporal_claim_coverage": False,
        "model_calls": 0, "new_service_reads": 0,
        "canonical_verifier_rereads": True,
        "world_truth_authority": False, "knowledge_write": False,
        "task_completion": "NOT_ESTABLISHED",
    }
    try:
        records = coordinator.decision_records(report["turn_id"])
        completion = evaluate_completion(requirement, report, records)
        result["information_satisfied"] = completion["information_requirement_satisfied"]
        if report["status"] == "REJECTED":
            result["status"] = "RESEARCH_REJECTED"
            return result
        if not result["information_satisfied"]:
            return result
        ctx = records[0]["context_snapshot"]

        def current_context_matches():
            view = coordinator._memory.context_for_cognition(
                focus_refs=focus_refs, memory_enabled=ctx["memory_enabled"],
            )
            return "ctx_" + _sha(_json(view)) == report["context_snapshot_id"]

        if not current_context_matches():
            result["status"] = "STALE_CONTEXT"
            return result
        sources = {}
        for record in records:
            for row in admitted_source_rows(record):
                event_id = row["event_id"]
                if event_id in sources and sources[event_id] != row:
                    result["status"] = "INCONSISTENT_SOURCE_READS"
                    return result
                sources[event_id] = row
        latest = completion["latest_source"]
        latest_row = sources[latest["event_id"]]
        verifier = ObservationClaimVerifier(coordinator)
        claims, verdicts, sentences = [], [], []
        for entity in requirement.entities:
            historical = [
                sources[event_id]
                for event_id in completion["historical_sources_by_entity"][entity]
            ]
            # Stable selection: most recent eligible historical sample, then ID.
            past = max(historical, key=lambda row: (row["sample_seq"], row["event_id"]))
            present = completion["latest_observed_by_entity"][entity]
            for row, value, scope in (
                    (past, True, "source_sample"),
                    (latest_row, present, "latest_captured_sample")):
                claim = ObservationClaim(entity, "observed_in_sample", value,
                                         row["event_id"], row["sample_id"], scope)
                verdict = verifier.verify(report["turn_id"], claim)
                verdicts.append(verdict)
                claims.append(verdict["claim"])
            sentences.append(
                f'{entity}: observed in historical sample {past["sample_seq"]}; '
                f'{"observed" if present else "not observed"} in latest captured '
                f'sample {latest_row["sample_seq"]}.'
            )
        if not current_context_matches():
            result["status"] = "STALE_CONTEXT"
            return result
        result["verdicts"] = verdicts
        candidate = {"format_status": "VALID", "verdicts": verdicts}
        if (len(verdicts) != 2 * len(requirement.entities)
                or not temporal_claim_coverage(completion, candidate)):
            result["status"] = "VERIFICATION_FAILED"
            return result
        result.update(
            status="VERIFIED", format_status="VALID", claims=claims,
            temporal_claim_coverage=True,
            answer=" ".join(sentences) + " Captured observations only; current world truth is not established.",
        )
        return result
    except (E24MemoryError, E25CognitionError, ValueError, TypeError, KeyError):
        # An integrity or binding failure cannot publish a partially verified answer.
        result.update(status="SOURCE_INTEGRITY_FAILURE", format_status="NOT_GENERATED",
                      answer=None, claims=[], temporal_claim_coverage=False)
        return result
