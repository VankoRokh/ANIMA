"""ANIMA H5.4b: pinned ledger compatibility and read-only legacy triage.

No user instances or migrations. All fixtures under pytest tmp_path. No
existing done/skipped is ever replayed or rewritten by the compatibility tool.
"""

from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_processing import (
    EventProcessingCoordinator, PROCESSOR_NAME, PROCESSOR_VERSION,
)
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore, SCHEMA_VERSION
from anima.memory.processor import MemoryProcessor
from anima.release_v01 import PROTOCOL
from labs.v02_h5_compatibility import analyze_snapshot


T0 = "2026-11-17T12:00:00+00:00"
AS_OF = "2026-11-17T13:00:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def stack(root):
    memory = MemoryStore(root / "memory.db")
    raw = EventLog(root / "events.jsonl")
    links = LinkStore(memory)
    processor = MemoryProcessor(
        memory_store=memory, event_log=raw, link_store=links,
    )
    coordinator = EventProcessingCoordinator(
        memory_store=memory, memory_processor=processor,
        event_log=raw,
    )
    return memory, raw, links, coordinator


def event(number, text="h54b-alpha: sensor tested, calibration confirmed",
          references=None, event_type="conversation.user"):
    return Event(
        event_type,
        {"text": text} if event_type == "conversation.user" else None,
        source="user" if event_type == "conversation.user" else "runtime",
        session_id="session_00000001",
        event_id=uid("ev_", number), timestamp=T0,
        references=references or [],
    )


def processed(root, number=1):
    memory, raw, links, coordinator = stack(root)
    e = event(number)
    raw.write(e)
    r = coordinator.process(e)
    assert r["action"] == "create"
    return memory, raw, links, coordinator, e, r


def analyze(memory, raw):
    return analyze_snapshot(
        memory.database_file, raw.log_file, at=AS_OF,
    )


def test_h54b_clean_current_ledger_is_read_only_and_pinned(tmp_path):
    memory, raw, _links, coordinator, e, r = processed(tmp_path)
    original_db = memory.database_file.read_bytes()
    original_raw = raw.log_file.read_bytes()
    report = analyze(memory, raw)
    assert report["status"] == "NO_ISSUES_DETECTED"
    assert report["base_diagnostic"] == "healthy"
    assert report["compatibility_findings"] == {}
    assert report["processor_ledger"]["name"] == PROCESSOR_NAME
    assert report["processor_ledger"]["version"] == PROCESSOR_VERSION == "1.0"
    assert report["memory_schema"] == SCHEMA_VERSION == 1
    assert report["release_protocol"] == PROTOCOL == "anima.release.v0_1/0.1"
    assert memory.database_file.read_bytes() == original_db
    assert raw.log_file.read_bytes() == original_raw
    assert coordinator.get(e.event_id)["status"] == "done"
    assert memory.source_events(r["memory_id"]) == [e.event_id]


def test_h54b_legacy_about_is_reviewed_not_inherited_or_deleted(tmp_path):
    memory, raw, links, coordinator = stack(tmp_path)
    vega = links.create_entity(
        entity_type="object", canonical_name="Vega",
        public_id=uid("ent_", 91),
    )["id"]
    orion = links.create_entity(
        entity_type="object", canonical_name="Orion",
        public_id=uid("ent_", 92),
    )["id"]
    original = event(
        101, "h54b-alpha: sensor tested, calibration confirmed",
        [{"kind": "entity", "id": vega}],
    )
    raw.write(original)
    first = coordinator.process(original)
    assert first["action"] == "create"
    # Represent an old auto-created about link. It has provenance but no
    # explicit authority-token field; it may also be legitimately reviewed.
    legacy = links.create_relation(
        source_kind="memory", source_id=first["memory_id"],
        relation_type="about", target_kind="entity", target_id=vega,
        source_memory_id=first["memory_id"], created_at=T0,
    )
    before = memory.database_file.read_bytes()
    report = analyze(memory, raw)
    assert report["status"] == "REVIEW_REQUIRED"
    assert legacy["id"] in report["compatibility_findings"][
        "legacy_about_authority_unverifiable"
    ]["ids"]
    assert memory.database_file.read_bytes() == before

    # A pinned done row must not be reprocessed under H4.
    restarted = stack(tmp_path)[3]
    old = restarted.process(original)
    assert old["action"] == "already_done"
    assert old["memory_id"] == first["memory_id"]
    assert restarted.recover() == {
        "adopted": 0, "retried": 0, "finalized": 1,
    }
    assert links.get_relation(legacy["id"]) is not None

    # The new claim must not inherit the old about or overwrite a mixed ID.
    next_event = event(
        102, "h54b-alpha: sensor tested, calibration confirmed",
        [{"kind": "entity", "id": orion}],
    )
    raw.write(next_event)
    second = restarted.process(next_event)
    assert second["action"] == "create"
    assert second["memory_id"] != first["memory_id"]
    assert memory.count() == 2
    assert links.relations_for(
        "memory", second["memory_id"], direction="outgoing",
        relation_types={"about"},
    ) == []
    assert links.get_relation(legacy["id"])["target_id"] == vega


def test_h54b_old_processor_version_without_duplicate_requires_review(
    tmp_path,
):
    memory, raw, _links, _coordinator, e, _r = processed(tmp_path)
    with memory.transaction() as conn:
        conn.execute(
            "UPDATE event_processing SET processor_version='0.9' "
            "WHERE event_id=?", (e.event_id,),
        )
    before = memory.database_file.read_bytes()
    report = analyze(memory, raw)
    assert report["status"] == "REVIEW_REQUIRED"
    assert e.event_id in report["compatibility_findings"][
        "other_memory_processor_version"
    ]["ids"]
    assert e.event_id in report["compatibility_findings"][
        "source_without_current_processing_row"
    ]["ids"]
    assert memory.database_file.read_bytes() == before


def test_h54b_same_event_across_two_versions_is_blocked(tmp_path):
    memory, raw, _links, _coordinator, e, _r = processed(tmp_path)
    with memory.transaction() as conn:
        conn.execute(
            "INSERT INTO event_processing("
            "event_id, processor, processor_version, status, attempts,"
            "started_at, finished_at, last_error"
            ") VALUES (?, ?, '2.0', 'done', 1, ?, ?, NULL)",
            (e.event_id, PROCESSOR_NAME, T0, T0),
        )
    report = analyze(memory, raw)
    assert report["status"] == "BLOCKED"
    assert e.event_id in report["compatibility_findings"][
        "event_processed_under_multiple_versions"
    ]["ids"]


def test_h54b_done_without_source_is_blocked(tmp_path):
    memory, raw, _links, _coordinator, e, _r = processed(tmp_path)
    with memory.transaction() as conn:
        conn.execute(
            "DELETE FROM memory_sources WHERE event_id=?", (e.event_id,),
        )
    report = analyze(memory, raw)
    assert report["status"] == "BLOCKED"
    assert e.event_id in report["compatibility_findings"][
        "done_without_source"
    ]["ids"]


def test_h54b_skipped_with_memory_source_is_blocked(tmp_path):
    memory, raw, _links, coordinator = stack(tmp_path)
    wake = event(201, event_type="system.wake")
    raw.write(wake)
    skipped = coordinator.process(wake)
    assert skipped["action"] == "skip"
    # Deliberately inject a legacy source mapping, not a real projection.
    memory.create_memory(
        memory_type="episodic", domain="user", status="closed",
        content="incompatible legacy source", importance=1,
        created_at=T0, source_event_id=wake.event_id,
    )
    report = analyze(memory, raw)
    assert report["status"] == "BLOCKED"
    assert wake.event_id in report["compatibility_findings"][
        "skipped_with_source"
    ]["ids"]


def test_h54b_pending_row_with_committed_effect_is_blocked(tmp_path):
    memory, raw, _links, _coordinator, e, _r = processed(tmp_path)
    with memory.transaction() as conn:
        conn.execute(
            "UPDATE event_processing SET status='pending',"
            "finished_at=NULL WHERE event_id=?", (e.event_id,),
        )
    report = analyze(memory, raw)
    assert report["status"] == "BLOCKED"
    assert e.event_id in report["compatibility_findings"][
        "unfinished_with_committed_source"
    ]["ids"]


def test_h54b_pending_ledger_without_raw_is_blocked(tmp_path):
    memory, raw, _links, _coordinator, _e, _r = processed(tmp_path)
    missing_id = uid("ev_", 999)
    with memory.transaction() as conn:
        conn.execute(
            "INSERT INTO event_processing("
            "event_id, processor, processor_version, status, attempts,"
            "started_at, finished_at, last_error"
            ") VALUES (?, ?, ?, 'pending', 0, NULL, NULL, NULL)",
            (missing_id, PROCESSOR_NAME, PROCESSOR_VERSION),
        )
    report = analyze(memory, raw)
    assert report["status"] == "BLOCKED"
    assert missing_id in report["compatibility_findings"][
        "processor_row_missing_raw"
    ]["ids"]
