"""Derived SQLite FTS5 index for the immutable legacy EventLog.

The JSONL file remains authoritative. This index is reconstructible, and
search is fail-closed unless all complete records have been indexed. It does
not admit Core observations, create Memory/Knowledge, or call an LLM.
"""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog

TOKENS = re.compile(r"[^\W_]+", re.UNICODE)
MAX_LINE = 1_000_000
ANCHOR_BYTES = 4096
MAX_RESULTS = 100


class EventRetrieval:
    """Explicitly synchronized, provenance-checking Event search service."""

    def __init__(self, event_log: EventLog, database_file, *, memory_store=None):
        if not isinstance(event_log, EventLog):
            raise TypeError("EventRetrieval requires an EventLog")
        self.event_log = event_log
        self.database_file = Path(database_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self.memory_store = memory_store
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.database_file, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self):
        with closing(self._connect()) as conn, conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS event_index_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    cursor INTEGER NOT NULL CHECK(cursor>=0),
                    dev INTEGER, ino INTEGER,
                    mtime_ns INTEGER, ctime_ns INTEGER,
                    head_digest TEXT, tail_digest TEXT
                );
                INSERT OR IGNORE INTO event_index_state(singleton,cursor)
                    VALUES (1,0);
                CREATE TABLE IF NOT EXISTS indexed_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    session_id TEXT,
                    content TEXT NOT NULL,
                    raw_offset INTEGER NOT NULL CHECK(raw_offset>=0),
                    raw_length INTEGER NOT NULL CHECK(raw_length>0),
                    raw_digest TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS indexed_event_fts
                    USING fts5(event_id UNINDEXED, content);
            """)

    @staticmethod
    def _state(conn):
        return conn.execute(
            "SELECT * FROM event_index_state WHERE singleton=1"
        ).fetchone()

    @staticmethod
    def _anchors(stream, cursor):
        if cursor == 0:
            return None, None
        stream.seek(0)
        head = stream.read(min(ANCHOR_BYTES, cursor))
        stream.seek(max(0, cursor - ANCHOR_BYTES))
        tail = stream.read(min(ANCHOR_BYTES, cursor))
        return sha256(head).hexdigest(), sha256(tail).hexdigest()

    @staticmethod
    def _content(record):
        payload = record["payload"]
        if payload is None:
            return ""
        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            return payload["text"]
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )

    @staticmethod
    def _parse(raw, offset):
        if not raw.endswith(b"\n"):
            raise ValueError("Unterminated raw Event at byte " + str(offset))
        try:
            record = json.loads(raw.decode("utf-8"))
            Event.validate_record(record)
        except (UnicodeDecodeError, ValueError, TypeError) as error:
            raise ValueError(
                f"Invalid raw Event at byte {offset}: {error}"
            ) from error
        return record

    def status(self):
        """O(1) source freshness probe; does not re-read the complete JSONL."""
        with closing(self._connect()) as conn:
            state = self._state(conn)
            count = conn.execute(
                "SELECT COUNT(*) FROM indexed_events"
            ).fetchone()[0]
        path = self.event_log.log_file
        try:
            stat = path.stat()
        except FileNotFoundError:
            stat = None
        cursor = state["cursor"]
        if stat is None:
            status = "complete" if cursor == 0 else "source_changed"
            size = 0
        else:
            size = stat.st_size
            if cursor and (
                (stat.st_dev, stat.st_ino) != (state["dev"], state["ino"])
                or size < cursor
                or (size == cursor and
                    (stat.st_mtime_ns != state["mtime_ns"] or
                     stat.st_ctime_ns != state["ctime_ns"]))
            ):
                status = "source_changed"
            elif size > cursor:
                status = "partial"
            else:
                status = "complete"
        return {
            "status": status, "indexed_events": count, "indexed_bytes": cursor,
            "source_bytes": size, "pending_bytes": max(0, size - cursor),
        }

    @staticmethod
    def _limits(max_events, max_bytes):
        if type(max_events) is not int or not 1 <= max_events <= 100_000:
            raise ValueError("max_events must be in 1..100000")
        if type(max_bytes) is not int or not MAX_LINE <= max_bytes <= 100_000_000:
            raise ValueError(f"max_bytes must be in {MAX_LINE}..100000000")

    def sync(self, *, max_events=256, max_bytes=2_000_000):
        """Index a bounded complete prefix; commit rows and cursor atomically.

        A torn trailing JSONL line is deliberately left pending. If source
        identity, indexed prefix anchors or size regress, require rebuild().
        """
        self._limits(max_events, max_bytes)
        path = self.event_log.log_file
        processed = 0
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                state = self._state(conn)
                cursor = state["cursor"]
                try:
                    stream = path.open("rb")
                except FileNotFoundError:
                    if cursor:
                        raise ValueError("EventLog disappeared: rebuild required")
                    conn.commit()
                    return {"indexed_now": 0, **self.status()}
                with stream:
                    stat = path.stat()
                    if cursor:
                        if (stat.st_dev, stat.st_ino) != (
                            state["dev"], state["ino"]
                        ) or stat.st_size < cursor:
                            raise ValueError("EventLog replaced/truncated: rebuild required")
                        anchors = self._anchors(stream, cursor)
                        if anchors != (state["head_digest"], state["tail_digest"]):
                            raise ValueError("Indexed EventLog prefix changed: rebuild required")
                        if stat.st_size == cursor and (
                            stat.st_mtime_ns != state["mtime_ns"] or
                            stat.st_ctime_ns != state["ctime_ns"]
                        ):
                            raise ValueError("EventLog modified in place: rebuild required")
                    source_size = stat.st_size
                    stream.seek(cursor)
                    processed_bytes = 0
                    scanned_lines = 0
                    while cursor < source_size and scanned_lines < max_events:
                        start = stream.tell()
                        if processed_bytes >= max_bytes:
                            break
                        remaining = min(source_size - start, MAX_LINE + 1)
                        raw = stream.readline(remaining)
                        if len(raw) > MAX_LINE:
                            raise ValueError(f"Raw Event exceeds {MAX_LINE} bytes at {start}")
                        if not raw.endswith(b"\n"):
                            # Never index a potentially in-progress append.
                            break
                        scanned_lines += 1
                        processed_bytes += len(raw)
                        cursor = stream.tell()
                        if not raw.strip():
                            continue
                        record = self._parse(raw, start)
                        digest = sha256(raw).hexdigest()
                        content = self._content(record)
                        try:
                            rowid = conn.execute(
                                "INSERT INTO indexed_events("
                                "event_id,event_type,source,timestamp,session_id,"
                                "content,raw_offset,raw_length,raw_digest)"
                                " VALUES(?,?,?,?,?,?,?,?,?)",
                                (
                                    record["id"], record["type"], record["source"],
                                    record["timestamp"], record["session_id"],
                                    content, start, len(raw), digest,
                                ),
                            ).lastrowid
                        except sqlite3.IntegrityError as error:
                            raise ValueError(
                                "Duplicate raw Event ID at byte " + str(start)
                            ) from error
                        conn.execute(
                            "INSERT INTO indexed_event_fts(rowid,event_id,content)"
                            " VALUES(?,?,?)",
                            (rowid, record["id"], content),
                        )
                        processed += 1
                    # Detect source rotation during ingestion, not just before.
                    if (path.stat().st_dev, path.stat().st_ino) != (
                        stat.st_dev, stat.st_ino
                    ):
                        raise ValueError("EventLog rotated during indexing")
                    head, tail = self._anchors(stream, cursor)
                    conn.execute(
                        "UPDATE event_index_state SET cursor=?, dev=?, ino=?, "
                        "mtime_ns=?, ctime_ns=?, head_digest=?, tail_digest=? "
                        "WHERE singleton=1",
                        (
                            cursor, stat.st_dev, stat.st_ino,
                            stat.st_mtime_ns, stat.st_ctime_ns, head, tail,
                        ),
                    )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return {"indexed_now": processed, **self.status()}

    def rebuild(self):
        """Explicitly discard only the derived SQLite index, never EventLog."""
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM indexed_event_fts")
                conn.execute("DELETE FROM indexed_events")
                conn.execute(
                    "UPDATE event_index_state SET cursor=0, dev=NULL, ino=NULL,"
                    " mtime_ns=NULL, ctime_ns=NULL, head_digest=NULL,"
                    " tail_digest=NULL WHERE singleton=1"
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return self.status()

    def _coverage(self, *, require_complete):
        info = self.status()
        if info["status"] == "source_changed":
            raise ValueError("EventLog identity changed: explicit rebuild required")
        if require_complete and info["status"] != "complete":
            raise RuntimeError(
                "Event index is partial: call sync(); "
                f"{info['pending_bytes']} unindexed source bytes"
            )
        return info

    def _read_row(self, row):
        # Re-open the original bytes and verify the exact source segment.
        with self.event_log.log_file.open("rb") as stream:
            stream.seek(row["raw_offset"])
            raw = stream.read(row["raw_length"])
        if len(raw) != row["raw_length"] or (
            sha256(raw).hexdigest() != row["raw_digest"]
        ):
            raise ValueError("Raw Event changed at indexed locator: rebuild required")
        record = self._parse(raw, row["raw_offset"])
        if (
            record["id"] != row["event_id"] or
            record["type"] != row["event_type"] or
            record["source"] != row["source"]
        ):
            raise ValueError("Raw Event identity mismatch")
        return record

    def get(self, event_id, *, require_complete=True):
        """Direct SQLite ID lookup with raw byte/sha256 verification."""
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Event ID must be a non-empty string")
        self._coverage(require_complete=require_complete)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM indexed_events WHERE event_id=?", (event_id,)
            ).fetchone()
        return None if row is None else self._read_row(row)

    @staticmethod
    def _query(query):
        if not isinstance(query, str):
            raise ValueError("Event query must be text")
        tokens = sorted({
            token.casefold() for token in TOKENS.findall(query)
            if len(token) >= 2
        })[:8]
        return " OR ".join('"' + token + '"' for token in tokens) if tokens else None

    def search(
        self, query, *, top_k=10, event_types=None, sources=None,
        require_complete=True,
    ):
        """FTS5 Event search; source/type filters are applied before LIMIT."""
        if type(top_k) is not int or not 1 <= top_k <= MAX_RESULTS:
            raise ValueError("top_k must be 1..100")
        for name, items in (("event_types", event_types), ("sources", sources)):
            if items is not None and (
                isinstance(items, str) or not isinstance(items, (set, tuple, list))
                or not items or any(not isinstance(x, str) or not x for x in items)
            ):
                raise ValueError(f"{name} must be a nonempty collection of strings")
        coverage = self._coverage(require_complete=require_complete)
        match = self._query(query)
        if match is None:
            return {"query": query, "coverage": coverage, "results": []}
        clauses = ["indexed_event_fts MATCH ?"]
        args = [match]
        if event_types is not None:
            values = sorted(set(event_types))
            clauses.append("e.event_type IN (" + ",".join("?" for _ in values) + ")")
            args.extend(values)
        if sources is not None:
            values = sorted(set(sources))
            clauses.append("e.source IN (" + ",".join("?" for _ in values) + ")")
            args.extend(values)
        args.append(top_k)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT e.*, bm25(indexed_event_fts) AS rank "
                "FROM indexed_event_fts "
                "JOIN indexed_events e ON e.rowid=indexed_event_fts.rowid "
                "WHERE " + " AND ".join(clauses) +
                " ORDER BY rank, e.event_id LIMIT ?",
                args,
            ).fetchall()
        results = [
            {
                "id": row["event_id"], "kind": "event",
                "record": self._read_row(row), "rank": row["rank"],
                "provenance": {
                    "source": row["source"],
                    "raw_offset": row["raw_offset"],
                    "raw_length": row["raw_length"],
                    "raw_sha256": row["raw_digest"],
                },
            }
            for row in rows
        ]
        return {"query": query, "coverage": coverage, "results": results}

    def events_for_memory(self, memory_id, *, require_complete=True):
        """Follow existing explicit Memory→raw Event sources, no graph walk."""
        if self.memory_store is None:
            raise ValueError("No MemoryStore supplied for source lookup")
        if self.memory_store.get_memory(memory_id) is None:
            raise ValueError("Unknown Memory ID: " + str(memory_id))
        self._coverage(require_complete=require_complete)
        events = []
        for event_id in self.memory_store.source_events(memory_id):
            event = self.get(event_id, require_complete=False)
            if event is None:
                raise ValueError("Missing indexed source Event: " + event_id)
            events.append(event)
        return events
