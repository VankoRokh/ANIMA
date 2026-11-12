"""E4 L1.1: experimental in-memory corrections atop unchanged L1/Shadow.

Works only on frozen raw Events, uses declared scope/provenance constraints,
never opens gold or writes production Memory. Derived resegmentation is NOT
durable E4 Memory revision or independent proof of physical-world truth.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

from labs.exp009.e4_l0_observation import _load_frozen_inputs
from labs.exp009.e4_l1_association import run_case as run_l1_case

SCHEMA = "anima.e4.association_observation_l1_1/0.1"
TRIAL = re.compile(r"\b(?:тест(?:е|а|у)?|испытани(?:и|е|я)?|эксперимент(?:е|а|у)?)\s+([A-ZА-Я0-9]{1,3})\b")
SEPARATE = re.compile(
    r"\b(?:два|две|2)\s+(?:независим\w*|отдельн\w*|различн\w*)\s+"
    r"(?:испытан\w*|тест\w*|эксперимент\w*)", re.I
)
NOT_MERGE = re.compile(r"\b(?:нельзя|не\s+следует)\s+объедин\w*|\bраздел\w*|\bне\s+один\s+и\s+тот\s+же\b", re.I)
REPORTED_CASE = re.compile(
    r"\b(?:тикет(?:а|у|е)?|ticket|case|случа[йеяю]|"
    r"авари[яиею]|инцидент(?:а|е|у)?|событи[еяи])"
    r"\s*(?:№\s*|#\s*)?(?P<id>[A-Za-zА-Я]?\d{1,6})\b", re.I
)
PROJECT = re.compile(r"\b(?:проект|проекте|project)\s+(?P<name>[A-Za-zА-Яа-я0-9_-]+)\b", re.I)
MAX_REVISIONS = 8


def normalize_feminine_alias(surface):
    """Bounded grammatical normalization; no synonym or Entity identity rule."""
    words = " ".join(surface.strip(" «»\"'\t").split()).casefold().replace("ё", "е").split()
    if (len(words) == 2 and words[0].endswith("ой")
            and words[1].endswith("кой")
            and len(words[0]) > 3 and len(words[1]) > 5):
        return words[0][:-2] + "ая " + words[1][:-3] + "ка"
    return " ".join(words)


def _raw_text(raw):
    value = raw["payload"].get("text", "")
    return value if isinstance(value, str) else ""


def _case_marker(raw):
    match = REPORTED_CASE.search(_raw_text(raw))
    return match.group("id").upper() if match else None


def _namespace(raw, setup):
    match = PROJECT.search(_raw_text(raw))
    if match:
        return ("project", match.group("name").casefold())
    if raw["source"] != "user":
        return ("unknown_external", raw["source"])
    declared = setup.get("ticket_namespace") or setup.get("case_id_namespace")
    return ("speaker", str(declared) if declared else "local")


def _entity_refs(raw):
    return frozenset(x["id"] for x in raw["references"] if x["kind"] == "entity")


def enhance_stories(case, legacy):
    """Only strengthen source-reported named-case relations, not world truth."""
    items = deepcopy(legacy)
    rows = {x["key"]: x["raw"] for x in case["events"]}
    setup = case["setup"]
    trusted_distinct = {str(x).casefold() for x in setup.get("distinct_ticket_namespaces", [])}
    for row in items:
        left, right = rows[row["left_event_key"]], rows[row["right_event_key"]]
        la, lb = _case_marker(left), _case_marker(right)
        if not (la and lb and left["source"] == right["source"] == "user"):
            continue
        na, nb = _namespace(left, setup), _namespace(right, setup)
        if na == nb:
            if la == lb and row["status"] != "same_case_reported":
                row.update(
                    status="same_case_reported",
                    reason_codes=["matching_source_reported_case_in_scoped_namespace"],
                    source_event_ids=[left["id"], right["id"]],
                    authority="source_report_not_world_fact",
                )
            # Do not promote different *reported* case markers to verified
            # distinct physical incidents; legacy labels are left unchanged.
        elif (la == lb and na[0] == nb[0] == "project"
              and na[1] != nb[1]
              and {na[1], nb[1]} <= trusted_distinct):
            row.update(
                status="not_same_case_reported",
                reason_codes=["trusted_distinct_ticket_namespaces"],
                source_event_ids=[left["id"], right["id"]],
                authority="source_report_not_world_fact",
                namespace_evidence={
                    "kind": "trusted_fixture_precondition",
                    "setup_key": "distinct_ticket_namespaces",
                    "left": na[1], "right": nb[1],
                },
            )
    return items


def derived_episode_view(case, baseline):
    """Materialize scoped derived assignments; never mutate baseline."""
    original = baseline["event_assignments"]
    effective = dict(original)
    proposals = []
    events = case["events"]
    by_key = {x["key"]: x["raw"] for x in events}
    prior = case["setup"].get("prior_projection")
    if not isinstance(prior, dict):
        return {
            "status": "identical_to_L0_shadow",
            "base_assignments": original,
            "effective_assignments": effective,
            "revision_proposals": proposals,
        }
    source_ids = prior.get("source_event_ids")
    source_keys = prior.get("episode_group")
    if (not isinstance(source_ids, list) or len(source_ids) != 2
            or not isinstance(source_keys, list) or len(source_keys) != 2
            or any(key not in by_key for key in source_keys)
            or [by_key[key]["id"] for key in source_keys] != source_ids
            or not isinstance(prior.get("revision"), int)
            or isinstance(prior["revision"], bool)
            or prior["revision"] < 1 or not prior.get("id")):
        return {
            "status": "inapplicable_unverified_projection_precondition",
            "base_assignments": original,
            "effective_assignments": effective,
            "revision_proposals": proposals,
        }
    first, second = [by_key[key] for key in source_keys]
    if (first["source"] != second["source"] or first["source"] != "user"
            or first["session_id"] != second["session_id"]
            or not _entity_refs(first) & _entity_refs(second)
            or not original.get(first["id"])
            or original.get(first["id"]) != original.get(second["id"])):
        return {
            "status": "no_qualified_merged_source_pair",
            "base_assignments": original,
            "effective_assignments": effective,
            "revision_proposals": proposals,
        }
    labels = [TRIAL.search(_raw_text(raw)) for raw in (first, second)]
    if not all(labels) or labels[0].group(1) == labels[1].group(1):
        return {
            "status": "insufficient_distinct_trial_identifiers",
            "base_assignments": original,
            "effective_assignments": effective,
            "revision_proposals": proposals,
        }
    for correction in events:
        raw = correction["raw"]
        if raw["id"] in source_ids or raw["source"] != "user":
            continue
        if (raw["session_id"] != first["session_id"]
                or raw["timestamp"] <= second["timestamp"]
                or not _entity_refs(raw) & _entity_refs(first)):
            continue
        text = _raw_text(raw)
        if not (SEPARATE.search(text) and NOT_MERGE.search(text)):
            continue
        # The new ID is a derived view label, not a production public_id.
        revised_id = "lab_revised_episode_" + second["id"]
        effective[second["id"]] = revised_id
        proposals.append({
            "status": "materialized_in_lab_view_only",
            "source_projection_id": prior["id"],
            "old_revision": prior["revision"],
            "new_revision": prior["revision"] + 1,
            "changed_event_id": second["id"],
            "related_original_event_id": first["id"],
            "new_episode_id": revised_id,
            "trigger_event_id": raw["id"],
            "trigger_source": "user",
            "source_event_ids": list(source_ids),
            "reason_codes": [
                "explicit_later_independent_trials",
                "separate_named_trial_identifiers",
                "previously_merged_in_L0_shadow",
            ],
            "authority": "source_user_report_for_lab_organization_only",
            "raw_events_modified": False,
        })
        break
    if len(proposals) > MAX_REVISIONS:
        raise ValueError("L1.1 revision budget exceeded")
    return {
        "status": "lab_revised_derived_view" if proposals else "identical_to_L0_shadow",
        "base_assignments": original,
        "effective_assignments": effective,
        "revision_proposals": proposals,
    }


def run_case(case, *, entity_registry):
    legacy = run_l1_case(case, entity_registry=entity_registry)
    out = deepcopy(legacy)
    out["level"] = "L1_1_CONSERVATIVE_REVISABLE_LAB"
    out["story_pair_assessments"] = enhance_stories(
        case, legacy["story_pair_assessments"]
    )
    for alias in out["alias_records"]:
        alias["surface_canonical"] = normalize_feminine_alias(alias["surface"])
        alias["normalization"] = "bounded_feminine_adj_instrumental_noun_v1"
    for mention in out["alias_mentions"]:
        mention["surface_canonical"] = normalize_feminine_alias(mention["surface"])
    out["episode_view"] = derived_episode_view(
        case, legacy["episode_baseline"]
    )
    old_usage = out.get("setup_usage", {"read_keys": [], "unhandled_keys": []})
    read = set(old_usage["read_keys"])
    if "prior_projection" in case["setup"]:
        read.add("prior_projection")
    if "distinct_ticket_namespaces" in case["setup"]:
        read.add("distinct_ticket_namespaces")
    out["setup_usage"] = {
        "read_keys": sorted(read),
        "unhandled_keys": sorted(set(case["setup"]) - read),
    }
    out["unsupported_capabilities"] = [
        "DurableEpisodeResegmentation", "GeneralEntityResolution",
        "UncertaintyRegistry", "GoalTask_research", "PeriodicScheduler",
        "CrashRecovery", "SLEEP_publication", "Knowledge_confirmation",
    ]
    out["semantic_conformance"] = "NOT_ASSESSED"
    return out


def run_suite(*, suite="positive", case_id=None):
    inp = _load_frozen_inputs(suite)
    cases = inp["cases"]
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
        if not cases:
            raise ValueError("Unknown E4 case ID: " + case_id)
    return {
        "schema": SCHEMA, "suite": suite,
        "status": "L1_1_PARTIAL_LAB_NOT_E4_CONFORMANCE",
        "gold_visible": False,
        "cases": [run_case(case, entity_registry=inp["entities"]) for case in cases],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--suite", choices=("positive", "negative"), default="positive")
    p.add_argument("--case", dest="case_id")
    p.add_argument("--output", type=Path)
    opts = p.parse_args(argv)
    report = run_suite(suite=opts.suite, case_id=opts.case_id)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if opts.output:
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        with opts.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
