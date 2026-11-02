#!/usr/bin/env python3
"""Analyze an existing DEEP baseline evidence.json without rerunning models.

The benchmark's strict PASS requires an exact allowed label. This analyzer adds a
second deterministic metric: semantic label correctness. If a response contains
exactly one allowed label token anywhere in the text, that label is counted as the
model's semantic classification even when surrounding explanation violates the
exact-output contract. Multiple different labels remain ambiguous and receive no
semantic credit.
"""

import argparse
import json
from pathlib import Path
import re


ALLOWED_LABELS = (
    "SUPPORT",
    "TEMPORAL_CHANGE",
    "CORRECTION",
    "CONTRADICTION",
    "UNRESOLVED",
)
_LABEL_RE = re.compile(
    r"(?<![A-Z0-9_])(" + "|".join(map(re.escape, ALLOWED_LABELS)) + r")(?![A-Z0-9_])",
    re.IGNORECASE,
)


def extract_semantic_label(response):
    """Return one unique allowed label mentioned in text, otherwise None."""
    if not isinstance(response, str) or not response.strip():
        return None
    labels = {match.upper() for match in _LABEL_RE.findall(response)}
    if len(labels) != 1:
        return None
    return next(iter(labels))


def analyze_case(case):
    expected = case.get("expected")
    response = case.get("response")
    label = extract_semantic_label(response)
    strict = bool(case.get("correct"))
    format_valid = bool(case.get("format_valid"))
    semantic_correct = label == expected
    return {
        "case_id": case.get("case_id"),
        "difficulty": case.get("difficulty"),
        "category": case.get("category"),
        "expected": expected,
        "semantic_label": label,
        "semantic_correct": semantic_correct,
        "strict_correct": strict,
        "format_valid": format_valid,
        "response": response,
    }


def analyze_arm(arm):
    cases = [analyze_case(item) for item in arm.get("cases", [])]
    abstention = [item for item in cases if item["expected"] == "UNRESOLVED"]
    return {
        "arm": arm.get("arm"),
        "model": arm.get("model"),
        "role": arm.get("role"),
        "total": len(cases),
        "strict_passes": sum(item["strict_correct"] for item in cases),
        "semantic_passes": sum(item["semantic_correct"] for item in cases),
        "format_valid": sum(item["format_valid"] for item in cases),
        "abstention_strict": sum(item["strict_correct"] for item in abstention),
        "abstention_semantic": sum(item["semantic_correct"] for item in abstention),
        "abstention_total": len(abstention),
        "cases": cases,
    }


def analyze_report(report):
    if not isinstance(report, dict):
        raise ValueError("evidence root must be a JSON object")
    arms = report.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ValueError("evidence must contain non-empty arms")
    return {
        "benchmark": report.get("benchmark"),
        "audit_version": report.get("audit_version"),
        "arms": [analyze_arm(arm) for arm in arms],
    }


def _short(text, limit=120):
    if not isinstance(text, str):
        return "—"
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def print_report(analysis):
    print("DEEP Baseline evidence analysis")
    print()
    print("Arm | Exact | Semantic | Format | Abstention exact | Abstention semantic")
    print("--- | ---: | ---: | ---: | ---: | ---:")
    for arm in analysis["arms"]:
        print(
            f"{arm['arm']} | "
            f"{arm['strict_passes']}/{arm['total']} | "
            f"{arm['semantic_passes']}/{arm['total']} | "
            f"{arm['format_valid']}/{arm['total']} | "
            f"{arm['abstention_strict']}/{arm['abstention_total']} | "
            f"{arm['abstention_semantic']}/{arm['abstention_total']}"
        )

    for arm in analysis["arms"]:
        failures = [
            item for item in arm["cases"]
            if not item["strict_correct"] or not item["semantic_correct"]
        ]
        if not failures:
            continue
        print()
        print(f"Failures / contract mismatches — {arm['arm']}")
        print("Case | Expected | Parsed | Exact | Format | Response")
        print("--- | --- | --- | --- | --- | ---")
        for item in failures:
            print(
                f"{item['case_id']} | {item['expected']} | "
                f"{item['semantic_label'] or '—'} | "
                f"{'PASS' if item['strict_correct'] else 'FAIL'} | "
                f"{'OK' if item['format_valid'] else 'BAD'} | "
                f"{_short(item['response'])}"
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="Path to benchmark evidence.json")
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path for machine-readable analysis JSON",
    )
    args = parser.parse_args(argv)

    report = json.loads(args.evidence.read_text(encoding="utf-8"))
    analysis = analyze_report(report)
    print_report(analysis)
    if args.json_out is not None:
        args.json_out.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
