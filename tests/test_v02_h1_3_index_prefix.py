"""v0.2 H1.3: verify prior indexed Events before accepting an appended tail.

All mutations below affect only disposable tmp_path fixture files.
The explicit rebuild is for a *valid but externally edited test journal*;
ANIMA does not rewrite the source or silently repair an index.
"""

import sqlite3
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_retrieval import EventRetrieval


STAMP = "2026-11-17T12:00:00+00:00"


def make_event(number, text):
    return Event(
        "conversation.user", {"text": text}, source="user",
        event_id=f"ev_{UUID(int=(4 << 76) | (2 << 62) | number)}",
        timestamp=STAMP, session_id="session_00000001",
    )


def stack(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    index = EventRetrieval(log, tmp_path / "event_index.db")
    return log, index


def index_to_end(index, *, max_events=128):
    for _ in range(20):
        state = index.sync(max_events=max_events)
        if state["status"] == "complete":
            return state
    raise RuntimeError("Fixture index did not converge")


def seed(log, n=32):
    for i in range(1, n + 1):
        label = "needleaaaa" if i == n // 2 else f"othermarker{i:02d}"
        log.write(make_event(i, label + " " + "x" * 1000))


def corrupt_middle(log):
    path = log.log_file
    original = path.read_bytes()
    assert original.count(b"needleaaaa") == 1
    path.write_bytes(original.replace(b"needleaaaa", b"needlebbbb", 1))


def test_h1_3_ordinary_append_is_still_indexed_and_searchable(tmp_path):
    log, index = stack(tmp_path)
    seed(log, n=8)
    index_to_end(index)
    older = make_event(100, "ordinary incremental newmarker")
    log.write(older)
    result = index.sync(max_events=128)
    assert result["status"] == "complete"
    assert result["indexed_now"] == 1
    assert index.get(older.event_id)["id"] == older.event_id
    assert [row["id"] for row in index.search("newmarker")["results"]] == [
        older.event_id
    ]


def test_h1_3_hidden_middle_mutation_plus_append_is_rejected_atomically(tmp_path):
    log, index = stack(tmp_path)
    seed(log)
    baseline = index_to_end(index)
    original_cursor = baseline["indexed_bytes"]
    assert baseline["indexed_events"] == 32

    corrupt_middle(log)
    appended = make_event(100, "a newly appended event")
    log.write(appended)
    with pytest.raises(ValueError, match="Indexed EventLog prefix changed"):
        index.sync(max_events=128)

    # The failed sync is atomic: neither the new record nor the cursor commits.
    after = index.status()
    assert after["status"] == "partial"
    assert after["indexed_events"] == 32
    assert after["indexed_bytes"] == original_cursor
    assert index.get(appended.event_id, require_complete=False) is None


def test_h1_3_missing_prior_locator_refuses_extension(tmp_path):
    log, index = stack(tmp_path)
    seed(log, n=8)
    index_to_end(index)
    with sqlite3.connect(index.database_file) as connection:
        connection.execute(
            "DELETE FROM indexed_events WHERE event_id = ?",
            (make_event(4, "ignored").event_id,),
        )
    log.write(make_event(100, "append after removed locator"))
    with pytest.raises(ValueError, match="Indexed EventLog prefix changed"):
        index.sync(max_events=128)


def test_h1_3_existing_blank_spacer_lines_are_not_mistaken_for_events(tmp_path):
    log, index = stack(tmp_path)
    log.write(make_event(1, "valid first event"))
    index_to_end(index)
    with log.log_file.open("ab") as out:
        out.write(b"\n \t\n")
    assert index.sync()["status"] == "complete"
    log.write(make_event(2, "valid second event"))
    assert index.sync()["status"] == "complete"
    assert index.status()["indexed_events"] == 2
    assert index.get(make_event(2, "valid second event").event_id) is not None


def test_h1_3_point_reads_do_not_scan_whole_prefix(tmp_path, monkeypatch):
    log, index = stack(tmp_path)
    log.write(make_event(1, "spotcheckmarker raw lookup"))
    index_to_end(index)

    def forbidden_verify(*_args, **_kwargs):
        raise AssertionError("Normal point lookup must not verify full prefix")

    monkeypatch.setattr(index, "_verify_indexed_prefix", forbidden_verify)
    assert index.get(make_event(1, "unused").event_id)["payload"]["text"] == (
        "spotcheckmarker raw lookup"
    )
    assert len(index.search("spotcheckmarker")["results"]) == 1


def test_h1_3_rebuild_is_explicit_after_valid_source_edit(tmp_path):
    log, index = stack(tmp_path)
    seed(log)
    index_to_end(index)
    corrupt_middle(log)
    log.write(make_event(101, "valid event after external edit"))
    with pytest.raises(ValueError, match="Indexed EventLog prefix changed"):
        index.sync(max_events=128)

    # Only the operator-facing explicit rebuilding of the *derived* index
    # accepts an externally modified but still parseable JSONL source.
    index.rebuild()
    result = index_to_end(index)
    assert result["status"] == "complete"
    assert len(index.search("needlebbbb")["results"]) == 1
    assert not index.search("needleaaaa")["results"]
