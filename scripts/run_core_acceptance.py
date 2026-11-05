#!/usr/bin/env python3
"""Run the selected Core acceptance suite and emit human + machine reports.

Execution is synchronous; nothing runs in the background. Data stays in the
explicit report directory. JUnit XML is test-runner evidence, not Core trace.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
CORE_MODULES = (
    "tests/test_core_p4_acceptance.py",
    "tests/test_core_p3c_autonomy.py",
    "tests/test_core_p3c_demo.py",
    "tests/test_core_p3b_execution.py",
    "tests/test_core_p3a_goal_decision.py",
    "tests/test_core_p2c_runtime.py",
    "tests/test_core_p2b_belief.py",
    "tests/test_core_p2a_ingress.py",
    "tests/test_core_p1_bootstrap.py",
)


def summarize_junit(path):
    """Parser independent of pytest's terminal progress-bar format."""
    tree = ElementTree.parse(path)
    cases = []
    for case in tree.findall(".//testcase"):
        failures = list(case.findall("failure")) + list(case.findall("error"))
        skipped = case.find("skipped") is not None
        cases.append({
            "name": case.attrib.get("name", "unnamed"),
            "classname": case.attrib.get("classname", ""),
            "seconds": float(case.attrib.get("time", "0")),
            "status": "FAIL" if failures else ("SKIP" if skipped else "PASS"),
            "message": failures[0].attrib.get("message", "") if failures else "",
        })
    totals = {
        "passed": sum(x["status"] == "PASS" for x in cases),
        "failed": sum(x["status"] == "FAIL" for x in cases),
        "skipped": sum(x["status"] == "SKIP" for x in cases),
        "total": len(cases),
    }
    return totals, cases


def render_markdown(record):
    totals = record["totals"]
    verdict = record["result"]
    lines = [
        "# ANIMA Core v0.1 — Acceptance Run",
        "",
        f"**Result:** {verdict}  ",
        f"**Suite:** `{record['suite']}`  ",
        f"**Commit:** `{record['commit']}`  ",
        f"**Python:** `{record['python']}`  ",
        f"**UTC timestamp:** `{record['timestamp']}`  ",
        f"**Process exit code:** `{record['exit_code']}`",
        "",
        "## Test summary",
        "",
        f"- Passed: **{totals['passed']}**",
        f"- Failed: **{totals['failed']}**",
        f"- Skipped: **{totals['skipped']}**",
        f"- Total: **{totals['total']}**",
        "",
        "## Cases",
        "",
        "| Status | Test | Seconds |",
        "|---|---|---:|",
    ]
    for case in record["cases"]:
        label = (case["classname"] + "::" + case["name"]).replace("|", "\\|")
        lines.append(
            f"| {case['status']} | `{label}` | {case['seconds']:.3f} |"
        )
    failed = [x for x in record["cases"] if x["status"] == "FAIL"]
    if failed:
        lines.extend(["", "## Failures", ""])
        for case in failed:
            lines.append(f"- `{case['name']}`: {case['message'][:500]}")
    lines.extend([
        "",
        "## Evidence and limits",
        "",
        "- JUnit XML preserves test-level pass/fail and duration.",
        "- JSON summary preserves the same machine-readable assessment.",
        "- Demo JSONL is a separate **Core causal timeline**; this JUnit report "
        "does not claim to contain all event/Belief/Action records.",
        "- Passing this suite does not prove unrestricted autonomy, real hardware "
        "reliability, distributed operation or immunity to storage corruption.",
        "",
    ])
    return "\n".join(lines)


def _commit():
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        text=True, capture_output=True, check=False, timeout=10,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run Core v0.1 tests and produce a readable acceptance report"
    )
    parser.add_argument("--suite", choices=("p4", "core", "full"), default="core")
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="empty or new directory for test results (never overwrite)",
    )
    args = parser.parse_args(argv)
    destination = args.output_dir.expanduser().resolve()
    if destination.exists() and (
        not destination.is_dir() or any(destination.iterdir())
    ):
        parser.error("output-dir must be absent or empty; refusing to overwrite")
    destination.mkdir(parents=True, exist_ok=True)
    files = (
        (CORE_MODULES[0],) if args.suite == "p4"
        else CORE_MODULES if args.suite == "core"
        else ()
    )
    junit = destination / "junit.xml"
    command = [
        sys.executable, "-m", "pytest", "-q", *files,
        f"--junitxml={junit}",
    ]
    completed = subprocess.run(
        command, cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False,
    )
    (destination / "pytest.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    if junit.is_file():
        totals, cases = summarize_junit(junit)
    else:
        totals, cases = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}, []
    verdict = (
        "PASS" if completed.returncode == 0
        and totals["total"] > 0 and totals["failed"] == 0 else "FAIL"
    )
    record = {
        "schema": "anima.core.acceptance-report/0.1",
        "suite": args.suite,
        "commit": _commit(),
        "python": sys.version.split()[0],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exit_code": completed.returncode,
        "result": verdict,
        "totals": totals,
        "cases": cases,
    }
    (destination / "summary.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (destination / "summary.md").write_text(
        render_markdown(record), encoding="utf-8"
    )
    print(
        f"ANIMA Core v0.1 / {args.suite} acceptance — {verdict}\n"
        f"  PASS {totals['passed']} | FAIL {totals['failed']} "
        f"| SKIP {totals['skipped']}\n"
        f"  Commit: {record['commit']}\n"
        f"  Отчёт: {destination / 'summary.md'}\n"
        f"  Данные: {destination / 'summary.json'}\n"
        f"  JUnit: {junit}\n"
        f"  Полный вывод: {destination / 'pytest.log'}"
    )
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
