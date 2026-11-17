"""ANIMA v0.2 H5.2: crash boundaries, replay, index rollback, process locks.

All destructive actions run only on pytest tmp_path data. A subprocess uses
os._exit(73) to emulate abrupt termination during an open SQLite transaction.
This is a process crash test, NOT a test of sudden physical power loss.
"""

import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.event_retrieval import EventRetrieval
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.release_v01 import _single_writer


ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-11-17T12:00:00+00:00"
SESSION = "session_00000001"


def uid(number):
    return "ev_" + str(UUID(int=(4 << 76) | (2 << 62) | number))


def event(number, *, text=None):
    return Event(
        "conversation.user",
        {"text": text or f"h52crash source event {number}"},
        source="user", session_id=SESSION,
        event_id=uid(number), timestamp=STAMP,
    )


def stack(root, *, fault_hook=None):
    store = MemoryStore(root / "memory.db")
    raw = EventLog(root / "events.jsonl")
    processor = MemoryProcessor(
        memory_store=store,
        event_log=raw,
        link_store=LinkStore(store),
    )
    coordinator = EventProcessingCoordinator(
        memory_store=store,
        memory_processor=processor,
        event_log=raw,
        fault_hook=fault_hook,
    )
    return store, raw, coordinator


CRASH_INSIDE_TRANSACTION = r"""
import os
import sys
from pathlib import Path
from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor

root = Path(sys.argv[1])
store = MemoryStore(root / "memory.db")
raw = EventLog(root / "events.jsonl")
event = Event(
    "conversation.user",
    {"text": "h52crash process killed before SQLite commit"},
    source="user", session_id="session_00000001",
    event_id="ev_00000000-0000-4000-8000-000000000701",
    timestamp="2026-11-17T12:00:00+00:00",
)
raw.write(event)

def crash_after_effect(*_args):
    # Injection point follows Memory mutation but precedes SQLite commit.
    os._exit(73)

coordinator = EventProcessingCoordinator(
    memory_store=store,
    memory_processor=MemoryProcessor(
        memory_store=store, event_log=raw, link_store=LinkStore(store),
    ),
    event_log=raw,
    fault_hook=crash_after_effect,
)
coordinator.process(event)
raise RuntimeError("Fault hook failed to terminate the subprocess")
"""


def _subprocess(command, *, timeout=30):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"]
        if env.get("PYTHONPATH") else ""
    )
    return subprocess.run(
        [sys.executable, "-B", *command],
        cwd=ROOT, env=env, timeout=timeout,
        check=False, capture_output=True, text=True,
    )


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process crash gate")
def test_h5_2_process_dies_after_raw_write_before_sqlite_commit(tmp_path):
    outcome = _subprocess(
        ["-c", CRASH_INSIDE_TRANSACTION, str(tmp_path)],
    )
    assert outcome.returncode == 73, outcome.stderr
    store, raw, coordinator = stack(tmp_path)
    records = raw.load_events()
    assert len(records) == 1
    assert records[0]["id"] == "ev_00000000-0000-4000-8000-000000000701"

    # SQLite rolled back the uncommitted Memory effect and processing claim.
    assert store.count() == 0
    assert coordinator.get(records[0]["id"]) is None

    # Recovery adopts the Raw source once, then finalizes exactly one effect.
    first = coordinator.recover()
    assert first["adopted"] == 1
    assert first["retried"] == 1
    assert first["finalized"] == 1
    assert store.count() == 1
    m = store.list_memories()[0]
    assert store.source_events(m["id"]) == [records[0]["id"]]

    for _ in range(3):
        repeated = stack(tmp_path)[2].recover()
        assert repeated["adopted"] == 0
        assert repeated["retried"] == 0
        assert repeated["finalized"] == 1
    assert store.count() == 1
    assert raw.load_events() == records


def test_h5_2_raw_append_before_processing_recover_then_index(tmp_path):
    store, raw, coordinator = stack(tmp_path)
    original = event(702)
    raw.write(original)
    # Crash boundary: Raw is committed, processing has not begun.
    assert coordinator.get(original.event_id) is None

    restarted_store, restarted_raw, restarted = stack(tmp_path)
    report = restarted.recover()
    assert report["adopted"] == 1
    assert report["retried"] == 1
    assert restarted_store.count() == 1
    assert restarted.get(original.event_id)["status"] == "done"

    index = EventRetrieval(
        restarted_raw, tmp_path / "event_index.db",
        memory_store=restarted_store,
    )
    assert index.sync()["status"] == "complete"
    results = index.search("h52crash")
    assert [row["id"] for row in results["results"]] == [
        original.event_id
    ]
    assert index.get(original.event_id)["id"] == original.event_id
    assert restarted.recover()["retried"] == 0


def test_h5_2_sqlite_processing_committed_before_index_sync(tmp_path):
    store, raw, coordinator = stack(tmp_path)
    original = event(703)
    raw.write(original)
    assert coordinator.process(original)["action"] == "create"
    count_before = store.count()

    # An index must tolerate being created AFTER the finalized Memory.
    _other_store, reopened_raw, reopened = stack(tmp_path)
    assert reopened.recover()["finalized"] == 1
    assert reopened.get(original.event_id)["attempts"] == 1

    index = EventRetrieval(reopened_raw, tmp_path / "event_index.db")
    assert index.sync()["status"] == "complete"
    assert index.get(original.event_id)["id"] == original.event_id
    assert index.sync()["indexed_now"] == 0
    assert store.count() == count_before
    assert raw.load_events() == [original.to_dict()]


def test_h5_2_failure_during_index_sync_rolls_back_all_rows(tmp_path, monkeypatch):
    raw = EventLog(tmp_path / "events.jsonl")
    for number in range(704, 708):
        raw.write(event(number))
    original_bytes = raw.log_file.read_bytes()
    index = EventRetrieval(raw, tmp_path / "event_index.db")
    parse_original = index._parse
    calls = 0

    def fail_on_second_record(line, offset):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("h52 interrupted index transaction")
        return parse_original(line, offset)

    monkeypatch.setattr(index, "_parse", fail_on_second_record)
    with pytest.raises(RuntimeError, match="interrupted index transaction"):
        index.sync()

    with sqlite3.connect(index.database_file) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM indexed_events"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM indexed_event_fts"
        ).fetchone()[0] == 0
        checkpoint = conn.execute(
            "SELECT cursor FROM event_index_state WHERE singleton=1"
        ).fetchone()[0]
        assert checkpoint == 0

    # Reopening after the failure must give a complete, exact derived index.
    rebuilt = EventRetrieval(raw, tmp_path / "event_index.db")
    synced = rebuilt.sync()
    assert synced["status"] == "complete"
    assert synced["indexed_events"] == 4
    assert rebuilt.sync()["indexed_now"] == 0
    assert raw.log_file.read_bytes() == original_bytes


def test_h5_2_modified_middle_indexed_source_refuses_atomic_extension(tmp_path):
    raw = EventLog(tmp_path / "events.jsonl")
    for number in range(710, 728):
        raw.write(event(number, text=f"h52raw middle marker {number}"))
    index = EventRetrieval(raw, tmp_path / "event_index.db")
    before = index.sync()
    assert before["status"] == "complete"
    bytes_before = raw.log_file.read_bytes()
    original = b"marker 718"
    replacement = b"marker 888"
    assert bytes_before.count(original) == 1
    raw.log_file.write_bytes(bytes_before.replace(original, replacement))
    raw.write(event(728, text="h52raw appended after corruption"))
    corrupted_raw = raw.log_file.read_bytes()

    with pytest.raises(ValueError, match="Indexed EventLog prefix changed"):
        index.sync()
    assert index.status()["indexed_events"] == 18
    assert index.status()["indexed_bytes"] == before["indexed_bytes"]
    assert raw.log_file.read_bytes() == corrupted_raw


def test_h5_2_torn_tail_refuses_recovery_append_and_false_completion(tmp_path):
    store, raw, coordinator = stack(tmp_path)
    original = event(729)
    raw.write(original)
    assert coordinator.process(original)["action"] == "create"

    incomplete = event(730).to_dict()
    fragment = json.dumps(incomplete, sort_keys=True).encode("utf-8")
    assert b"\n" not in fragment
    with raw.log_file.open("ab") as output:
        output.write(fragment)
    damaged_bytes = raw.log_file.read_bytes()
    ledger_before = coordinator.list_records()

    with pytest.raises(ValueError, match="unterminated"):
        coordinator.recover()
    with pytest.raises(ValueError, match="unterminated trailing JSONL"):
        raw.write(event(731))
    assert coordinator.list_records() == ledger_before
    assert store.count() == 1

    index = EventRetrieval(raw, tmp_path / "event_index.db")
    result = index.sync()
    assert result["status"] == "partial"
    assert result["indexed_events"] == 1
    assert raw.log_file.read_bytes() == damaged_bytes


LOCK_HOLDER = r"""
import sys
import time
from pathlib import Path
from anima.release_v01 import _single_writer

with _single_writer(Path(sys.argv[1])):
    print("LOCKED", flush=True)
    time.sleep(30)
"""


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX flock gate")
def test_h5_2_separate_process_cannot_acquire_same_release_lock(tmp_path):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    proc = subprocess.Popen(
        [sys.executable, "-B", "-c", LOCK_HOLDER, str(tmp_path)],
        cwd=ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        readable, _, _ = select.select([proc.stdout], [], [], 10)
        assert readable, "lock holder did not report readiness"
        assert proc.stdout.readline().strip() == "LOCKED"
        with pytest.raises(RuntimeError, match="already running"):
            with _single_writer(tmp_path):
                pass
        assert proc.poll() is None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        proc.stdout.close()
        proc.stderr.close()

    # Kernel releases the advisory lock after the holder is killed.
    with _single_writer(tmp_path):
        pass
