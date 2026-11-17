"""ANIMA H5.4a: backup/restore, identity, legacy and no-overwrite gates.

All source instances, backup directories, corruptions and migrations are
constructed under pytest tmp_path. No real user data is read or changed.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from anima.memory.event_log import EventLog
from anima.memory.event_retrieval import EventRetrieval
from anima.memory.memory_store import MemoryStore
from anima.release_v01 import PROTOCOL, open_release
from labs.v02_h5_legacy_diagnostic import audit_snapshot
from labs.v02_h5_snapshot import (
    MANIFEST, create_snapshot, restore_snapshot, verify_snapshot,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_instance(root, *, sandbox=False):
    with open_release(root, sandbox_door=sandbox) as release:
        identity = release.core.identity.get()["instance_id"]
        message = release.handle({
            "op": "report",
            "text": "h54 unique source marker independent Raw history",
        })
        event_id = message["event_ids"][0]
        search = release.handle({
            "op": "search_events", "query": "h54",
        })
        assert event_id in {
            row["id"] for row in search["result"]["results"]
        }
        assert search["result"]["coverage"]["status"] == "complete"
        if sandbox:
            goal = release.handle({"op": "ensure_sandbox_door_closed"})
            assert goal["goal_status"] == "completed"
    return identity, event_id


def test_h54_backup_restore_preserves_original_ids_and_raw(
    tmp_path,
):
    source, snap, restored = (
        tmp_path / "source", tmp_path / "snap", tmp_path / "restored"
    )
    identity, event_id = _create_instance(source)
    original_raw = source / "events.jsonl"
    original_identity = source / "identity.json"
    initial_raw_hash = _sha(original_raw)
    initial_identity_hash = _sha(original_identity)
    original_store = MemoryStore(source / "memory.db")
    initial_record = original_store.source_events(
        original_store.list_memories()[0]["id"]
    )
    assert event_id in initial_record

    report = create_snapshot(source, snap)
    assert report["status"] == "SNAPSHOT_CREATED"
    assert report["protocol"] == PROTOCOL
    assert verify_snapshot(snap)["status"] == "VERIFIED"
    assert (snap / "event_index.db").is_file()
    assert _sha(original_raw) == initial_raw_hash
    assert _sha(original_identity) == initial_identity_hash

    restored_info = restore_snapshot(snap, restored)
    assert restored_info["status"] == "RESTORED_TO_NEW_DIRECTORY"
    assert "event_index.db" in restored_info["derived_indexes_rebuild_on_open"]
    assert not (restored / "event_index.db").exists()
    assert not (restored / ".anima-v01.lock").exists()
    assert (restored / "events.jsonl").read_bytes() == original_raw.read_bytes()
    assert (restored / "release_profile.json").read_bytes() == (
        source / "release_profile.json"
    ).read_bytes()

    with open_release(restored) as release:
        assert release.core.identity.get()["instance_id"] == identity
        found = release.handle({"op": "search_events", "query": "h54"})
        assert event_id in {
            row["id"] for row in found["result"]["results"]
        }
        assert found["result"]["coverage"]["status"] == "complete"
        assert release.core.event_processing.get(event_id)["status"] == "done"
        assert release.core.event_processing.get(event_id)["attempts"] == 1
    assert _sha(original_raw) == initial_raw_hash
    assert _sha(original_identity) == initial_identity_hash
    assert verify_snapshot(snap)["status"] == "VERIFIED"


def test_h54_release_sandbox_effects_survive_restore_without_reexecution(
    tmp_path,
):
    source, snap, restored = (
        tmp_path / "source", tmp_path / "snap", tmp_path / "restored"
    )
    identity, _ = _create_instance(source, sandbox=True)
    with sqlite3.connect(source / "sandbox_world" / "virtual_door.db") as db:
        initial_effects = db.execute(
            "SELECT COUNT(*) FROM door_effects WHERE applied=1"
        ).fetchone()[0]
    assert initial_effects == 1

    create_snapshot(source, snap)
    assert (snap / "sandbox_world" / "virtual_door.db").is_file()
    restore_snapshot(snap, restored)
    with sqlite3.connect(restored / "sandbox_world" / "virtual_door.db") as db:
        effects = db.execute(
            "SELECT COUNT(*) FROM door_effects WHERE applied=1"
        ).fetchone()[0]
    assert effects == initial_effects
    with open_release(restored, sandbox_door=True) as release:
        assert release.core.identity.get()["instance_id"] == identity
        assert release.core.core_execution is not None
        assert release.handle({"op": "status"})["result"][
            "sandbox_adapter_enabled"
        ] is True
    with sqlite3.connect(restored / "sandbox_world" / "virtual_door.db") as db:
        after = db.execute(
            "SELECT COUNT(*) FROM door_effects WHERE applied=1"
        ).fetchone()[0]
    assert after == initial_effects


def test_h54_while_release_active_snapshot_refuses_without_output(tmp_path):
    source, snap = tmp_path / "source", tmp_path / "snap"
    with open_release(source):
        with pytest.raises(RuntimeError, match="active"):
            create_snapshot(source, snap)
        assert not snap.exists()
    assert create_snapshot(source, snap)["status"] == "SNAPSHOT_CREATED"


def test_h54_never_overwrites_snapshot_or_restored_destination(tmp_path):
    source, snap, restored = (
        tmp_path / "source", tmp_path / "snap", tmp_path / "restored"
    )
    _create_instance(source)
    create_snapshot(source, snap)
    with pytest.raises(FileExistsError):
        create_snapshot(source, snap)
    restore_snapshot(snap, restored)
    sentinel = restored / "restore_sentinel.txt"
    sentinel.write_text("protected", encoding="utf-8")
    with pytest.raises(FileExistsError):
        restore_snapshot(snap, restored)
    assert sentinel.read_text(encoding="utf-8") == "protected"
    assert verify_snapshot(snap)["status"] == "VERIFIED"


def test_h54_corrupted_snapshot_refuses_restore_before_creating_directory(
    tmp_path,
):
    source, snap, restored = (
        tmp_path / "source", tmp_path / "snap", tmp_path / "restored"
    )
    _create_instance(source)
    create_snapshot(source, snap)
    target = snap / "events.jsonl"
    target.write_bytes(target.read_bytes() + b"CORRUPT")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_snapshot(snap)
    with pytest.raises(ValueError, match="hash mismatch"):
        restore_snapshot(snap, restored)
    assert not restored.exists()


def test_h54_rejects_unlabelled_instance_and_symlink_before_snapshot(
    tmp_path,
):
    unlabelled = tmp_path / "unlabelled"
    unlabelled.mkdir()
    (unlabelled / "memory.db").write_bytes(b"unrelated legacy data")
    with pytest.raises(ValueError, match="Unlabeled"):
        create_snapshot(unlabelled, tmp_path / "no-snap")
    assert not (tmp_path / "no-snap").exists()

    source = tmp_path / "source"
    _create_instance(source)
    (source / "external_link").symlink_to(
        unlabelled / "memory.db"
    )
    with pytest.raises(ValueError, match="Non-regular"):
        create_snapshot(source, tmp_path / "no-snap")
    assert not (tmp_path / "no-snap").exists()


def test_h54_legacy_index_migration_only_on_disposable_restored_copy(
    tmp_path,
):
    source, snap, restored = (
        tmp_path / "source", tmp_path / "snap", tmp_path / "restored"
    )
    _, event_id = _create_instance(source)
    create_snapshot(source, snap)
    restore_snapshot(snap, restored)
    raw = EventLog(restored / "events.jsonl")
    index = EventRetrieval(raw, restored / "event_index.db")
    assert index.sync()["status"] == "complete"

    with sqlite3.connect(index.database_file) as conn:
        conn.execute("ALTER TABLE event_index_state DROP COLUMN indexed_count")
        conn.execute("ALTER TABLE event_index_state DROP COLUMN prefix_digest")

    reloaded = EventRetrieval(raw, restored / "event_index.db")
    with sqlite3.connect(reloaded.database_file) as conn:
        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(event_index_state)"
            )
        }
    assert {"prefix_digest", "indexed_count"} <= columns
    assert reloaded.sync()["status"] == "complete"
    assert reloaded.get(event_id)["id"] == event_id
    with sqlite3.connect(reloaded.database_file) as conn:
        row = conn.execute(
            "SELECT prefix_digest, indexed_count FROM event_index_state"
        ).fetchone()
    assert row[0] is not None
    assert row[1] > 0

    assert verify_snapshot(snap)["status"] == "VERIFIED"
    with sqlite3.connect(source / "event_index.db") as conn:
        original_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(event_index_state)"
            )
        }
    assert {"prefix_digest", "indexed_count"} <= original_columns


def test_h54_orphaned_confirmed_is_not_auto_repaired_by_restore(tmp_path):
    source, snap, restored = (
        tmp_path / "source", tmp_path / "snap", tmp_path / "restored"
    )
    _create_instance(source)
    store = MemoryStore(source / "memory.db")
    rogue = "kn_" + str(UUID(int=(4 << 76) | (2 << 62) | 42))
    timestamp = "2026-11-17T12:00:00+00:00"
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO knowledge("
            "public_id, domain, statement, status, created_at, updated_at"
            ") VALUES (?, 'project', 'unverified legacy claim', 'confirmed', ?, ?)",
            (rogue, timestamp, timestamp),
        )
    create_snapshot(source, snap)
    restore_snapshot(snap, restored)
    report = audit_snapshot(
        restored / "memory.db", restored / "events.jsonl",
    )
    assert report["status"] == "degraded"
    assert rogue in report["findings"][
        "confirmed_without_live_closed_support"
    ]["ids"]
    assert rogue in report["findings"][
        "confirmed_without_confirmation_history"
    ]["ids"]
    with sqlite3.connect(restored / "memory.db") as conn:
        status = conn.execute(
            "SELECT status FROM knowledge WHERE public_id=?", (rogue,)
        ).fetchone()[0]
    assert status == "confirmed"
    assert verify_snapshot(snap)["status"] == "VERIFIED"


def test_h54_incomplete_labeled_instance_cannot_be_blessed_as_snapshot(
    tmp_path,
):
    source, snap = tmp_path / "source", tmp_path / "snap"
    _create_instance(source)
    (source / "identity.json").unlink()  # Only disposable test data.
    with pytest.raises(ValueError, match="identity.json"):
        create_snapshot(source, snap)
    assert not snap.exists()


def test_h54_parent_symlink_cannot_hide_nested_snapshot_destination(
    tmp_path,
):
    source = tmp_path / "source"
    _create_instance(source)
    alias = tmp_path / "alias-to-source"
    alias.symlink_to(source, target_is_directory=True)
    inside = source / "nested-snap"
    with pytest.raises(ValueError, match="overlap"):
        create_snapshot(source, alias / "nested-snap")
    assert not inside.exists()


def test_h54_untrusted_manifest_path_is_rejected_before_restore(tmp_path):
    source, snap, restored = (
        tmp_path / "source", tmp_path / "snap", tmp_path / "restored"
    )
    _create_instance(source)
    create_snapshot(source, snap)
    manifest_file = snap / MANIFEST
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["entries"][0]["path"] = "../escape.json"
    manifest_file.write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsafe"):
        verify_snapshot(snap)
    with pytest.raises(ValueError, match="Unsafe"):
        restore_snapshot(snap, restored)
    assert not restored.exists()
    assert not (tmp_path / "escape.json").exists()


def test_h54_torn_original_raw_refused_before_any_snapshot_output(tmp_path):
    source, snap = tmp_path / "source", tmp_path / "snapshot"
    _create_instance(source)
    raw = source / "events.jsonl"
    with raw.open("ab") as handle:
        handle.write(b'{"id":"ev_uncommitted"')  # Disposable torn tail.
    before = raw.read_bytes()
    with pytest.raises(ValueError, match="unterminated"):
        create_snapshot(source, snap)
    assert not snap.exists()
    assert raw.read_bytes() == before
