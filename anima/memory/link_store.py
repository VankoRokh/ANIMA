import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4


ENTITY_ID_PREFIX = "ent_"
KNOWLEDGE_ID_PREFIX = "kn_"
RELATION_ID_PREFIX = "rel_"

ENTITY_TYPES = {
    "person",
    "project",
    "system",
    "component",
    "technology",
    "place",
    "object",
    "concept",
}
ENTITY_STATUSES = {"active", "inactive", "merged"}
KNOWLEDGE_STATUSES = {
    "provisional",
    "confirmed",
    "challenged",
    "superseded",
    "rejected",
}
OBJECT_KINDS = {"memory", "knowledge", "entity"}

RELATION_RULES = {
    "about": {
        ("memory", "entity"),
        ("knowledge", "entity"),
    },
    "related_to": {
        ("memory", "memory"),
        ("knowledge", "knowledge"),
        ("entity", "entity"),
    },
    "continues": {("memory", "memory")},
    "derived_from": {
        ("memory", "memory"),
        ("knowledge", "memory"),
    },
    "supports": {
        ("memory", "knowledge"),
        ("knowledge", "knowledge"),
    },
    "contradicts": {
        ("memory", "knowledge"),
        ("knowledge", "knowledge"),
    },
    "investigates": {("memory", "knowledge")},
    "supersedes": {("knowledge", "knowledge")},
}


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


def _validate_public_id(public_id, prefix, label):
    if (
        not isinstance(public_id, str)
        or not public_id.startswith(prefix)
    ):
        raise ValueError(f"{label} must be a {prefix}UUIDv4")

    raw_uuid = public_id[len(prefix):]

    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a {prefix}UUIDv4") from error

    if parsed.version != 4 or str(parsed) != raw_uuid:
        raise ValueError(f"{label} must be a {prefix}UUIDv4")


def _clean_name(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")

    return " ".join(value.split())


def _normalize_name(value):
    return " ".join(value.split()).casefold()


class LinkStore:
    """Store Stage 1.3 entities, knowledge anchors and semantic relations."""

    def __init__(self, memory_store):
        self.memory_store = memory_store

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
    def _row_to_entity(row, aliases=None):
        if row is None:
            return None

        return {
            "id": row["public_id"],
            "type": row["type"],
            "canonical_name": row["canonical_name"],
            "aliases": list(aliases or []),
            "status": row["status"],
        }

    @staticmethod
    def _row_to_relation(row):
        if row is None:
            return None

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

    def create_knowledge(
        self,
        *,
        domain,
        statement,
        status="provisional",
        created_at=None,
        public_id=None,
    ):
        if domain not in {
            "self",
            "user",
            "project",
            "environment",
            "system",
        }:
            raise ValueError(f"Unknown knowledge domain: {domain!r}")

        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("Knowledge statement must be a non-empty string")

        if status not in KNOWLEDGE_STATUSES:
            raise ValueError(f"Unknown knowledge status: {status!r}")

        public_id = public_id or f"{KNOWLEDGE_ID_PREFIX}{uuid4()}"
        created_at = created_at or _now()
        _validate_public_id(
            public_id,
            KNOWLEDGE_ID_PREFIX,
            "Knowledge public_id",
        )
        _validate_timestamp(created_at, "Knowledge created_at")

        try:
            with self.memory_store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO knowledge(
                        public_id, domain, statement, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        public_id,
                        domain,
                        statement.strip(),
                        status,
                        created_at,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot create knowledge {public_id}: {error}"
            ) from error

        return self.get_knowledge(public_id)

    def get_knowledge(self, public_id):
        _validate_public_id(
            public_id,
            KNOWLEDGE_ID_PREFIX,
            "Knowledge public_id",
        )

        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge WHERE public_id = ?",
                (public_id,),
            ).fetchone()

        return self._row_to_knowledge(row)

    def create_entity(
        self,
        *,
        entity_type,
        canonical_name,
        aliases=None,
        status="active",
        public_id=None,
    ):
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Unknown entity type: {entity_type!r}")

        if status not in ENTITY_STATUSES:
            raise ValueError(f"Unknown entity status: {status!r}")

        canonical_name = _clean_name(
            canonical_name,
            "Entity canonical_name",
        )
        public_id = public_id or f"{ENTITY_ID_PREFIX}{uuid4()}"
        _validate_public_id(
            public_id,
            ENTITY_ID_PREFIX,
            "Entity public_id",
        )

        if aliases is None:
            aliases = []
        if not isinstance(aliases, (list, tuple, set)):
            raise ValueError("Entity aliases must be a list-like collection")

        cleaned_aliases = []
        seen = set()
        canonical_key = _normalize_name(canonical_name)

        for alias in aliases:
            cleaned = _clean_name(alias, "Entity alias")
            key = _normalize_name(cleaned)
            if key == canonical_key or key in seen:
                continue
            seen.add(key)
            cleaned_aliases.append(cleaned)

        try:
            with self.memory_store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO entities(
                        public_id, type, canonical_name, status
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        public_id,
                        entity_type,
                        canonical_name,
                        status,
                    ),
                )
                for alias in cleaned_aliases:
                    connection.execute(
                        """
                        INSERT INTO entity_aliases(entity_id, alias)
                        VALUES (?, ?)
                        """,
                        (public_id, alias),
                    )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot create entity {public_id}: {error}"
            ) from error

        return self.get_entity(public_id)

    def add_entity_alias(self, entity_id, alias):
        entity = self._require_entity(entity_id)
        alias = _clean_name(alias, "Entity alias")

        if _normalize_name(alias) == _normalize_name(
            entity["canonical_name"]
        ):
            return entity

        try:
            with self.memory_store.transaction() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO entity_aliases(entity_id, alias)
                    VALUES (?, ?)
                    """,
                    (entity_id, alias),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot add alias to entity {entity_id}: {error}"
            ) from error

        return self.get_entity(entity_id)

    def get_entity(self, public_id):
        _validate_public_id(
            public_id,
            ENTITY_ID_PREFIX,
            "Entity public_id",
        )

        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM entities WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                return None

            aliases = [
                item["alias"]
                for item in connection.execute(
                    """
                    SELECT alias FROM entity_aliases
                    WHERE entity_id = ?
                    ORDER BY alias
                    """,
                    (public_id,),
                ).fetchall()
            ]

        return self._row_to_entity(row, aliases)

    def resolve_entity(self, name):
        name = _clean_name(name, "Entity name")
        resolved_id = None

        with self.memory_store.transaction() as connection:
            exact_canonical = connection.execute(
                """
                SELECT public_id FROM entities
                WHERE canonical_name = ? AND status = 'active'
                ORDER BY row_id
                """,
                (name,),
            ).fetchall()
            resolved_id = self._resolve_unique_ids(
                exact_canonical,
                name,
            )

            if resolved_id is None:
                exact_alias = connection.execute(
                    """
                    SELECT e.public_id
                    FROM entity_aliases a
                    JOIN entities e ON e.public_id = a.entity_id
                    WHERE a.alias = ? AND e.status = 'active'
                    ORDER BY e.row_id
                    """,
                    (name,),
                ).fetchall()
                resolved_id = self._resolve_unique_ids(
                    exact_alias,
                    name,
                )

            if resolved_id is None:
                rows = connection.execute(
                    """
                    SELECT e.public_id, e.canonical_name, a.alias
                    FROM entities e
                    LEFT JOIN entity_aliases a ON a.entity_id = e.public_id
                    WHERE e.status = 'active'
                    ORDER BY e.row_id
                    """
                ).fetchall()
            else:
                rows = []

        if resolved_id is not None:
            return self.get_entity(resolved_id)

        key = _normalize_name(name)
        matches = set()
        for row in rows:
            if _normalize_name(row["canonical_name"]) == key:
                matches.add(row["public_id"])
            elif (
                row["alias"] is not None
                and _normalize_name(row["alias"]) == key
            ):
                matches.add(row["public_id"])

        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(f"Ambiguous entity name: {name!r}")

        return self.get_entity(next(iter(matches)))

    @staticmethod
    def _resolve_unique_ids(rows, name):
        ids = {row["public_id"] for row in rows}
        if not ids:
            return None
        if len(ids) > 1:
            raise ValueError(f"Ambiguous entity name: {name!r}")
        return next(iter(ids))

    def create_relation(
        self,
        *,
        source_kind,
        source_id,
        relation_type,
        target_kind,
        target_id,
        source_memory_id=None,
        created_at=None,
        valid_until=None,
        public_id=None,
    ):
        self._validate_relation_rule(
            source_kind,
            relation_type,
            target_kind,
        )
        self._require_object(source_kind, source_id)
        self._require_object(target_kind, target_id)

        if source_kind == target_kind and source_id == target_id:
            raise ValueError("Relation cannot point an object to itself")

        if source_memory_id is None and source_kind == "memory":
            source_memory_id = source_id
        if source_memory_id is None:
            raise ValueError(
                "Relation source_memory_id is required for provenance"
            )
        self._require_memory(source_memory_id)

        public_id = public_id or f"{RELATION_ID_PREFIX}{uuid4()}"
        created_at = created_at or _now()
        _validate_public_id(
            public_id,
            RELATION_ID_PREFIX,
            "Relation public_id",
        )
        _validate_timestamp(created_at, "Relation created_at")
        if valid_until is not None:
            _validate_timestamp(valid_until, "Relation valid_until")

        with self.memory_store.transaction() as connection:
            if valid_until is None:
                duplicate = connection.execute(
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
            else:
                duplicate = connection.execute(
                    """
                    SELECT public_id FROM relations
                    WHERE source_kind = ? AND source_id = ?
                      AND relation_type = ?
                      AND target_kind = ? AND target_id = ?
                      AND source_memory_id = ?
                      AND valid_until = ?
                    """,
                    (
                        source_kind,
                        source_id,
                        relation_type,
                        target_kind,
                        target_id,
                        source_memory_id,
                        valid_until,
                    ),
                ).fetchone()

            if duplicate is not None:
                raise ValueError(
                    "Equivalent relation already exists: "
                    f"{duplicate['public_id']}"
                )

            try:
                connection.execute(
                    """
                    INSERT INTO relations(
                        public_id, source_kind, source_id, relation_type,
                        target_kind, target_id, created_at, valid_until,
                        source_memory_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        public_id,
                        source_kind,
                        source_id,
                        relation_type,
                        target_kind,
                        target_id,
                        created_at,
                        valid_until,
                        source_memory_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Cannot create relation {public_id}: {error}"
                ) from error

        return self.get_relation(public_id)

    def get_relation(self, public_id):
        _validate_public_id(
            public_id,
            RELATION_ID_PREFIX,
            "Relation public_id",
        )
        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM relations WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_relation(row)

    def relations_for(
        self,
        object_kind,
        object_id,
        *,
        direction="both",
        relation_types=None,
    ):
        self._require_object(object_kind, object_id)

        if direction not in {"incoming", "outgoing", "both"}:
            raise ValueError(
                "Relation direction must be incoming, outgoing or both"
            )

        if relation_types is not None:
            relation_types = set(relation_types)
            unknown = relation_types - set(RELATION_RULES)
            if unknown:
                raise ValueError(
                    "Unknown relation type(s): "
                    + ", ".join(sorted(unknown))
                )

        clauses = []
        values = []
        if direction in {"outgoing", "both"}:
            clauses.append("(source_kind = ? AND source_id = ?)")
            values.extend([object_kind, object_id])
        if direction in {"incoming", "both"}:
            clauses.append("(target_kind = ? AND target_id = ?)")
            values.extend([object_kind, object_id])

        sql = "SELECT * FROM relations WHERE (" + " OR ".join(clauses) + ")"
        if relation_types:
            placeholders = ", ".join("?" for _ in relation_types)
            sql += f" AND relation_type IN ({placeholders})"
            values.extend(sorted(relation_types))
        sql += " ORDER BY row_id"

        with self.memory_store.transaction() as connection:
            rows = connection.execute(sql, values).fetchall()

        return [self._row_to_relation(row) for row in rows]

    def _validate_relation_rule(
        self,
        source_kind,
        relation_type,
        target_kind,
    ):
        if source_kind not in OBJECT_KINDS:
            raise ValueError(f"Unknown relation source kind: {source_kind!r}")
        if target_kind not in OBJECT_KINDS:
            raise ValueError(f"Unknown relation target kind: {target_kind!r}")
        if relation_type not in RELATION_RULES:
            raise ValueError(f"Unknown relation type: {relation_type!r}")
        if (
            source_kind,
            target_kind,
        ) not in RELATION_RULES[relation_type]:
            raise ValueError(
                f"Relation {relation_type!r} does not allow "
                f"{source_kind} -> {target_kind}"
            )

    def _require_object(self, kind, public_id):
        if kind not in OBJECT_KINDS:
            raise ValueError(f"Unknown object kind: {kind!r}")
        if kind == "memory":
            self._require_memory(public_id)
            return
        if kind == "knowledge":
            if self.get_knowledge(public_id) is None:
                raise ValueError(f"Unknown knowledge: {public_id}")
            return
        self._require_entity(public_id)

    def _require_memory(self, public_id):
        memory = self.memory_store.get_memory(public_id)
        if memory is None:
            raise ValueError(f"Unknown memory: {public_id}")
        return memory

    def _require_entity(self, public_id):
        entity = self.get_entity(public_id)
        if entity is None:
            raise ValueError(f"Unknown entity: {public_id}")
        return entity
