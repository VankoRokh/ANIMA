"""E4 lab-only SQLite journal for immutable Events and derived revisions.

This is *not* production Memory, and does not confer Core action authority.
All state is stored in a new isolated database. Crash simulation is process-
boundary exception injection, not physical power-loss certification.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from anima.core.event_bus import Event


class RevisionConflict(RuntimeError):
    pass


class IntegrityFault(RuntimeError):
    pass


class SimulatedCrash(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DerivedRevisionJournal:
    """Isolated, source-immutable, CAS and idempotent revision laboratory."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True)
        with self._connection() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS source_streams(
                  stream_id TEXT PRIMARY KEY, version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS raw_events(
                  event_id TEXT PRIMARY KEY, stream_id TEXT NOT NULL,
                  sequence INTEGER NOT NULL, body TEXT NOT NULL,
                  digest TEXT NOT NULL,
                  FOREIGN KEY(stream_id) REFERENCES source_streams(stream_id)
                );
                CREATE INDEX IF NOT EXISTS idx_lab_raw_stream
                  ON raw_events(stream_id, sequence);
                CREATE TABLE IF NOT EXISTS projection_heads(
                  projection_id TEXT PRIMARY KEY, revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projection_revisions(
                  projection_id TEXT NOT NULL, revision INTEGER NOT NULL,
                  stream_id TEXT NOT NULL, stream_version INTEGER NOT NULL,
                  operation_key TEXT NOT NULL UNIQUE,
                  record TEXT NOT NULL, digest TEXT NOT NULL,
                  PRIMARY KEY(projection_id, revision)
                );
                CREATE TABLE IF NOT EXISTS operation_ledger(
                  operation_key TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
                  projection_id TEXT NOT NULL, revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revision_dependencies(
                  projection_id TEXT NOT NULL, revision INTEGER NOT NULL,
                  event_id TEXT NOT NULL, digest TEXT NOT NULL,
                  PRIMARY KEY(projection_id, revision, event_id),
                  FOREIGN KEY(event_id) REFERENCES raw_events(event_id)
                );
            """)

    @contextmanager
    def _connection(self):
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA busy_timeout=10000")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def _tx(self):
        with self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
                con.commit()
            except BaseException:
                if con.in_transaction:
                    con.rollback()
                raise

    @staticmethod
    def _check_key(value, name):
        if (not isinstance(value, str) or not value.strip()
                or len(value) > 120):
            raise ValueError(name + " must be 1..120 nonblank characters")

    def append_event(self, stream_id, raw, *, cut=None):
        """Durable append; same Event ID and same body are a no-op."""
        self._check_key(stream_id, "stream_id")
        if cut not in (None, "before_commit", "after_commit"):
            raise ValueError("Unknown crash point")
        Event.validate_record(raw)
        body = _json(raw)
        digest = _digest(body)
        with self._tx() as con:
            existing = con.execute(
                "SELECT stream_id, body, digest FROM raw_events WHERE event_id=?",
                (raw["id"],),
            ).fetchone()
            if existing is not None:
                if (existing["stream_id"] != stream_id
                        or existing["digest"] != digest
                        or existing["body"] != body):
                    raise IntegrityFault("Raw Event identity has different content")
                result = {"status": "duplicate", "event_id": raw["id"],
                          "stream_version": self._version(con, stream_id)}
            else:
                con.execute(
                    "INSERT OR IGNORE INTO source_streams(stream_id,version) VALUES (?,0)",
                    (stream_id,),
                )
                con.execute(
                    "UPDATE source_streams SET version=version+1 WHERE stream_id=?",
                    (stream_id,),
                )
                version = self._version(con, stream_id)
                con.execute(
                    "INSERT INTO raw_events(event_id,stream_id,sequence,body,digest) "
                    "VALUES(?,?,?,?,?)",
                    (raw["id"], stream_id, version, body, digest),
                )
                result = {"status": "appended", "event_id": raw["id"],
                          "stream_version": version}
            if cut == "before_commit":
                raise SimulatedCrash("Event append: cut before commit")
        if cut == "after_commit":
            raise SimulatedCrash("Event append: cut after commit")
        return result

    @staticmethod
    def _version(con, stream_id):
        row = con.execute(
            "SELECT version FROM source_streams WHERE stream_id=?", (stream_id,)
        ).fetchone()
        return row["version"] if row else 0

    def stream_version(self, stream_id):
        with self._connection() as con:
            return self._version(con, stream_id)

    def record_revision(
        self, *, projection_id, stream_id, expected_head,
        expected_source_version, source_event_ids, assignments, operation_key,
        correction_event_id=None, cut=None,
    ):
        """Compare-and-swap one immutable derived view and its dependencies.

        expected_head=0 seeds a projection. Subsequent changes require a
        same-stream source-user correction Event ingested *after* the sources
        it reorganizes. The journal never decides if correction is semantically
        true; the caller/independent verifier owns that gate.
        """
        for name, value in (("projection_id", projection_id), ("stream_id", stream_id),
                            ("operation_key", operation_key)):
            self._check_key(value, name)
        if (type(expected_head) is not int or expected_head < 0
                or type(expected_source_version) is not int
                or expected_source_version < 1):
            raise ValueError("Expected versions must be nonnegative integers")
        if (not isinstance(source_event_ids, list) or not source_event_ids
                or len(set(source_event_ids)) != len(source_event_ids)
                or not isinstance(assignments, dict)
                or not assignments or set(assignments) - set(source_event_ids)
                or any(not isinstance(x, str) or not x for x in assignments.values())):
            raise ValueError("Malformed source dependency or assignment set")
        if expected_head and (not correction_event_id
                              or correction_event_id not in source_event_ids):
            raise ValueError("A later correction Event is required for revision")
        if expected_head == 0 and correction_event_id is not None:
            raise ValueError("Seed has no correction Event")
        if cut not in (None, "before_commit", "after_commit"):
            raise ValueError("Unknown crash point")
        request = {
            "projection_id": projection_id, "stream_id": stream_id,
            "expected_head": expected_head,
            "expected_source_version": expected_source_version,
            "source_event_ids": source_event_ids,
            "assignments": assignments,
            "correction_event_id": correction_event_id,
        }
        request_hash = _digest(_json(request))
        with self._tx() as con:
            previous_op = con.execute(
                "SELECT * FROM operation_ledger WHERE operation_key=?",
                (operation_key,),
            ).fetchone()
            if previous_op is not None:
                if (previous_op["request_digest"] != request_hash
                        or previous_op["projection_id"] != projection_id):
                    raise IntegrityFault("Operation key reused with a different request")
                result = {
                    "projection_id": projection_id,
                    "revision": previous_op["revision"],
                    "status": "idempotent_replay",
                }
            else:
                version = self._version(con, stream_id)
                if version != expected_source_version:
                    raise RevisionConflict("Source stream advanced or is missing")
                head = con.execute(
                    "SELECT revision FROM projection_heads WHERE projection_id=?",
                    (projection_id,),
                ).fetchone()
                observed_head = head["revision"] if head else 0
                if observed_head != expected_head:
                    raise RevisionConflict("Projection head changed")
                sources = {}
                for event_id in source_event_ids:
                    row = con.execute(
                        "SELECT * FROM raw_events WHERE event_id=?", (event_id,)
                    ).fetchone()
                    if row is None or row["stream_id"] != stream_id:
                        raise RevisionConflict("Missing or foreign source Event")
                    if _digest(row["body"]) != row["digest"]:
                        raise IntegrityFault("Raw Event bytes changed")
                    sources[event_id] = row
                if expected_head:
                    old = self._revision_row(con, projection_id, expected_head)
                    previous = json.loads(old["record"])
                    prior_assignments = previous["assignments"]
                    if (set(assignments) != set(prior_assignments)
                            or all(assignments[key] == prior_assignments[key]
                                   for key in assignments)):
                        raise RevisionConflict("Revision must alter an existing assignment")
                    if not set(previous["source_event_ids"]) <= set(source_event_ids):
                        raise RevisionConflict("Revision lost prior source provenance")
                    correction = sources[correction_event_id]
                    corrected_raw = json.loads(correction["body"])
                    if (corrected_raw["source"] != "user"
                            or corrected_raw["type"] != "conversation.user"
                            or correction["sequence"] <=
                            max(sources[key]["sequence"] for key in prior_assignments)):
                        raise RevisionConflict("Correction not later source-user Event")
                elif set(assignments) != set(source_event_ids):
                    raise ValueError("Seed must assign every source Event")
                next_rev = observed_head + 1
                record = {
                    "projection_id": projection_id, "revision": next_rev,
                    "previous_revision": observed_head or None,
                    "stream_id": stream_id, "stream_version": version,
                    "source_event_ids": source_event_ids,
                    "assignments": assignments,
                    "correction_event_id": correction_event_id,
                    "source_digests": {key: sources[key]["digest"]
                                      for key in source_event_ids},
                    "authority": "LAB_DERIVED_ONLY",
                }
                body = _json(record)
                con.execute(
                    "INSERT INTO projection_revisions(projection_id,revision,"
                    "stream_id,stream_version,operation_key,record,digest) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (projection_id, next_rev, stream_id, version, operation_key,
                     body, _digest(body)),
                )
                for event_id in source_event_ids:
                    con.execute(
                        "INSERT INTO revision_dependencies(projection_id,revision,event_id,digest)"
                        " VALUES(?,?,?,?)",
                        (projection_id, next_rev, event_id, sources[event_id]["digest"]),
                    )
                if observed_head:
                    con.execute(
                        "UPDATE projection_heads SET revision=? WHERE projection_id=? "
                        "AND revision=?",
                        (next_rev, projection_id, observed_head),
                    )
                    if con.execute("SELECT changes()").fetchone()[0] != 1:
                        raise RevisionConflict("Projection CAS lost race")
                else:
                    con.execute(
                        "INSERT INTO projection_heads(projection_id,revision) VALUES(?,?)",
                        (projection_id, next_rev),
                    )
                con.execute(
                    "INSERT INTO operation_ledger(operation_key,request_digest,"
                    "projection_id,revision) VALUES(?,?,?,?)",
                    (operation_key, request_hash, projection_id, next_rev),
                )
                result = {
                    "projection_id": projection_id,
                    "revision": next_rev, "status": "committed",
                }
            if cut == "before_commit":
                raise SimulatedCrash("Derived view: cut before commit")
        if cut == "after_commit":
            raise SimulatedCrash("Derived view: cut after commit")
        return result

    @staticmethod
    def _revision_row(con, projection_id, revision):
        row = con.execute(
            "SELECT * FROM projection_revisions WHERE projection_id=? AND revision=?",
            (projection_id, revision),
        ).fetchone()
        if row is None:
            raise KeyError("No derived revision")
        if _digest(row["record"]) != row["digest"]:
            raise IntegrityFault("Derived record checksum mismatch")
        return row

    def read_revision(self, projection_id, revision=None):
        self._check_key(projection_id, "projection_id")
        with self._connection() as con:
            head_row = con.execute(
                "SELECT revision FROM projection_heads WHERE projection_id=?",
                (projection_id,),
            ).fetchone()
            if head_row is None:
                raise KeyError("Unknown projection")
            head = head_row["revision"]
            selected = head if revision is None else revision
            row = self._revision_row(con, projection_id, selected)
            record = json.loads(row["record"])
            links = con.execute(
                "SELECT d.event_id, d.digest, e.stream_id, e.body, e.digest AS raw_digest "
                "FROM revision_dependencies d LEFT JOIN raw_events e "
                "ON d.event_id=e.event_id WHERE d.projection_id=? AND d.revision=?",
                (projection_id, selected),
            ).fetchall()
            actual_links = {x["event_id"]: x for x in links}
            if set(actual_links) != set(record["source_event_ids"]):
                raise IntegrityFault("Derived dependencies missing")
            for event_id, link in actual_links.items():
                if (link["stream_id"] != record["stream_id"]
                        or link["raw_digest"] != link["digest"]
                        or _digest(link["body"]) != link["digest"]
                        or record["source_digests"].get(event_id) != link["digest"]):
                    raise IntegrityFault("Source integrity or dependency checksum mismatch")
            version = self._version(con, record["stream_id"])
            is_fresh = version == record["stream_version"]
            return {
                "record": record,
                "head_revision": head,
                "is_head": selected == head,
                "source_current_version": version,
                "fresh_source_snapshot": is_fresh,
                "eligible_for_lab_preflight": bool(selected == head and is_fresh),
            }

    def versions(self, projection_id):
        with self._connection() as con:
            return [
                row[0] for row in con.execute(
                    "SELECT revision FROM projection_revisions WHERE projection_id=? "
                    "ORDER BY revision", (projection_id,)
                )
            ]

    def publication_guard(self, projection_id, *, expected_revision):
        current = self.read_revision(projection_id)
        if (current["head_revision"] != expected_revision
                or not current["eligible_for_lab_preflight"]):
            raise RevisionConflict("Derived view is stale or is not current head")
        # Only a read-only validation receipt; no actual Memory publication.
        return {"status": "lab_preflight_only", "revision": expected_revision,
                "authority": "NO_CORE_PUBLISH_PERMISSION"}
