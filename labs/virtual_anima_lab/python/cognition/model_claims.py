"""Experimental final claim wire format, not a completion or Knowledge gate."""
from anima.agent.native_tools import strict_json
from .claim_verification import ObservationClaim, ObservationClaimVerifier
from .source_binding import admitted_source_rows

CLAIM_INSTRUCTION = (
    ' Finish with one JSON object, no markdown: {"answer":"brief answer","claims":[]}. '
    'For each observation assertion supported by a verified source, include a claim '
    'with keys entity_ref, predicate, value, event_id, sample_seq, scope. '
    'Predicates: observed_in_sample (boolean), bearing_mdeg (integer), '
    'range_milli_cells (integer), owner_status ("known" or "absent"). '
    'Scope: source_sample or latest_captured_sample. Use actual source event_id '
    'and sample_seq. Do not claim current visibility using historical evidence. '
    'If no supported observation assertion is available, claims may be empty. '
    'Keep answer concise and at most 4 claims.'
)


def parse_final(text):
    if type(text) is not str or len(text.encode("utf-8")) > 8192:
        raise ValueError("bounded final response required")
    obj = strict_json(text)
    if (type(obj) is not dict or set(obj) != {"answer", "claims"}
            or type(obj["answer"]) is not str or not obj["answer"].strip()
            or len(obj["answer"]) > 2048 or type(obj["claims"]) is not list
            or len(obj["claims"]) > 4):
        raise ValueError("invalid final envelope")
    for item in obj["claims"]:
        if (type(item) is not dict or set(item) != {
                "entity_ref", "predicate", "value", "event_id", "sample_seq", "scope"}
                or type(item["sample_seq"]) is not int or item["sample_seq"] < 1):
            raise ValueError("invalid claim fields")
        # Validate shape without inventing a source binding.
        ObservationClaim(item["entity_ref"], item["predicate"], item["value"],
                         item["event_id"], "unresolved", item["scope"])
    return obj


def evaluate_model_claims(coordinator, report, calls):
    result = {"schema":"anima.lab.model_claims/0.1", "format_status":"NO_ACCEPTED_FINAL",
              "answer":None, "claims":[], "verdicts":[],
              "verified_positive_entities":[], "free_text_verified":False,
              "task_completion":"NOT_ESTABLISHED"}
    if (report["status"] != "STOPPED" or not calls or not calls[-1].get("valid")
            or not calls[-1].get("transport_ok") or calls[-1].get("finish_reason") != "stop"
            or calls[-1].get("turn_id") != report["turn_id"]
            or calls[-1].get("context_snapshot_id") != report["context_snapshot_id"]):
        return result
    try:
        obj = parse_final(calls[-1].get("final_text"))
    except (ValueError, TypeError, KeyError, UnicodeError):
        result["format_status"] = "INVALID"
        return result
    result.update(format_status="VALID", answer=obj["answer"], claims=obj["claims"])
    records = coordinator.decision_records(report["turn_id"])
    # Resolve only through admitted source results in this turn; never query
    # the database to discover a source ID supplied by the model.
    sources = {}
    for rec in records:
        for row in admitted_source_rows(rec):
            sources.setdefault((row["event_id"],row["sample_seq"]),set()).add(row["sample_id"])
    verifier = ObservationClaimVerifier(coordinator)
    for item in obj["claims"]:
        ids = sources.get((item["event_id"],item["sample_seq"]),set())
        if len(ids) != 1:
            verdict = {"status":"UNSUPPORTED","reason_code":"SOURCE_SEQUENCE_NOT_BOUND"}
        else:
            claim = ObservationClaim(item["entity_ref"],item["predicate"],item["value"],
                                     item["event_id"],next(iter(ids)),item["scope"])
            verdict = verifier.verify(report["turn_id"],claim)
        result["verdicts"].append({"submitted_claim":item,**verdict})
    result["verified_positive_entities"] = sorted({
        v["submitted_claim"]["entity_ref"] for v in result["verdicts"]
        if v["status"] == "VERIFIED" and v["submitted_claim"]["predicate"] == "observed_in_sample"
        and v["submitted_claim"]["value"] is True})
    return result


def temporal_claim_coverage(completion, evaluation):
    """Check both time scopes using trusted same-turn completion/verifier outputs."""
    if (completion["requirement"]["kind"] != "historical_and_latest_observation"
            or not completion["information_requirement_satisfied"]
            or evaluation["format_status"] != "VALID"
            or any(v["status"] != "VERIFIED" for v in evaluation["verdicts"])):
        return False
    latest = completion["latest_source"]
    claims = [v["claim"] for v in evaluation["verdicts"]
              if v["claim"]["predicate"] == "observed_in_sample"]
    for entity in completion["requirement"]["entities"]:
        historical = any(c["entity_ref"] == entity and c["scope"] == "source_sample"
                         and c["value"] is True and c["event_id"] in
                         completion["historical_sources_by_entity"][entity]
                         for c in claims)
        current = any(c["entity_ref"] == entity and c["scope"] == "latest_captured_sample"
                      and c["event_id"] == latest["event_id"] and c["sample_id"] == latest["sample_id"]
                      and c["value"] is completion["latest_observed_by_entity"][entity]
                      for c in claims)
        if not historical or not current:
            return False
    return True
