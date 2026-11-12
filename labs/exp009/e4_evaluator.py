"""Independent E4-L1 post-hoc evaluator; never imports or runs the adapter.

PASS is a narrow Shadow/L1 diagnostic, never full E4 conformance.
Uninstrumented prohibitions remain NOT_SUPPORTED, not silent PASS.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "docs" / "TESTING" / "Fixtures"
FILES = {
    "positive": ("memory_e4_inputs_v0.json", "memory_e4_gold_v0.json"),
    "negative": ("memory_e4_negative_inputs_v0.json", "memory_e4_negative_gold_v0.json"),
}
TRACE_SCHEMA = "anima.e4.association_observation_l1/0.1"
RESULT_SCHEMA = "anima.e4.independent_evaluation/0.1"
STATUSES = ("PASS", "FAIL", "NOT_SUPPORTED", "NOT_OBSERVED")
STORY_STATUS = {"same_case_reported", "not_same_case_reported", "candidate_only", "insufficient"}


def _blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _read_frozen(name, manifest):
    raw = (FIX / name).read_bytes()
    pin = manifest["pinned_files"]["docs/TESTING/Fixtures/" + name]
    if len(raw) != pin["bytes"] or _blob_sha(raw) != pin["git_blob_sha1"]:
        raise ValueError("Frozen fixture mismatch: " + name)
    return json.loads(raw)


def _fixtures(suite):
    if suite not in FILES:
        raise ValueError("Unknown E4 suite")
    manifest = json.loads((FIX / "memory_e4_frozen_manifest_v0.json").read_text())
    if manifest["status"] != "FROZEN_DESIGN_BASELINE_V0":
        raise ValueError("Manifest is not a frozen design baseline")
    inputs, gold = (_read_frozen(x, manifest) for x in FILES[suite])
    if (inputs["status"] != (
        "FROZEN_DESIGN_INPUTS_V0" if suite == "positive"
        else "FROZEN_DEV_NEGATIVES_NOT_HOLDOUT"
    ) or gold["status"] != (
        "FROZEN_PROVISIONAL_GOLD_V0" if suite == "positive"
        else "FROZEN_PROVISIONAL_DEV_GOLD_V0"
    )):
        raise ValueError("Frozen fixture status mismatch")
    return inputs, gold


def _check_trace(observed, source):
    """Validate identities and sources independently of the adapter."""
    if observed.get("case_id") != source["id"] or observed.get("track") != source["track"]:
        raise ValueError("Wrong case/track")
    if observed.get("level") != "L1_CONSERVATIVE_ASSOCIATION_LAB":
        raise ValueError("Wrong adapter level")
    if (observed.get("semantic_conformance") != "NOT_ASSESSED"
            or observed.get("memory_store_unchanged") is not True):
        raise ValueError("Adapter claimed an unverified conformance/write state")
    required = ("episode_baseline", "story_pair_assessments", "alias_records",
                "alias_mentions", "source_origin_links", "unsupported_controls",
                "unsupported_capabilities")
    if any(k not in observed for k in required):
        raise ValueError("Incomplete L1 trace")
    events = {e["key"]: e["raw"] for e in source["events"]}
    by_id = {r["id"]: r for r in events.values()}
    baseline = observed["episode_baseline"]
    emitted = [(x["event_key"], x["event_id"]) for x in baseline["decisions"]]
    if emitted != [(k, r["id"]) for k, r in events.items()]:
        raise ValueError("Trace event sequence/identity mismatch")
    if any(x["decision"]["event_id"] != x["event_id"] for x in baseline["decisions"]):
        raise ValueError("Shadow decision event mismatch")
    assignments = baseline["event_assignments"]
    if not set(assignments) <= set(by_id):
        raise ValueError("Unknown Event in episode assignments")
    from_episodes = {}
    for episode in baseline["episodes"]:
        for eid in episode["source_event_ids"]:
            if eid not in by_id or eid in from_episodes:
                raise ValueError("Invalid or duplicate Episode source")
            from_episodes[eid] = episode["episode_id"]
    if from_episodes != assignments:
        raise ValueError("Episode grouping differs from assignments")
    pair_rows = {}
    for row in observed["story_pair_assessments"]:
        a, b = row["left_event_key"], row["right_event_key"]
        if (a not in events or b not in events or a == b or (a, b) in pair_rows
                or row["left_event_id"] != events[a]["id"]
                or row["right_event_id"] != events[b]["id"]):
            raise ValueError("Foreign or duplicate Story pair")
        status = row["status"]
        if (status not in STORY_STATUS or row.get("authority") != "source_report_not_world_fact"
                or not row.get("reason_codes")
                or not set(row.get("source_event_ids", [])) <= set(by_id)):
            raise ValueError("Story source/authority not traceable")
        if status in ("same_case_reported", "not_same_case_reported") and not row["source_event_ids"]:
            raise ValueError("Positive Story without source")
        if status == "insufficient" and row["source_event_ids"]:
            raise ValueError("Insufficient Story cannot claim affirmative source")
        pair_rows[(a, b)] = row
    for row in observed["alias_records"]:
        event = by_id.get(row.get("source_event_id"))
        if (event is None or event["type"] != "conversation.user"
                or event["source"] != "user" or row.get("speaker") != "user"
                or event["session_id"] != row.get("session_id")
                or row.get("target_entity_id") not in {
                    x["id"] for x in event["references"] if x["kind"] == "entity"
                } or row.get("authority") != "speaker_intent_only_not_physical_truth"
                or row.get("status") != "speaker_intent_confirmed_in_scope"):
            raise ValueError("Alias source/authority mismatch")
    for row in observed["alias_mentions"]:
        if row["event_key"] not in events:
            raise ValueError("Foreign alias mention")
        if row["status"] == "scoped_alias_reuse" and not any(
            x["source_event_id"] == row.get("source_event_id")
            and x["surface"] == row.get("surface")
            and x["target_entity_id"] == row.get("target_entity_id")
            for x in observed["alias_records"]
        ):
            raise ValueError("Alias cache reuse without a source definition")
    actual_origins = set()
    legal_origins = {
        (r["id"], link["id"])
        for r in events.values() for link in r["references"] if link["kind"] == "event"
    }
    for link in observed["source_origin_links"]:
        pair = (link["child_event_id"], link["parent_event_id"])
        if (pair in actual_origins or pair not in legal_origins
                or link["status"] != "source_pointer_not_independent_evidence"
                or link["authority"] != "pointer_only_not_world_truth"):
            raise ValueError("Forged or duplicate provenance pointer")
        actual_origins.add(pair)
    control_pairs = [(x["at"], x["kind"]) for x in source["controls"]]
    if control_pairs != [(x["at"], x["kind"]) for x in observed["unsupported_controls"]]:
        raise ValueError("Hidden or modified unsupported controls")
    if not {
        "GoalTask_research", "PeriodicScheduler", "CrashRecovery",
        "Knowledge_confirmation", "Episode_resegmentation",
    } <= set(observed["unsupported_capabilities"]):
        raise ValueError("L1 falsely claims unsupported functionality")
    return events, assignments, pair_rows


def _grade(status, reason, *, actual=None, level=None):
    item = {"status": status, "reason": reason}
    if actual is not None:
        item["actual"] = actual
    if level is not None:
        item["evidence_level"] = level
    return item


def _score(gold, source, output, checked, entities):
    kind, expected = gold["kind"], gold["expected"]
    events, assignments, pairs = checked
    if kind == "episode_pair":
        if expected not in ("same", "distinct"):
            return _grade("NOT_SUPPORTED", "Shadow cannot express episode uncertainty")
        if "a" not in gold or "b" not in gold:
            return _grade("NOT_OBSERVED", "Missing pair locators")
        a, b = (assignments.get(events[gold[key]]["id"]) for key in ("a", "b"))
        if a is None or b is None:
            return _grade("NOT_SUPPORTED", "Shadow skipped a non-selected Event")
        actual = "same" if a == b else "distinct"
        return _grade("PASS" if actual == expected else "FAIL",
                      "L0 Shadow association proxy, not E4 Episode segmentation",
                      actual=actual, level="L0_SHADOW_PROXY")
    if kind == "story_pair":
        if "a" not in gold or "b" not in gold:
            return _grade("NOT_OBSERVED", "Missing Story pair locators")
        row = pairs.get((gold["a"], gold["b"]))
        if row is None:
            return _grade("NOT_OBSERVED", "Story assessment missing from trace")
        actual = row["status"]
        accepted = gold.get("acceptable", [expected])
        match = actual in accepted or (
            expected == "not_same_case" and actual == "not_same_case_reported"
        )
        return _grade("PASS" if match else "FAIL",
                      "Reported Story relation, not verified external truth",
                      actual=actual, level="L1_REPORTED_RELATION")
    if kind == "alias":
        surface = gold.get("from", gold.get("surface"))
        if not surface:
            return _grade("NOT_SUPPORTED", "No scoped alias surface")
        records = [x for x in output["alias_records"]
                   if x["surface"].casefold() == surface.casefold()]
        mentions = [x for x in output["alias_mentions"]
                    if x["surface"].casefold() == surface.casefold()]
        if expected in ("confirmed_in_scope", "known_reuse"):
            target = entities.get(gold.get("to"))
            if target is None:
                return _grade("NOT_SUPPORTED", "Target Entity not in registry")
            if expected == "confirmed_in_scope":
                match = any(x["target_entity_id"] == target for x in records)
            else:
                match = any(x["status"] == "scoped_alias_reuse"
                            and x["target_entity_id"] == target
                            and x.get("expensive_method_calls") == 0 for x in mentions)
            return _grade("PASS" if match else "FAIL",
                          "Source-backed contextual alias only",
                          actual="observed" if match else "missing",
                          level="L1_EXPLICIT_ALIAS")
        if expected == "unresolved":
            if not records and not mentions:
                return _grade("NOT_OBSERVED", "No lexical abstention recorded")
            correct = not records and any(x["status"] == "insufficient" for x in mentions)
            return _grade("PASS" if correct else "FAIL",
                          "Literal abstention is not UncertaintyRegistry",
                          actual="insufficient" if correct else "other",
                          level="L1_LEXICAL_ABSTENTION")
        return _grade("NOT_SUPPORTED", "No L1 negative/general Entity Resolution")
    if kind == "evidence" and expected in (
        "same_origin_not_independent", "no_duplicate_evidence"
    ):
        available = {(r["id"], link["id"])
                     for r in events.values() for link in r["references"]
                     if link["kind"] == "event"}
        if "a" in gold and "b" in gold:
            ids = {events[gold["a"]]["id"], events[gold["b"]]["id"]}
            available = {pair for pair in available if set(pair) == ids}
        if not available:
            return _grade("NOT_SUPPORTED", "No typed source pointer supplied")
        present = {(x["child_event_id"], x["parent_event_id"])
                   for x in output["source_origin_links"]}
        correct = available <= present
        return _grade("PASS" if correct else "FAIL",
                      "Typed Event pointer only; authenticity not verified",
                      actual={"present": len(available & present), "expected": len(available)},
                      level="L1_SOURCE_POINTER")
    if kind == "budget" and expected == "no_expensive_method":
        used = [m for m in output["alias_mentions"]
                if m["status"] == "scoped_alias_reuse"]
        if used:
            correct = all(m.get("expensive_method_calls") == 0 for m in used)
            return _grade("PASS" if correct else "FAIL",
                          "Alias reuse counter only; not a Core compute budget",
                          level="L1_ALIAS_REUSE_PROXY")
    return _grade("NOT_SUPPORTED", "No instrumented L1 contract for " + kind)


def _metrics(rows):
    statuses = Counter(x["status"] for x in rows)
    observed = statuses["PASS"] + statuses["FAIL"]
    total = len(rows)
    return {
        "total": total,
        "by_status": {name: statuses[name] for name in STATUSES},
        "observed": observed,
        "coverage": observed / total if total else None,
        "observed_pass_rate": statuses["PASS"] / observed if observed else None,
        "full_e4_conformance": False,
    }


def evaluate_trace(trace_path, suite=None):
    """Read a completed trace, verify it, then open frozen gold for scoring."""
    trace_path = Path(trace_path)
    if not trace_path.is_file():
        raise ValueError("Completed raw JSON trace required")
    raw = trace_path.read_bytes()
    if len(raw) > 15_000_000:
        raise ValueError("Raw trace over size limit")
    trace = json.loads(raw)
    if (trace.get("schema") != TRACE_SCHEMA
            or trace.get("status") != "L1_PARTIAL_OBSERVATION_NOT_E4_CONFORMANCE"
            or trace.get("gold_visible") is not False):
        raise ValueError("Wrong trace schema or gold leakage")
    chosen_suite = suite or trace.get("suite")
    if chosen_suite not in FILES or trace.get("suite") != chosen_suite:
        raise ValueError("Suite mismatch")
    inputs, gold = _fixtures(chosen_suite)
    originals = {x["id"]: x for x in inputs["cases"]}
    oracles = {x["id"]: x for x in gold["cases"]}
    records = trace.get("cases")
    if not isinstance(records, list) or not records:
        raise ValueError("No trace cases")
    ids = [x.get("case_id") for x in records]
    if len(ids) != len(set(ids)) or not set(ids) <= set(originals):
        raise ValueError("Unknown or duplicated case")
    expected_order = [x["id"] for x in inputs["cases"] if x["id"] in set(ids)]
    if ids != expected_order:
        raise ValueError("Trace case ordering mismatch")
    results, forbidden_all, by_track, all_checks = [], [], defaultdict(list), []
    for record in records:
        original = originals[record["case_id"]]
        oracle = oracles[record["case_id"]]
        checked = _check_trace(record, original)
        graded = []
        for index, target in enumerate(oracle["checks"], start=1):
            item = {
                "id": f"{record['case_id']}:check:{index}",
                "kind": target["kind"], "expected": target["expected"],
                "acceptable": target.get("acceptable", [target["expected"]]),
                **_score(target, original, record, checked, inputs["entities"]),
            }
            graded.append(item)
            all_checks.append(item)
            by_track[original["track"]].append(item)
        forbidden = []
        for index, name in enumerate(oracle["forbidden"], start=1):
            item = {
                "id": f"{record['case_id']}:forbidden:{index}",
                "forbidden": name,
                **_grade("NOT_SUPPORTED",
                         "No independent L1 authority/Knowledge/effect ledger"),
            }
            forbidden.append(item)
            forbidden_all.append(item)
        results.append({
            "case_id": record["case_id"], "track": record["track"],
            "checks": graded, "forbidden": forbidden,
            "check_metrics": _metrics(graded),
        })
    return {
        "schema": RESULT_SCHEMA,
        "status": "L1_LIMITED_DIAGNOSTIC_NOT_E4_CONFORMANCE",
        "suite": chosen_suite, "trace_sha256": hashlib.sha256(raw).hexdigest(),
        "trace_bytes": len(raw),
        "scope": {
            "cases": len(ids), "available_cases": len(inputs["cases"]),
            "complete_suite": len(ids) == len(inputs["cases"]),
            "level": "L0_SHADOW_PROXY_AND_PARTIAL_L1",
        },
        "checks": _metrics(all_checks),
        "forbidden": _metrics(forbidden_all),
        "by_track": {key: _metrics(rows) for key, rows in sorted(by_track.items())},
        "cases": results,
        "limitations": [
            "Gold is frozen but provisional, no independent full oracle adjudication",
            "No blinded holdout; visible development suite only",
            "Missing capabilities and prohibited-action evidence never count as PASS",
            "Observed L0/L1 PASS does not imply full E4 conformance",
            "Trace SHA-256 is a content fingerprint, not an attestation",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--suite", choices=tuple(FILES))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate_trace(args.trace, suite=args.suite)
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        if args.output.resolve() == args.trace.resolve():
            raise ValueError("Evaluator may not overwrite its raw trace")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    elif not args.print_summary:
        print(payload, end="")
    if args.print_summary:
        print(json.dumps({
            "status": result["status"], "suite": result["suite"],
            "cases": result["scope"]["cases"], "checks": result["checks"],
            "forbidden": result["forbidden"],
            "trace_sha256": result["trace_sha256"],
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
