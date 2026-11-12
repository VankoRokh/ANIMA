"""Independent E4 L1.1 scorer: reads closed trace and frozen gold only.

Does NOT import, call, or instantiate L0/L1/L1.1 adapters. Reuses the
previous independently tested evaluator for the unchanged L1 subcontracts.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from labs.exp009 import e4_evaluator as prior

TRACE_SCHEMA = "anima.e4.association_observation_l1_1/0.1"
RESULT_SCHEMA = "anima.e4.independent_evaluation_l1_1/0.1"
ACCEPT_STATUS = "L1_1_PARTIAL_LAB_NOT_E4_CONFORMANCE"


def _canonical(surface):
    """Independently validate bounded canonical form (no gold lexicon)."""
    words = " ".join(surface.strip(" «»\"'\t").split()).casefold().replace("ё", "е").split()
    if (len(words) == 2 and words[0].endswith("ой")
            and words[1].endswith("кой")
            and len(words[0]) > 3 and len(words[1]) > 5):
        return words[0][:-2] + "ая " + words[1][:-3] + "ка"
    return " ".join(words)


def _validate_extensions(observed, original):
    if observed.get("level") != "L1_1_CONSERVATIVE_REVISABLE_LAB":
        raise ValueError("Unexpected L1.1 level")
    if "DurableEpisodeResegmentation" not in observed.get("unsupported_capabilities", []):
        raise ValueError("L1.1 must not claim durable Episode revision")
    # Reuse legacy consistency gates, but do not weaken the original output
    # validator by allowing a fabricated L1.1 proxy to masquerade as old L1.
    legacy = dict(observed)
    legacy["level"] = "L1_CONSERVATIVE_ASSOCIATION_LAB"
    legacy["unsupported_capabilities"] = [
        *observed["unsupported_capabilities"], "Episode_resegmentation"
    ]
    events, assignments, pairs = prior._check_trace(legacy, original)
    by_id = {raw["id"]: raw for raw in events.values()}
    view = observed.get("episode_view")
    if not isinstance(view, dict):
        raise ValueError("Missing L1.1 derived Episode view")
    if (view.get("base_assignments") != assignments
            or not isinstance(view.get("effective_assignments"), dict)
            or set(view["effective_assignments"]) != set(assignments)
            or not isinstance(view.get("revision_proposals"), list)):
        raise ValueError("Revision view does not match verified L0 assignments")
    proposals = view["revision_proposals"]
    if len(proposals) > 8:
        raise ValueError("Revision proposal limit exceeded")
    diffs = {
        event_id for event_id in assignments
        if assignments[event_id] != view["effective_assignments"][event_id]
    }
    if not proposals and (diffs or view.get("status") == "lab_revised_derived_view"):
        raise ValueError("Unexplained Episode assignment mutation")
    if proposals and view.get("status") != "lab_revised_derived_view":
        raise ValueError("False revised view status")
    recognized = set()
    setup = original["setup"]
    fixture_projection = setup.get("prior_projection")
    for proposal in proposals:
        if not isinstance(fixture_projection, dict):
            raise ValueError("Revision requires versioned fixture projection")
        source_ids = proposal.get("source_event_ids")
        if (source_ids != fixture_projection.get("source_event_ids")
                or proposal.get("source_projection_id") != fixture_projection.get("id")
                or proposal.get("old_revision") != fixture_projection.get("revision")
                or proposal.get("new_revision") != fixture_projection["revision"] + 1
                or proposal.get("authority") != "source_user_report_for_lab_organization_only"
                or proposal.get("status") != "materialized_in_lab_view_only"
                or proposal.get("raw_events_modified") is not False):
            raise ValueError("Revision source/version/authority forged")
        first, second = source_ids
        changed = proposal.get("changed_event_id")
        if (changed != second or proposal.get("related_original_event_id") != first
                or changed in recognized or set(source_ids) - set(by_id)
                or assignments.get(first) != assignments.get(second)
                or proposal.get("new_episode_id") != "lab_revised_episode_" + changed
                or view["effective_assignments"].get(changed) != proposal["new_episode_id"]):
            raise ValueError("Revision does not match previously merged raw Events")
        trigger = by_id.get(proposal.get("trigger_event_id"))
        if (not trigger or trigger["source"] != "user"
                or trigger["session_id"] != by_id[second]["session_id"]
                or trigger["timestamp"] <= by_id[second]["timestamp"]
                or "независим" not in trigger["payload"].get("text", "").casefold()
                or "объедин" not in trigger["payload"].get("text", "").casefold()):
            raise ValueError("Revision has no qualifying later source report")
        recognized.add(changed)
    if diffs != recognized:
        raise ValueError("Derived assignment changes are not explained by revisions")
    if not proposals and view.get("status") not in (
        "identical_to_L0_shadow", "no_qualified_merged_source_pair",
        "inapplicable_unverified_projection_precondition",
        "insufficient_distinct_trial_identifiers",
    ):
        raise ValueError("Unknown Episode view status")
    for alias in observed["alias_records"]:
        event = by_id[alias["source_event_id"]]
        if (alias.get("surface_canonical") != _canonical(alias["surface"])
                or alias["surface"].casefold() not in event["payload"].get("text", "").casefold()
                or alias.get("normalization") != "bounded_feminine_adj_instrumental_noun_v1"):
            raise ValueError("Alias source phrase or normalization is forged")
    for mention in observed["alias_mentions"]:
        if mention.get("surface_canonical") != _canonical(mention["surface"]):
            raise ValueError("Alias mention normalization is forged")
    for row in observed["story_pair_assessments"]:
        if "namespace_evidence" in row:
            x = row["namespace_evidence"]
            if (x.get("kind") != "trusted_fixture_precondition"
                    or x.get("setup_key") != "distinct_ticket_namespaces"):
                raise ValueError("Unsupported namespace authority")
            known = {str(value).casefold() for value in setup.get(
                "distinct_ticket_namespaces", []
            )}
            if (x.get("left") not in known or x.get("right") not in known
                    or x["left"] == x["right"]
                    or row["status"] != "not_same_case_reported"):
                raise ValueError("Namespace distinction is not in trusted setup")
    usage = observed.get("setup_usage")
    if (not isinstance(usage, dict)
            or set(usage) != {"read_keys", "unhandled_keys"}
            or set(usage["read_keys"]) | set(usage["unhandled_keys"]) != set(setup)
            or set(usage["read_keys"]) & set(usage["unhandled_keys"])):
        raise ValueError("L1.1 setup usage is not completely declared")
    return (events, view["effective_assignments"], pairs), proposals, diffs


def _score(gold, original, output, checked, entities, proposals, diffs):
    kind, expected = gold["kind"], gold["expected"]
    if kind == "episode_pair":
        # Preserve old result semantics where no derived event changed.
        result = prior._score(gold, original, output, checked, entities)
        if (result["status"] in ("PASS", "FAIL")
                and "a" in gold and "b" in gold):
            a = checked[0][gold["a"]]["id"]
            b = checked[0][gold["b"]]["id"]
            if {a, b} & diffs:
                result["evidence_level"] = "L1_1_IN_MEMORY_REVISED_EPISODE_PROXY"
                result["reason"] = "Derived lab-only resegmentation, not durable Memory revision"
        return result
    if kind == "revision" and expected in (
        "resegment_without_raw_change", "versioned_resegmentation"
    ):
        if not proposals:
            return prior._grade("FAIL", "Expected a revision but derived view stayed unchanged",
                                actual="no_revision", level="L1_1_LAB_PROJECTION")
        proposal = proposals[0]
        matched = (expected == "resegment_without_raw_change"
                   and proposal["raw_events_modified"] is False) or (
                       expected == "versioned_resegmentation"
                       and proposal["source_projection_id"] == gold.get("source_projection_id")
                       and proposal["old_revision"] == gold.get("old_revision")
                       and proposal["new_revision"] > proposal["old_revision"])
        return prior._grade(
            "PASS" if matched else "FAIL",
            "Versioned ephemeral derived view only; no durable E4 revision verified",
            actual={"revision_count": len(proposals), "new_revision": proposal["new_revision"]},
            level="L1_1_LAB_PROJECTION",
        )
    if kind == "alias" and expected in ("confirmed_in_scope", "known_reuse"):
        expected_key = gold.get("from") or gold.get("surface")
        target = entities.get(gold.get("to"))
        if not expected_key or target is None:
            return prior._grade("NOT_SUPPORTED", "No scoped Entity target/surface")
        wanted = _canonical(expected_key)
        rows = (output["alias_records"] if expected == "confirmed_in_scope"
                else output["alias_mentions"])
        matched = any(
            row.get("surface_canonical") == wanted
            and row.get("target_entity_id") == target
            and (expected == "confirmed_in_scope"
                 or (row.get("status") == "scoped_alias_reuse"
                     and row.get("expensive_method_calls") == 0))
            for row in rows
        )
        return prior._grade(
            "PASS" if matched else "FAIL",
            "Source-backed bounded inflection, not synonym or physical identity",
            actual="canonical_source_match" if matched else "not_emitted",
            level="L1_1_CONTEXTUAL_ALIAS",
        )
    return prior._score(gold, original, output, checked, entities)


def evaluate_trace(trace_path, suite=None):
    path = Path(trace_path)
    if not path.is_file():
        raise ValueError("Completed L1.1 raw trace file required")
    raw = path.read_bytes()
    if len(raw) > 15_000_000:
        raise ValueError("Trace exceeds bound")
    data = json.loads(raw)
    if (data.get("schema") != TRACE_SCHEMA or data.get("status") !=
            "L1_1_PARTIAL_LAB_NOT_E4_CONFORMANCE" or data.get("gold_visible") is not False):
        raise ValueError("Invalid L1.1 raw trace or gold leakage")
    current_suite = suite or data.get("suite")
    if current_suite not in prior.FILES or current_suite != data.get("suite"):
        raise ValueError("Trace suite mismatch")
    original, gold = prior._fixtures(current_suite)
    inputs = {x["id"]: x for x in original["cases"]}
    oracles = {x["id"]: x for x in gold["cases"]}
    seen = data.get("cases")
    if not isinstance(seen, list) or not seen:
        raise ValueError("Empty L1.1 trace")
    ids = [x.get("case_id") for x in seen]
    if (len(ids) != len(set(ids)) or not set(ids) <= set(inputs)
            or ids != [x["id"] for x in original["cases"] if x["id"] in set(ids)]):
        raise ValueError("Invalid L1.1 case list or order")
    all_checks, forbiddens, by_track, cases = [], [], defaultdict(list), []
    for observed in seen:
        source = inputs[observed["case_id"]]
        oracle = oracles[observed["case_id"]]
        checked, proposals, diffs = _validate_extensions(observed, source)
        checks = []
        for index, check in enumerate(oracle["checks"], 1):
            result = {
                "id": f"{source['id']}:check:{index}", "kind": check["kind"],
                "expected": check["expected"],
                "acceptable": check.get("acceptable", [check["expected"]]),
                **_score(check, source, observed, checked,
                         original["entities"], proposals, diffs),
            }
            checks.append(result)
            all_checks.append(result)
            by_track[source["track"]].append(result)
        denied = []
        for index, forbidden in enumerate(oracle["forbidden"], 1):
            result = {
                "id": f"{source['id']}:forbidden:{index}",
                "forbidden": forbidden,
                **prior._grade("NOT_SUPPORTED", "No independent L2/L3 effect or authority ledger"),
            }
            forbiddens.append(result)
            denied.append(result)
        cases.append({
            "case_id": source["id"], "track": source["track"],
            "checks": checks, "forbidden": denied,
            "check_metrics": prior._metrics(checks),
        })
    return {
        "schema": RESULT_SCHEMA,
        "status": "L1_1_LIMITED_DIAGNOSTIC_NOT_E4_CONFORMANCE",
        "suite": current_suite,
        "trace_sha256": hashlib.sha256(raw).hexdigest(),
        "trace_bytes": len(raw),
        "scope": {
            "cases": len(seen), "available_cases": len(original["cases"]),
            "complete_suite": len(seen) == len(original["cases"]),
            "level": "L0_SHADOW_PLUS_L1_1_TEMPORARY_DERIVED_VIEW",
        },
        "checks": prior._metrics(all_checks),
        "forbidden": prior._metrics(forbiddens),
        "by_track": {x: prior._metrics(v) for x, v in sorted(by_track.items())},
        "cases": cases,
        "limitations": [
            "L1.1 revisions are temporary lab projections, NOT durable Memory recovery",
            "Bounded grammatical normalization is not general Entity Resolution",
            "99 prohibitions remain uninstrumented, no full E4 conformance",
            "Gold provisional; visible suite only, no blind holdout",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace", type=Path, required=True)
    p.add_argument("--suite", choices=tuple(prior.FILES))
    p.add_argument("--output", type=Path)
    p.add_argument("--print-summary", action="store_true")
    options = p.parse_args(argv)
    result = evaluate_trace(options.trace, suite=options.suite)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if options.output:
        if options.output.resolve() == options.trace.resolve():
            raise ValueError("Cannot replace raw trace with evaluation")
        options.output.parent.mkdir(parents=True, exist_ok=True)
        with options.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    elif not options.print_summary:
        print(text, end="")
    if options.print_summary:
        print(json.dumps({
            "suite": result["suite"], "status": result["status"],
            "checks": result["checks"], "forbidden": result["forbidden"],
            "trace_sha256": result["trace_sha256"],
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
