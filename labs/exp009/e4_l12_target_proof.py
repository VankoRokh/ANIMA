"""Source-pointer evidence for E4 CorrectionTarget research, read-only.

A typed event reference is evidence of WHAT the reporting Event points at;
it is not proof the correction is true or admissible by production Core.
There are no MemoryStore writes, no gold access and no automatic revisions.
"""
from datetime import datetime
import hashlib
import json

from anima.core.event_bus import Event
from labs.exp009.e4_l11_association import SEPARATE, NOT_MERGE

SCHEMA = "anima.e4.explicit_correction_target_lab/0.1"
MAX_SOURCE_EVENTS = 64
MAX_POINTERS = 8


def source_fingerprint(raw):
    data = json.dumps(raw, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _text(raw):
    return raw["payload"].get("text", "")


def _reason(code, *, trigger_id=None):
    return {
        "status": "rejected_or_insufficient",
        "reason_codes": [code],
        "trigger_event_id": trigger_id,
        "authority": "NO_CORE_ADMISSION",
        "production_admission": False,
        "core_authority_verified": False,
        "memory_store_unchanged": True,
    }


def assess(case, base_assignments, *, expected_snapshot):
    """Assess explicit source-event pointers against a versioned prior view.

    Never mutate the caller's case, L0 assignments or production memory.
    """
    if (not isinstance(case, dict) or not isinstance(base_assignments, dict)
            or not isinstance(expected_snapshot, dict)):
        raise ValueError("Case, L0 assignments and versioned source snapshot required")
    events = case.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_SOURCE_EVENTS:
        raise ValueError("Out-of-budget or absent source Events")
    by_id, by_key = {}, {}
    for item in events:
        if not isinstance(item, dict) or set(item) != {"key", "raw"}:
            raise ValueError("Malformed source event entry")
        Event.validate_record(item["raw"])
        if (item["raw"]["id"] in by_id or item["key"] in by_key
                or not isinstance(item["key"], str) or not item["key"]):
            raise ValueError("Duplicate or malformed source Event key/ID")
        by_id[item["raw"]["id"]] = item["raw"]
        by_key[item["key"]] = item["raw"]
    prior = case.get("setup", {}).get("prior_projection")
    response = {
        "schema": SCHEMA, "status": "LAB_ONLY_NEVER_PRODUCTION_ADMISSION",
        "projection_id": prior.get("id") if isinstance(prior, dict) else None,
        "projection_revision": prior.get("revision") if isinstance(prior, dict) else None,
        "assessments": [],
        "memory_store_unchanged": True,
        "core_authority_verified": False,
        "production_admission": False,
    }
    if not isinstance(prior, dict):
        response["assessments"].append(_reason("no_versioned_prior_projection"))
        return response
    prior_ids = prior.get("source_event_ids")
    prior_group = prior.get("episode_group")
    if (not isinstance(prior.get("id"), str) or not prior["id"]
            or type(prior.get("revision")) is not int or prior["revision"] < 1
            or not isinstance(prior_ids, list) or len(prior_ids) != 2
            or len(set(prior_ids)) != 2
            or not isinstance(prior_group, list) or len(prior_group) != 2
            or len(set(prior_group)) != 2
            or set(prior_ids) - set(by_id)
            or [by_key.get(x, {}).get("id") for x in prior_group] != prior_ids):
        response["assessments"].append(_reason("invalid_prior_projection_source_binding"))
        return response
    # Snapshot is supplied by the laboratory's *separate* source ledger.
    # Matching this caller-provided record is necessary, not Core attestation.
    expected = {
        "projection_id": prior["id"],
        "revision": prior["revision"],
        "source_event_ids": list(prior_ids),
        "source_sha256": {key: source_fingerprint(by_id[key]) for key in prior_ids},
    }
    if expected_snapshot != expected:
        response["assessments"].append(_reason("projection_snapshot_mismatch"))
        return response
    first, second = (by_id[x] for x in prior_ids)
    assignments = [base_assignments.get(x) for x in prior_ids]
    if not assignments[0] or assignments[0] != assignments[1]:
        response["assessments"].append(_reason("source_pair_not_merged_in_L0"))
        return response
    previous_ids = set(prior_ids)
    offsets = {e["raw"]["id"]: i for i, e in enumerate(events)}
    candidate_triggers = [
        item["raw"] for item in events
        if item["raw"]["id"] not in previous_ids
        and any(ref["kind"] == "event" for ref in item["raw"]["references"])
    ]
    if not candidate_triggers:
        response["assessments"].append(_reason("no_explicit_source_event_pointers"))
        return response
    for trigger in candidate_triggers:
        trigger_id = trigger["id"]
        refs = [r["id"] for r in trigger["references"] if r["kind"] == "event"]
        reason = None
        if (len(refs) != 2 or len(refs) > MAX_POINTERS
                or len(set(refs)) != 2 or set(refs) != previous_ids):
            reason = "wrong_or_ambiguous_typed_source_pointers"
        elif (trigger["source"] != first["source"] or
              first["source"] != second["source"] or
              trigger["source"] != "user" or
              any(raw["type"] != "conversation.user"
                  for raw in (first, second, trigger))):
            reason = "unverified_source_authority"
        elif (not first["session_id"]
              or trigger["session_id"] != first["session_id"]
              or first["session_id"] != second["session_id"]):
            reason = "outside_bounded_session_scope"
        elif (offsets[trigger_id] <= max(offsets[x] for x in prior_ids)
              or datetime.fromisoformat(trigger["timestamp"]) <=
              max(datetime.fromisoformat(x["timestamp"]) for x in (first, second))):
            reason = "correction_not_later_than_sources"
        elif (not SEPARATE.search(_text(trigger))
              or not NOT_MERGE.search(_text(trigger))):
            reason = "pointers_without_explicit_separation_report"
        if reason:
            response["assessments"].append(_reason(reason, trigger_id=trigger_id))
            continue
        receipt = {
            "status": "source_pointer_candidate_only",
            "reason_codes": ["exact_typed_event_pointers_and_versioned_L0_merger"],
            "target_projection_id": prior["id"],
            "target_revision": prior["revision"],
            "source_event_ids": list(prior_ids),
            "source_sha256": {key: source_fingerprint(by_id[key]) for key in prior_ids},
            "trigger_event_id": trigger_id,
            "trigger_sha256": source_fingerprint(trigger),
            "binding_method": "exact_typed_event_pointer_source_report",
            "authority": "SOURCE_REPORTED_POINTERS_NOT_WORLD_TRUTH",
            "production_admission": False,
            "core_authority_verified": False,
            "memory_store_unchanged": True,
        }
        response["assessments"].append(receipt)
    return response


def verify_receipt(case, base_assignments, receipt, *, expected_snapshot):
    """Self-consistency recheck against raw Events and a caller snapshot.

    Not an independent authority verifier; never grants production permission.
    """
    if not isinstance(receipt, dict):
        raise ValueError("Receipt must be an object")
    verdict = assess(case, base_assignments, expected_snapshot=expected_snapshot)
    if (receipt.get("status") != "source_pointer_candidate_only"
            or receipt.get("production_admission") is not False
            or receipt.get("core_authority_verified") is not False
            or receipt.get("memory_store_unchanged") is not True
            or receipt not in verdict["assessments"]):
        raise ValueError("Source-pointer receipt not supported by original Events")
    return {
        "status": "receipt_consistent_with_raw_source_only",
        "production_admission": False,
        "core_authority_verified": False,
    }
