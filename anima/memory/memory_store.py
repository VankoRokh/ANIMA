import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


SCHEMA_VERSION = 1
# R5: persist the canonical Raw EventLog authority once bound. All
# terminal Knowledge writes require this binding; standalone/unbound stores
# remain readable and may create provisional records, but cannot publish
# terminal Knowledge without verified Raw. Kept in schema_meta without
# changing the table schema.
RAW_PROVENANCE_META_KEY = "knowledge_raw_provenance_policy"
RAW_PROVENANCE_META_VALUE = "canonical_events_jsonl_v1"
MEMORY_TYPES = {"episodic", "procedural"}
MEMORY_DOMAINS = {
    "self",
    "user",
    "project",
    "environment",
    "system",
}
MEMORY_STATUSES = {"open", "closed", "merged"}
MEMORY_ID_PREFIX = "mem_"
_UNSET = object()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('episodic', 'procedural')),
    domain TEXT NOT NULL CHECK (
        domain IN ('self', 'user', 'project', 'environment', 'system')
    ),
    status TEXT NOT NULL CHECK (status IN ('open', 'closed', 'merged')),
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 1 CHECK (importance BETWEEN 0 AND 3),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    merged_into TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_status
    ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_domain
    ON memories(domain);
CREATE INDEX IF NOT EXISTS idx_memories_type
    ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories(created_at);

CREATE TABLE IF NOT EXISTS memory_sources (
    memory_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    PRIMARY KEY (memory_id, event_id),
    FOREIGN KEY (memory_id) REFERENCES memories(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_sources_event
    ON memory_sources(event_id);

CREATE TABLE IF NOT EXISTS knowledge (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL CHECK (
        domain IN ('self', 'user', 'project', 'environment', 'system')
    ),
    statement TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('provisional', 'confirmed', 'challenged', 'superseded', 'rejected')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_status
    ON knowledge(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_domain
    ON knowledge(domain);

CREATE TABLE IF NOT EXISTS knowledge_sources (
    knowledge_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('supports', 'contradicts')),
    PRIMARY KEY (knowledge_id, memory_id, relation),
    FOREIGN KEY (knowledge_id) REFERENCES knowledge(public_id) ON DELETE CASCADE,
    FOREIGN KEY (memory_id) REFERENCES memories(public_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS entities (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_type
    ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name
    ON entities(canonical_name);

CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    PRIMARY KEY (entity_id, alias),
    FOREIGN KEY (entity_id) REFERENCES entities(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_alias
    ON entity_aliases(alias);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (memory_id, entity_id),
    FOREIGN KEY (memory_id) REFERENCES memories(public_id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES entities(public_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge_entities (
    knowledge_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (knowledge_id, entity_id),
    FOREIGN KEY (knowledge_id) REFERENCES knowledge(public_id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES entities(public_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relations (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    valid_until TEXT,
    source_memory_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_relations_source
    ON relations(source_kind, source_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_target
    ON relations(target_kind, target_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_type
    ON relations(relation_type);

CREATE TABLE IF NOT EXISTS history (
    row_id INTEGER PRIMARY KEY,
    object_kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source_kind TEXT,
    source_id TEXT,
    changes_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_object
    ON history(object_kind, object_id, timestamp);

CREATE TABLE IF NOT EXISTS event_processing (
    event_id TEXT NOT NULL,
    processor TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'processing', 'done', 'failed', 'skipped')
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    started_at TEXT,
    finished_at TEXT,
    last_error TEXT,
    PRIMARY KEY (event_id, processor, processor_version)
);

CREATE INDEX IF NOT EXISTS idx_event_processing_status
    ON event_processing(status);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
USING fts5(public_id UNINDEXED, content);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
USING fts5(public_id UNINDEXED, statement);

CREATE TRIGGER IF NOT EXISTS memories_fts_insert
AFTER INSERT ON memories BEGIN
    INSERT INTO memory_fts(rowid, public_id, content)
    VALUES (new.row_id, new.public_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_update
AFTER UPDATE OF public_id, content ON memories BEGIN
    DELETE FROM memory_fts WHERE rowid = old.row_id;
    INSERT INTO memory_fts(rowid, public_id, content)
    VALUES (new.row_id, new.public_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_delete
AFTER DELETE ON memories BEGIN
    DELETE FROM memory_fts WHERE rowid = old.row_id;
END;

CREATE TRIGGER IF NOT EXISTS knowledge_fts_insert
AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, public_id, statement)
    VALUES (new.row_id, new.public_id, new.statement);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_fts_update
AFTER UPDATE OF public_id, statement ON knowledge BEGIN
    DELETE FROM knowledge_fts WHERE rowid = old.row_id;
    INSERT INTO knowledge_fts(rowid, public_id, statement)
    VALUES (new.row_id, new.public_id, new.statement);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_fts_delete
AFTER DELETE ON knowledge BEGIN
    DELETE FROM knowledge_fts WHERE rowid = old.row_id;
END;
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_timestamp(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty ISO 8601 string")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")


def _validate_memory_id(public_id):
    if (
        not isinstance(public_id, str)
        or not public_id.startswith(MEMORY_ID_PREFIX)
    ):
        raise ValueError("Memory public_id must be a mem_ UUIDv4")

    raw_uuid = public_id[len(MEMORY_ID_PREFIX):]

    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError("Memory public_id must be a mem_ UUIDv4") from error

    if parsed.version != 4 or str(parsed) != raw_uuid:
        raise ValueError("Memory public_id must be a mem_ UUIDv4")


def _validate_memory_fields(
    *,
    memory_type,
    domain,
    status,
    content,
    importance,
    created_at,
):
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"Unknown memory type: {memory_type!r}")

    if domain not in MEMORY_DOMAINS:
        raise ValueError(f"Unknown memory domain: {domain!r}")

    if status not in MEMORY_STATUSES:
        raise ValueError(f"Unknown memory status: {status!r}")

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Memory content must be a non-empty string")

    if (
        not isinstance(importance, int)
        or isinstance(importance, bool)
        or importance not in range(4)
    ):
        raise ValueError("Memory importance must be an integer from 0 to 3")

    _validate_timestamp(created_at, "Memory created_at")


def validate_memory_record(memory):
    """Validate the temporary Runtime -> MemoryStore boundary used in Stage 1.2."""
    if not isinstance(memory, dict):
        raise ValueError("Memory record must be an object")

    required_fields = {
        "type",
        "domain",
        "status",
        "content",
        "importance",
        "created_at",
        "source_event_id",
    }

    if set(memory) != required_fields:
        missing = required_fields - memory.keys()
        unknown = memory.keys() - required_fields
        details = []

        if missing:
            details.append("missing: " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown: " + ", ".join(sorted(unknown)))

        raise ValueError("Invalid memory record fields (" + "; ".join(details) + ")")

    _validate_memory_fields(
        memory_type=memory["type"],
        domain=memory["domain"],
        status=memory["status"],
        content=memory["content"],
        importance=memory["importance"],
        created_at=memory["created_at"],
    )

    source_event_id = memory["source_event_id"]
    if not isinstance(source_event_id, str) or not source_event_id.startswith("ev_"):
        raise ValueError("Memory source_event_id must be an ev_ ID")

    return memory


class MemoryStore:
    def __init__(self, database_file="data/memory.db", *, event_log=None):
        self.database_file = Path(database_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if event_log is not None:
            self.bind_event_log(event_log)

    def bind_event_log(self, event_log):
        """Persist Raw verification for every KnowledgeLayer using this DB.

        The binding must be the canonical sibling events.jsonl. A reopened
        MemoryStore without an explicit EventLog still honors the persisted
        policy; this prevents accidental bypass by a second Python store.
        """
        from anima.memory.event_log import EventLog

        if not isinstance(event_log, EventLog):
            raise TypeError("Raw provenance binding requires EventLog")
        expected = (self.database_file.parent / "events.jsonl").resolve()
        actual = event_log.log_file.resolve()
        if actual != expected:
            raise ValueError(
                "Raw provenance requires canonical sibling events.jsonl"
            )
        with self.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (RAW_PROVENANCE_META_KEY,),
            ).fetchone()
            if (
                existing is not None
                and existing["value"] != RAW_PROVENANCE_META_VALUE
            ):
                raise ValueError("Unsupported Raw provenance policy")
            if existing is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES (?, ?)",
                    (RAW_PROVENANCE_META_KEY, RAW_PROVENANCE_META_VALUE),
                )

    def require_knowledge_raw_sources(self, connection, memory_ids):
        """Require all declared Memory source IDs to exist in complete Raw.

        Runs inside the caller's Knowledge SQLite transaction. All Raw rows
        are validated, not looked up in a stale ID cache. The check proves
        Raw *existence*, not that Memory text faithfully represents Raw.
        Cross-file atomicity against uncooperative writers is not claimed.

        R5: an unbound standalone/legacy store is readable but cannot
        finalize Knowledge without a canonical Raw binding. No silent
        transition to verified, no test-only bypass or auto migration.
        """
        from anima.memory.event_log import EventLog

        policy = connection.execute(
            "SELECT value FROM schema_meta WHERE key = ?",
            (RAW_PROVENANCE_META_KEY,),
        ).fetchone()
        if policy is None:
            raise ValueError(
                "Knowledge Raw provenance is unbound: "
                "bind the canonical EventLog before terminal transition"
            )
        if policy["value"] != RAW_PROVENANCE_META_VALUE:
            raise ValueError("Unsupported Raw provenance policy")

        unique_ids = sorted(set(memory_ids))
        if not unique_ids:
            raise ValueError("Knowledge Raw provenance needs Memory evidence")
        for memory_id in unique_ids:
            _validate_memory_id(memory_id)
        placeholders = ",".join("?" for _ in unique_ids)
        rows = connection.execute(
            "SELECT memory_id, event_id FROM memory_sources "
            f"WHERE memory_id IN ({placeholders})",
            tuple(unique_ids),
        ).fetchall()
        declared = {memory_id: set() for memory_id in unique_ids}
        for row in rows:
            declared[row["memory_id"]].add(row["event_id"])
        missing_sources = [
            memory_id for memory_id, event_ids in declared.items()
            if not event_ids
        ]
        if missing_sources:
            raise ValueError(
                "Knowledge Raw provenance requires source Events for Memory: "
                + ", ".join(missing_sources)
            )

        # EventLog.load_events validates every physical LF, Event shape and
        # duplicate ID before returning; it does not trust an ID cache.
        events_file = self.database_file.parent / "events.jsonl"
        raw_ids = {
            record["id"] for record in EventLog(events_file).load_events()
        }
        unavailable = sorted({
            source_id
            for event_ids in declared.values()
            for source_id in event_ids
            if source_id not in raw_ids
        })
        if unavailable:
            raise ValueError(
                "Knowledge Raw provenance missing source Event(s): "
                + ", ".join(unavailable)
            )
        return True

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _require_supported_existing_schema(self, connection):
        """Validate version metadata before any schema-writing statement.

        Missing schema_meta/version remains an explicitly supported legacy
        bootstrap input. An *existing* unknown version is never migrated
        or modified through constructor side effects.
        """
        schema_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'schema_meta'"
        ).fetchone()
        if schema_table is None:
            return
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None and row["value"] != str(SCHEMA_VERSION):
            raise ValueError(
                "Unsupported memory database schema in "
                f"{self.database_file}"
            )

    def _initialize(self):
        # R7.3 / H56-04: a database with a future/unknown schema must not
        # acquire *any* DDL side effects merely because it was opened.
        # Keep the version preflight and the schema bootstrap under one
        # BEGIN IMMEDIATE lock. sqlite3.executescript() is not suitable:
        # it implicitly COMMITs a pending transaction before executing DDL.
        try:
            if self.database_file.is_file():
                # Existing DBs are screened before opening a writable
                # connection. Do not take a write lock on an already-known
                # unsupported version. URI escaping handles spaces and ?.
                uri = self.database_file.resolve().as_uri() + "?mode=ro"
                with closing(sqlite3.connect(uri, uri=True)) as readonly:
                    readonly.row_factory = sqlite3.Row
                    readonly.execute("PRAGMA query_only = ON")
                    self._require_supported_existing_schema(readonly)

            with self.transaction(immediate=True) as connection:
                # Recheck under the actual writer lock: a concurrent
                # cooperative schema writer cannot invalidate the preflight
                # between read-only inspection and transactional bootstrap.
                self._require_supported_existing_schema(connection)

                # sqlite3.complete_statement recognizes BEGIN/END inside
                # FTS triggers. Each full DDL statement is executed with
                # execute(), preserving transactional rollback on failure.
                statement = ""
                for line in SCHEMA_SQL.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        connection.execute(statement)
                        statement = ""
                if statement.strip():
                    raise ValueError("Incomplete memory schema SQL")

                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(key, value) "
                    "VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                row = connection.execute(
                    "SELECT value FROM schema_meta "
                    "WHERE key = 'schema_version'"
                ).fetchone()
                if row is None or row["value"] != str(SCHEMA_VERSION):
                    raise ValueError(
                        "Unsupported memory database schema in "
                        f"{self.database_file}"
                    )
        except sqlite3.DatabaseError as error:
            raise ValueError(
                f"Cannot initialize memory database {self.database_file}: {error}"
            ) from error

    @contextmanager
    def transaction(self, *, immediate=False):
        """Use an immediate write lock for operations that must claim first."""
        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _row_to_memory(row):
        if row is None:
            return None

        return {
            "id": row["public_id"],
            "type": row["type"],
            "domain": row["domain"],
            "status": row["status"],
            "content": row["content"],
            "importance": row["importance"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "closed_at": row["closed_at"],
            "merged_into": row["merged_into"],
        }

    def schema_version(self):
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    def create_memory(
        self,
        *,
        memory_type,
        domain,
        content,
        status="open",
        importance=1,
        created_at=None,
        public_id=None,
        source_event_id=None,
    ):
        public_id = public_id or f"{MEMORY_ID_PREFIX}{uuid4()}"
        created_at = created_at or _now()

        _validate_memory_id(public_id)
        _validate_memory_fields(
            memory_type=memory_type,
            domain=domain,
            status=status,
            content=content,
            importance=importance,
            created_at=created_at,
        )

        if source_event_id is not None:
            if not isinstance(source_event_id, str) or not source_event_id.startswith("ev_"):
                raise ValueError("source_event_id must be an ev_ ID or null")

        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO memories(
                        public_id, type, domain, status, content, importance,
                        created_at, updated_at, closed_at, merged_into
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        public_id,
                        memory_type,
                        domain,
                        status,
                        content,
                        importance,
                        created_at,
                        created_at,
                    ),
                )

                if source_event_id is not None:
                    connection.execute(
                        "INSERT INTO memory_sources(memory_id, event_id) VALUES (?, ?)",
                        (public_id, source_event_id),
                    )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Cannot create memory {public_id}: {error}") from error

        return self.get_memory(public_id)

    def write(self, memory):
        validate_memory_record(memory)
        return self.create_memory(
            memory_type=memory["type"],
            domain=memory["domain"],
            status=memory["status"],
            content=memory["content"],
            importance=memory["importance"],
            created_at=memory["created_at"],
            source_event_id=memory["source_event_id"],
        )

    def get_memory(self, public_id):
        _validate_memory_id(public_id)

        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE public_id = ?",
                (public_id,),
            ).fetchone()

        return self._row_to_memory(row)

    def list_memories(self):
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM memories ORDER BY row_id"
            ).fetchall()

        return [self._row_to_memory(row) for row in rows]

    def count(self):
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM memories"
            ).fetchone()
        return row["count"]

    def last(self, limit=5):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("Memory limit must be a non-negative integer")

        if limit == 0:
            return []

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM memories ORDER BY row_id DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [self._row_to_memory(row) for row in reversed(rows)]

    def source_events(self, public_id):
        _validate_memory_id(public_id)

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT event_id FROM memory_sources WHERE memory_id = ? ORDER BY event_id",
                (public_id,),
            ).fetchall()

        return [row["event_id"] for row in rows]

    @staticmethod
    def _require_no_confirmed_knowledge_dependencies(connection, memory_id):
        """Fail closed before changing a Memory used by confirmed Knowledge.

        A finalized Knowledge transition is not a permanent proof that the
        supporting Memory will remain CLOSED and unchanged. Until an explicit
        Knowledge revision/invalidation protocol exists, protect both current
        and historical supports/contradicts dependencies, including relations
        with a finite valid_until. The guard runs under the same SQLite writer
        lock as the subsequent mutation; direct SQL remains outside the API
        contract.
        """
        dependent = connection.execute(
            """
            SELECT r.public_id AS relation_id, k.public_id AS knowledge_id
            FROM relations AS r
            JOIN knowledge AS k ON k.public_id = r.target_id
            WHERE k.status = 'confirmed'
              AND r.target_kind = 'knowledge'
              AND r.relation_type IN ('supports', 'contradicts')
              AND (
                    (r.source_kind = 'memory' AND r.source_id = ?)
                    OR r.source_memory_id = ?
                  )
            LIMIT 1
            """,
            (memory_id, memory_id),
        ).fetchone()
        if dependent is not None:
            raise ValueError(
                "Cannot mutate Memory with confirmed Knowledge evidence: "
                f"{memory_id} (knowledge={dependent['knowledge_id']})"
            )

    def update_memory(
        self,
        public_id,
        *,
        content=_UNSET,
        status=_UNSET,
        importance=_UNSET,
        closed_at=_UNSET,
        merged_into=_UNSET,
        updated_at=None,
    ):
        _validate_memory_id(public_id)
        current = self.get_memory(public_id)

        if current is None:
            raise ValueError(f"Unknown memory: {public_id}")

        assignments = []
        values = []

        if content is not _UNSET:
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Memory content must be a non-empty string")
            assignments.append("content = ?")
            values.append(content)

        if status is not _UNSET:
            if status not in MEMORY_STATUSES:
                raise ValueError(f"Unknown memory status: {status!r}")
            assignments.append("status = ?")
            values.append(status)

        if importance is not _UNSET:
            if (
                not isinstance(importance, int)
                or isinstance(importance, bool)
                or importance not in range(4)
            ):
                raise ValueError("Memory importance must be an integer from 0 to 3")
            assignments.append("importance = ?")
            values.append(importance)

        if closed_at is not _UNSET:
            if closed_at is not None:
                _validate_timestamp(closed_at, "Memory closed_at")
            assignments.append("closed_at = ?")
            values.append(closed_at)

        if merged_into is not _UNSET:
            if merged_into is not None:
                _validate_memory_id(merged_into)
            assignments.append("merged_into = ?")
            values.append(merged_into)

        if not assignments:
            raise ValueError("No memory fields supplied for update")

        updated_at = updated_at or _now()
        _validate_timestamp(updated_at, "Memory updated_at")
        assignments.append("updated_at = ?")
        values.append(updated_at)
        values.append(public_id)

        # Serialize the evidence check with Knowledge confirmation and
        # public Relation writers. A separate preflight would race a confirm.
        with self.transaction(immediate=True) as connection:
            self._require_no_confirmed_knowledge_dependencies(
                connection, public_id,
            )
            connection.execute(
                "UPDATE memories SET "
                + ", ".join(assignments)
                + " WHERE public_id = ?",
                values,
            )

        return self.get_memory(public_id)

    def delete_memory(self, public_id):
        _validate_memory_id(public_id)

        # Relations have polymorphic IDs and no SQLite foreign keys to
        # memories. A plain DELETE would strand evidence/provenance (N4).
        # Prefer refusing deletion to silently cascading historical proof.
        # BEGIN IMMEDIATE serializes this check with public relation writers.
        with self.transaction(immediate=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM memories WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if exists is None:
                return False

            # R4.1/F-03: a committed "done" processing ledger entry
            # owns the durable Event -> Memory projection. Deleting its
            # last (or any) Memory would leave a finalized event without a
            # recoverable result: replay would otherwise return
            # already_done/memory_id=None. The guard is in the SAME writer
            # transaction as DELETE and covers all historical processor
            # versions, while preserving deletion of unprocessed fixtures.
            finalized_projection = connection.execute(
                """
                SELECT ep.event_id, ep.processor_version
                FROM memory_sources AS ms
                JOIN event_processing AS ep ON ep.event_id = ms.event_id
                WHERE ms.memory_id = ?
                  AND ep.processor = 'memory_processor'
                  AND ep.status = 'done'
                ORDER BY ep.event_id, ep.processor_version
                LIMIT 1
                """,
                (public_id,),
            ).fetchone()
            if finalized_projection is not None:
                raise ValueError(
                    "Cannot delete Memory with finalized Event processing "
                    "projection: "
                    f"{public_id} (event={finalized_projection['event_id']}, "
                    f"version={finalized_projection['processor_version']})"
                )

            related = connection.execute(
                """
                SELECT 1 FROM relations
                WHERE (source_kind = 'memory' AND source_id = ?)
                   OR (target_kind = 'memory' AND target_id = ?)
                   OR source_memory_id = ?
                LIMIT 1
                """,
                (public_id, public_id, public_id),
            ).fetchone()
            legacy_source = connection.execute(
                "SELECT 1 FROM knowledge_sources WHERE memory_id = ? LIMIT 1",
                (public_id,),
            ).fetchone()
            history_reference = connection.execute(
                """
                SELECT 1 FROM history
                WHERE (source_kind = 'memory' AND source_id = ?)
                   OR (object_kind = 'memory' AND object_id = ?)
                LIMIT 1
                """,
                (public_id, public_id),
            ).fetchone()
            legacy_entity = connection.execute(
                "SELECT 1 FROM memory_entities WHERE memory_id = ? LIMIT 1",
                (public_id,),
            ).fetchone()
            merged_target = connection.execute(
                "SELECT 1 FROM memories WHERE merged_into = ? LIMIT 1",
                (public_id,),
            ).fetchone()
            if (
                related or legacy_source or history_reference
                or legacy_entity or merged_target
            ):
                raise ValueError(
                    "Cannot delete Memory with evidence, relations or "
                    f"history dependencies: {public_id}"
                )

            cursor = connection.execute(
                "DELETE FROM memories WHERE public_id = ?",
                (public_id,),
            )

        return cursor.rowcount == 1

    def search_memories(self, query, limit=10):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Memory search query must be a non-empty string")

        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("Memory search limit must be a positive integer")

        try:
            with closing(self._connect()) as connection, connection:
                rows = connection.execute(
                    """
                    SELECT m.*
                    FROM memory_fts f
                    JOIN memories m ON m.row_id = f.rowid
                    WHERE memory_fts MATCH ?
                    ORDER BY bm25(memory_fts), m.row_id
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
        except sqlite3.OperationalError as error:
            raise ValueError(f"Invalid FTS query: {query!r}") from error

        return [self._row_to_memory(row) for row in rows]

    def export_debug(self):
        """Small structured snapshot for tests/debugging; not a backup format."""
        with closing(self._connect()) as connection, connection:
            tables = [
                row["name"]
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type IN ('table', 'view')
                    ORDER BY name
                    """
                ).fetchall()
            ]

        return {
            "schema_version": self.schema_version(),
            "tables": tables,
            "memory_count": self.count(),
        }
