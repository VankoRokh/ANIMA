"""Event Retrieval v1: source-authoritative, resumable derived FTS index."""

import json
from pathlib import Path
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_retrieval import EventRetrieval
from anima.memory.memory_store import MemoryStore


STAMP = "2026-11-11T12:00:00+00:00"


def eid(i):
    return f"ev_{UUID(int=(4 << 76) | (2 << 62) | (i + 1))}"


def event(i, text, *, event_type="conversation.user", source="user"):
    payload = {"text": text}
    return Event(
        event_type, payload, source=source, timestamp=STAMP,
        event_id=eid(i),
    )


def stack(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    store = MemoryStore(tmp_path / "memory.db")
    index = EventRetrieval(log, tmp_path / "event_index.db", memory_store=store)
    return log, store, index


def index_to_end(index):
    for _ in range(20):
        result = index.sync(max_events=3)
        if result["status"] == "complete":
            return result
    raise AssertionError("Index did not converge")


def test_explicit_core_port_and_first_sync_finds_raw_details(tmp_path):
    inactive = build_core(tmp_path / "disabled")
    assert inactive.event_retrieval is None
    assert not (inactive.data_dir / "event_index.db").exists()

    core = build_core(tmp_path / "enabled", enable_event_retrieval=True)
    index = core.event_retrieval
    assert index is not None
    core.runtime.wake()
    messages = core.runtime.user_input(
        "cooling incident CPU reached exactly 82 degrees before shutdown"
    )
    raw = next(m for m in messages if m.event_type == "conversation.user")
    assert index.status()["status"] == "partial"
    with pytest.raises(RuntimeError, match="partial"):
        index.search("82")
    index_to_end(index)
    found = index.search("82", event_types=["conversation.user"])
    assert [r["id"] for r in found["results"]] == [raw.event_id]
    assert found["results"][0]["record"]["payload"]["text"].endswith(
        "before shutdown"
    )
    assert index.get(raw.event_id)["id"] == raw.event_id
    assert index.get(eid(88)) is None
    assert index.status()["status"] == "complete"

    memories = core.memory_store.list_memories()
    selected = next(m for m in memories
                    if raw.event_id in core.memory_store.source_events(m["id"]))
    assert [r["id"] for r in index.events_for_memory(selected["id"])] == [
        raw.event_id
    ]
    assert len(core.event_log.load_events()) >= 2  # system.wake plus message


def test_incremental_checkpoint_restart_and_event_count(tmp_path):
    log, _, index = stack(tmp_path)
    for i in range(7):
        log.write(event(i, f"eventmarker{i:02d} cooling sensor"))
    assert index.status()["indexed_events"] == 0
    step = index.sync(max_events=2)
    assert step["indexed_now"] == 2
    assert step["indexed_events"] == 2
    assert step["status"] == "partial"
    assert step["pending_bytes"] > 0

    resumed = EventRetrieval(log, tmp_path / "event_index.db")
    with pytest.raises(RuntimeError, match="partial"):
        resumed.get(eid(0))
    assert resumed.get(eid(0), require_complete=False)["id"] == eid(0)
    assert index_to_end(resumed)["indexed_events"] == 7
    assert resumed.sync()["indexed_now"] == 0
    assert len(resumed.search("cooling", top_k=10)["results"]) == 7
    assert resumed.status()["pending_bytes"] == 0

    log.write(event(8, "late insertion cooldown 71"))
    assert resumed.status()["status"] == "partial"
    assert index_to_end(resumed)["indexed_events"] == 8
    assert resumed.get(eid(8))["payload"]["text"] == "late insertion cooldown 71"


def test_read_contract_distinguishes_unindexed_source_from_no_match(tmp_path):
    log, _, index = stack(tmp_path)
    assert index.status()["status"] == "complete"
    assert index.search("unavailable")["results"] == []
    log.write(event(0, "present but unindexed 83"))
    with pytest.raises(RuntimeError, match="partial"):
        index.search("unavailable")
    incomplete = index.search("unavailable", require_complete=False)
    assert incomplete["coverage"]["status"] == "partial"
    assert incomplete["results"] == []
    index_to_end(index)
    assert index.search("unavailable")["coverage"]["status"] == "complete"
    assert index.get(eid(0))["id"] == eid(0)


def test_fts_filter_applies_before_limit_and_typed_fields(tmp_path):
    log, _, index = stack(tmp_path)
    for i in range(32):
        log.write(event(i, "universal hotword cooling",
                        event_type="lab.distractor", source="other"))
    target = event(32, "universal hotword cooling sensor 82",
                   event_type="lab.sensor", source="trusted")
    log.write(target)
    index_to_end(index)
    hit = index.search("universal", top_k=1,
                       event_types=["lab.sensor"], sources=["trusted"])
    assert [r["id"] for r in hit["results"]] == [target.event_id]
    assert hit["results"][0]["provenance"]["source"] == "trusted"
    assert len(index.search("universal", top_k=2)["results"]) == 2
    assert index.search("universal", sources=["unknown"])["results"] == []


def test_partial_tail_is_not_indexed_until_newline(tmp_path):
    log, _, index = stack(tmp_path)
    original = event(0, "stable record")
    log.write(original)
    index_to_end(index)
    fresh = event(1, "split across writes")
    raw = json.dumps(fresh.to_dict(), ensure_ascii=False).encode("utf-8")
    with log.log_file.open("ab") as stream:
        stream.write(raw[:25])
    after_torn = index.sync()
    assert after_torn["indexed_now"] == 0
    assert after_torn["status"] == "partial"
    assert index.get(original.event_id, require_complete=False)
    with pytest.raises(RuntimeError, match="partial"):
        index.get(fresh.event_id)
    with log.log_file.open("ab") as stream:
        stream.write(raw[25:] + b"\n")
    assert index.sync()["status"] == "complete"
    assert index.get(fresh.event_id)["payload"]["text"] == "split across writes"


def test_failed_ingest_rolls_back_rows_and_checkpoint(tmp_path, monkeypatch):
    log, _, index = stack(tmp_path)
    for i in range(2):
        log.write(event(i, f"marker{i}"))
    original_content = index._content

    def fault(record):
        if record["id"] == eid(1):
            raise RuntimeError("fault during index transaction")
        return original_content(record)

    monkeypatch.setattr(index, "_content", fault)
    with pytest.raises(RuntimeError, match="fault during index"):
        index.sync()
    assert index.status()["indexed_events"] == 0
    assert index.status()["indexed_bytes"] == 0
    monkeypatch.setattr(index, "_content", original_content)
    assert index.sync()["status"] == "complete"
    assert index.status()["indexed_events"] == 2


def test_corrupt_complete_record_does_not_advance_cursor(tmp_path):
    log, _, index = stack(tmp_path)
    log.write(event(0, "valid source"))
    with log.log_file.open("ab") as stream:
        stream.write(b'{"broken": invalid}\n')
    with pytest.raises(ValueError, match="Invalid raw Event"):
        index.sync()
    assert index.status()["indexed_events"] == 0
    # Fix only the unindexed bad tail; raw Event 0 remains byte-for-byte intact.
    with log.log_file.open("rb+") as stream:
        data = stream.read()
        stream.seek(0)
        stream.write(data.split(b'{"broken":')[0])
        stream.truncate()
    assert index.sync()["status"] == "complete"
    assert index.get(eid(0))["payload"]["text"] == "valid source"


def test_source_mutation_detected_and_explicit_rebuild(tmp_path):
    log, _, index = stack(tmp_path)
    original = event(0, "cooling 82")
    log.write(original)
    index_to_end(index)
    old_bytes = log.log_file.read_bytes()
    assert b"cooling 82" in old_bytes
    log.log_file.write_bytes(old_bytes.replace(b"cooling 82", b"cooling 92"))
    assert index.status()["status"] == "source_changed"
    with pytest.raises(ValueError, match="rebuild"):
        index.get(eid(0), require_complete=False)
    with pytest.raises(ValueError, match="rebuild"):
        index.sync()
    index.rebuild()
    assert index.sync()["status"] == "complete"
    assert index.search("92")["results"][0]["record"]["payload"]["text"] == (
        "cooling 92"
    )
    assert log.load_events()[0]["payload"]["text"] == "cooling 92"


def test_truncate_and_rotate_do_not_masquerade_as_empty_history(tmp_path):
    log, _, index = stack(tmp_path)
    log.write(event(0, "indexed history"))
    index_to_end(index)
    log.log_file.write_text("", encoding="utf-8")
    assert index.status()["status"] == "source_changed"
    with pytest.raises(ValueError, match="rebuild"):
        index.search("indexed", require_complete=False)
    index.rebuild()
    assert index.status()["status"] == "complete"
    assert index.search("indexed")["results"] == []


def test_edited_prefix_then_append_fails_anchor_verification(tmp_path):
    log, _, index = stack(tmp_path)
    log.write(event(0, "cooling 82"))
    index_to_end(index)
    with log.log_file.open("rb+") as stream:
        original = stream.read().replace(b"cooling 82", b"cooling 92")
        stream.seek(0)
        stream.write(original)
        stream.truncate()
    log.write(event(1, "new append"))
    assert index.status()["status"] == "partial"
    with pytest.raises(ValueError, match="prefix changed"):
        index.sync()


def test_duplicate_raw_id_never_increments_evidence_count(tmp_path):
    log, _, index = stack(tmp_path)
    ev = event(0, "same event")
    log.write(ev)
    index_to_end(index)
    with log.log_file.open("ab") as stream:
        stream.write((json.dumps(ev.to_dict()) + "\n").encode())
    with pytest.raises(ValueError, match="Duplicate raw Event ID"):
        index.sync()
    assert index.status()["indexed_events"] == 1
    assert index.status()["status"] == "partial"


def test_parser_injection_and_bounds(tmp_path):
    log, _, index = stack(tmp_path)
    log.write(event(0, "Unicode пример CPU-82"))
    index_to_end(index)
    for text in ("", "a", "x' OR 1=1 --", "прим", "\" OR DROP TABLE"):
        response = index.search(text)
        assert response["coverage"]["status"] == "complete"
        assert isinstance(response["results"], list)
    for invalid in (0, True, -1, 101):
        with pytest.raises(ValueError):
            index.search("CPU", top_k=invalid)
    for invalid in (0, True, 2_000_000):
        with pytest.raises(ValueError):
            index.sync(max_events=invalid)
    with pytest.raises(ValueError):
        index.search("CPU", sources="user")
    with pytest.raises(ValueError):
        index.search(None)


def test_missing_memory_source_is_error_not_fabricated_evidence(tmp_path):
    log, store, index = stack(tmp_path)
    log.write(event(0, "real source"))
    index_to_end(index)
    memory = store.create_memory(
        memory_type="episodic", domain="project", content="backlinked",
        source_event_id=eid(777), created_at=STAMP, status="closed",
    )
    with pytest.raises(ValueError, match="Missing indexed source Event"):
        index.events_for_memory(memory["id"])
