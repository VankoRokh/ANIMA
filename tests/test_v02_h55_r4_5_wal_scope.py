"""H5.5 R4.5 / F-08 — SQLite WAL/SHM snapshot source I/O contract.

Independent H5.5 auditor reproduced snapshot_wal:
a process exits with a committed WAL; sqlite3 mode=ro backup recovers the
logical record while the original memory.db-shm SHA-256 may change.
This is NOT a forensic byte-immutable copy of an evidence root.

Only throwaway pytest tmp_path instances. Never inspect or modify users'
real instance roots, and never assert SHM hashes must change (SQLite/OS
variations). Verify the explicit not-guaranteed contract instead.
"""

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from anima.release_v01 import open_release
from labs.v02_h5_snapshot import (
    MANIFEST,
    SOURCE_READ_ONLY_SCOPE,
    create_snapshot,
    main,
    restore_snapshot,
    verify_snapshot,
)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(root):
    return {
        file.relative_to(root).as_posix(): _hash(file)
        for file in sorted(root.rglob("*"))
        if file.is_file()
    }


def _release(root):
    with open_release(root) as release:
        response = release.handle({
            "op": "report",
            "text": "h55f08 source fixture for forensic WAL contract",
        })
        assert response["ok"] is True
        assert response["event_ids"]
    assert (root / ".anima-v01.lock").is_file()


def _crash_after_committed_wal(db_path):
    # Child exits without sqlite3.close() to keep a committed WAL sidecar.
    # This is the auditor's exact mechanism; executable only in tmp_path.
    code = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
db.execute('CREATE TABLE h55f08_committed_marker(value TEXT NOT NULL)')
db.execute("INSERT INTO h55f08_committed_marker VALUES ('committed in WAL')")
db.commit()
os._exit(74)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(db_path)],
        check=False,
        capture_output=True, text=True,
        timeout=20,
    )
    assert result.returncode == 74, (result.stdout, result.stderr)
    assert db_path.with_name(db_path.name + "-wal").stat().st_size > 0
    return result


@pytest.mark.parametrize(
    "database",
    ["memory.db", "internal_state.db", "core_state.db"],
)
def test_h55_r45_committed_wal_backup_is_logical_not_forensic(
    tmp_path, database,
):
    source = tmp_path / "source"
    snapshot = tmp_path / "snapshot"
    restored = tmp_path / "restored"
    _release(source)
    db_path = source / database
    _crash_after_committed_wal(db_path)

    before = _fingerprint(source)
    assert database + "-wal" in before
    assert database + "-shm" in before
    created = create_snapshot(source, snapshot)
    after = _fingerprint(source)

    assert created["status"] == "SNAPSHOT_CREATED"
    assert created["source_read_only_scope"] == SOURCE_READ_ONLY_SCOPE
    assert created["forensic_byte_stability_guaranteed"] is False
    assert verify_snapshot(snapshot)["status"] == "VERIFIED"

    # The forensic boundary is NOT claimed for SHM and other transient
    # sidecars, even if this particular OS happens not to alter them.
    assert before["events.jsonl"] == after["events.jsonl"]
    assert before["identity.json"] == after["identity.json"]
    assert not any(
        path.name.endswith(("-wal", "-shm", "-journal"))
        for path in snapshot.rglob("*") if path.is_file()
    )
    assert (snapshot / MANIFEST).is_file()

    result = restore_snapshot(snapshot, restored)
    assert result["status"] == "RESTORED_TO_NEW_DIRECTORY"
    with sqlite3.connect(restored / database) as connection:
        assert connection.execute(
            "SELECT value FROM h55f08_committed_marker",
        ).fetchone()[0] == "committed in WAL"


def test_h55_r45_normal_instance_still_reports_no_forensic_guarantee(
    tmp_path,
):
    source = tmp_path / "source"
    snapshot = tmp_path / "snapshot"
    _release(source)
    report = create_snapshot(source, snapshot)
    assert report["source_read_only_scope"] == SOURCE_READ_ONLY_SCOPE
    assert report["forensic_byte_stability_guaranteed"] is False
    assert verify_snapshot(snapshot)["status"] == "VERIFIED"
    # Schema/manifest contract is NOT silently changed by an API status.
    manifest = json.loads((snapshot / MANIFEST).read_text())
    assert "source_read_only_scope" not in manifest
    assert "forensic_byte_stability_guaranteed" not in manifest


def test_h55_r45_cli_output_explicitly_discloses_sidecar_scope(
    tmp_path, capsys,
):
    source = tmp_path / "source"
    snapshot = tmp_path / "snapshot"
    _release(source)
    code = main([
        "create",
        "--source", str(source),
        "--destination", str(snapshot),
    ])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source_read_only_scope"] == SOURCE_READ_ONLY_SCOPE
    assert report["forensic_byte_stability_guaranteed"] is False


def test_h55_r45_forensic_workflow_uses_disposable_working_clone(
    tmp_path,
):
    # To require byte-for-byte stability, open SQLite only on an offline
    # working COPY, never on the original evidence image. This demonstrates
    # the documented procedure without adding a misleading safe mode.
    original = tmp_path / "original"
    working_copy = tmp_path / "working"
    snapshot = tmp_path / "snapshot"
    restored = tmp_path / "restored"
    _release(original)
    _crash_after_committed_wal(original / "memory.db")
    before = _fingerprint(original)

    # All files, including committed WAL and SHM, are copied as bytes.
    shutil.copytree(original, working_copy)
    assert _fingerprint(working_copy) == before
    created = create_snapshot(working_copy, snapshot)
    assert created["forensic_byte_stability_guaranteed"] is False
    # Any WAL-index side effects occur on the working copy, not original.
    assert _fingerprint(original) == before
    assert verify_snapshot(snapshot)["status"] == "VERIFIED"

    restore_snapshot(snapshot, restored)
    with sqlite3.connect(restored / "memory.db") as connection:
        assert connection.execute(
            "SELECT value FROM h55f08_committed_marker",
        ).fetchone()[0] == "committed in WAL"
