"""Post-hoc E4-L1.1 challenge scorer. Does not import adapter or runner.

The openly predeclared challenge oracle is not a blinded holdout.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from labs.exp009 import e4_l11_evaluator as previous
from labs.exp009 import e4_evaluator as basic

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "docs" / "TESTING" / "Fixtures"
MANIFEST = "memory_e4_l11_challenge_manifest_v0.json"
INPUT = "memory_e4_l11_challenge_inputs_v0.json"
GOLD = "memory_e4_l11_challenge_gold_v0.json"
TRACE_SCHEMA = "anima.e4.l11_challenge_raw/0.1"
RESULT_SCHEMA = "anima.e4.l11_challenge_evaluation/0.1"


def _blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _read_pinned(filename, manifest):
    raw = (FIX / filename).read_bytes()
    pin = manifest["pinned_files"]["docs/TESTING/Fixtures/" + filename]
    if len(raw) != pin["bytes"] or _blob_sha(raw) != pin["git_blob_sha1"]:
        raise ValueError("Pinned challenge fixture checksum mismatch")
    return json.loads(raw), pin


def _judge(check, observed, source):
    kind, expected = check["kind"], check["expected"]
    pairs = {(x["left_event_key"], x["right_event_key"]): x
             for x in observed["story_pair_assessments"]}
    by_key = {e["key"]: e["raw"] for e in source["events"]}
    if kind == "story_pair":
        row = pairs.get((check["a"], check["b"]))
        if row is None:
            return basic._grade("NOT_OBSERVED", "No pair in trace")
        actual = row["status"]
    elif kind == "revision_count":
        actual = len(observed["episode_view"]["revision_proposals"])
    elif kind == "episode_pair":
        e1 = by_key[check["a"]]["id"]
        e2 = by_key[check["b"]]["id"]
        assigned = observed["episode_view"]["effective_assignments"]
        if e1 not in assigned or e2 not in assigned:
            return basic._grade("NOT_SUPPORTED", "Shadow skipped one source Event")
        actual = "same" if assigned[e1] == assigned[e2] else "distinct"
    elif kind == "alias_mention":
        rows = [x for x in observed["alias_mentions"]
                if x.get("event_key") == check["event"]
                and x.get("surface") == check["surface"]]
        if not rows:
            return basic._grade("NOT_OBSERVED", "No matching alias mention in raw trace")
        actual = rows[-1]["status"]
        if check.get("target") and actual == expected:
            key = check["target"]
            # When status matches but target does not, count as a real FAIL.
            registry_id = source["_challenge_entity_registry"].get(key)
            if rows[-1].get("target_entity_id") != registry_id:
                actual = actual + ":wrong_target"
    elif kind == "alias_records_count":
        actual = len(observed["alias_records"])
    elif kind == "alias_canonical":
        records = [x for x in observed["alias_records"]
                   if x.get("source_event_id") == by_key[check["event"]]["id"]
                   and x.get("target_entity_id") ==
                   source["_challenge_entity_registry"].get(check["target"])]
        if not records:
            return basic._grade("NOT_OBSERVED", "No source-backed alias record")
        actual = records[-1]["surface_canonical"]
    else:
        return basic._grade("NOT_SUPPORTED", "Challenge check unsupported: " + kind)
    return basic._grade(
        "PASS" if actual == expected else "FAIL",
        "Predeclared development challenge: narrow trace requirement",
        actual=actual,
        level="OPEN_DEV_CHALLENGE_NOT_E4_CONFORMANCE",
    )


def evaluate(trace_path):
    path = Path(trace_path)
    if not path.is_file():
        raise ValueError("Closed raw challenge trace required")
    raw = path.read_bytes()
    if len(raw) > 15_000_000:
        raise ValueError("Challenge trace exceeds bound")
    trace = json.loads(raw)
    if (trace.get("schema") != TRACE_SCHEMA
            or trace.get("status") != "VISIBLE_DEVELOPMENT_RAW_NOT_CONFORMANCE"
            or trace.get("gold_visible") is not False):
        raise ValueError("Wrong challenge trace envelope")
    manifest = json.loads((FIX / MANIFEST).read_text(encoding="utf-8"))
    if manifest["status"] != "PREDECLARED_VISIBLE_DEVELOPMENT_NOT_HOLDOUT":
        raise ValueError("Challenge baseline is not predeclared")
    inputs, pinned = _read_pinned(INPUT, manifest)
    if trace.get("challenge_input_blob_sha1") != pinned["git_blob_sha1"]:
        raise ValueError("Raw trace references a different input")
    cases = trace.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("No observed challenge cases")
    input_by_id = {x["id"]: x for x in inputs["cases"]}
    ids = [x.get("case_id") for x in cases]
    expected = [c["id"] for c in inputs["cases"] if c["id"] in set(ids)]
    if ids != expected or len(ids) != len(set(ids)):
        raise ValueError("Challenge trace order or case ID mismatch")
    for observed in cases:
        source = input_by_id[observed["case_id"]]
        previous._validate_extensions(observed, dict(source, track=source["topic"]))

    # Only AFTER an already persisted trace has passed source/provenance
    # validation do we open the independently stored proposed gold.
    gold, _ = _read_pinned(GOLD, manifest)
    targets = {x["id"]: x for x in gold["cases"]}
    all_rows, per_topic, rows = [], defaultdict(list), []
    for observed in cases:
        source = input_by_id[observed["case_id"]]
        # Private object passed only within the evaluator; never to adapter.
        source = dict(source, _challenge_entity_registry=inputs["entities"])
        evaluated = []
        for number, check in enumerate(targets[source["id"]]["checks"], 1):
            outcome = {
                "id": f"{source['id']}:check:{number}",
                "kind": check["kind"], "expected": check["expected"],
                **_judge(check, observed, source),
            }
            evaluated.append(outcome)
            all_rows.append(outcome)
            per_topic[source["topic"]].append(outcome)
        rows.append({
            "case_id": source["id"], "topic": source["topic"],
            "checks": evaluated,
        })
    return {
        "schema": RESULT_SCHEMA,
        "status": "OPEN_VISIBLE_CHALLENGE_NOT_BLIND_OR_E4_CONFORMANCE",
        "trace_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": {"cases": len(ids), "available_cases": len(inputs["cases"]),
                  "complete_suite": len(ids) == len(inputs["cases"])},
        "checks": basic._metrics(all_rows),
        "by_topic": {name: basic._metrics(out)
                     for name, out in sorted(per_topic.items())},
        "cases": rows,
        "limitations": [
            "Same development team authored model and challenge oracle",
            "Visible cases and gold cannot establish blinded generalization",
            "No production Memory/Goal/Task/effect verification",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace", type=Path, required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--print-summary", action="store_true")
    args = p.parse_args(argv)
    report = evaluate(args.trace)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        if args.output.resolve() == args.trace.resolve():
            raise ValueError("Cannot overwrite raw trace")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as target:
            target.write(payload)
    elif not args.print_summary:
        print(payload, end="")
    if args.print_summary:
        print(json.dumps({"checks": report["checks"],
                          "cases": report["scope"]["cases"]},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
