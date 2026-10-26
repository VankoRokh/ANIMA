import json
from datetime import datetime, timezone
from uuid import uuid4

from anima.memory.link_store import (
    KNOWLEDGE_ID_PREFIX,
    RELATION_ID_PREFIX,
    _validate_public_id,
    _validate_timestamp,
)
from anima.memory.memory_store import (
    MEMORY_DOMAINS,
    _validate_memory_id,
)


class KnowledgeLayer:
    """Explicit Stage 1.7 Knowledge lifecycle with Memory-backed evidence."""

    def __init__(self, *, memory_store, trace=None):
        self.memory_store = memory_store
        self.trace = trace

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _parsed_time(value):
        return datetime.fromisoformat(value)

    @classmethod
    def _require_not_before(cls, timestamp, reference, label):
        if cls._parsed_time(timestamp) < cls._parsed_time(reference):
            raise ValueError(f"{label} cannot be earlier than {reference}")

    @staticmethod
    def _clean_statement(statement):
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("Knowledge statement must be a non-empty string")
        return " ".join(statement.split())

    @staticmethod
    def _row_to_knowledge(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "domain": row["domain"],
            "statement": row["statement"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _history_payload(changes):
        return json.dumps(
            changes,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _insert_history(
        connection,
        *,
        knowledge_id,
        operation,
        timestamp,
        source_kind=None,
        source_id=None,
        changes,
    ):
        connection.execute(
            """
            INSERT INTO history(
                object_kind,
                object_id,
                operation,
                timestamp,
                source_kind,
                source_id,
                changes_json
            ) VALUES ('knowledge', ?, ?, ?, ?, ?, ?)
            """,
            (
                knowledge_id,
                operation,
                timestamp,
                source_kind,
                source_id,
                KnowledgeLayer._history_payload(changes),
            ),
        )

    @staticmethod
    def _relation_row_to_dict(row):
        return {
            "id": row["public_id"],
            "source_kind": row["source_kind"],
            "source_id": row["source_id"],
            "type": row["relation_type"],
            "target_kind": row["target_kind"],
            "target_id": row["target_id"],
            "created_at": row["created_at"],
            "valid_until": row["valid_until"],
            "source_memory_id": row["source_memory_id"],
        }

    @staticmethod
    def _require_knowledge(connection, knowledge_id):
        _validate_public_id(
            knowledge_id,
            KNOWLEDGE_ID_PREFIX,
            "Knowledge public_id",
        )
        row = connection.execute(
            "SELECT * FROM knowledge WHERE public_id = ?",
            (knowledge_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown knowledge: {knowledge_id}")
        return row

    @staticmethod
    def _require_memory(connection, memory_id, *, closed=False):
        _validate_memory_id(memory_id)
        row = connection.execute(
            "SELECT * FROM memories WHERE public_id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown memory: {memory_id}")
        if closed and row["status"] != "closed":
            raise ValueError(
                "Knowledge evidence must be CLOSED memory: "
                f"{memory_id} is {row['status']}"
            )
        return row

    @staticmethod
    def _relation_exists(
        connection,
        *,
        source_kind,
        source_id,
        relation_type,
        target_kind,
        target_id,
        source_memory_id,
    ):
        return connection.execute(
            """
            SELECT public_id FROM relations
            WHERE source_kind = ? AND source_id = ?
              AND relation_type = ?
              AND target_kind = ? AND target_id = ?
              AND source_memory_id = ?
              AND valid_until IS NULL
            """,
            (
                source_kind,
                source_id,
                relation_type,
                target_kind,
                target_id,
                source_memory_id,
            ),
        ).fetchone()

    @classmethod
    def _insert_relation(
        cls,
        connection,
        *,
        source_kind,
        source_id,
        relation_type,
        target_kind,
        target_id,
        source_memory_id,
        created_at,
        reject_duplicate=True,
    ):
        duplicate = cls._relation_exists(
            connection,
            source_kind=source_kind,
            source_id=source_id,
            relation_type=relation_type,
            target_kind=target_kind,
            target_id=target_id,
            source_memory_id=source_memory_id,
        )
        if duplicate is not None:
            if reject_duplicate:
                raise ValueError(
                    "Equivalent relation already exists: "
                    f"{duplicate['public_id']}"
                )
            row = connection.execute(
                "SELECT * FROM relations WHERE public_id = ?",
                (duplicate["public_id"],),
            ).fetchone()
            return cls._relation_row_to_dict(row), False

        public_id = f"{RELATION_ID_PREFIX}{uuid4()}"
        connection.execute(
            """
            INSERT INTO relations(
                public_id,
                source_kind,
                source_id,
                relation_type,
                target_kind,
                target_id,
                created_at,
                valid_until,
                source_memory_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                public_id,
                source_kind,
                source_id,
                relation_type,
                target_kind,
                target_id,
                created_at,
                source_memory_id,
            ),
        )
        row = connection.execute(
            "SELECT * FROM relations WHERE public_id = ?",
            (public_id,),
        ).fetchone()
        return cls._relation_row_to_dict(row), True

    def create_candidate(
        self,
        *,
        domain,
        statement,
        source_memory_id,
        created_at=None,
        public_id=None,
    ):
        if domain not in MEMORY_DOMAINS:
            raise ValueError(f"Unknown knowledge domain: {domain!r}")
        statement = self._clean_statement(statement)
        public_id = public_id or f"{KNOWLEDGE_ID_PREFIX}{uuid4()}"
        created_at = created_at or self._now()
        _validate_public_id(
            public_id,
            KNOWLEDGE_ID_PREFIX,
            "Knowledge public_id",
        )
        _validate_timestamp(created_at, "Knowledge created_at")

        with self.memory_store.transaction() as connection:
            source = self._require_memory(
                connection,
                source_memory_id,
                closed=True,
            )
            self._require_not_before(
                created_at,
                source["updated_at"],
                "Knowledge created_at",
            )
            existing = connection.execute(
                "SELECT public_id FROM knowledge WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError(f"Knowledge already exists: {public_id}")

            connection.execute(
                """
                INSERT INTO knowledge(
                    public_id, domain, statement, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'provisional', ?, ?)
                """,
                (
                    public_id,
                    domain,
                    statement,
                    created_at,
                    created_at,
                ),
            )
            support, _ = self._insert_relation(
                connection,
                source_kind="memory",
                source_id=source_memory_id,
                relation_type="supports",
                target_kind="knowledge",
                target_id=public_id,
                source_memory_id=source_memory_id,
                created_at=created_at,
            )
            self._insert_history(
                connection,
                knowledge_id=public_id,
                operation="create",
                timestamp=created_at,
                source_kind="memory",
                source_id=source_memory_id,
                changes={
                    "statement": statement,
                    "status": [None, "provisional"],
                    "support_relation": support["id"],
                },
            )

        self._trace(
            "knowledge: create "
            f"knowledge={public_id} status=provisional source={source_memory_id}"
        )
        return self.describe(public_id)

    def investigate(
        self,
        knowledge_id,
        memory_id,
        *,
        created_at=None,
    ):
        created_at = created_at or self._now()
        _validate_timestamp(created_at, "Investigation created_at")

        with self.memory_store.transaction() as connection:
            knowledge = self._require_knowledge(connection, knowledge_id)
            memory = self._require_memory(connection, memory_id)
            if memory["status"] == "merged":
                raise ValueError("MERGED memory cannot open a new investigation")
            self._require_not_before(
                created_at,
                knowledge["updated_at"],
                "Investigation created_at",
            )
            self._require_not_before(
                created_at,
                memory["updated_at"],
                "Investigation created_at",
            )
            relation, _ = self._insert_relation(
                connection,
                source_kind="memory",
                source_id=memory_id,
                relation_type="investigates",
                target_kind="knowledge",
                target_id=knowledge_id,
                source_memory_id=memory_id,
                created_at=created_at,
            )

        self._trace(
            "knowledge: investigate "
            f"knowledge={knowledge_id} memory={memory_id} status={knowledge['status']}"
        )
        return relation

    def confirm(
        self,
        knowledge_id,
        *,
        source_memory_id=None,
        confirmed_at=None,
    ):
        confirmed_at = confirmed_at or self._now()
        _validate_timestamp(confirmed_at, "Knowledge confirmed_at")

        with self.memory_store.transaction() as connection:
            knowledge = self._require_knowledge(connection, knowledge_id)
            if knowledge["status"] not in {"provisional", "challenged"}:
                raise ValueError(
                    "Knowledge can be confirmed only from provisional or challenged: "
                    f"{knowledge_id} is {knowledge['status']}"
                )
            self._require_not_before(
                confirmed_at,
                knowledge["updated_at"],
                "Knowledge confirmed_at",
            )

            added_support = None
            if source_memory_id is not None:
                memory = self._require_memory(
                    connection,
                    source_memory_id,
                    closed=True,
                )
                self._require_not_before(
                    confirmed_at,
                    memory["updated_at"],
                    "Knowledge confirmed_at",
                )
                if (
                    knowledge["status"] == "challenged"
                    and self._relation_exists(
                        connection,
                        source_kind="memory",
                        source_id=source_memory_id,
                        relation_type="supports",
                        target_kind="knowledge",
                        target_id=knowledge_id,
                        source_memory_id=source_memory_id,
                    )
                    is not None
                ):
                    raise ValueError(
                        "Challenged knowledge requires new supporting evidence"
                    )
                added_support, _ = self._insert_relation(
                    connection,
                    source_kind="memory",
                    source_id=source_memory_id,
                    relation_type="supports",
                    target_kind="knowledge",
                    target_id=knowledge_id,
                    source_memory_id=source_memory_id,
                    created_at=confirmed_at,
                    reject_duplicate=False,
                )
            elif knowledge["status"] == "challenged":
                raise ValueError(
                    "Challenged knowledge requires new supporting evidence"
                )

            support_count = connection.execute(
                """
                SELECT COUNT(*) AS count FROM relations
                WHERE target_kind = 'knowledge' AND target_id = ?
                  AND relation_type = 'supports'
                  AND valid_until IS NULL
                """,
                (knowledge_id,),
            ).fetchone()["count"]
            if support_count == 0:
                raise ValueError("Knowledge cannot be confirmed without support")

            previous = knowledge["status"]
            connection.execute(
                """
                UPDATE knowledge
                SET status = 'confirmed', updated_at = ?
                WHERE public_id = ?
                """,
                (confirmed_at, knowledge_id),
            )
            self._insert_history(
                connection,
                knowledge_id=knowledge_id,
                operation="confirm",
                timestamp=confirmed_at,
                source_kind="memory" if source_memory_id else "manual",
                source_id=source_memory_id,
                changes={
                    "status": [previous, "confirmed"],
                    "support_relation": (
                        added_support["id"] if added_support else None
                    ),
                },
            )

        self._trace(
            "knowledge: confirm "
            f"knowledge={knowledge_id} status=confirmed"
        )
        return self.describe(knowledge_id)

    def challenge(
        self,
        knowledge_id,
        contradiction_memory_id,
        *,
        challenged_at=None,
    ):
        challenged_at = challenged_at or self._now()
        _validate_timestamp(challenged_at, "Knowledge challenged_at")

        with self.memory_store.transaction() as connection:
            knowledge = self._require_knowledge(connection, knowledge_id)
            if knowledge["status"] != "confirmed":
                raise ValueError(
                    "Only confirmed knowledge can be challenged: "
                    f"{knowledge_id} is {knowledge['status']}"
                )
            memory = self._require_memory(
                connection,
                contradiction_memory_id,
                closed=True,
            )
            self._require_not_before(
                challenged_at,
                knowledge["updated_at"],
                "Knowledge challenged_at",
            )
            self._require_not_before(
                challenged_at,
                memory["updated_at"],
                "Knowledge challenged_at",
            )
            contradiction, _ = self._insert_relation(
                connection,
                source_kind="memory",
                source_id=contradiction_memory_id,
                relation_type="contradicts",
                target_kind="knowledge",
                target_id=knowledge_id,
                source_memory_id=contradiction_memory_id,
                created_at=challenged_at,
            )
            connection.execute(
                """
                UPDATE knowledge
                SET status = 'challenged', updated_at = ?
                WHERE public_id = ?
                """,
                (challenged_at, knowledge_id),
            )
            self._insert_history(
                connection,
                knowledge_id=knowledge_id,
                operation="challenge",
                timestamp=challenged_at,
                source_kind="memory",
                source_id=contradiction_memory_id,
                changes={
                    "status": ["confirmed", "challenged"],
                    "contradiction_relation": contradiction["id"],
                },
            )

        self._trace(
            "knowledge: challenge "
            f"knowledge={knowledge_id} status=challenged"
        )
        return self.describe(knowledge_id)

    def reject(
        self,
        knowledge_id,
        *,
        contradiction_memory_id=None,
        rejected_at=None,
    ):
        rejected_at = rejected_at or self._now()
        _validate_timestamp(rejected_at, "Knowledge rejected_at")

        with self.memory_store.transaction() as connection:
            knowledge = self._require_knowledge(connection, knowledge_id)
            if knowledge["status"] != "challenged":
                raise ValueError(
                    "Only challenged knowledge can be rejected: "
                    f"{knowledge_id} is {knowledge['status']}"
                )
            self._require_not_before(
                rejected_at,
                knowledge["updated_at"],
                "Knowledge rejected_at",
            )

            added = None
            if contradiction_memory_id is not None:
                memory = self._require_memory(
                    connection,
                    contradiction_memory_id,
                    closed=True,
                )
                self._require_not_before(
                    rejected_at,
                    memory["updated_at"],
                    "Knowledge rejected_at",
                )
                added, _ = self._insert_relation(
                    connection,
                    source_kind="memory",
                    source_id=contradiction_memory_id,
                    relation_type="contradicts",
                    target_kind="knowledge",
                    target_id=knowledge_id,
                    source_memory_id=contradiction_memory_id,
                    created_at=rejected_at,
                    reject_duplicate=False,
                )

            contradiction_count = connection.execute(
                """
                SELECT COUNT(*) AS count FROM relations
                WHERE target_kind = 'knowledge' AND target_id = ?
                  AND relation_type = 'contradicts'
                  AND valid_until IS NULL
                """,
                (knowledge_id,),
            ).fetchone()["count"]
            if contradiction_count == 0:
                raise ValueError("Knowledge cannot be rejected without contradiction")

            connection.execute(
                """
                UPDATE knowledge
                SET status = 'rejected', updated_at = ?
                WHERE public_id = ?
                """,
                (rejected_at, knowledge_id),
            )
            self._insert_history(
                connection,
                knowledge_id=knowledge_id,
                operation="reject",
                timestamp=rejected_at,
                source_kind=(
                    "memory" if contradiction_memory_id else "manual"
                ),
                source_id=contradiction_memory_id,
                changes={
                    "status": ["challenged", "rejected"],
                    "contradiction_relation": added["id"] if added else None,
                },
            )

        self._trace(
            "knowledge: reject "
            f"knowledge={knowledge_id} status=rejected"
        )
        return self.describe(knowledge_id)

    def supersede(
        self,
        knowledge_id,
        *,
        statement,
        source_memory_id,
        superseded_at=None,
        public_id=None,
    ):
        statement = self._clean_statement(statement)
        superseded_at = superseded_at or self._now()
        public_id = public_id or f"{KNOWLEDGE_ID_PREFIX}{uuid4()}"
        _validate_timestamp(superseded_at, "Knowledge superseded_at")
        _validate_public_id(
            public_id,
            KNOWLEDGE_ID_PREFIX,
            "Knowledge public_id",
        )

        with self.memory_store.transaction() as connection:
            old = self._require_knowledge(connection, knowledge_id)
            if old["status"] != "challenged":
                raise ValueError(
                    "Only challenged knowledge can be superseded: "
                    f"{knowledge_id} is {old['status']}"
                )
            if statement.casefold() == old["statement"].casefold():
                raise ValueError("Superseding knowledge must change the statement")
            source = self._require_memory(
                connection,
                source_memory_id,
                closed=True,
            )
            self._require_not_before(
                superseded_at,
                old["updated_at"],
                "Knowledge superseded_at",
            )
            self._require_not_before(
                superseded_at,
                source["updated_at"],
                "Knowledge superseded_at",
            )
            existing = connection.execute(
                "SELECT public_id FROM knowledge WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError(f"Knowledge already exists: {public_id}")

            connection.execute(
                """
                INSERT INTO knowledge(
                    public_id, domain, statement, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'confirmed', ?, ?)
                """,
                (
                    public_id,
                    old["domain"],
                    statement,
                    superseded_at,
                    superseded_at,
                ),
            )
            support, _ = self._insert_relation(
                connection,
                source_kind="memory",
                source_id=source_memory_id,
                relation_type="supports",
                target_kind="knowledge",
                target_id=public_id,
                source_memory_id=source_memory_id,
                created_at=superseded_at,
            )
            supersedes, _ = self._insert_relation(
                connection,
                source_kind="knowledge",
                source_id=public_id,
                relation_type="supersedes",
                target_kind="knowledge",
                target_id=knowledge_id,
                source_memory_id=source_memory_id,
                created_at=superseded_at,
            )
            connection.execute(
                """
                UPDATE knowledge
                SET status = 'superseded', updated_at = ?
                WHERE public_id = ?
                """,
                (superseded_at, knowledge_id),
            )
            self._insert_history(
                connection,
                knowledge_id=knowledge_id,
                operation="supersede",
                timestamp=superseded_at,
                source_kind="knowledge",
                source_id=public_id,
                changes={
                    "status": ["challenged", "superseded"],
                    "superseded_by": public_id,
                    "supersedes_relation": supersedes["id"],
                },
            )
            self._insert_history(
                connection,
                knowledge_id=public_id,
                operation="create_superseding",
                timestamp=superseded_at,
                source_kind="memory",
                source_id=source_memory_id,
                changes={
                    "statement": statement,
                    "status": [None, "confirmed"],
                    "support_relation": support["id"],
                    "supersedes": knowledge_id,
                },
            )

        self._trace(
            "knowledge: supersede "
            f"old={knowledge_id} new={public_id}"
        )
        return {
            "old": self.describe(knowledge_id),
            "new": self.describe(public_id),
            "supersedes_relation": supersedes,
        }

    def get(self, knowledge_id):
        _validate_public_id(
            knowledge_id,
            KNOWLEDGE_ID_PREFIX,
            "Knowledge public_id",
        )
        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge WHERE public_id = ?",
                (knowledge_id,),
            ).fetchone()
        return self._row_to_knowledge(row)

    def describe(self, knowledge_id):
        knowledge = self.get(knowledge_id)
        if knowledge is None:
            raise ValueError(f"Unknown knowledge: {knowledge_id}")

        with self.memory_store.transaction() as connection:
            incoming = connection.execute(
                """
                SELECT * FROM relations
                WHERE target_kind = 'knowledge' AND target_id = ?
                  AND valid_until IS NULL
                ORDER BY row_id
                """,
                (knowledge_id,),
            ).fetchall()
            outgoing = connection.execute(
                """
                SELECT * FROM relations
                WHERE source_kind = 'knowledge' AND source_id = ?
                  AND valid_until IS NULL
                ORDER BY row_id
                """,
                (knowledge_id,),
            ).fetchall()

        incoming_relations = [
            self._relation_row_to_dict(row) for row in incoming
        ]
        outgoing_relations = [
            self._relation_row_to_dict(row) for row in outgoing
        ]

        supporting = [
            relation["source_memory_id"]
            for relation in incoming_relations
            if relation["type"] == "supports"
        ]
        contradicting = [
            relation["source_memory_id"]
            for relation in incoming_relations
            if relation["type"] == "contradicts"
        ]
        investigating = [
            relation["source_memory_id"]
            for relation in incoming_relations
            if relation["type"] == "investigates"
        ]
        superseded_by = [
            relation["source_id"]
            for relation in incoming_relations
            if relation["type"] == "supersedes"
        ]
        supersedes = [
            relation["target_id"]
            for relation in outgoing_relations
            if relation["type"] == "supersedes"
        ]

        return {
            "knowledge": knowledge,
            "supporting_sources": supporting,
            "contradicting_sources": contradicting,
            "investigating_sources": investigating,
            "open_challenges": knowledge["status"] == "challenged",
            "superseded_by": superseded_by,
            "supersedes": supersedes,
        }

    def history(self, knowledge_id):
        if self.get(knowledge_id) is None:
            raise ValueError(f"Unknown knowledge: {knowledge_id}")

        with self.memory_store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM history
                WHERE object_kind = 'knowledge' AND object_id = ?
                ORDER BY row_id
                """,
                (knowledge_id,),
            ).fetchall()

        return [
            {
                "operation": row["operation"],
                "timestamp": row["timestamp"],
                "source_kind": row["source_kind"],
                "source_id": row["source_id"],
                "changes": json.loads(row["changes_json"]),
            }
            for row in rows
        ]

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)
