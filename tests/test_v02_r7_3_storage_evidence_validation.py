"""R7.3 — H56-04 and H56-05 negative storage/Knowledge gates.

All SQL corruption happens only under pytest tmp_path. Tests never open or
mutate a real legacy instance. R7.3 does not attempt schema migration/repair.
"""

import hashlib
import sqlite3
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.memory_store import MemoryStore, SCHEMA_VERSION
from labs.v02_h5_legacy_diagnostic import audit_snapshot


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"
T7 = "2020-01-01T00:07:00+00:00"
T8 = "2020-01-01T00:08:00+00:00"
T9 = "2020-01-01T00:09:00+00:00"


def uid(prefix, n):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | n))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_names(path):
    with sqlite3.connect(path) as connection:
        return {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


@pytest.mark.parametrize("version", ["999", "2", "-1", "future-schema"])
def test_r73_h5604_unknown_schema_has_zero_ddl_side_effects(tmp_path, version):
    db = tmp_path / "memory.db"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (version,),
        )
        connection.execute(
            "CREATE TABLE user_fixture(marker TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO user_fixture(marker) VALUES('must-survive')"
        )
    original_sha, original_tables = sha(db), table_names(db)

    with pytest.raises(ValueError, match="Unsupported memory database schema"):
        MemoryStore(db)

    assert sha(db) == original_sha
    assert table_names(db) == original_tables
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == version
        assert connection.execute(
            "SELECT marker FROM user_fixture"
        ).fetchone()[0] == "must-survive"


def test_r73_h5604_existing_supported_schema_reopens_without_damage(tmp_path):
    db = tmp_path / "memory.db"
    first = MemoryStore(db)
    assert first.schema_version() == SCHEMA_VERSION
    prior_tables = table_names(db)
    reopened = MemoryStore(db)
    assert reopened.schema_version() == SCHEMA_VERSION
    assert table_names(db) == prior_tables


def test_r73_h5604_new_database_bootstraps_full_schema_and_triggers(tmp_path):
    db = tmp_path / "memory.db"
    assert not db.exists()
    store = MemoryStore(db)
    assert store.schema_version() == SCHEMA_VERSION
    tables = table_names(db)
    assert {"memories", "memory_sources", "knowledge",
            "relations", "history", "memory_fts", "knowledge_fts"} <= tables
    with sqlite3.connect(db) as connection:
        triggers = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
    assert {"memories_fts_insert", "memories_fts_update",
            "memories_fts_delete", "knowledge_fts_insert",
            "knowledge_fts_update", "knowledge_fts_delete"} <= triggers


def test_r73_h5604_failed_bootstrap_rolls_back_existing_partial_schema(tmp_path):
    db = tmp_path / "memory.db"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_meta VALUES ('schema_version', '1')"
        )
        # This user-created table deliberately conflicts with canonical
        # CREATE INDEX: no column named 'status'.
        connection.execute("CREATE TABLE memories(unexpected TEXT)")
    before_tables = table_names(db)
    before_sha = sha(db)

    with pytest.raises(ValueError, match="Cannot initialize memory database"):
        MemoryStore(db)
    assert table_names(db) == before_tables
    assert sha(db) == before_sha


def closed_source(core, number):
    event = Event(
        "conversation.user",
        {"text": f"r73-evidence-{number}: independent observation"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", number),
        timestamp=T0,
    )
    core.event_log.write(event)
    return core.memory_store.create_memory(
        memory_type="episodic", domain="user", status="closed",
        content=event.payload["text"], created_at=T0,
        public_id=uid("mem_", number),
        source_event_id=event.event_id,
    )["id"]


def stack(root):
    core = build_core(root)
    a, b, c, d = [
        closed_source(core, number) for number in (7301, 7302, 7303, 7304)
    ]
    layer = KnowledgeLayer(memory_store=core.memory_store)
    kn = layer.create_candidate(
        domain="user", statement="R7.3 positive baseline",
        source_memory_id=a,
        created_at=T2, public_id=uid("kn_", 7301),
    )["knowledge"]["id"]
    return core, layer, kn, a, b, c, d


def mutate_interval(core, relation_id, end):
    with core.memory_store.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE relations SET valid_until=? WHERE public_id=?",
            (end, relation_id),
        )


def future_support(core, kn, c, *, start=T8, end=T9):
    return core.link_store.create_relation(
        source_kind="memory", source_id=c,
        relation_type="supports",
        target_kind="knowledge", target_id=kn,
        created_at=start, valid_until=end,
    )


def state(core, layer, kn):
    with core.memory_store.transaction() as connection:
        related = [
            tuple(row) for row in connection.execute(
                "SELECT public_id, created_at, valid_until, source_memory_id "
                "FROM relations WHERE target_kind='knowledge' AND target_id=? "
                "ORDER BY row_id", (kn,),
            )
        ]
    return {
        "knowledge": layer.get(kn),
        "history": layer.history(kn),
        "relations": related,
        "raw": core.event_log.log_file.read_bytes(),
    }


@pytest.mark.parametrize("end", [T7, T8, "2020-01-01T00:07:00"])
@pytest.mark.parametrize("explicit", [False, True], ids=["implicit", "explicit"])
def test_r73_h5605_confirm_rejects_corrupted_dormant_support(
    tmp_path, end, explicit,
):
    core, layer, kn, a, b, c, d = stack(tmp_path)
    bad = future_support(core, kn, c)
    mutate_interval(core, bad["id"], end)
    before = state(core, layer, kn)

    with pytest.raises(ValueError, match="Knowledge evidence|interval|UTC offset"):
        layer.confirm(
            kn, confirmed_at=T3, **({"source_memory_id": a} if explicit else {}),
        )

    assert state(core, layer, kn) == before
    assert layer.get(kn)["status"] == "provisional"
    report = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file, at=T3,
    )
    assert report["status"] == "degraded"
    finding_name = (
        "invalid_relation_timestamp"
        if end.endswith("00:07:00") else "invalid_relation_interval"
    )
    assert bad["id"] in report["findings"][finding_name]["ids"]


@pytest.mark.parametrize("end", [T7, T8, "2020-01-01T00:09:00"])
def test_r73_public_evidence_writer_refuses_invalid_intervals(tmp_path, end):
    core, layer, kn, a, b, c, d = stack(tmp_path)
    before = state(core, layer, kn)
    with pytest.raises(ValueError, match="Knowledge evidence|UTC offset"):
        core.link_store.create_relation(
            source_kind="memory", source_id=c,
            relation_type="supports", target_kind="knowledge", target_id=kn,
            created_at=T8, valid_until=end,
        )
    assert state(core, layer, kn) == before


@pytest.mark.parametrize("transition", ["challenge", "reject", "supersede"])
def test_r73_h5605_all_terminal_transitions_fail_closed_with_bad_history(
    tmp_path, transition,
):
    core, layer, kn, a, b, c, d = stack(tmp_path)
    layer.confirm(kn, confirmed_at=T3)
    if transition in {"reject", "supersede"}:
        layer.challenge(kn, b, challenged_at=T4)

    # Deliberate SQL-only legacy corruption of a published claim. Ordinary
    # LinkStore refuses new Evidence on published Knowledge (R6.1).
    bad_id = uid("rel_", 7399)
    with core.memory_store.transaction(immediate=True) as conn:
        conn.execute(
            """
            INSERT INTO relations(
                public_id, source_kind, source_id, relation_type,
                target_kind, target_id, created_at, valid_until,
                source_memory_id
            ) VALUES (?, 'memory', ?, 'supports',
                      'knowledge', ?, ?, ?, ?)
            """,
            (bad_id, c, kn, T8, T7, c),
        )
    before = state(core, layer, kn)
    kwargs = {
        "challenge": lambda: layer.challenge(kn, b, challenged_at=T5),
        "reject": lambda: layer.reject(kn, rejected_at=T5),
        "supersede": lambda: layer.supersede(
            kn, statement="R7.3 new assertion", source_memory_id=d,
            superseded_at=T5, public_id=uid("kn_", 7309),
        ),
    }

    with pytest.raises(ValueError, match="Invalid Knowledge evidence relation interval"):
        kwargs[transition]()

    assert state(core, layer, kn) == before
    if transition == "supersede":
        assert layer.get(uid("kn_", 7309)) is None


def test_r73_valid_future_evidence_keeps_half_open_interval(tmp_path):
    core, layer, kn, a, b, c, d = stack(tmp_path)
    support = future_support(core, kn, c, start=T8, end=T9)
    result = layer.confirm(kn, confirmed_at=T3)
    assert result["knowledge"]["status"] == "confirmed"
    with core.memory_store.transaction() as connection:
        row = connection.execute(
            "SELECT created_at, valid_until FROM relations WHERE public_id=?",
            (support["id"],),
        ).fetchone()
    assert row["created_at"] == T8
    assert row["valid_until"] == T9


def test_r73_valid_offset_equivalent_interval_accepted(tmp_path):
    core, layer, kn, a, b, c, d = stack(tmp_path)
    support = future_support(
        core, kn, c,
        start="2020-01-01T11:08:00+11:00",
        end="2020-01-01T02:09:00+02:00",
    )
    assert layer.confirm(kn, confirmed_at=T3)["knowledge"]["status"] == "confirmed"
    assert support["valid_until"] == "2020-01-01T02:09:00+02:00"
