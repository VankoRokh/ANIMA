"""Read-only E4 L1 association proposals based on frozen raw Events.

Only existing L0 Shadow groups, explicit speaker statements and source-scoped
case IDs contribute. Gold never enters the adapter. No persistent writes.
"""
import argparse
import json
from itertools import combinations
from pathlib import Path
import re

from labs.exp009.e4_l0_observation import _load_frozen_inputs, run_case as l0_case

TRACE_SCHEMA = "anima.e4.association_observation_l1/0.1"
MAX_PAIRS = 128
CASE_ID = re.compile(
    r"\b(?:тикет|тикета|случай|случая|ticket|case)"
    r"\s*(?:№\s*|#\s*)?(?P<token>[A-Za-z]?\d{1,6})\b", re.I
)
PROJECT = re.compile(r"\b(?:проект|проекте|project)\s+([A-Za-zА-Яа-я0-9_-]+)", re.I)
SAME_INCIDENT = re.compile(
    r"\bоба\s+отказа\s+относятся\s+к\s+одному\s+аварийному\s+событию"
    r"\s+[A-Za-z]\d{1,6}\b", re.I
)
RECURS = re.compile(r"\b(?:снова|опять|вновь|повторно|again|recurring)\b", re.I)
ALIAS_QUOTED = re.compile(
    r"\bпод\s+[«\"'](?P<label>[^»\"']{1,48})[»\"']"
    r"\s+я\s+имел\s+в\s+виду\b", re.I
)
ALIAS_SIMPLE = re.compile(
    r"\bпод\s+(?P<label>[А-Яа-яA-Za-z_-]{3,40})\s+я\s+имел\s+в\s+виду\b", re.I
)
ALIAS_CONTEXT = re.compile(
    r"\bкогда\s+я\s+говорю\s+(?P<label>[A-Za-zА-Яа-я0-9_-]{2,40})"
    r"\s+в\s+контексте\b", re.I
)
ALIAS_MENTION = re.compile(r"\b(?:адаптер(?:ом|а|е)?|PSU)\b", re.I)


def _refs(raw, kind="entity"):
    return frozenset(x["id"] for x in raw["references"] if x["kind"] == kind)


def _raw_text(raw):
    value = raw["payload"].get("text", "")
    return value if isinstance(value, str) else ""


def _case_marker(raw):
    found = CASE_ID.search(_raw_text(raw))
    return found.group("token").upper() if found else None


def _scope(raw, setup):
    project = PROJECT.search(_raw_text(raw))
    if project:
        return (raw["source"], "project:" + project.group(1).casefold())
    if raw["source"] != "user":
        return (raw["source"], "untrusted_external")
    namespace = setup.get("ticket_namespace") or setup.get("case_id_namespace")
    return ("user", str(namespace) if namespace else "speaker_local")


def story_assessments(case):
    events = case["events"]
    if len(events) * (len(events) - 1) // 2 > MAX_PAIRS:
        raise ValueError("E4-L1 pair budget exceeded")
    rows = []
    for a, b in combinations(events, 2):
        ar, br = a["raw"], b["raw"]
        ca, cb = _case_marker(ar), _case_marker(br)
        ra, rb = _refs(ar), _refs(br)
        value, reason, sources = "insufficient", "no_scoped_case_evidence", []
        if ca and cb and _scope(ar, case["setup"]) == _scope(br, case["setup"]):
            sources = [ar["id"], br["id"]]
            value = "same_case_reported" if ca == cb else "not_same_case_reported"
            reason = "same_case_marker" if ca == cb else "different_case_markers"
        elif ca and cb:
            reason = "different_or_untrusted_namespaces"
        elif (ar["source"] == br["source"] == "user"
              and ar["session_id"] != br["session_id"]
              and ra & rb
              and (RECURS.search(_raw_text(ar)) or RECURS.search(_raw_text(br)))):
            value, reason = "candidate_only", "recurrence_shared_entity"
            sources = [ar["id"], br["id"]]

        if value == "insufficient" and ar["source"] == br["source"] == "user":
            for later in events:
                rr = later["raw"]
                if (later is a or later is b or rr["source"] != "user"
                    or rr["session_id"] != ar["session_id"]
                    or rr["session_id"] != br["session_id"]
                    or rr["timestamp"] < max(ar["timestamp"], br["timestamp"])
                    or not SAME_INCIDENT.search(_raw_text(rr))):
                    continue
                if ra and rb and ra.isdisjoint(rb) and ra | rb <= _refs(rr):
                    value, reason, sources = (
                        "same_case_reported", "later_explicit_shared_incident",
                        [rr["id"]]
                    )
                    break
        rows.append({
            "left_event_key": a["key"], "right_event_key": b["key"],
            "left_event_id": ar["id"], "right_event_id": br["id"],
            "status": value, "reason_codes": [reason],
            "source_event_ids": sources, "authority": "source_report_not_world_fact",
        })
    return rows


def _surface(text):
    text = " ".join(text.strip(" «»\"'\t").split()).casefold()
    # Small declared inflection rule, not a general language model.
    if text.endswith("тером") and len(text) > 6:
        return text[:-2]
    return text


def _explicit_label(raw):
    if raw["source"] != "user" or raw["type"] != "conversation.user":
        return None
    for expression in (ALIAS_QUOTED, ALIAS_SIMPLE, ALIAS_CONTEXT):
        match = expression.search(_raw_text(raw))
        if match:
            return _surface(match.group("label"))
    return None


def _source_target(raw, entities):
    text, refs = _raw_text(raw).casefold(), _refs(raw)
    if "блок питания" in text:
        matches = [eid for name, eid in entities.items()
                   if "psu" in name.casefold() and eid in refs]
    elif "wi-fi" in text or "wifi" in text:
        matches = [eid for name, eid in entities.items()
                   if "wifi" in name.casefold() and eid in refs]
    else:
        matches = []
    return matches[0] if len(matches) == 1 else None


def alias_observations(case, entities):
    records, mentions = [], []
    for event in case["events"]:
        raw = event["raw"]
        label = _explicit_label(raw)
        target = _source_target(raw, entities) if label else None
        if label:
            if target is None:
                mentions.append({
                    "event_key": event["key"], "surface": label,
                    "status": "abstain_target_ambiguous",
                })
            else:
                records.append({
                    "surface": label, "target_entity_id": target,
                    "status": "speaker_intent_confirmed_in_scope",
                    "source_event_id": raw["id"], "speaker": raw["source"],
                    "session_id": raw["session_id"],
                    "anchor_entity_ids": sorted(_refs(raw) - {target}),
                    "authority": "speaker_intent_only_not_physical_truth",
                })
        for match in ALIAS_MENTION.finditer(_raw_text(raw)):
            surface = _surface(match.group(0))
            eligible = [item for item in records
                        if item["surface"] == surface and item["speaker"] == raw["source"]
                        and item["source_event_id"] != raw["id"]
                        and (item["session_id"] == raw["session_id"]
                             or bool(set(item["anchor_entity_ids"]) & _refs(raw)))]
            if eligible:
                item = eligible[-1]
                mentions.append({
                    "event_key": event["key"], "surface": surface,
                    "status": "scoped_alias_reuse",
                    "target_entity_id": item["target_entity_id"],
                    "source_event_id": item["source_event_id"],
                    "expensive_method_calls": 0,
                })
            elif label is None:
                mentions.append({
                    "event_key": event["key"], "surface": surface,
                    "status": "insufficient",
                })
        if len(records) > 32:
            raise ValueError("E4-L1 alias budget exceeded")
    return records, mentions


def origin_links(case):
    seen, links = set(), []
    for event in case["events"]:
        raw = event["raw"]
        for parent in _refs(raw, "event"):
            if parent not in seen:
                raise ValueError("Forward or foreign Event provenance reference")
            links.append({
                "child_event_id": raw["id"], "parent_event_id": parent,
                "status": "source_pointer_not_independent_evidence",
                "authority": "pointer_only_not_world_truth",
            })
        seen.add(raw["id"])
    return links


def run_case(case, *, entity_registry):
    l0 = l0_case(case, entity_registry=entity_registry)
    records, mentions = alias_observations(case, entity_registry)
    return {
        "case_id": case["id"], "track": case["track"],
        "level": "L1_CONSERVATIVE_ASSOCIATION_LAB",
        "episode_baseline": {
            "decisions": l0["decisions"], "episodes": l0["episodes"],
            "event_assignments": l0["event_assignments"],
        },
        "story_pair_assessments": story_assessments(case),
        "alias_records": records, "alias_mentions": mentions,
        "source_origin_links": origin_links(case),
        "memory_store_unchanged": l0["memory_store_unchanged"],
        "ignored_setup_keys": l0["ignored_setup_keys"],
        "unsupported_controls": l0["unsupported_controls"],
        "unsupported_capabilities": [
            "Episode_resegmentation", "GeneralEntityResolution",
            "UncertaintyRegistry", "GoalTask_research", "PeriodicScheduler",
            "CrashRecovery", "SLEEP_publication", "Knowledge_confirmation",
        ],
        "semantic_conformance": "NOT_ASSESSED",
    }


def run_suite(*, suite="positive", case_id=None):
    data = _load_frozen_inputs(suite)
    cases = data["cases"]
    if case_id is not None:
        cases = [item for item in cases if item["id"] == case_id]
        if not cases:
            raise ValueError("Unknown E4 case ID: " + case_id)
    return {
        "schema": TRACE_SCHEMA, "suite": suite,
        "status": "L1_PARTIAL_OBSERVATION_NOT_E4_CONFORMANCE",
        "gold_visible": False,
        "cases": [run_case(item, entity_registry=data["entities"]) for item in cases],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("positive", "negative"), default="positive")
    parser.add_argument("--case", dest="case_id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_suite(suite=args.suite, case_id=args.case_id)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)


if __name__ == "__main__":
    main()
