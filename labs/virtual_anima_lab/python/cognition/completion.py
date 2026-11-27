"""E2.6d.0: host-owned informational completion, separate from model stop.

Consumes the trusted lab coordinator report and decision_records (not model
text or arbitrary imported evidence). No execution, retries, knowledge writes,
or inference of claims. This is not a canonical Core Goal/Task completion gate.
"""
from .turn_status import valid_turn_status
from dataclasses import dataclass
from .source_binding import admitted_source_rows


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
        if self.kind not in ("verified_observation", "empty_search", "no_service_read",
                             "historical_and_latest_observation"):
            raise ValueError("unknown completion requirement")
        if type(self.entities) is not tuple or any(
            type(e) is not str or not e.strip() for e in self.entities
        ) or len(set(self.entities)) != len(self.entities):
            raise ValueError("unique entity references required")
        if type(self.query) is not str:
            raise ValueError("query must be text")
        if self.kind in ("verified_observation", "historical_and_latest_observation"):
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
    if not valid_turn_status(report):
        raise ValueError("unknown turn status")
    outcomes = report["outcomes"]
    if len(records) != len(outcomes):
        raise ValueError("incomplete decision trace")
    verified = {}
    # Preserve historical verdicts; corrected profiles share Retrieval's key.
    query_key = _query_key
    if report.get("control", {}).get("profile") in ("r942/0.2", "r943/0.1"):
        from .retrieval_policy import query_key
    empty_queries = set()
    completed_reads = 0
    historical = {}
    latest_rows = []
    temporal = requirement.kind == "historical_and_latest_observation"
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
        if temporal:
            for row in admitted_source_rows(record):
                if row["sample_id"] == record["context_snapshot"]["latest_sample_id"]:
                    if row not in latest_rows:
                        latest_rows.append(row)
                else:
                    for entity in row["entities_observed"]:
                        historical.setdefault(entity, set()).add(row["event_id"])
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
                empty_queries.add(query_key(proposal["arguments"]["query"]))

    missing = []
    temporal_details = {}
    if temporal:
        missing = [e for e in requirement.entities if e not in historical]
        latest = latest_rows[0] if len(latest_rows) == 1 else None
        missing_conditions = (["VERIFIED_HISTORICAL_OBSERVATION"] if missing else [])
        if latest is None:
            missing_conditions.append("VERIFIED_LATEST_CAPTURED_SAMPLE")
        satisfied = not missing_conditions
        reason = ("TEMPORAL_EVIDENCE_COMPLETE" if satisfied else
                  "INCONSISTENT_LATEST_SOURCE" if len(latest_rows) > 1 else
                  "TEMPORAL_EVIDENCE_INCOMPLETE")
        temporal_details = {
            "missing_requirements": missing_conditions,
            "historical_sources_by_entity": {e:sorted(ids) for e,ids in sorted(historical.items())},
            "latest_source": ({"event_id":latest["event_id"],"sample_id":latest["sample_id"],
                               "sample_seq":latest["sample_seq"]} if latest is not None else None),
            "latest_observed_by_entity": {e:e in latest["entities_observed"] for e in requirement.entities}
                                         if latest is not None else {},
        }
    elif requirement.kind == "verified_observation":
        missing = [e for e in requirement.entities if e not in verified]
        satisfied = not missing
        reason = "VERIFIED_TARGET_OBSERVATIONS" if satisfied else "REQUIRED_SOURCE_NOT_VERIFIED"
    elif requirement.kind == "empty_search":
        satisfied = query_key(requirement.query) in empty_queries
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
        **temporal_details,
        "verified_sources_by_entity": {e: sorted(verified[e]) for e in sorted(verified)},
        "completed_service_reads": completed_reads,
        "rejected_steps": sum(o["status"] == "REJECTED" for o in outcomes),
        "claim_verification": "NOT_PERFORMED",
        "task_completion": "NOT_ESTABLISHED",
    }
