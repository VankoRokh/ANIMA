"""E2.6d.1 narrow deterministic verification of typed observation claims.

An observation proves only its captured sample, not physical existence,
current sensor freshness, or a natural-language conclusion. The verifier
has no write or action authority. Only previously admitted source reads
from the same turn are eligible; re-read canonical Raw with E24 checks.
"""
from dataclasses import dataclass
from contextlib import closing
import hashlib

from .coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import E24MemoryError


@dataclass(frozen=True)
class ObservationClaim:
    entity_ref: str
    predicate: str
    value: bool | int | str
    event_id: str
    sample_id: str
    scope: str = "source_sample"

    def __post_init__(self):
        for value in (self.entity_ref, self.event_id, self.sample_id):
            if type(value) is not str or not value.strip() or len(value) > 256:
                raise ValueError("bounded reference required")
        if self.scope not in ("source_sample", "latest_captured_sample"):
            raise ValueError("unsupported temporal scope")
        if self.predicate == "observed_in_sample":
            if type(self.value) is not bool:
                raise ValueError("observation claim requires boolean")
        elif self.predicate in ("bearing_mdeg", "range_milli_cells"):
            if type(self.value) is not int:
                raise ValueError("measurement claim requires integer")
        elif self.predicate == "owner_status":
            if self.value not in ("known", "absent"):
                raise ValueError("invalid owner status")
        else:
            raise ValueError("unsupported predicate")


class ObservationClaimVerifier:
    def __init__(self, coordinator):
        if type(coordinator) is not E25LabCognitiveCoordinator:
            raise TypeError("trusted lab coordinator required")
        self._coordinator = coordinator
        self._memory = coordinator._memory

    def verify(self, turn_id, claim):
        if type(claim) is not ObservationClaim:
            raise TypeError("typed claim required")
        def verdict(status, reason, actual=None):
            return {"schema":"anima.lab.observation_claim_verdict/0.1",
                    "turn_id":turn_id,"claim":{
                        "entity_ref":claim.entity_ref,"predicate":claim.predicate,
                        "value":claim.value,"event_id":claim.event_id,
                        "sample_id":claim.sample_id,"scope":claim.scope},
                    "status":status,"reason_code":reason,"observed_value":actual,
                    "world_truth_authority":False,"knowledge_write":False}
        records = self._coordinator.decision_records(turn_id)
        eligible = []
        for record in records:
            p, o = record["proposal"], record["outcome"]
            if (record["admission"] != "ADMITTED" or o["status"] != "COMPLETED"
                    or p is None or p["operation_kind"] != "lookup_raw_evidence"
                    or o.get("operation_kind") != p["operation_kind"]
                    or p["turn_id"] != turn_id
                    or p["context_snapshot_id"] != record["context_snapshot"]["context_snapshot_id"]
                    or o["result"]["kind"] != "verified_raw_evidence"
                    or claim.event_id not in p["arguments"]["event_ids"]):
                continue
            eligible.extend((row,record["context_snapshot"]) for row in o["result"]["records"]
                if row["event_id"] == claim.event_id and row["status"] == "verified_source_view")
        if not eligible:
            return verdict("UNSUPPORTED","SOURCE_NOT_VERIFIED_IN_TURN")
        row, ctx = eligible[0]
        if any(r != row or c != ctx for r,c in eligible):
            return verdict("UNSUPPORTED","INCONSISTENT_SOURCE_READS")
        if row["sample_id"] != claim.sample_id:
            return verdict("UNSUPPORTED","SAMPLE_ID_MISMATCH")
        if claim.scope == "latest_captured_sample" and claim.sample_id != ctx["latest_sample_id"]:
            return verdict("UNSUPPORTED","HISTORICAL_SOURCE_NOT_LATEST")
        # Resolve the same event to the same sample, not arbitrary model IDs.
        with closing(self._memory._connect()) as db:
            binding = db.execute("SELECT core_event_id FROM e24_raw WHERE sample_id=?",
                                 (claim.sample_id,)).fetchone()
        if binding is None or binding["core_event_id"] != claim.event_id:
            return verdict("UNSUPPORTED","RAW_EVENT_BINDING_MISMATCH")
        try:
            view = self._memory.raw_evidence(claim.sample_id)
        except (E24MemoryError, ValueError, TypeError):
            return verdict("UNSUPPORTED","RAW_INTEGRITY_FAILURE")
        data = view.as_dict()
        if (hashlib.sha256(view.canonical_json.encode("utf-8")).hexdigest() != row["raw_sha256"]
                or data["sample_id"] != row["sample_id"]
                or data["sample_seq"] != row["sample_seq"]
                or data["source_ref"] != row["source_ref"]
                or [r["entity_ref"] for r in data["readings"]] != row["entities_observed"]):
            return verdict("UNSUPPORTED","RAW_RESULT_MISMATCH")
        reading = next((r for r in data["readings"] if r["entity_ref"] == claim.entity_ref),None)
        if claim.predicate == "observed_in_sample":
            actual = reading is not None
        elif reading is None:
            return verdict("UNSUPPORTED","ENTITY_NOT_OBSERVED")
        elif claim.predicate == "owner_status":
            if "owner" not in reading["properties"]:
                return verdict("UNSUPPORTED","PROPERTY_NOT_OBSERVED")
            actual = reading["properties"]["owner"]["status"]
        else:
            actual = reading[claim.predicate]
        return verdict("VERIFIED" if actual == claim.value else "CONTRADICTED",
                       "MATCHES_CAPTURED_SAMPLE" if actual == claim.value else "VALUE_MISMATCH",
                       actual)
