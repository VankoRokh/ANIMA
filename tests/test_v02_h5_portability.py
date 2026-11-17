"""H5.1: honest, reproducible compatibility report contracts.

No production data, no network and no implicit Python 3.12 PASS. Tests
inject interpreter subprocess responses to exercise failure reporting.
"""

import json
import sys
import venv

from labs import v02_h5_portability as portability


def profile(version=(3, 14), *, fts5=True, json1=True, pytest=True):
    return {
        "python": [version[0], version[1], 0],
        "implementation": "CPython",
        "machine": "x86_64",
        "platform": "linux",
        "sqlite": "3.45.1",
        "fts5": fts5,
        "json1": json1,
        "pytest_available": pytest,
    }


def test_h5_1_classify_pass_requires_implemented_runtime_and_actual_success():
    assert portability.classify_profile(
        profile(), {"returncode": 0}
    ) == "PASS"
    assert portability.classify_profile(
        profile((3, 12)), {"returncode": 0}
    ) == "PASS"
    assert portability.classify_profile(
        profile(), {"returncode": 1}
    ) == "FAIL"
    assert portability.classify_profile(None, None) == "NOT_TESTED"


def test_h5_1_missing_sqlite_capability_is_not_pass():
    assert portability.classify_profile(
        profile(fts5=False), {"returncode": 0},
    ) == "UNSUPPORTED"
    assert portability.classify_profile(
        profile(json1=False), {"returncode": 0},
    ) == "UNSUPPORTED"
    assert portability.classify_profile(
        profile((3, 11)), {"returncode": 0},
    ) == "UNSUPPORTED"


def test_h5_1_missing_target_interpreter_cannot_borrow_another_pass(
    monkeypatch,
):
    monkeypatch.setattr(portability.shutil, "which", lambda _x: None)
    result = portability.inspect_interpreter("missing-python-3.12")
    assert result["status"] == "NOT_TESTED"
    assert result["probe"] is None
    assert result["regression"] is None


def test_h5_1_probe_without_pytest_remains_not_tested(monkeypatch):
    def fake_run(command, **_kwargs):
        assert "-c" in command
        return {
            "returncode": 0,
            "stdout": json.dumps(profile(pytest=False)),
            "stderr": "",
            "error": None,
        }

    monkeypatch.setattr(portability, "_run", fake_run)
    result = portability.inspect_interpreter(sys.executable)
    assert result["status"] == "NOT_TESTED"
    assert result["regression"] is None
    assert "pytest not installed" in result["reason"]


def test_h5_1_interpreter_test_failure_reported_as_fail(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "-c" in command:
            return {
                "returncode": 0,
                "stdout": json.dumps(profile()),
                "stderr": "",
                "error": None,
            }
        assert command[1:5] == ["-B", "-m", "pytest", "-q"]
        return {
            "returncode": 1,
            "stdout": "1 failed, 42 passed\n",
            "stderr": "failure evidence",
            "error": None,
        }

    monkeypatch.setattr(portability, "_run", fake_run)
    result = portability.inspect_interpreter(sys.executable)
    assert len(calls) == 2
    assert result["status"] == "FAIL"
    assert result["regression"]["returncode"] == 1
    assert "1 failed" in result["regression"]["stdout_tail"]


def test_h5_1_report_marks_missing_second_runtime_incomplete(monkeypatch):
    monkeypatch.setattr(
        portability, "_git_snapshot",
        lambda: {
            "head": "f" * 40,
            "branch": "work/h5",
            "status_porcelain": "",
        },
    )
    monkeypatch.setattr(
        portability, "inspect_interpreter",
        lambda target, **_kw: {
            "requested": target,
            "status": "PASS" if target == "python3.14" else "NOT_TESTED",
        },
    )
    result = portability.build_report(["python3.14", "python3.12"])
    assert result["status"] == "INCOMPLETE"
    assert result["git_clean"] is True
    assert [x["status"] for x in result["runs"]] == [
        "PASS", "NOT_TESTED",
    ]


def test_h5_1_dirty_git_snapshot_is_incomplete_even_if_tests_pass(
    monkeypatch,
):
    monkeypatch.setattr(
        portability, "_git_snapshot",
        lambda: {
            "head": "a" * 40,
            "branch": "work/h5",
            "status_porcelain": " M anima/memory/processor.py",
        },
    )
    monkeypatch.setattr(
        portability, "inspect_interpreter",
        lambda _target, **_kw: {"status": "PASS"},
    )
    result = portability.build_report(["python3.14"])
    assert result["status"] == "INCOMPLETE"
    assert result["git_clean"] is False


def test_h5_1_local_probe_returns_json_without_mutating_repo():
    outcome = portability._run(
        [sys.executable, "-B", "-c", portability.PROBE],
    )
    assert outcome["returncode"] == 0
    details = json.loads(outcome["stdout"])
    assert details["python"][:2] == list(sys.version_info[:2])
    assert isinstance(details["fts5"], bool)
    assert isinstance(details["json1"], bool)
    assert isinstance(details["pytest_available"], bool)


def test_h5_1_virtualenv_launch_does_not_resolve_python_symlink(tmp_path, monkeypatch):
    """A symlinked Python may have a different sys.prefix and installed libs."""
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    entrypoint = bin_dir / "python"
    entrypoint.symlink_to(sys.executable)

    def fake_run(command, **_kwargs):
        assert command[0] == str(entrypoint)
        assert "-c" in command
        return {
            "returncode": 0,
            "stdout": json.dumps(profile(pytest=False)),
            "stderr": "",
            "error": None,
        }

    monkeypatch.setattr(portability, "_run", fake_run)
    result = portability.inspect_interpreter(str(entrypoint))
    assert result["status"] == "NOT_TESTED"
    assert result["resolved"] == str(entrypoint)
    assert result["reason"] == "pytest not installed for this interpreter"


def test_h5_1_real_virtualenv_probe_preserves_environment_prefix(tmp_path):
    """Integration test: exercise CPython's real venv path discovery."""
    venv_dir = tmp_path / "isolated-venv"
    venv.create(venv_dir, with_pip=False, symlinks=True)
    executable = venv_dir / "bin" / "python"
    assert executable.exists()

    # Do not install dependencies or invoke focused pytest. Probe must
    # identify the virtual environment even if it lacks pytest.
    result = portability.inspect_interpreter(str(executable))
    assert result["status"] == "NOT_TESTED"
    assert result["probe"]["sys_prefix"] == str(venv_dir)
    assert result["probe"]["sys_base_prefix"] != str(venv_dir)
    assert result["resolved"] == str(executable)
