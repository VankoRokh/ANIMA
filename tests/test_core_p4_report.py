"""P4 acceptance reporting: deterministic test evidence and overwrite guards."""

import subprocess
import sys
from pathlib import Path

from scripts.run_core_acceptance import render_markdown, summarize_junit, required_coverage, P4_REQUIRED


ROOT = Path(__file__).resolve().parents[1]


def test_p4_junit_parser_and_markdown_are_human_readable(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="3">'
        '<testcase classname="core.acceptance" name="open" time="0.03"/>'
        '<testcase classname="core.acceptance" name="closed" time="0.02">'
        '<skipped/></testcase>'
        '<testcase classname="core.acceptance" name="crash" time="0.04">'
        '<failure message="injected failure">traceback</failure></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    totals, cases = summarize_junit(junit)
    assert totals == {"passed": 1, "failed": 1, "skipped": 1, "total": 3}
    assert [case["status"] for case in cases] == ["PASS", "SKIP", "FAIL"]
    text = render_markdown({
        "result": "FAIL", "suite": "p4", "commit": "tested-commit",
        "python": "3.14.4", "timestamp": "2026-11-05T00:00:00+00:00",
        "exit_code": 1, "totals": totals, "cases": cases,
    })
    assert "**Result:** FAIL" in text
    assert "tested-commit" in text
    assert "Passed: **1**" in text
    assert "Failures" in text and "injected failure" in text
    assert "not claim to contain all event/Belief/Action" in text


def test_p4_runner_refuses_nonempty_output_directory(tmp_path):
    output = tmp_path / "real_results"
    output.mkdir()
    sentinel = output / "summary.md"
    sentinel.write_text("keep existing results", encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable, "-B", "scripts/run_core_acceptance.py",
            "--suite", "p4", "--output-dir", str(output),
        ],
        cwd=ROOT, text=True, capture_output=True,
        timeout=15, check=False,
    )
    assert run.returncode != 0
    assert "refusing to overwrite" in run.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep existing results"



def test_p4b_required_coverage_blocks_missing_or_skipped_cases():
    cases = [
        {
            "name": name, "status": "PASS", "classname": "tests.test_core_p4_acceptance",
            "seconds": 0.01,
        }
        for name in P4_REQUIRED
    ]
    coverage = required_coverage(cases)
    assert len(coverage) == len(P4_REQUIRED)
    assert set(coverage.values()) == {"PASS"}

    cases[0]["status"] = "SKIP"
    assert required_coverage(cases)[P4_REQUIRED[0]] == "SKIP"

    cases[0]["status"] = "FAIL"
    assert required_coverage(cases)[P4_REQUIRED[0]] == "FAIL"

    cases.pop()
    assert required_coverage(cases)[P4_REQUIRED[-1]] == "MISSING"


def test_p4b_report_displays_measured_baselines_not_unsupported_thresholds():
    cases = [
        {
            "name": name, "classname": "tests.test_core_p4_acceptance",
            "status": "PASS", "seconds": 0.01 + index * 0.005,
            "message": "",
        }
        for index, name in enumerate(P4_REQUIRED)
    ]
    report = {
        "result": "PASS", "suite": "p4", "commit": "reproducible-sha",
        "python": "3.14.4", "timestamp": "2026-11-05T10:00:00+00:00",
        "exit_code": 0,
        "totals": {"passed": len(cases), "failed": 0, "skipped": 0, "total": len(cases)},
        "cases": cases, "required_coverage": required_coverage(cases),
    }
    result = render_markdown(report)
    assert "**Result:** PASS" in result
    assert "Mandatory P4 evidence" in result
    assert "Case duration p95 (observed)" in result
    assert "Slowest test cases (observed baseline)" in result
    assert "reproducible-sha" in result
    assert "MISSING" not in result
