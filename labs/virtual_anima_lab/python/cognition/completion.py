"""E2.6d.0: host-owned informational completion, separate from model stop.

Consumes the trusted lab coordinator report and decision_records (not model
text or arbitrary imported evidence). No execution, retries, knowledge writes,
or inference of claims. This is not a canonical Core Goal/Task completion gate.
"""
from dataclasses import dataclass


def _query_key(value):
    if type(value) is not str or not value.strip():
        raise ValueError("nonempty search query required")
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class CompletionRequirement:
    kind: str
    entities: tuple[str, ...] = ()
    query: str = ""

    def __post_init__(self):
        if self.kind not in ("verified_observation", "empty_search", "no_service_read"):
            raise ValueError("unknown completion requirement")
        if type(self.entities) is not tuple or any(
            type(e) is not str or not e.strip() for e in self.entities
        ) or len(set(self.entities)) != len(self.entities):
            raise ValueError("unique entity references required")
        if type(self.query) is not str:
            raise ValueError("query must be text")
        if self.kind == "verified_observation":
            if not self.entities or self.query:
                raise ValueError("verified observation requires entity refs only")
        elif self.kind == "empty_search":
            if self.entities:
                raise ValueError("empty search requires query only")
            _query_key(self.query)
        elif self.entities or self.query:
            raise ValueError("no-service-read requires no arguments")


def evaluate_completion(requirement, report, records):
    """Evaluate informational prerequisites, never accept model claims.

    Caller must obtain records through the coordinator's integrity-checked
    decision_records API. Matching records/report is an additional consistency
    check, not cryptographic attestation of an arbitrary supplied journal.
    """
    if type(requirement) is not CompletionRequirement:
        raise TypeError("trusted completion requirement required")
    status = report["status"]
    if status not in ("STOPPED", "REJECTED", "STEP_BUDGET_EXHAUSTED"):
        raise ValueError("unknown turn status")
    outcomes = report["outcomes"]
    if len(records) != len(outcomes):
        raise ValueError("incomplete decision trace")
    verified = {}
    empty_queries = set()
    completed_reads = 0
    for step, (record, outcome) in enumerate(zip(records, outcomes)):
        if (record["turn_id"] != report["turn_id"]
                or record["step_index"] != step
                or record["context_snapshot"]["context_snapshot_id"] != report["context_snapshot_id"]
                or record["outcome"] != outcome or outcome["step_index"] != step):
            raise ValueError("decision trace does not bind turn")
        if outcome["status"] == "REJECTED":
            continue
        proposal = record["proposal"]
        if (outcome["status"] != "COMPLETED" or record["admission"] != "ADMITTED"
                or not proposal or proposal["proposal_id"] != outcome["proposal_id"]
                or proposal["turn_id"] != report["turn_id"]
                or proposal["context_snapshot_id"] != report["context_snapshot_id"]
                or proposal["operation_kind"] != outcome["operation_kind"]):
            raise ValueError("invalid completed read")
        completed_reads += 1
        result = outcome["result"]
        if proposal["operation_kind"] == "lookup_raw_evidence":
            if result["kind"] != "verified_raw_evidence":
                raise ValueError("unexpected evidence result")
            for row in result["records"]:
                if row["event_id"] not in proposal["arguments"]["event_ids"]:
                    raise ValueError("evidence outside requested sources")
                if row["status"] == "verified_source_view":
                    for entity in row["entities_observed"]:
                        verified.setdefault(entity, set()).add(row["event_id"])
        elif proposal["operation_kind"] == "retrieve_memory":
            if result["kind"] != "working_world_memory_search":
                raise ValueError("unexpected search result")
            if (result["records"] == [] and result["returned"] == 0
                    and result["possible_matches"] == 0 and result["truncated"] is False):
                empty_queries.add(_query_key(proposal["arguments"]["query"]))

    missing = []
    if requirement.kind == "verified_observation":
        missing = [e for e in requirement.entities if e not in verified]
        satisfied = not missing
        reason = "VERIFIED_TARGET_OBSERVATIONS" if satisfied else "REQUIRED_SOURCE_NOT_VERIFIED"
    elif requirement.kind == "empty_search":
        satisfied = _query_key(requirement.query) in empty_queries
        reason = "EMPTY_SEARCH_CONFIRMED" if satisfied else "REQUIRED_EMPTY_SEARCH_NOT_CONFIRMED"
    else:
        # Denied attempts are not service reads but are tracked separately.
        satisfied = completed_reads == 0
        reason = "NO_COMPLETED_SERVICE_READ" if satisfied else "UNNECESSARY_SERVICE_READ"
    return {
        "schema": "anima.lab.information_completion/0.1",
        "requirement": {"kind": requirement.kind, "entities": list(requirement.entities),
                        "query": requirement.query},
        "model_stopped": status == "STOPPED",
        "turn_status": status,
        "information_requirement_satisfied": satisfied,
        "reason_code": reason,
        "missing_entities": missing,
        "verified_sources_by_entity": {e: sorted(verified[e]) for e in sorted(verified)},
        "completed_service_reads": completed_reads,
        "rejected_steps": sum(o["status"] == "REJECTED" for o in outcomes),
        "claim_verification": "NOT_PERFORMED",
        "task_completion": "NOT_ESTABLISHED",
    }
