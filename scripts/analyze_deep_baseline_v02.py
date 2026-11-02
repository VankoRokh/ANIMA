#!/usr/bin/env python3
"""Analyze dual-axis DEEP baseline v0.2 evidence without rerunning models."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


def _short(text, limit=120):
    if not isinstance(text, str):
        return "—"
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def analyze_arm(arm):
    cases = list(arm.get("cases", ()))
    relation_confusion = Counter()
    resolution_confusion = Counter()
    category = defaultdict(lambda: {"relation": 0, "resolution": 0, "pair": 0, "total": 0})
    for row in cases:
        expected_relation = row.get("expected_relation")
        parsed_relation = row.get("parsed_relation") or "—"
        expected_resolution = row.get("expected_resolution")
        parsed_resolution = row.get("parsed_resolution") or "—"
        relation_confusion[(expected_relation, parsed_relation)] += 1
        resolution_confusion[(expected_resolution, parsed_resolution)] += 1
        bucket = category[row.get("category") or "unknown"]
        bucket["total"] += 1
        bucket["relation"] += int(bool(row.get("relation_correct")))
        bucket["resolution"] += int(bool(row.get("resolution_correct")))
        bucket["pair"] += int(bool(row.get("semantic_pair_correct")))
    return {
        "arm": arm.get("arm"),
        "summary": arm.get("summary", {}),
        "cases": cases,
        "relation_confusion": relation_confusion,
        "resolution_confusion": resolution_confusion,
        "category": dict(category),
    }


def analyze_report(report):
    arms = [analyze_arm(arm) for arm in report.get("arms", ())]
    if not arms:
        raise ValueError("evidence contains no benchmark arms")
    by_case = defaultdict(dict)
    for arm in arms:
        for row in arm["cases"]:
            by_case[row.get("case_id")][arm["arm"]] = row
    return {"arms": arms, "by_case": dict(by_case)}


def print_arm(arm):
    s = arm["summary"]
    total = s.get("total", 0)
    print(f"\n{arm['arm']}")
    print(
        f"relation {s.get('relation_passes', 0)}/{total}; "
        f"resolution {s.get('resolution_passes', 0)}/{total}; "
        f"pair {s.get('semantic_pair_passes', 0)}/{total}; "
        f"exact {s.get('exact_passes', 0)}/{total}"
    )
    print("\nRelation confusion")
    print("Expected | Parsed | Count")
    print("--- | --- | ---:")
    for (expected, parsed), count in sorted(arm["relation_confusion"].items()):
        print(f"{expected} | {parsed} | {count}")
    print("\nResolution confusion")
    print("Expected | Parsed | Count")
    print("--- | --- | ---:")
    for (expected, parsed), count in sorted(arm["resolution_confusion"].items()):
        print(f"{expected} | {parsed} | {count}")
    print("\nCategory accuracy")
    print("Category | Relation | Resolution | Pair")
    print("--- | ---: | ---: | ---:")
    for name, values in sorted(arm["category"].items()):
        total = values["total"]
        print(
            f"{name} | {values['relation']}/{total} | "
            f"{values['resolution']}/{total} | {values['pair']}/{total}"
        )


def print_disagreements(analysis):
    if len(analysis["arms"]) < 2:
        return
    names = [arm["arm"] for arm in analysis["arms"]]
    print("\nCross-arm disagreements")
    print("Case | Expected | " + " | ".join(names))
    print("--- | --- | " + " | ".join("---" for _ in names))
    for case_id in sorted(analysis["by_case"]):
        rows = analysis["by_case"][case_id]
        if not all(name in rows for name in names):
            continue
        parsed = [
            f"{rows[name].get('parsed_relation') or '—'}|{rows[name].get('parsed_resolution') or '—'}"
            for name in names
        ]
        if len(set(parsed)) == 1:
            continue
        first = rows[names[0]]
        expected = f"{first.get('expected_relation')}|{first.get('expected_resolution')}"
        print(f"{case_id} | {expected} | " + " | ".join(parsed))

    print("\nPair failures")
    print("Arm | Case | Expected | Parsed | Response")
    print("--- | --- | --- | --- | ---")
    for arm in analysis["arms"]:
        for row in arm["cases"]:
            if row.get("semantic_pair_correct"):
                continue
            expected = f"{row.get('expected_relation')}|{row.get('expected_resolution')}"
            parsed = f"{row.get('parsed_relation') or '—'}|{row.get('parsed_resolution') or '—'}"
            print(
                f"{arm['arm']} | {row.get('case_id')} | {expected} | {parsed} | "
                f"{_short(row.get('response'))}"
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args(argv)
    report = json.loads(args.evidence.read_text(encoding="utf-8"))
    analysis = analyze_report(report)
    print("DEEP Baseline v0.2 evidence analysis")
    for arm in analysis["arms"]:
        print_arm(arm)
    print_disagreements(analysis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
