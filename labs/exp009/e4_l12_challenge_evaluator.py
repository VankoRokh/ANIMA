"""Independent L1.2 challenge scorer: closed raw trace + pinned open gold.

Does not import or execute L1.2 adapter. These developer-authored cases are
NOT a blinded independent holdout or production-memory acceptance.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from labs.exp009 import e4_evaluator as basic
from labs.exp009 import e4_l11_challenge_evaluator as old
from labs.exp009 import e4_l12_evaluator as independent

SCHEMA = "anima.e4.l12_challenge_raw/0.1"
RESULT = "anima.e4.l12_challenge_evaluation/0.1"


def _judge(item, trace, source, registry):
    if item["kind"] == "alias_canonical":
        event_id = next(
            x["raw"]["id"] for x in source["events"] if x["key"] == item["event"]
        )
        records = [
            x for x in trace["alias_records"]
            if (x["source_event_id"] == event_id and
                x["target_entity_id"] == registry[item["target"]])
        ]
        if not records:
            return basic._grade("NOT_OBSERVED", "No source-backed alias record")
        actual = records[-1]["canonical_l12"]
        return basic._grade(
            "PASS" if actual == item["expected"] else "FAIL",
            "Bounded grammatical source normalization",
            actual=actual, level="OPEN_VISIBLE_L12_DEVELOPMENT_CHECK",
        )
    # Other challenge check formats are stable and inspect only the raw
    # dispositions, not any adapter implementation or scorer feedback.
    with_registry = dict(source, _challenge_entity_registry=registry)
    return old._judge(item, trace, with_registry)


def evaluate_trace(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Completed L1.2 raw challenge trace required")
    raw = path.read_bytes()
    if len(raw) > 15_000_000:
        raise ValueError("L1.2 challenge trace too large")
    result = json.loads(raw)
    if (result.get("schema") != SCHEMA
            or result.get("gold_visible") is not False
            or result.get("status") !=
            "VISIBLE_L12_DEVELOPMENT_RAW_NOT_CONFORMANCE"):
        raise ValueError("Invalid L1.2 challenge raw envelope")
    manifest = json.loads((old.FIX / old.MANIFEST).read_text(encoding="utf-8"))
    if manifest["status"] != "PREDECLARED_VISIBLE_DEVELOPMENT_NOT_HOLDOUT":
        raise ValueError("Challenge manifest has been replaced")
    inputs, pin = old._read_pinned(old.INPUT, manifest)
    if result.get("challenge_input_blob_sha1") != pin["git_blob_sha1"]:
        raise ValueError("Raw trace did not use original pinned input")
    source_by_id = {c["id"]: c for c in inputs["cases"]}
    observed = result.get("cases")
    if not isinstance(observed, list) or not observed:
        raise ValueError("Empty L1.2 challenge")
    ids = [x.get("case_id") for x in observed]
    if (len(ids) != len(set(ids)) or not set(ids) <= set(source_by_id)
            or ids != [c["id"] for c in inputs["cases"] if c["id"] in set(ids)]):
        raise ValueError("Challenge IDs/order do not match pinned fixture")
    for item in observed:
        case = source_by_id[item["case_id"]]
        independent._validate(item, dict(case, track=case["topic"]))
    # Gold opened AFTER the entire source/provenance validation.
    gold, _ = old._read_pinned(old.GOLD, manifest)
    targets = {c["id"]: c for c in gold["cases"]}
    all_outcomes, topics, per_case = [], defaultdict(list), []
    for item in observed:
        src = source_by_id[item["case_id"]]
        checks = []
        for number, check in enumerate(targets[src["id"]]["checks"], 1):
            row = {
                "id": f"{src['id']}:check:{number}",
                "kind": check["kind"],
                "expected": check["expected"],
                **_judge(check, item, src, inputs["entities"]),
            }
            checks.append(row)
            all_outcomes.append(row)
            topics[src["topic"]].append(row)
        per_case.append({"case_id":src["id"],"topic":src["topic"],"checks":checks})
    return {
        "schema": RESULT,
        "status": "OPEN_L12_CHALLENGE_NOT_BLIND_OR_E4_CONFORMANCE",
        "trace_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": {"cases":len(observed), "available_cases":len(inputs["cases"]),
                  "complete_suite":len(observed)==len(inputs["cases"])},
        "checks": basic._metrics(all_outcomes),
        "by_topic": {kind:basic._metrics(rows)
                     for kind,rows in sorted(topics.items())},
        "cases": per_case,
        "limitations": [
            "Visible developer-authored challenge, not independent holdout",
            "No production Memory revision or Core action authority",
            "A bounded deictic CorrectionTarget is NOT verified source truth",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace", type=Path, required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--print-summary", action="store_true")
    args = p.parse_args(argv)
    result = evaluate_trace(args.trace)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        if not args.print_summary:
            print(payload, end="")
    else:
        if args.trace.resolve() == args.output.resolve():
            raise ValueError("Cannot overwrite challenge raw trace")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    if args.print_summary:
        print(json.dumps(
            {"cases":result["scope"]["cases"],"checks":result["checks"]},
            ensure_ascii=False
        ))


if __name__ == "__main__":
    main()
