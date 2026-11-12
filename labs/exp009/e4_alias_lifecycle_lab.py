"""Isolated E4 lab: immutable alias versions and selective derived invalidation.

No Core admission, MemoryStore writes, global alias replacement, or physical-
world identity verification. Revocation controls are synthetic source reports.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from anima.core.event_bus import Event

MAX_EDGES = 128


class LifecycleConflict(RuntimeError):
    pass


class LifecycleIntegrity(RuntimeError):
    pass


class LifecycleCut(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _receipt(kind, **kwargs):
    return dict(kind=kind, authority="LAB_ONLY", production_admission=False,
                memory_store_unchanged=True, **kwargs)


class AliasLifecycleLab:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.name in {"memory.db", "core_state.db"}:
            raise ValueError("Refusing production-looking database name")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS raw_events(
                  event_id TEXT PRIMARY KEY,
                  seq INTEGER NOT NULL UNIQUE,
                  body TEXT NOT NULL,
                  digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alias_heads(
                  alias_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                  state TEXT NOT NULL, definition_event_id TEXT NOT NULL UNIQUE,
                  surface TEXT NOT NULL, target_entity_id TEXT NOT NULL,
                  speaker TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alias_versions(
                  alias_id TEXT NOT NULL, revision INTEGER NOT NULL,
                  state TEXT NOT NULL, event_id TEXT NOT NULL,
                  body TEXT NOT NULL, digest TEXT NOT NULL,
                  PRIMARY KEY(alias_id, revision)
                );
                CREATE TABLE IF NOT EXISTS derived_heads(
                  node_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                  revision INTEGER NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS derived_versions(
                  node_id TEXT NOT NULL, revision INTEGER NOT NULL,
                  body TEXT NOT NULL, digest TEXT NOT NULL,
                  PRIMARY KEY(node_id, revision)
                );
                CREATE TABLE IF NOT EXISTS edges(
                  node_id TEXT NOT NULL, node_revision INTEGER NOT NULL,
                  upstream_kind TEXT NOT NULL, upstream_id TEXT NOT NULL,
                  upstream_revision INTEGER NOT NULL,
                  PRIMARY KEY(node_id, node_revision, upstream_kind,
                              upstream_id, upstream_revision)
                );
                CREATE INDEX IF NOT EXISTS idx_alias_lifecycle_edges
                  ON edges(upstream_kind, upstream_id, upstream_revision);
                CREATE TABLE IF NOT EXISTS invalidations(
                  operation_key TEXT NOT NULL, node_id TEXT NOT NULL,
                  old_revision INTEGER NOT NULL, cause_event_id TEXT NOT NULL,
                  PRIMARY KEY(operation_key, node_id)
                );
                CREATE TABLE IF NOT EXISTS operations(
                  operation_key TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
                  body TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _tx(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                if db.in_transaction:
                    db.rollback()
                raise

    @staticmethod
    def _key(value, name):
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ValueError(f"{name} must be 1..128 nonblank characters")

    @staticmethod
    def _cut(cut):
        if cut not in (None, "before_commit", "after_commit"):
            raise ValueError("Unknown simulated cut point")

    @staticmethod
    def _op(db, operation_key, request):
        row = db.execute(
            "SELECT * FROM operations WHERE operation_key=?", (operation_key,)
        ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != _digest(_json(request)):
            raise LifecycleIntegrity("Operation key collision")
        return {**json.loads(row["body"]), "status": "idempotent_replay"}

    @staticmethod
    def _save_op(db, operation_key, request, result):
        db.execute(
            "INSERT INTO operations VALUES(?,?,?)",
            (operation_key, _digest(_json(request)), _json(result)),
        )

    @staticmethod
    def _raw(db, event_id):
        row = db.execute("SELECT * FROM raw_events WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            raise LifecycleConflict("Missing source Event")
        if _digest(row["body"]) != row["digest"]:
            raise LifecycleIntegrity("Raw Event bytes were altered")
        return json.loads(row["body"]), row["digest"], row["seq"]

    @staticmethod
    def _alias_version(db, alias_id, revision):
        row = db.execute(
            "SELECT * FROM alias_versions WHERE alias_id=? AND revision=?",
            (alias_id, revision),
        ).fetchone()
        if row is None or _digest(row["body"]) != row["digest"]:
            raise LifecycleIntegrity("Alias revision missing or corrupted")
        return json.loads(row["body"])

    @staticmethod
    def _node_version(db, node_id, revision):
        row = db.execute(
            "SELECT * FROM derived_versions WHERE node_id=? AND revision=?",
            (node_id, revision),
        ).fetchone()
        if row is None or _digest(row["body"]) != row["digest"]:
            raise LifecycleIntegrity("Derived revision missing or corrupted")
        return json.loads(row["body"])

    def append_event(self, raw):
        Event.validate_record(raw)
        body = _json(raw)
        with self._tx() as db:
            existing = db.execute(
                "SELECT * FROM raw_events WHERE event_id=?", (raw["id"],)
            ).fetchone()
            if existing:
                if (existing["body"] != body or existing["digest"] != _digest(body)):
                    raise LifecycleIntegrity("Event ID replay with altered bytes")
                return _receipt("Event", status="idempotent_replay",
                                event_id=raw["id"], seq=existing["seq"])
            next_seq = db.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM raw_events"
            ).fetchone()[0]
            db.execute("INSERT INTO raw_events VALUES(?,?,?,?)",
                       (raw["id"], next_seq, body, _digest(body)))
            return _receipt("Event", status="appended",
                            event_id=raw["id"], seq=next_seq)

    def define(self, *, alias_id, definition_event_id, operation_key,
               expected_head=0, cut=None):
        self._key(alias_id, "alias_id")
        self._key(operation_key, "operation_key")
        self._cut(cut)
        request = dict(kind="define", alias_id=alias_id, event=definition_event_id,
                       expected_head=expected_head)
        with self._tx() as db:
            old = self._op(db, operation_key, request)
            if old:
                result = old
            else:
                if expected_head != 0 or db.execute(
                    "SELECT 1 FROM alias_heads WHERE alias_id=?", (alias_id,)
                ).fetchone():
                    raise LifecycleConflict("Alias head already exists")
                raw, digest, _seq = self._raw(db, definition_event_id)
                control = raw["payload"].get("alias_control", {})
                if (raw["source"] != "user" or raw["type"] != "conversation.user"
                        or not isinstance(control, dict)
                        or set(control) != {"action", "alias_id", "surface", "target_entity_id"}
                        or control["action"] != "define" or control["alias_id"] != alias_id):
                    raise LifecycleConflict("Unverified alias definition source")
                surface = control["surface"]
                target = control["target_entity_id"]
                if (not isinstance(surface, str) or not surface.strip()
                        or not isinstance(target, str) or not target.strip()
                        or not any(r == {"kind": "entity", "id": target}
                                   for r in raw["references"])):
                    raise LifecycleConflict("Alias definition target not source-bound")
                record = dict(alias_id=alias_id, revision=1, state="active",
                              source_event_id=definition_event_id,
                              source_sha256=digest, surface=surface,
                              target_entity_id=target, authority="SOURCE_REPORT_LAB_ONLY")
                db.execute("INSERT INTO alias_heads VALUES(?,?,?,?,?,?,?)",
                           (alias_id, 1, "active", definition_event_id,
                            surface, target, raw["source"]))
                body = _json(record)
                db.execute("INSERT INTO alias_versions VALUES(?,?,?,?,?,?)",
                           (alias_id, 1, "active", definition_event_id,
                            body, _digest(body)))
                result = _receipt("Alias", status="created", alias_id=alias_id,
                                  revision=1, state="active")
                self._save_op(db, operation_key, request, result)
            if cut == "before_commit":
                raise LifecycleCut("Alias definition cut before commit")
        if cut == "after_commit":
            raise LifecycleCut("Alias definition cut after commit")
        return result

    def create_node(self, *, node_id, kind, source_event_ids,
                    alias_dependencies, node_dependencies, operation_key,
                    cut=None):
        self._key(node_id, "node_id")
        self._key(operation_key, "operation_key")
        self._cut(cut)
        if (kind not in ("Story", "Episode") or not isinstance(source_event_ids, list)
                or not source_event_ids or len(set(source_event_ids)) != len(source_event_ids)
                or not isinstance(alias_dependencies, list)
                or not isinstance(node_dependencies, list)):
            raise ValueError("Malformed derived node")
        aliases = [tuple(x) for x in alias_dependencies]
        parents = [tuple(x) for x in node_dependencies]
        all_deps = [("alias", *x) for x in aliases] + [("node", *x) for x in parents]
        if (len(all_deps) > MAX_EDGES or len(set(all_deps)) != len(all_deps)
                or not all(isinstance(x[1], str) and type(x[2]) is int
                           and x[2] >= 1 for x in all_deps)
                or not all(isinstance(x, str) for x in source_event_ids)):
            raise ValueError("Invalid or over-budget dependency edges")
        request = dict(kind="create_node", id=node_id, node_kind=kind,
                       sources=source_event_ids, edges=all_deps)
        with self._tx() as db:
            prior = self._op(db, operation_key, request)
            if prior:
                result = prior
            else:
                if db.execute("SELECT 1 FROM derived_heads WHERE node_id=?",
                              (node_id,)).fetchone():
                    raise LifecycleConflict("Derived node already exists")
                source_digests = {
                    source_id: self._raw(db, source_id)[1]
                    for source_id in source_event_ids
                }
                for alias_id, rev in aliases:
                    head = db.execute("SELECT * FROM alias_heads WHERE alias_id=?",
                                      (alias_id,)).fetchone()
                    if not head or head["revision"] != rev or head["state"] != "active":
                        raise LifecycleConflict("Stale alias dependency")
                    self._alias_version(db, alias_id, rev)
                for parent_id, rev in parents:
                    head = db.execute("SELECT * FROM derived_heads WHERE node_id=?",
                                      (parent_id,)).fetchone()
                    if not head or head["revision"] != rev or head["state"] != "current":
                        raise LifecycleConflict("Missing or stale upstream derived node")
                    self._node_version(db, parent_id, rev)
                record = dict(node_id=node_id, revision=1, kind=kind,
                              state="current", source_event_ids=source_event_ids,
                              source_sha256=source_digests,
                              dependencies=all_deps, authority="LAB_ONLY")
                body = _json(record)
                db.execute("INSERT INTO derived_heads VALUES(?,?,?,?)",
                           (node_id, kind, 1, "current"))
                db.execute("INSERT INTO derived_versions VALUES(?,?,?,?)",
                           (node_id, 1, body, _digest(body)))
                for dep_kind, dep_id, dep_rev in all_deps:
                    db.execute("INSERT INTO edges VALUES(?,?,?,?,?)",
                               (node_id, 1, dep_kind, dep_id, dep_rev))
                result = _receipt("Derived", status="created", node_id=node_id,
                                  revision=1, state="current")
                self._save_op(db, operation_key, request, result)
            if cut == "before_commit":
                raise LifecycleCut("Derived seed cut before commit")
        if cut == "after_commit":
            raise LifecycleCut("Derived seed cut after commit")
        return result

    @staticmethod
    def _downstream(db, kind, identifier, revision):
        return db.execute("""
            SELECT DISTINCT h.node_id, h.revision
            FROM edges e JOIN derived_heads h
                ON h.node_id=e.node_id AND h.revision=e.node_revision
            WHERE e.upstream_kind=? AND e.upstream_id=? AND e.upstream_revision=?
              AND h.state='current'
            ORDER BY h.node_id
            """, (kind, identifier, revision)).fetchall()

    def revoke(self, *, alias_id, revocation_event_id, expected_head,
               operation_key, cut=None):
        self._key(alias_id, "alias_id")
        self._key(operation_key, "operation_key")
        self._cut(cut)
        request = dict(kind="revoke", alias_id=alias_id,
                       event=revocation_event_id, expected_head=expected_head)
        with self._tx() as db:
            prior = self._op(db, operation_key, request)
            if prior:
                result = prior
            else:
                head = db.execute("SELECT * FROM alias_heads WHERE alias_id=?",
                                  (alias_id,)).fetchone()
                if (not head or head["revision"] != expected_head
                        or head["state"] != "active"):
                    raise LifecycleConflict("Alias head already changed")
                self._alias_version(db, alias_id, expected_head)
                original, def_digest, def_seq = self._raw(db, head["definition_event_id"])
                revoke_raw, revoke_digest, revoke_seq = self._raw(db, revocation_event_id)
                control = revoke_raw["payload"].get("alias_control", {})
                refs = [r["id"] for r in revoke_raw["references"] if r["kind"] == "event"]
                if (revoke_raw["source"] != original["source"] or
                        revoke_raw["source"] != "user" or
                        revoke_raw["type"] != "conversation.user" or
                        not isinstance(control, dict) or
                        control != {"action": "revoke", "alias_id": alias_id,
                                    "definition_event_id": head["definition_event_id"]} or
                        refs != [head["definition_event_id"]] or
                        revoke_seq <= def_seq or
                        datetime.fromisoformat(revoke_raw["timestamp"]) <=
                        datetime.fromisoformat(original["timestamp"])):
                    raise LifecycleConflict("Revocation source/identity not bound")
                record = dict(alias_id=alias_id, revision=expected_head + 1,
                              previous_revision=expected_head, state="revoked",
                              definition_event_id=head["definition_event_id"],
                              definition_sha256=def_digest,
                              revocation_event_id=revocation_event_id,
                              revocation_sha256=revoke_digest,
                              authority="SOURCE_REPORT_LAB_ONLY")
                body = _json(record)
                db.execute("INSERT INTO alias_versions VALUES(?,?,?,?,?,?)",
                           (alias_id, expected_head + 1, "revoked",
                            revocation_event_id, body, _digest(body)))
                db.execute("UPDATE alias_heads SET revision=?,state='revoked' WHERE alias_id=?",
                           (expected_head + 1, alias_id))
                pending = [("alias", alias_id, expected_head)]
                affected = []
                visited = set()
                while pending:
                    upstream = pending.pop(0)
                    for downstream in self._downstream(db, *upstream):
                        node_id, node_rev = downstream["node_id"], downstream["revision"]
                        if node_id in visited:
                            continue
                        visited.add(node_id)
                        if len(visited) > MAX_EDGES:
                            raise LifecycleConflict("Dependency invalidation exceeds budget")
                        self._node_version(db, node_id, node_rev)
                        db.execute(
                            "UPDATE derived_heads SET state='stale' "
                            "WHERE node_id=? AND revision=? AND state='current'",
                            (node_id, node_rev),
                        )
                        db.execute("INSERT INTO invalidations VALUES(?,?,?,?)",
                                   (operation_key, node_id, node_rev,
                                    revocation_event_id))
                        affected.append(node_id)
                        pending.append(("node", node_id, node_rev))
                result = _receipt("Alias", status="revoked",
                                  alias_id=alias_id, revision=expected_head + 1,
                                  affected_nodes=sorted(affected),
                                  invalidation_count=len(affected))
                self._save_op(db, operation_key, request, result)
            if cut == "before_commit":
                raise LifecycleCut("Alias revoke cut before commit")
        if cut == "after_commit":
            raise LifecycleCut("Alias revoke cut after commit")
        return result

    def reassess_unresolved(self, *, node_id, expected_head, operation_key,
                            cut=None):
        self._key(node_id, "node_id")
        self._key(operation_key, "operation_key")
        self._cut(cut)
        request = dict(kind="reassess_unresolved", node_id=node_id,
                       expected_head=expected_head)
        with self._tx() as db:
            old = self._op(db, operation_key, request)
            if old:
                result = old
            else:
                head = db.execute("SELECT * FROM derived_heads WHERE node_id=?",
                                  (node_id,)).fetchone()
                if (not head or head["revision"] != expected_head
                        or head["state"] != "stale"):
                    raise LifecycleConflict("Node not stale at requested revision")
                previous = self._node_version(db, node_id, expected_head)
                new_rev = expected_head + 1
                record = dict(node_id=node_id, revision=new_rev,
                              previous_revision=expected_head, kind=head["kind"],
                              state="unresolved", source_event_ids=previous["source_event_ids"],
                              source_sha256=previous["source_sha256"],
                              dependencies=[], authority="LAB_ONLY",
                              reason="prior_alias_dependency_revoked")
                body = _json(record)
                db.execute("INSERT INTO derived_versions VALUES(?,?,?,?)",
                           (node_id, new_rev, body, _digest(body)))
                db.execute("UPDATE derived_heads SET revision=?,state='unresolved' "
                           "WHERE node_id=?", (new_rev, node_id))
                result = _receipt("Derived", status="unresolved",
                                  node_id=node_id, revision=new_rev)
                self._save_op(db, operation_key, request, result)
            if cut == "before_commit":
                raise LifecycleCut("Derived reassess cut before commit")
        if cut == "after_commit":
            raise LifecycleCut("Derived reassess cut after commit")
        return result

    def alias(self, alias_id, revision=None):
        with self._connection() as db:
            head = db.execute("SELECT * FROM alias_heads WHERE alias_id=?",
                              (alias_id,)).fetchone()
            if head is None:
                raise KeyError("Unknown alias")
            target = head["revision"] if revision is None else revision
            record = self._alias_version(db, alias_id, target)
            definition, digest, _seq = self._raw(db, head["definition_event_id"])
            if record.get("source_sha256", record.get("definition_sha256")) != digest:
                raise LifecycleIntegrity("Alias definition source hash mismatch")
            if target > 1:
                _raw, event_hash, _seq2 = self._raw(db, record["revocation_event_id"])
                if event_hash != record["revocation_sha256"]:
                    raise LifecycleIntegrity("Alias revocation source hash mismatch")
            return {"record": record, "head_revision": head["revision"],
                    "head_state": head["state"], "is_head": target == head["revision"],
                    "production_admission": False}

    def node(self, node_id, revision=None):
        with self._connection() as db:
            head = db.execute("SELECT * FROM derived_heads WHERE node_id=?",
                              (node_id,)).fetchone()
            if head is None:
                raise KeyError("Unknown derived node")
            target = head["revision"] if revision is None else revision
            record = self._node_version(db, node_id, target)
            for src_id, digest in record["source_sha256"].items():
                if self._raw(db, src_id)[1] != digest:
                    raise LifecycleIntegrity("Derived source hash mismatch")
            links = [
                [row["upstream_kind"], row["upstream_id"], row["upstream_revision"]]
                for row in db.execute(
                    "SELECT upstream_kind,upstream_id,upstream_revision FROM edges "
                    "WHERE node_id=? AND node_revision=? ORDER BY upstream_kind,upstream_id",
                    (node_id, target),
                )
            ]
            if sorted(links) != sorted(record["dependencies"]):
                raise LifecycleIntegrity("Derived dependency links tampered")
            return {"record": record, "head_revision": head["revision"],
                    "head_state": head["state"], "is_head": target == head["revision"],
                    "eligible_for_lab_preflight": (target == head["revision"] and
                                                   head["state"] == "current"),
                    "production_admission": False}

    def invalidations(self, operation_key):
        with self._connection() as db:
            return [
                row["node_id"] for row in db.execute(
                    "SELECT node_id FROM invalidations WHERE operation_key=? ORDER BY node_id",
                    (operation_key,),
                )
            ]

    def count(self, table):
        if table not in {"raw_events", "alias_versions", "derived_versions",
                         "invalidations", "operations"}:
            raise ValueError("Unknown laboratory table")
        with self._connection() as db:
            return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
