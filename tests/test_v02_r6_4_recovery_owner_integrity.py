"""R6.4 / NEW-06: dangling memory_sources may not finalize or replay Events.

All damage is deliberate on temporary SQLite databases under pytest tmp_path
with a separate connection and PRAGMA foreign_keys=OFF. No production data,
repair, ledger rewrite or implicit reprocessing is used.
"""

import sqlite3
from contextlib import closing
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from labs.v02_h5_compatibility import analyze_snapshot
from labs.v02_h5_legacy_diagnostic import audit_snapshot


T0 = "2020-01-01T00:00:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def event(number, *, text=None, kind="conversation.user"):
    return Event(
        kind,
        {"text": text or f"r64owner: independent observation {number}"}
        if kind == "conversation.user" else None,
        source="user" if kind == "conversation.user" else "runtime",
        session_id="session_00000001",
        timestamp=T0,
        event_id=uid("ev_", number),
    )


def projection(root, number=4101):
    core = build_core(root)
    item = event(number)
    core.event_log.write(item)
    result = core.event_processing.process(item)
    assert result["action"] == "create"
    assert core.event_processing.get(item.event_id)["status"] == "done"
    return core, item, result["memory_id"]


def orphan_source_owner(core, memory_id):
    """Only a disposable DB: deliberately simulate noncooperative SQL."""
    with closing(sqlite3.connect(core.memory_store.database_file)) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        cursor = conn.execute(
            "DELETE FROM memories WHERE public_id = ?", (memory_id,),
        )
        assert cursor.rowcount == 1
        conn.commit()


def inject_orphan_source(core, event_id, memory_id):
    with closing(sqlite3.connect(core.memory_store.database_file)) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT INTO memory_sources(memory_id, event_id) VALUES (?, ?)",
            (memory_id, event_id),
        )
        conn.commit()


def assert_dangling(core, event_id, memory_id):
    assert core.memory_store.get_memory(memory_id) is None
    with core.memory_store.transaction() as conn:
        mapping = conn.execute(
            "SELECT memory_id FROM memory_sources WHERE event_id=?",
            (event_id,),
        ).fetchall()
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert any(row["memory_id"] == memory_id for row in mapping)
    assert violations


def test_r64_recover_refuses_orphan_owner_before_adopting_other_events(tmp_path):
    core, done_event, memory_id = projection(tmp_path)
    new_event = event(4102)
    core.event_log.write(new_event)
    orphan_source_owner(core, memory_id)
    assert_dangling(core, done_event.event_id, memory_id)

    before_ledger = core.event_processing.get(done_event.event_id)
    before_raw = core.event_log.log_file.read_bytes()
    before_db = core.memory_store.database_file.read_bytes()
    for _ in range(2):
        with pytest.raises(ValueError, match="missing Memory source owner"):
            core.event_processing.recover()

    assert core.event_processing.get(done_event.event_id) == before_ledger
    assert core.event_processing.get(new_event.event_id) is None
    assert core.memory_store.database_file.read_bytes() == before_db
    assert core.event_log.log_file.read_bytes() == before_raw
    assert core.memory_store.count() == 0


def test_r64_direct_done_replay_refuses_orphan_owner_without_side_effects(
    tmp_path,
):
    core, done_event, memory_id = projection(tmp_path)
    orphan_source_owner(core, memory_id)
    before_ledger = core.event_processing.get(done_event.event_id)
    before_raw = core.event_log.log_file.read_bytes()
    with pytest.raises(ValueError, match="Memory source owner missing"):
        core.event_processing.process(done_event)
    assert core.event_processing.get(done_event.event_id) == before_ledger
    assert core.event_log.log_file.read_bytes() == before_raw
    assert_dangling(core, done_event.event_id, memory_id)


def test_r64_reopened_coordinator_cannot_replay_corrupted_done(tmp_path):
    core, done_event, memory_id = projection(tmp_path)
    orphan_source_owner(core, memory_id)
    reopened = build_core(tmp_path)
    assert reopened.event_processing.get(done_event.event_id)["status"] == "done"
    with pytest.raises(ValueError, match="Memory source owner missing"):
        reopened.event_processing.process(done_event)
    with pytest.raises(ValueError, match="missing Memory source owner"):
        reopened.event_processing.recover()
    assert reopened.memory_store.count() == 0


def test_r64_mixed_valid_and_orphan_sources_are_not_accepted(tmp_path):
    core, done_event, valid_memory_id = projection(tmp_path)
    ghost_memory_id = uid("mem_", 4199)
    inject_orphan_source(core, done_event.event_id, ghost_memory_id)
    assert core.memory_store.get_memory(valid_memory_id) is not None
    assert_dangling(core, done_event.event_id, ghost_memory_id)
    before = core.event_processing.get(done_event.event_id)

    with pytest.raises(ValueError, match="missing Memory source owner"):
        core.event_processing.recover()
    with pytest.raises(ValueError, match="Memory source owner missing"):
        core.event_processing.process(done_event)

    assert core.event_processing.get(done_event.event_id) == before
    assert core.memory_store.get_memory(valid_memory_id) is not None


def test_r64_legacy_adoption_refuses_orphan_source_without_ledger(tmp_path):
    core = build_core(tmp_path)
    legacy_event = event(4201)
    core.event_log.write(legacy_event)
    memory_id = core.memory_store.create_memory(
        memory_type="episodic", domain="user", status="open",
        content="r64owner legacy projection", created_at=T0,
        source_event_id=legacy_event.event_id,
        public_id=uid("mem_", 4201),
    )["id"]
    assert core.event_processing.get(legacy_event.event_id) is None
    orphan_source_owner(core, memory_id)
    raw_before = core.event_log.log_file.read_bytes()

    with pytest.raises(ValueError, match="Memory source owner missing"):
        core.event_processing.recover()
    assert core.event_processing.get(legacy_event.event_id) is None
    assert core.event_log.log_file.read_bytes() == raw_before
    assert_dangling(core, legacy_event.event_id, memory_id)


def test_r64_existing_valid_done_still_replays_and_recovers(tmp_path):
    core, done_event, memory_id = projection(tmp_path)
    replay = core.event_processing.process(done_event)
    assert replay["action"] == "already_done"
    assert replay["memory_id"] == memory_id
    recovery = core.event_processing.recover()
    assert recovery["retried"] == 0
    assert recovery["finalized"] == 1
    assert core.event_processing.get(done_event.event_id)["attempts"] == 1


def test_r64_existing_valid_legacy_adoption_still_works(tmp_path):
    core = build_core(tmp_path)
    legacy_event = event(4202)
    core.event_log.write(legacy_event)
    memory_id = core.memory_store.create_memory(
        memory_type="episodic", domain="user", status="open",
        content="r64owner valid legacy projection", created_at=T0,
        public_id=uid("mem_", 4202),
        source_event_id=legacy_event.event_id,
    )["id"]
    recovery = core.event_processing.recover()
    assert recovery["adopted"] == 1
    assert core.event_processing.get(legacy_event.event_id)["status"] == "done"
    assert core.event_processing.process(legacy_event)["memory_id"] == memory_id


def test_r64_skipped_event_still_requires_no_memory(tmp_path):
    core = build_core(tmp_path)
    skipped = event(4203, kind="system.wake")
    core.event_log.write(skipped)
    assert core.event_processing.process(skipped)["action"] == "skip"
    assert core.event_processing.recover()["finalized"] == 1
    assert core.event_processing.process(skipped)["action"] == "skip"
    assert core.memory_store.count() == 0


def test_r64_offline_diagnostic_detects_orphan_and_blocks(tmp_path):
    core, done_event, memory_id = projection(tmp_path)
    orphan_source_owner(core, memory_id)
    report = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert report["status"] == "degraded"
    assert memory_id in report["findings"]["orphan_memory_source_owner"]["ids"]
    compatibility = analyze_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert compatibility["status"] == "BLOCKED"
    assert core.event_processing.get(done_event.event_id)["status"] == "done"
