"""Common source eligibility for journal-backed observation consumers.

No DB discovery from a model claim. Raw re-read and digest verification remain
the responsibility of ObservationClaimVerifier. Invalid bindings fail closed.
"""
import re


def admitted_source_rows(record):
    p, o, ctx = record["proposal"], record["outcome"], record["context_snapshot"]
    if (record["admission"] != "ADMITTED" or o["status"] != "COMPLETED"
            or not p or p["operation_kind"] not in ("lookup_raw_evidence","inspect_latest_observation")
            or o.get("operation_kind") != p["operation_kind"]
            or p["proposal_id"] != o["proposal_id"]
            or p["turn_id"] != record["turn_id"]
            or p["context_snapshot_id"] != ctx["context_snapshot_id"]
            or o["result"]["kind"] != "verified_raw_evidence"):
        return ()
    latest = ctx["latest_sample_id"]
    prefix = f'worldobs:{ctx["world_instance_id"]}:{ctx["epoch"]}:'
    if type(latest) is not str or not latest.startswith(prefix):
        return ()
    latest_seq = latest[len(prefix):]
    if re.fullmatch(r"[1-9][0-9]*",latest_seq) is None:
        return ()
    rows = o["result"]["records"]
    is_latest = p["operation_kind"] == "inspect_latest_observation"
    if is_latest and (p["arguments"] != {} or len(rows) != 1):
        return ()
    eligible = []
    for row in rows:
        if row["status"] != "verified_source_view":
            continue
        seq = row["sample_seq"]
        if (type(seq) is not int or not 1 <= seq <= int(latest_seq)
                or row["sample_id"] != prefix + str(seq)
                or row["source_ref"] != ctx["source_ref"]):
            continue
        if is_latest:
            if row["sample_id"] != latest:
                continue
        elif row["event_id"] not in p["arguments"]["event_ids"]:
            continue
        eligible.append(row)
    return tuple(eligible)
