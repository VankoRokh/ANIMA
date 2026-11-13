"""True process-level SIGKILL recovery gates for isolated E4 authority lab.

Every phase runs in a fresh Python interpreter; the child really dies by
SIGKILL, not a handled Python exception. Linux/POSIX-only.
"""
import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]


def _run(phase, db):
    return subprocess.run(
        [sys.executable, "-m", "labs.exp009.e4_process_kill_probe",
         "--phase", phase, "--db", str(db)],
        cwd=REPO, capture_output=True, text=True, timeout=30,
        check=False,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal 9 required")
@pytest.mark.parametrize("cut", [
    ("before", "CUT_INSIDE_UNCOMMITTED_TRANSACTION"),
    ("after", "CUT_AFTER_COMMITTED_TRANSACTION"),
])
def test_real_sigkill_atomicity_reopen_replay(tmp_path, cut):
    stage, marker = cut
    db = tmp_path / f"e4-authority-{stage}.db"
    seed = _run("seed", db)
    assert seed.returncode == 0, seed.stderr
    assert json.loads(seed.stdout)["status"] == "SIGKILL_REOPEN_INVARIANTS_PASS"

    killed = _run(f"kill_{stage}", db)
    assert killed.returncode == -signal.SIGKILL, (
        killed.returncode, killed.stdout, killed.stderr
    )
    assert marker in killed.stdout, killed.stdout

    verified = _run(f"verify_{stage}", db)
    assert verified.returncode == 0, verified.stderr
    raw = json.loads(verified.stdout)
    assert raw["status"] == "SIGKILL_REOPEN_INVARIANTS_PASS"
    assert raw["alias_b"] == "active" and raw["heads"]["U"] == "current"

    replayed = _run(f"replay_{stage}", db)
    assert replayed.returncode == 0, replayed.stderr
    result = json.loads(replayed.stdout)
    assert result["replay_status"] == (
        "revoked" if stage == "before" else "idempotent_replay")
    assert result["invalidations"] == ["E", "S"]
    assert result["allowed"] == 1 and result["operations"] == 6

    after_replay = _run("verify_after", db)
    assert after_replay.returncode == 0, after_replay.stderr
    assert json.loads(after_replay.stdout)["status"] == "SIGKILL_REOPEN_INVARIANTS_PASS"
