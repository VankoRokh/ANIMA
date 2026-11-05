"""P4 acceptance reporting: deterministic test evidence and overwrite guards."""

import subprocess
import sys
from pathlib import Path

from scripts.run_core_acceptance import render_markdown, summarize_junit


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
