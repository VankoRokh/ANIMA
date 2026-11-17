"""ANIMA v0.2 / H0: R1-S1 negative regression baseline (N1-N9).

These tests express TARGET invariants, not the current v0.1 behavior.
Each test is marked strict XFAIL while the defect is known to exist.
On a successful fix, REMOVE its xfail marker; an XPASS is an intentional
release gate, not an ordinary green test.

All data is created under pytest's tmp_path. N6/N7/N9 intentionally corrupt
ONLY disposable, temporary copies of the EventLog. No production data touched.

Source: R1-S1 Structural Memory Audit, snapshot
b461a51a6349c8d18dd27da423f1bcac0811eb99.
"""

import json
import sqlite3
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_retrieval import EventRetrieval
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.memory.retrieval import RetrievalEngine
from anima.release_v01 import open_release


T0 = "2026-11-17T12:00:00+00:00"
T1 = "2026-11-17T12:01:00+00:00"
T2 = "2026-11-17T12:02:00+00:00"
YEAR_2020 = "2020-01-01T00:00:00+00:00"
YEAR_2021 = "2021-01-01T00:00:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def event(number, text, *, references=None, timestamp=T0):
    return Event(
        "conversation.user", {"text": text}, source="user",
        session_id="session_00000001", references=references or [],
        event_id=uid("ev_", number), timestamp=timestamp,
    )


def _stack(root):
    store = MemoryStore(root / "memory.db")
    log = EventLog(root / "events.jsonl")
    links = LinkStore(store)
    processor = MemoryProcessor(memory_store=store, event_log=log, link_store=links)
    return store, log, links, processor


def _memory(store, number, content, *, status="open", timestamp=T0):
    return store.create_memory(
        memory_type="episodic", domain="project", content=content,
        status=status, importance=1, created_at=timestamp,
        public_id=uid("mem_", number), source_event_id=uid("ev_", number),
    )


# N1: text similarity alone must not merge explicitly disjoint object histories.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="R1-S1 N1: cross-entity merge")
def test_h0_n1_disjoint_registered_entities_do_not_merge(tmp_path):
    store, log, links, processor = _stack(tmp_path)
    vega = uid("ent_", 1001)
    orion = uid("ent_", 1002)
    links.create_entity(entity_type="object", canonical_name="Vega", public_id=vega)
    links.create_entity(entity_type="object", canonical_name="Orion", public_id=orion)
    a = event(101, "Контроллер Vega сообщил о перегреве датчика температуры.",
              references=[{"kind": "entity", "id": vega}])
    b = event(102, "Контроллер Orion сообщил о перегреве датчика температуры.",
              references=[{"kind": "entity", "id": orion}], timestamp=T1)
    log.write(a)
    first = processor.process_event(a)
    log.write(b)
    second = processor.process_event(b)
    assert first["memory_id"] != second["memory_id"], (
        "Explicitly disjoint object histories were merged into one Memory"
    )


# N2: existence is not a license to publish about an inactive entity.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="R1-S1 N2: inactive entity accepted")
def test_h0_n2_inactive_entity_reference_is_not_published_as_current(tmp_path):
    _, log, links, processor = _stack(tmp_path)
    inactive = uid("ent_", 2001)
    links.create_entity(entity_type="object", canonical_name="Orion",
                        status="inactive", public_id=inactive)
    wrong = event(201, "Контроллер Vega исправен.",
                  references=[{"kind": "entity", "id": inactive}])
    log.write(wrong)
    try:
        outcome = processor.process_event(wrong)
    except ValueError:
        return
    relations = links.relations_for("memory", outcome["memory_id"],
                                    direction="outgoing", relation_types={"about"})
    assert not any(r["target_id"] == inactive and r["valid_until"] is None
                   for r in relations), "Unverified inactive ID published as current about"


# N3: direct base API must not materialize confirmed Knowledge without evidence.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="R1-S1 N3: direct confirmed writer")
def test_h0_n3_unbacked_confirmed_knowledge_is_rejected(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    try:
        links.create_knowledge(domain="project", statement="Unbacked fact",
                               status="confirmed")
    except ValueError:
        return
    assert False, "Confirmed Knowledge created with no evidence and no lifecycle history"


# N4: removing a supporting Memory must not leave live orphan evidence.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="R1-S1 N4: orphan evidence")
def test_h0_n4_delete_memory_rejects_or_invalidates_live_support(tmp_path):
    store, _log, links, _processor = _stack(tmp_path)
    memory = _memory(store, 401, "Evidence for a provisional hypothesis")
    knowledge = links.create_knowledge(domain="project", statement="Hypothesis",
                                        status="provisional", created_at=T1)
    relation = links.create_relation(
        source_kind="memory", source_id=memory["id"], relation_type="supports",
        target_kind="knowledge", target_id=knowledge["id"], created_at=T1,
    )
    try:
        store.delete_memory(memory["id"])
    except (ValueError, sqlite3.IntegrityError):
        return
    remains = links.get_relation(relation["id"])
    assert not (store.get_memory(memory["id"]) is None and remains is not None
                and remains["valid_until"] is None), (
        "Deleted Memory left a live supports relation referencing it"
    )


# N5: expired relation should not be returned as a current entity match.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="R1-S1 N5: expired about included")
def test_h0_n5_expired_relation_is_not_current_retrieval(tmp_path):
    store, _log, links, _processor = _stack(tmp_path)
    memory = _memory(store, 501, "A historical thermal condition", timestamp=YEAR_2020)
    entity_id = uid("ent_", 5001)
    links.create_entity(entity_type="object", canonical_name="OldController", public_id=entity_id)
    links.create_relation(
        source_kind="memory", source_id=memory["id"], relation_type="about",
        target_kind="entity", target_id=entity_id,
        created_at=YEAR_2020, valid_until=YEAR_2021,
    )
    engine = RetrievalEngine(memory_store=store, link_store=links)
    current = engine.retrieve(entity_ids=[entity_id], kinds=("memory",), top_k=10)
    assert memory["id"] not in {r["id"] for r in current["results"]}, (
        "Historical about relation was returned as a current link"
    )


# N6: mutating middle of an indexed prefix then appending must not yield complete.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="R1-S1 N6: middle-prefix mutation hidden")
def test_h0_n6_middle_of_indexed_eventlog_is_not_silently_trusted(tmp_path):
    store, log, _links, _processor = _stack(tmp_path)
    for i in range(32):
        marker = "needleaaaa" if i == 16 else f"othermarker{i:02d}"
        log.write(event(600 + i, marker + " " + "x" * 1000))
    index = EventRetrieval(log, tmp_path / "event_index.db", memory_store=store)
    before = index.sync(max_events=128, max_bytes=2_000_000)
    if before["status"] != "complete":
        raise RuntimeError("N6 fixture: baseline index did not reach complete")
    path = log.log_file
    data = path.read_bytes()
    if data.count(b"needleaaaa") != 1:
        raise RuntimeError("N6 fixture: expected exactly one corruption marker")
    path.write_bytes(data.replace(b"needleaaaa", b"needlebbbb", 1))
    log.write(event(699, "new event after changed prefix"))
    try:
        after = index.sync(max_events=128, max_bytes=2_000_000)
    except (ValueError, RuntimeError):
        return
    assert after["status"] != "complete", (
        "Index declared complete after an undetected rewrite of indexed bytes"
    )


# N7: a syntactically valid JSON without final LF is an incomplete JSONL record.
def test_h0_n7_unterminated_jsonl_is_not_accepted_as_complete(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.write(event(701, "valid JSON but incomplete JSONL record"))
    raw = log.log_file.read_bytes()
    assert raw.endswith(b"\n")
    log.log_file.write_bytes(raw[:-1])
    try:
        log.load_events()
    except ValueError:
        return
    assert False, "Raw loader accepted an unterminated trailing JSONL record"


# N8: terminal FTS matches must not consume the entire pre-filter seed window.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="R1-S1 N8: FTS seeds exhausted")
def test_h0_n8_merged_fts_candidates_do_not_hide_open_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    for i in range(25):
        _memory(store, 800 + i, "filtermarker legacy entry", status="merged")
    live = _memory(store, 899, "filtermarker current entry", status="open")
    engine = RetrievalEngine(memory_store=store, link_store=links)
    result = engine.retrieve("filtermarker", kinds=("memory",), top_k=10)
    assert live["id"] in {item["id"] for item in result["results"]}, (
        "An open Memory was lost behind 25 terminal FTS seeds"
    )


# N9: a finalized but missing raw source must not appear as healthy/complete.
def test_h0_n9_missing_finalized_raw_is_not_silent_after_reopen(tmp_path):
    with open_release(tmp_path) as instance:
        report = instance.handle({"op": "report", "text": "h0n9marker unique incident"})
        source_id = report["event_ids"][0]
    path = tmp_path / "events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if json.loads(line)["id"] != source_id]
    if len(kept) != len(lines) - 1:
        raise RuntimeError("N9 fixture: report raw event not found exactly once")
    path.write_text("".join(kept), encoding="utf-8")
    try:
        with open_release(tmp_path) as instance:
            searched = instance.handle({"op": "search_events", "query": "h0n9marker"})
            context = instance.handle({"op": "context", "query": "h0n9marker"})
    except (ValueError, RuntimeError):
        return
    coverage = searched["result"]["coverage"]["status"]
    raw_ids = {r["id"] for r in searched["result"]["results"]}
    derived = context["result"]["memories"]
    assert not (coverage == "complete" and source_id not in raw_ids and derived), (
        "Complete raw search hid missing source while Context served its Memory"
    )
