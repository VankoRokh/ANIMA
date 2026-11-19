import json
from datetime import datetime, timezone
from uuid import uuid4

from anima.memory.link_store import (
    KNOWLEDGE_ID_PREFIX,
    RELATION_ID_PREFIX,
    _validate_public_id,
    _validate_timestamp,
    _relation_active_at,
    _evidence_intervals_overlap,
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
    def _active_relation(
        cls, connection, *, source_kind, source_id, relation_type,
        target_kind, target_id, source_memory_id, at,
    ):
        """Find an existing Relation effective at a transition instant.

        An open-ended-only duplicate lookup is insufficient: legitimate
        finite [start, end) support must be reused without minting a new
        infinite support that overlaps a future contradiction (NEW-04).
        """
        rows = connection.execute(
            """
            SELECT * FROM relations
            WHERE source_kind = ? AND source_id = ?
              AND relation_type = ?
              AND target_kind = ? AND target_id = ?
              AND source_memory_id = ?
            ORDER BY row_id
            """,
            (
                source_kind, source_id, relation_type,
                target_kind, target_id, source_memory_id,
            ),
        ).fetchall()
        for row in rows:
            if _relation_active_at(row, at):
                return cls._relation_row_to_dict(row)
        return None

    @classmethod
    def _require_no_opposite_evidence(
        cls,
        connection,
        *,
        memory_id,
        knowledge_id,
        relation_type,
        at,
    ):
        """Check opposite Evidence at the same instant as the transition.

        A future open-ended relation (valid_until=NULL) is not yet active.
        This matches _require_effective_memory_evidence() and the canonical
        half-open [created_at, valid_until) relation semantics.
        """
        opposite = "contradicts" if relation_type == "supports" else "supports"
        rows = connection.execute(
            """
            SELECT created_at, valid_until FROM relations
            WHERE source_kind = 'memory' AND source_id = ?
              AND relation_type = ?
              AND target_kind = 'knowledge' AND target_id = ?
              AND source_memory_id = ?
            """,
            (memory_id, opposite, knowledge_id, memory_id),
        ).fetchall()
        if any(_relation_active_at(row, at) for row in rows):
            raise ValueError(
                "Memory cannot both support and contradict the same knowledge"
            )

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

        # R3/F-04 also applies to this internal relation writer.
        # A new permanent support/contradiction cannot overlap a future
        # opposite interval. Reusing an existing support is not a new
        # relation and is checked only at the effective transition time.
        if (
            source_kind == "memory"
            and target_kind == "knowledge"
            and relation_type in {"supports", "contradicts"}
        ):
            opposite = (
                "contradicts" if relation_type == "supports"
                else "supports"
            )
            rows = connection.execute(
                """
                SELECT created_at, valid_until FROM relations
                WHERE source_kind = 'memory' AND source_id = ?
                  AND relation_type = ?
                  AND target_kind = 'knowledge' AND target_id = ?
                """,
                (source_id, opposite, target_id),
            ).fetchall()
            if any(
                _evidence_intervals_overlap(
                    first_start=created_at,
                    first_end=None,
                    second_start=row["created_at"],
                    second_end=row["valid_until"],
                )
                for row in rows
            ):
                raise ValueError(
                    "Memory cannot both support and contradict "
                    "the same knowledge in overlapping intervals"
                )

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

    @classmethod
    def _require_effective_memory_evidence(
        cls, connection, *, knowledge_id, relation_type, at,
    ):
        """Require real, CLOSED Memory evidence valid at the transition time.

        A relation row is not itself proof. Reject orphaned, open, merged,
        mislabeled, and self-contradicting active evidence. Older expired or
        future-dated relations do not count as support at this timestamp.
        """
        if relation_type not in {"supports", "contradicts"}:
            raise ValueError("Unexpected Knowledge evidence type")
        when = cls._parsed_time(at)
        rows = connection.execute(
            """
            SELECT * FROM relations
            WHERE target_kind = 'knowledge' AND target_id = ?
              AND relation_type = ?
            ORDER BY row_id
            """,
            (knowledge_id, relation_type),
        ).fetchall()
        opposite = (
            "contradicts" if relation_type == "supports" else "supports"
        )
        valid_sources = []
        for row in rows:
            if cls._parsed_time(row["created_at"]) > when:
                continue
            if (
                row["valid_until"] is not None
                and cls._parsed_time(row["valid_until"]) <= when
            ):
                continue

            source_id = row["source_memory_id"]
            if (
                row["source_kind"] != "memory"
                or row["source_id"] != source_id
                or not source_id
            ):
                raise ValueError(
                    "Invalid active Knowledge evidence source: "
                    f"{row['public_id']}"
                )
            source = connection.execute(
                "SELECT status, updated_at FROM memories WHERE public_id = ?",
                (source_id,),
            ).fetchone()
            if source is None or source["status"] != "closed":
                raise ValueError(
                    "Active Knowledge evidence requires existing CLOSED Memory: "
                    f"{row['public_id']}"
                )
            if cls._parsed_time(source["updated_at"]) > when:
                raise ValueError(
                    "Knowledge evidence Memory changed after transition time: "
                    f"{source_id}"
                )

            opposing = connection.execute(
                """
                SELECT created_at, valid_until FROM relations
                WHERE target_kind = 'knowledge' AND target_id = ?
                  AND relation_type = ?
                  AND source_kind = 'memory' AND source_id = ?
                  AND source_memory_id = ?
                """,
                (knowledge_id, opposite, source_id, source_id),
            ).fetchall()
            if any(
                cls._parsed_time(item["created_at"]) <= when
                and (
                    item["valid_until"] is None
                    or cls._parsed_time(item["valid_until"]) > when
                )
                for item in opposing
            ):
                raise ValueError(
                    "Memory cannot both support and contradict the same knowledge"
                )
            valid_sources.append(source_id)
        if not valid_sources:
            action = (
                "confirmed" if relation_type == "supports" else "rejected"
            )
            requirement = (
                "support" if relation_type == "supports" else "contradiction"
            )
            raise ValueError(
                f"Knowledge cannot be {action} without {requirement} "
                "from a valid CLOSED Memory"
            )
        return valid_sources

    def _require_published_evidence_raw_sources(
        self, connection, knowledge_id, *, at, additional_memory_ids=(),
    ):
        """Validate *every* evidence dependency before publishing Knowledge.

        Checking only the supports used for the current transition is not
        enough: an unbacked contradiction or future-dated support can be
        staged on a provisional claim and then survive confirmation. Every
        attached supports/contradicts Relation must have a real CLOSED Memory
        source, matching provenance, and canonical Raw Events.

        The complete Raw scan happens once per transition under its SQLite
        transaction. This does not claim cross-file atomicity against an
        uncooperative Raw writer.
        """
        rows = connection.execute(
            """
            SELECT public_id, source_kind, source_id, source_memory_id,
                   created_at, valid_until
            FROM relations
            WHERE target_kind = 'knowledge' AND target_id = ?
              AND relation_type IN ('supports', 'contradicts')
            ORDER BY row_id
            """,
            (knowledge_id,),
        ).fetchall()
        sources = list(additional_memory_ids)
        for relation in rows:
            source_id = relation["source_memory_id"]
            if (
                relation["source_kind"] != "memory"
                or relation["source_id"] != source_id
                or not source_id
            ):
                raise ValueError(
                    "Invalid published Knowledge evidence source: "
                    + relation["public_id"]
                )
            # Historical and future Evidence must have a real owner and
            # Raw provenance, but only an *active* witness must be CLOSED at
            # this transition instant. Preserve half-open interval semantics.
            self._require_memory(
                connection, source_id,
                closed=_relation_active_at(relation, at),
            )
            sources.append(source_id)
        self.memory_store.require_knowledge_raw_sources(connection, sources)

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
            if knowledge["status"] in {"superseded", "rejected"}:
                raise ValueError(
                    "Terminal knowledge cannot open a new investigation: "
                    f"{knowledge_id} is {knowledge['status']}"
                )
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
                self._require_no_opposite_evidence(
                    connection,
                    memory_id=source_memory_id,
                    knowledge_id=knowledge_id,
                    relation_type="supports",
                    at=confirmed_at,
                )
                active_support = self._active_relation(
                    connection,
                    source_kind="memory",
                    source_id=source_memory_id,
                    relation_type="supports",
                    target_kind="knowledge",
                    target_id=knowledge_id,
                    source_memory_id=source_memory_id,
                    at=confirmed_at,
                )
                if (
                    knowledge["status"] == "challenged"
                    and active_support is not None
                ):
                    raise ValueError(
                        "Challenged knowledge requires new supporting evidence"
                    )
                if active_support is not None:
                    # Finite and open-ended active support are equally
                    # effective at confirmed_at. Reusing the existing row
                    # preserves its valid_until and never crosses the
                    # half-open boundary into a future contradiction.
                    added_support = active_support
                else:
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

            supporting_sources = self._require_effective_memory_evidence(
                connection,
                knowledge_id=knowledge_id,
                relation_type="supports",
                at=confirmed_at,
            )
            # R2: a CLOSED Memory with a declared event ID is not
            # sufficient proof that an authoritative Raw Event exists.
            self._require_published_evidence_raw_sources(
                connection, knowledge_id, at=confirmed_at,
            )

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
            self._require_no_opposite_evidence(
                connection,
                memory_id=contradiction_memory_id,
                knowledge_id=knowledge_id,
                relation_type="contradicts",
                at=challenged_at,
            )
            # R5: a challenge changes the epistemic state of already
            # confirmed Knowledge. Its contradiction must therefore have
            # the same canonical Raw authority as confirm/reject/supersede.
            # No standalone/unbound or missing-Raw bypass is permitted.
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
            self._require_published_evidence_raw_sources(
                connection, knowledge_id, at=challenged_at,
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
                self._require_no_opposite_evidence(
                    connection,
                    memory_id=contradiction_memory_id,
                    knowledge_id=knowledge_id,
                    relation_type="contradicts",
                    at=rejected_at,
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

            contradicting_sources = self._require_effective_memory_evidence(
                connection,
                knowledge_id=knowledge_id,
                relation_type="contradicts",
                at=rejected_at,
            )
            self._require_published_evidence_raw_sources(
                connection, knowledge_id, at=rejected_at,
            )

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
            # Supersede writes a new confirmed Knowledge without invoking
            # the ordinary confirm transition: enforce the same Raw policy.
            self._require_published_evidence_raw_sources(
                connection, knowledge_id, at=superseded_at,
                additional_memory_ids=[source_memory_id],
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

        # Share the same half-open temporal semantics as Retrieval. Read
        # history without deleting it, then project only current relations.
        as_of = self._now()
        with self.memory_store.transaction() as connection:
            incoming = connection.execute(
                """
                SELECT * FROM relations
                WHERE target_kind = 'knowledge' AND target_id = ?
                ORDER BY row_id
                """,
                (knowledge_id,),
            ).fetchall()
            outgoing = connection.execute(
                """
                SELECT * FROM relations
                WHERE source_kind = 'knowledge' AND source_id = ?
                ORDER BY row_id
                """,
                (knowledge_id,),
            ).fetchall()

        incoming_relations = [
            self._relation_row_to_dict(row) for row in incoming
            if _relation_active_at(row, as_of)
        ]
        outgoing_relations = [
            self._relation_row_to_dict(row) for row in outgoing
            if _relation_active_at(row, as_of)
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
