"""v0.2 H1.3 optimized prefix digest: trust, migration, and rollback.

All mutations affect disposable tmp_path data. This test suite verifies the
new prefix digest is not fabricated from an unverified preexisting index.
"""

import sqlite3
from hashlib import sha256
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_retrieval import EventRetrieval


STAMP = "2026-11-17T12:00:00+00:00"


def ev(i, *, text=None):
    return Event(
        "conversation.user",
        {"text": text or f"digestmarker event {i:04d} " + ("x" * 1024)},
        source="user",
        timestamp=STAMP,
        event_id=f"ev_{UUID(int=(4 << 76) | (2 << 62) | i)}",
    )


def make_stack(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    index = EventRetrieval(log, tmp_path / "event_index.db")
    return log, index


def state(index):
    with sqlite3.connect(index.database_file) as conn:
        return conn.execute(
            "SELECT cursor, prefix_digest, indexed_count "
            "FROM event_index_state WHERE singleton=1"
        ).fetchone()


def fill(log, n=20):
    for i in range(1, n + 1):
        log.write(ev(i))


def check_digest(log, index):
    cursor, digest, n = state(index)
    assert cursor > 0
    assert digest == sha256(log.log_file.read_bytes()[:cursor]).hexdigest()
    assert n == index.status()["indexed_events"]


def test_h1_3_digest_matches_byte_exact_prefix_and_row_count(tmp_path):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    assert index.sync()["status"] == "complete"
    check_digest(log, index)

    # Cached partial hasher must keep the hash of old prefix + new bytes.
    log.write(ev(21))
    assert index.sync()["status"] == "complete"
    check_digest(log, index)


def test_h1_3_digest_survives_reopen_and_append(tmp_path):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    index.sync()
    old_digest = state(index)[1]
    restarted = EventRetrieval(log, index.database_file)
    log.write(ev(21))
    assert restarted.sync()["status"] == "complete"
    assert state(restarted)[1] != old_digest
    check_digest(log, restarted)


def test_h1_3_legacy_index_schema_is_migrated_without_rebuild(tmp_path):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    index.sync()
    # Reconstruct the previous index-state schema without the two v0.2
    # optimization fields. Index and Event bytes themselves stay intact.
    with sqlite3.connect(index.database_file) as conn:
        if sqlite3.sqlite_version_info < (3, 35, 0):
            pytest.skip("SQLite DROP COLUMN requires >=3.35")
        conn.execute("ALTER TABLE event_index_state DROP COLUMN indexed_count")
        conn.execute("ALTER TABLE event_index_state DROP COLUMN prefix_digest")
    legacy = EventRetrieval(log, index.database_file)
    with sqlite3.connect(legacy.database_file) as conn:
        column_names = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(event_index_state)"
            )
        }
    assert {"prefix_digest", "indexed_count"} <= column_names
    assert state(legacy)[1:] == (None, None)
    log.write(ev(21))
    assert legacy.sync()["status"] == "complete"
    check_digest(log, legacy)


def test_h1_3_migrating_null_digest_first_rechecks_each_old_row(tmp_path):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    index.sync()
    with sqlite3.connect(index.database_file) as conn:
        conn.execute(
            "UPDATE event_index_state "
            "SET prefix_digest=NULL, indexed_count=NULL WHERE singleton=1"
        )
    restarted = EventRetrieval(log, index.database_file)
    log.write(ev(21))
    assert restarted.sync()["status"] == "complete"
    check_digest(log, restarted)


def test_h1_3_migrating_null_digest_rejects_historical_edit(tmp_path):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    index.sync()
    with sqlite3.connect(index.database_file) as conn:
        conn.execute(
            "UPDATE event_index_state "
            "SET prefix_digest=NULL, indexed_count=NULL WHERE singleton=1"
        )
    restarted = EventRetrieval(log, index.database_file)
    raw = log.log_file.read_bytes()
    assert raw.count(b"digestmarker event 0010") == 1
    log.log_file.write_bytes(
        raw.replace(b"digestmarker event 0010",
                    b"editedmarker event 0010", 1)
    )
    log.write(ev(21))
    with pytest.raises(ValueError, match="Indexed EventLog prefix changed"):
        restarted.sync()
    assert state(restarted)[1] is None


def test_h1_3_digest_detects_middle_edit_before_new_checkpoint(tmp_path):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    index.sync()
    old_state = state(index)
    raw = log.log_file.read_bytes()
    assert raw.count(b"digestmarker event 0010") == 1
    log.log_file.write_bytes(
        raw.replace(b"digestmarker event 0010",
                    b"editedmarker event 0010", 1)
    )
    log.write(ev(21))
    with pytest.raises(ValueError, match="Indexed EventLog prefix changed"):
        index.sync()
    assert state(index) == old_state


def test_h1_3_digest_detects_row_deletion_before_append(tmp_path):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    index.sync()
    old_state = state(index)
    with sqlite3.connect(index.database_file) as conn:
        conn.execute(
            "DELETE FROM indexed_events WHERE event_id=?",
            (ev(10).event_id,),
        )
    log.write(ev(21))
    with pytest.raises(ValueError, match="locator count mismatch"):
        index.sync()
    assert state(index) == old_state


def test_h1_3_rebuild_clears_digest_and_next_sync_rebuilds(tmp_path):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    index.sync()
    assert state(index)[1] is not None
    rebuilt = index.rebuild()
    assert rebuilt["indexed_events"] == 0
    assert state(index) == (0, None, 0)
    assert index.sync()["status"] == "complete"
    check_digest(log, index)


def test_h1_3_unchanged_backlog_uses_cached_hash_state(tmp_path, monkeypatch):
    log, index = make_stack(tmp_path)
    fill(log, n=20)
    first = index.sync(max_events=3)
    assert first["status"] == "partial"

    def cannot_rehash(*_args):
        raise AssertionError("Unchanged file need not be rehashed for catch-up")

    monkeypatch.setattr(index, "_hash_indexed_prefix", cannot_rehash)
    for _ in range(20):
        result = index.sync(max_events=3)
        if result["status"] == "complete":
            break
    else:
        raise RuntimeError("Index never caught up")
    check_digest(log, index)
