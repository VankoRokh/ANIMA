#!/usr/bin/env python3
"""Run the selected Core acceptance suite and emit human + machine reports.

Execution is synchronous; nothing runs in the background. Data stays in the
explicit report directory. JUnit XML is test-runner evidence, not Core trace.
"""

import argparse
import json
import subprocess
import sys
import time
from math import ceil
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
P4_MODULES = (
    "tests/test_core_p4_acceptance.py",
    "tests/test_core_p4c_release.py",
    "tests/test_core_p4_report.py",
    "tests/test_core_audit_blockers.py",
)
CORE_MODULES = P4_MODULES + (
    "tests/test_core_p3c_autonomy.py",
    "tests/test_core_p3c_demo.py",
    "tests/test_core_p3b_execution.py",
    "tests/test_core_p3a_goal_decision.py",
    "tests/test_core_p2c_runtime.py",
    "tests/test_core_p2b_belief.py",
    "tests/test_core_p2a_ingress.py",
    "tests/test_core_p1_bootstrap.py",
)


P4_REQUIRED = (
    "test_p4_priority_two_goals_and_repeat_goal_after_restart",
    "test_p4_conflicts_duplicates_late_and_noise_not_trusted_as_truth",
    "test_p4_false_success_then_new_external_evidence_completes_without_retry",
    "test_p4_crash_after_applied_effect_reconciles_without_double_execution",
    "test_p4_missing_capability_never_acts_even_after_restart",
    "test_p4_recover_verified_goal_without_task_completion",
    "test_p4_many_irrelevant_events_advance_cursor_without_effects",
    "test_p4b_crash_after_goal_completed_before_scheduler_audit",
    "test_p4b_cancelled_started_attempt_finishes_deferred_without_effect",
    "test_p4b_operator_completed_goal_does_not_invent_core_evidence",
    "test_p4b_multi_episode_cold_restart_and_noise_stay_bounded[2]",
    "test_p4b_multi_episode_cold_restart_and_noise_stay_bounded[4]",
    "test_p4c_seeded_24_episode_endurance_with_cold_restarts[7]",
    "test_p4c_seeded_24_episode_endurance_with_cold_restarts[31]",
    "test_p4c_seeded_24_episode_endurance_with_cold_restarts[73]",
    "test_p4c_seed_plan_replays_same_workload_independent_of_uuid",
    "test_p4c_bounded_no_work_idle_does_not_mutate_world",
    "test_p4c_readonly_belief_unknown_without_event_and_no_goal",
    "test_p4c_registered_untrusted_source_cannot_forge_door_completion",
    "test_core_audit_b1_atomic_prepare_failure_rolls_back_all_rows",
    "test_core_audit_b1_os_exit_inside_atomic_prepare_recovers",
    "test_core_audit_b1_legacy_missing_spec_is_local_and_next_goal_progresses",
    "test_core_audit_b2_cancel_after_proof_does_not_poison_other_goals[goal]",
    "test_core_audit_b2_cancel_after_proof_does_not_poison_other_goals[task]",
    "test_core_audit_b3_same_runtime_retry_uses_identical_stage2_request",
    "test_core_audit_b4_blocked_to_active_resumes_parked_goal",
    "test_core_audit_t1_mandatory_test_identity_includes_module",
)


def required_coverage(cases):
    """A green run cannot silently omit or skip required P4 scenarios."""
    statuses = {}
    for name in P4_REQUIRED:
        # JUnit name alone is not a trustworthy acceptance identity.
        # Bind every mandatory test to its canonical module as well.
        module = (
            "tests.test_core_p4c_release"
            if name.startswith("test_p4c_")
            else "tests.test_core_p4_acceptance"
            if name.startswith(("test_p4_", "test_p4b_"))
            else "tests.test_core_audit_blockers"
            if name.startswith("test_core_audit_")
            else None
        )
        if module is None:
            raise ValueError(f"Unrecognized mandatory P4 test origin: {name}")
        matched = [
            case for case in cases
            if case.get("classname") == module
            and (case.get("name") == name or case.get("name", "").startswith(name + "["))
        ]
        if not matched:
            statuses[name] = "MISSING"
        elif any(case["status"] == "FAIL" for case in matched):
            statuses[name] = "FAIL"
        elif any(case["status"] == "SKIP" for case in matched):
            statuses[name] = "SKIP"
        else:
            statuses[name] = "PASS"
    return statuses


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
    coverage = record.get("required_coverage", {})
    times = sorted(case["seconds"] for case in record["cases"])
    p95 = times[ceil(0.95 * len(times)) - 1] if times else 0.0
    lines = [
        "# ANIMA Core v0.1 — Acceptance Run",
        "",
        f"**Result:** {verdict}  ",
        f"**Suite:** `{record['suite']}`  ",
        f"**Commit:** `{record['commit']}`  ",
        f"**Git tree:** `{record.get('tree', 'not recorded')}`  ",
        f"**Clean/unchanged checkout:** `{record.get('checkout_unchanged', 'unknown')}`  ",
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
        f"- Sum of case durations: **{sum(times):.3f}s**",
        f"- Case duration p95 (observed): **{p95:.3f}s**",
        "",
        "## Mandatory P4 evidence",
        "",
    ]
    if coverage:
        for name, status in coverage.items():
            lines.append(f"- {name}: **{status}**")
    else:
        lines.append("- Not evaluated.")
    lines.extend([
        "",
        "## Cases",
        "",
        "| Status | Test | Seconds |",
        "|---|---|---:|",
    ])
    for case in record["cases"]:
        label = (case["classname"] + "::" + case["name"]).replace("|", "\\|")
        lines.append(
            f"| {case['status']} | `{label}` | {case['seconds']:.3f} |"
        )
    lines.extend(["", "## Slowest test cases (observed baseline)", ""])
    for case in sorted(
        record["cases"], key=lambda row: row["seconds"], reverse=True
    )[:5]:
        lines.append(
            f"- {case['seconds']:.3f}s : {case['classname']}::{case['name']}"
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


def _git_snapshot():
    """Verified HEAD/tree/clean-worktree identity for each acceptance run."""
    results = {}
    for name, command in (
        ("commit", ("git", "rev-parse", "HEAD")),
        ("tree", ("git", "rev-parse", "HEAD^{tree}")),
        ("porcelain", ("git", "status", "--porcelain=v1", "--untracked-files=normal")),
    ):
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            check=False, timeout=10,
        )
        if result.returncode != 0:
            results[name] = None
            results.setdefault("git_errors", []).append(
                f"{name}: {result.stderr.strip() or result.returncode}"
            )
        else:
            results[name] = result.stdout.strip()
    results["clean"] = results.get("porcelain") == ""
    return results


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
    git_before = _git_snapshot()
    files = (
        P4_MODULES if args.suite == "p4"
        else CORE_MODULES if args.suite == "core"
        else ()
    )
    junit = destination / "junit.xml"
    command = [
        sys.executable, "-m", "pytest", "-q", *files,
        f"--junitxml={junit}",
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed_wall_seconds = round(time.monotonic() - started, 6)
    git_after = _git_snapshot()
    checkout_unchanged = (
        git_before["clean"] and git_after["clean"]
        and git_before["commit"] is not None
        and git_before["commit"] == git_after["commit"]
        and git_before["tree"] is not None
        and git_before["tree"] == git_after["tree"]
    )
    (destination / "pytest.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    if junit.is_file():
        totals, cases = summarize_junit(junit)
    else:
        totals, cases = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}, []
    coverage = required_coverage(cases)
    verdict = (
        "PASS" if completed.returncode == 0
        and totals["total"] > 0 and totals["failed"] == 0
        and all(status == "PASS" for status in coverage.values())
        and checkout_unchanged
        else "FAIL"
    )
    record = {
        "schema": "anima.core.acceptance-report/0.1",
        "suite": args.suite,
        "commit": git_before["commit"] or "unknown",
        "tree": git_before["tree"] or "unknown",
        "git_before": git_before,
        "git_after": git_after,
        "checkout_unchanged": checkout_unchanged,
        "python": sys.version.split()[0],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exit_code": completed.returncode,
        "result": verdict,
        "elapsed_wall_seconds": elapsed_wall_seconds,
        "required_coverage": coverage,
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
