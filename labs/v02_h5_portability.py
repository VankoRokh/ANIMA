"""H5.1 reproducible Python/SQLite compatibility probe and regression runner.

Does not modify production ANIMA data. Runs a bounded suite on disposable
pytest fixtures, captures a Git snapshot and reports precise test status.
Use --python repeatedly for different interpreters, e.g.:
    PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_portability \
      --python .venv/bin/python --python python3.12

A missing 3.12 environment MUST be NOT_TESTED, never PASS. The exit code
will be 2 for incomplete evidence or failed checks. This is not the full
H5 release gate and does not test aarch64 unless executed on that hardware.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "anima.v02.h5.portability/0.1"
FOCUSED_TESTS = (
    "tests/test_v02_h0_foundation_contracts.py",
    "tests/test_v02_h1_3_prefix_digest.py",
    "tests/test_v02_h2_2_evidence.py",
    "tests/test_v02_h3_1_temporal_relations.py",
    "tests/test_v02_h3_2_retrieval_eligibility.py",
    "tests/test_v02_h4_identity_guard.py",
    "tests/test_v02_h5_legacy_diagnostic.py",
    "tests/test_stage1_validation.py",
)

# The probe is evaluated by the *target* interpreter, not the launcher.
PROBE = r"""
import importlib.util
import json
import platform
import sqlite3
import sys

connection = sqlite3.connect(":memory:")
try:
    connection.execute("CREATE VIRTUAL TABLE probe_fts USING fts5(text)")
    fts5 = True
except sqlite3.DatabaseError:
    fts5 = False
try:
    json1 = connection.execute(
        "SELECT json_valid('{\"probe\":true}')"
    ).fetchone()[0] == 1
except sqlite3.DatabaseError:
    json1 = False
finally:
    connection.close()
print(json.dumps({
    "python": list(sys.version_info[:3]),
    "implementation": platform.python_implementation(),
    "machine": platform.machine(),
    "platform": sys.platform,
    "sqlite": sqlite3.sqlite_version,
    "fts5": fts5,
    "json1": json1,
    "pytest_available": importlib.util.find_spec("pytest") is not None,
    "sys_prefix": sys.prefix,
    "sys_base_prefix": sys.base_prefix,
    "executable": sys.executable,
}, sort_keys=True))
"""


def _run(command, *, timeout=30, env=None):
    try:
        process = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "returncode": None,
            "error": type(error).__name__ + ": " + str(error),
            "stdout": "", "stderr": "",
        }
    return {
        "returncode": process.returncode,
        "error": None,
        "stdout": process.stdout,
        "stderr": process.stderr,
    }


def _git_snapshot():
    def git(*args):
        result = _run(["git", *args])
        if result["returncode"] != 0:
            return None
        return result["stdout"].strip()

    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "status_porcelain": git("status", "--porcelain"),
    }


def classify_profile(probe, regression):
    """No target gets PASS unless it executed tests with required SQLite."""
    if probe is None or regression is None:
        return "NOT_TESTED"
    if (
        probe["implementation"] != "CPython"
        or tuple(probe["python"][:2]) not in {(3, 12), (3, 14)}
        or not probe["fts5"] or not probe["json1"]
    ):
        return "UNSUPPORTED"
    return "PASS" if regression["returncode"] == 0 else "FAIL"


def inspect_interpreter(executable, *, timeout=240):
    """Keep the requested Python launch path: realpath strips venv context.

    The CPython venv lookup depends on the path used to launch Python.
    A typical .venv/bin/python is a symlink to /usr/bin/python3.x; using
    Path.resolve() silently changes the interpreter environment and masks
    installed packages. Absolute lexical paths preserve that symlink.
    """
    candidate = Path(executable).expanduser()
    resolved = (
        str(candidate.absolute())
        if candidate.is_file()
        else shutil.which(executable)
    )
    if resolved is None:
        return {
            "requested": executable,
            "status": "NOT_TESTED",
            "reason": "interpreter not found",
            "probe": None,
            "regression": None,
        }

    probe_result = _run([resolved, "-B", "-c", PROBE])
    if probe_result["returncode"] != 0:
        return {
            "requested": executable,
            "resolved": resolved,
            "status": "NOT_TESTED",
            "reason": "interpreter probe failed",
            "probe": None,
            "regression": None,
            "probe_error": probe_result["error"],
            "probe_stderr": probe_result["stderr"][-800:],
        }
    try:
        probe = json.loads(probe_result["stdout"])
    except ValueError:
        return {
            "requested": executable,
            "resolved": resolved,
            "status": "NOT_TESTED",
            "reason": "probe did not return JSON",
            "probe": None,
            "regression": None,
        }

    if not probe["pytest_available"]:
        return {
            "requested": executable,
            "resolved": resolved,
            "status": "NOT_TESTED",
            "reason": "pytest not installed for this interpreter",
            "probe": probe,
            "regression": None,
        }
    if (
        probe["implementation"] != "CPython"
        or tuple(probe["python"][:2]) not in {(3, 12), (3, 14)}
        or not probe["fts5"]
        or not probe["json1"]
    ):
        return {
            "requested": executable,
            "resolved": resolved,
            "status": "UNSUPPORTED",
            "reason": "Python version or required SQLite features mismatch",
            "probe": probe,
            "regression": None,
        }

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"]
        if env.get("PYTHONPATH") else ""
    )
    command = [resolved, "-B", "-m", "pytest", "-q", "--maxfail=1"]
    command.extend(FOCUSED_TESTS)
    outcome = _run(command, timeout=timeout, env=env)
    status = "PASS" if outcome["returncode"] == 0 else "FAIL"
    if outcome["returncode"] is None:
        status = "NOT_TESTED"
    return {
        "requested": executable,
        "resolved": resolved,
        "status": status,
        "reason": outcome["error"],
        "probe": probe,
        "regression": {
            "returncode": outcome["returncode"],
            "stdout_tail": outcome["stdout"][-3000:],
            "stderr_tail": outcome["stderr"][-1000:],
            "tests": list(FOCUSED_TESTS),
        },
    }


def build_report(interpreters, *, timeout=240):
    snapshot = _git_snapshot()
    # Each Python variant is recorded separately; a missing target cannot
    # borrow a successful result from the primary interpreter.
    runs = [inspect_interpreter(p, timeout=timeout) for p in interpreters]
    clean = snapshot["head"] is not None and snapshot["status_porcelain"] == ""
    ready = clean and all(item["status"] == "PASS" for item in runs)
    return {
        "schema": SCHEMA,
        "git": snapshot,
        "git_clean": clean,
        "runs": runs,
        "status": "PASS" if ready else "INCOMPLETE",
        "scope": [
            "Focused pytest only: not full regression, fault injection or RC.",
            "Missing Python 3.12 and aarch64 are not verified implicitly.",
            "No target private instance data is accessed.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python", action="append", dest="interpreters",
        help="Existing Python command/path (repeat for each target).",
    )
    parser.add_argument(
        "--timeout", type=int, default=240,
        help="Per-interpreter focused pytest timeout in seconds.",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Create a NEW JSON report file; refuses to overwrite.",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    targets = args.interpreters or [sys.executable, "python3.12"]
    report = build_report(targets, timeout=args.timeout)
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(output + "\n")
    print(output)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
