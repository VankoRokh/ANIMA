"""E4 L1.2: typed reported-case identity, conflict-aware speaker aliases,
and bounded CorrectionTarget scoping for a read-only lab.

This is an opt-in isolated research adapter. Gold is never imported. No raw
Event rewrite, durable revision, Core policy admission, or world-truth claim.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

from labs.exp009.e4_l0_observation import _load_frozen_inputs
from labs.exp009.e4_l11_association import (
    run_case as l11_case, TRIAL, SEPARATE, NOT_MERGE,
)
from labs.exp009.e4_l1_association import _explicit_label

SCHEMA = "anima.e4.association_observation_l1_2/0.1"
STATUS = "L1_2_CONSERVATIVE_SCOPED_LAB_NOT_E4_CONFORMANCE"

CASE_MARKER = re.compile(
    r"\b(?P<type>"
    r"тикет(?:а|е|у)?|ticket|"
    r"случа(?:й|я|е|ю)|case|"
    r"авари(?:я|и|е|ю)|инцидент(?:а|е|у)?|событи(?:е|я|ю|и)"
    r")\s*(?:№\s*|#\s*)?(?P<token>[A-Za-zА-Я]?\d{1,6})\b", re.I
)
PROJECT = re.compile(r"\b(?:проект|проекте|project)\s+(?P<name>[A-Za-zА-Яа-я0-9_-]+)\b", re.I)
DEICTIC = re.compile(r"^\s*(?:это|эти|они)\s+были\b", re.I)
TRIAL_PAIR = re.compile(
    r"\b(?:испытани(?:я|й)|тест(?:ы|а|ов)|эксперимент(?:ы|а|ов))"
    r"\s+(?P<a>[A-ZА-Я0-9]{1,3})\s+и\s+(?P<b>[A-ZА-Я0-9]{1,3})\b",
    re.I,
)
MAX_ALIAS_DEFINITIONS = 32


def text_of(event):
    result = event["payload"].get("text", "")
    return result if isinstance(result, str) else ""


def entity_ids(event):
    return {r["id"] for r in event["references"] if r["kind"] == "entity"}


def canonical_surface(surface):
    """Deliberately bounded 1–3 adjectives + feminine -кой instrumental noun."""
    words = " ".join(surface.strip(" «»\"'\t").split()).casefold().replace("ё", "е").split()
    if (2 <= len(words) <= 4
            and all(word.endswith("ой") and len(word) > 3 for word in words[:-1])
            and words[-1].endswith("кой") and len(words[-1]) > 5):
        return " ".join(
            [word[:-2] + "ая" for word in words[:-1]]
            + [words[-1][:-3] + "ка"]
        )
    return " ".join(words)


def typed_identifier(event, setup):
    match = CASE_MARKER.search(text_of(event))
    if not match:
        return None
    prefix = match.group("type").casefold()
    kind = (
        "ticket" if prefix.startswith(("тикет", "ticket"))
        else "case" if prefix.startswith(("случа", "case"))
        else "incident"
    )
    project = PROJECT.search(text_of(event))
    if project:
        scope = {"kind": "reported_project", "name": project.group("name").casefold()}
    elif kind == "ticket" and setup.get("ticket_namespace"):
        scope = {"kind": "declared_speaker_scope", "name": str(setup["ticket_namespace"])}
    elif kind == "case" and setup.get("case_id_namespace"):
        scope = {"kind": "declared_speaker_scope", "name": str(setup["case_id_namespace"])}
    else:
        scope = {"kind": "speaker_session_local", "name": event["source"],
                 "session_id": event["session_id"]}
    return {
        "kind": kind,
        "token": match.group("token").upper(),
        "namespace": scope,
        "source": event["source"],
        "source_event_id": event["id"],
        "authority": "source_report_only_not_verified_identity",
    }


def typed_story_assessments(case, legacy):
    rows = deepcopy(legacy)
    events = {e["key"]: e["raw"] for e in case["events"]}
    setup = case["setup"]
    trusted_distinct = {str(v).casefold() for v in setup.get("distinct_ticket_namespaces", [])}
    for row in rows:
        left = events[row["left_event_key"]]
        right = events[row["right_event_key"]]
        a = typed_identifier(left, setup)
        b = typed_identifier(right, setup)
        row["typed_identifiers"] = {"left": a, "right": b}
        if a is None or b is None:
            # A later user-reported joint incident may have separate evidence
            # even though the two initial reports lack explicit case markers.
            continue
        if (a["source"], b["source"]) != ("user", "user"):
            row.update(
                status="insufficient",
                reason_codes=["untrusted_case_identity"],
                source_event_ids=[],
            )
        elif a["kind"] != b["kind"]:
            row.update(
                status="insufficient",
                reason_codes=["cross_kind_identity_unverified"],
                source_event_ids=[],
            )
        elif a["namespace"] == b["namespace"]:
            status = ("same_case_reported" if a["token"] == b["token"]
                      else "not_same_case_reported")
            row.update(
                status=status,
                reason_codes=["same_typed_reported_identifier" if
                              status == "same_case_reported" else
                              "different_typed_reported_identifiers"],
                source_event_ids=[a["source_event_id"], b["source_event_id"]],
                authority="source_report_not_world_fact",
            )
            row.pop("namespace_evidence", None)
        elif (a["kind"] == "ticket" and a["token"] == b["token"]
              and a["namespace"]["kind"] == "reported_project"
              and b["namespace"]["kind"] == "reported_project"
              and {a["namespace"]["name"], b["namespace"]["name"]} <= trusted_distinct
              and a["namespace"]["name"] != b["namespace"]["name"]):
            row.update(
                status="not_same_case_reported",
                reason_codes=["verified_distinct_ticket_namespaces"],
                source_event_ids=[left["id"], right["id"]],
                namespace_evidence={
                    "kind": "trusted_fixture_precondition",
                    "setup_key": "distinct_ticket_namespaces",
                    "left": a["namespace"]["name"],
                    "right": b["namespace"]["name"],
                },
            )
        else:
            row.update(
                status="insufficient",
                reason_codes=["namespace_not_proven_equivalent"],
                source_event_ids=[],
            )
            row.pop("namespace_evidence", None)
    return rows


def conflict_aware_aliases(case, legacy_records, legacy_mentions):
    """Do not select last definition when earlier scoped referents conflict."""
    events = {e["key"]: e["raw"] for e in case["events"]}
    index = {e["raw"]["id"]: i for i, e in enumerate(case["events"])}
    records = deepcopy(legacy_records)
    if len(records) > MAX_ALIAS_DEFINITIONS:
        raise ValueError("L1.2 candidate alias budget exceeded")
    for record in records:
        record["canonical_l12"] = canonical_surface(record["surface"])
        record["canonical_method_l12"] = "bounded_multi_adjective_instrumental_v0"
    mentions = []
    for legacy in legacy_mentions:
        item = deepcopy(legacy)
        raw = events[item["event_key"]]
        surface = item["surface"]
        item["canonical_l12"] = canonical_surface(surface)
        item["candidate_source_event_ids"] = []
        item["reason_codes_l12"] = []
        if _explicit_label(raw) is not None:
            # The current sentence redefines a term. It is not evidence that
            # an older target was the intended referent of this very sentence.
            item.update(status="insufficient", reason_codes_l12=["definition_not_reuse"])
            item.pop("target_entity_id", None)
            item.pop("source_event_id", None)
            item.pop("expensive_method_calls", None)
            mentions.append(item)
            continue
        candidates = [
            d for d in records
            if (d["surface"] == surface and d["speaker"] == raw["source"]
                and index[d["source_event_id"]] < index[raw["id"]]
                and (d["session_id"] == raw["session_id"]
                     or bool(entity_ids(raw) & set(d["anchor_entity_ids"]))))
        ]
        item["candidate_source_event_ids"] = [d["source_event_id"] for d in candidates]
        anchors = entity_ids(raw)
        matched = [
            d for d in candidates
            if (d["target_entity_id"] in anchors
                or bool(anchors & set(d["anchor_entity_ids"])))
        ] if anchors else []
        if matched:
            # Explicitly named current Entity/source anchor constrains scope.
            candidates = matched
            reason = "source_entity_anchor_filters_competing_aliases"
        elif anchors and any(d["anchor_entity_ids"] for d in candidates):
            candidates = []
            reason = "current_anchor_disagrees_with_known_alias_context"
        else:
            reason = "unique_source_backed_candidate" if candidates else "no_eligible_definition"
        targets = {d["target_entity_id"] for d in candidates}
        if len(targets) == 1:
            last = candidates[-1]
            item.update(
                status="scoped_alias_reuse",
                target_entity_id=last["target_entity_id"],
                source_event_id=last["source_event_id"],
                expensive_method_calls=0,
                reason_codes_l12=[reason],
            )
        else:
            item.update(
                status="insufficient",
                reason_codes_l12=[
                    "competing_scoped_entity_definitions" if len(targets) > 1 else reason
                ],
            )
            item.pop("target_entity_id", None)
            item.pop("source_event_id", None)
            item.pop("expensive_method_calls", None)
        mentions.append(item)
    return records, mentions


def correction_scope(case, previous_view):
    """Bounded discourse binding; emits *lab-only* materializations/candidates."""
    view = deepcopy(previous_view)
    reports = []
    prior = case["setup"].get("prior_projection")
    events_by_id = {row["raw"]["id"]: row["raw"] for row in case["events"]}
    by_index = {row["raw"]["id"]: i for i, row in enumerate(case["events"])}
    if not prior or not isinstance(prior, dict):
        return view, reports
    for proposal in previous_view["revision_proposals"]:
        target_ids = proposal["source_event_ids"]
        trigger_id = proposal["trigger_event_id"]
        sources = [events_by_id.get(source_id) for source_id in target_ids]
        trigger = events_by_id.get(trigger_id)
        status = "rejected_unbound"
        binding = "none"
        reason = "cannot_bind_correction_to_exact_prior_pair"
        if (len(sources) == 2 and all(sources) and trigger
                and set(target_ids) == set(prior.get("source_event_ids", []))
                and prior.get("id") == proposal["source_projection_id"]
                and prior.get("revision") == proposal["old_revision"]
                and trigger["source"] == sources[0]["source"] == sources[1]["source"] == "user"
                and trigger["session_id"] == sources[0]["session_id"] ==
                    sources[1]["session_id"]
                and by_index[trigger_id] > max(by_index[x] for x in target_ids)
                and SEPARATE.search(text_of(trigger))
                and NOT_MERGE.search(text_of(trigger))):
            labels = [TRIAL.search(text_of(s)) for s in sources]
            expected_labels = {m.group(1).upper() for m in labels if m}
            event_refs = {
                x["id"] for x in trigger["references"] if x["kind"] == "event"
            }
            paired = TRIAL_PAIR.search(text_of(trigger))
            # Verified typed raw pointers are strongest. If absent, the two
            # language-only alternatives are explicit laboratory heuristics.
            if event_refs == set(target_ids) and len(event_refs) == 2:
                status, binding, reason = (
                    "lab_scoped_candidate",
                    "explicit_event_source_pointers_lab_only",
                    "exact_typed_event_pointers_and_later_correction",
                )
            elif paired and {paired["a"].upper(), paired["b"].upper()} == expected_labels and len(expected_labels) == 2:
                status, binding, reason = (
                    "lab_scoped_candidate",
                    "explicit_trial_labels_lab_only",
                    "correction_names_both_source_trial_labels",
                )
            elif (DEICTIC.search(text_of(trigger)) and len(expected_labels) == 2
                  and len(prior.get("episode_group", [])) == 2):
                # A deictic correction is scoped only if no other same-entity
                # named trial occurred after original pair and before trigger.
                after_pair = max(by_index[x] for x in target_ids)
                competing = [
                    row["raw"] for row in case["events"][after_pair + 1:by_index[trigger_id]]
                    if (row["raw"]["source"] == trigger["source"]
                        and row["raw"]["session_id"] == trigger["session_id"]
                        and entity_ids(row["raw"]) & entity_ids(sources[0])
                        and TRIAL.search(text_of(row["raw"])))
                ]
                if not competing:
                    status, binding, reason = (
                        "lab_scoped_candidate",
                        "bounded_deictic_lab_only",
                        "deictic_correction_unique_local_antecedent",
                    )
        reports.append({
            "target_projection_id": proposal["source_projection_id"],
            "target_revision": proposal["old_revision"],
            "target_source_event_ids": list(target_ids),
            "correction_event_id": trigger_id,
            "status": status,
            "binding_method": binding,
            "reason_codes": [reason],
            "authority": "SOURCE_SCOPED_LAB_CANDIDATE_NOT_CORE_ADMITTED",
            "production_admission": False,
            "raw_events_modified": False,
        })
        if status != "lab_scoped_candidate":
            # An unbound correction must never modify the derived head view.
            view["effective_assignments"] = dict(view["base_assignments"])
            view["revision_proposals"] = []
            view["status"] = "identical_to_L0_shadow"
    return view, reports


def run_case(case, *, entity_registry):
    old = l11_case(case, entity_registry=entity_registry)
    out = deepcopy(old)
    out["level"] = "L1_2_SCOPED_RESEARCH_LAB"
    out["story_pair_assessments"] = typed_story_assessments(
        case, old["story_pair_assessments"]
    )
    out["alias_records"], out["alias_mentions"] = conflict_aware_aliases(
        case, old["alias_records"], old["alias_mentions"]
    )
    out["episode_view"], out["correction_target_assessments"] = correction_scope(
        case, old["episode_view"]
    )
    out["unsupported_capabilities"] = [
        "DurableEpisodeResegmentation", "GeneralEntityResolution",
        "AutonomousCorrectionTargetVerification", "UncertaintyRegistry",
        "GoalTask_research", "PeriodicScheduler", "CrashRecovery",
        "SLEEP_publication", "Knowledge_confirmation",
    ]
    out["semantic_conformance"] = "NOT_ASSESSED"
    out["memory_store_unchanged"] = True
    return out


def run_suite(*, suite="positive", case_id=None):
    data = _load_frozen_inputs(suite)
    cases = data["cases"]
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
        if not cases:
            raise ValueError("Unknown frozen E4 case ID")
    return {
        "schema": SCHEMA, "suite": suite, "status": STATUS,
        "gold_visible": False, "cases": [
            run_case(case, entity_registry=data["entities"]) for case in cases
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("positive", "negative"), default="positive")
    parser.add_argument("--case", dest="case_id")
    parser.add_argument("--output", type=Path)
    options = parser.parse_args(argv)
    result = run_suite(suite=options.suite, case_id=options.case_id)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if options.output is None:
        print(payload, end="")
    else:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        with options.output.open("x", encoding="utf-8") as target:
            target.write(payload)


if __name__ == "__main__":
    main()
