"""Read-only authority for Knowledge supersedes lifecycle projections.

The generic Relations graph is not an authority ledger. A supersedes edge
may be rendered as a Knowledge lifecycle outcome only when it agrees with
both sides of the durable Knowledge history and the saved Knowledge state.
This never writes, repairs or reclassifies the underlying Relation.
"""

import json
from datetime import datetime


def _same_instant(left, right):
    """Compare offset-aware historical instants, not ISO string spellings."""
    try:
        a = datetime.fromisoformat(left)
        b = datetime.fromisoformat(right)
    except (TypeError, ValueError):
        return False
    return (
        a.tzinfo is not None and a.utcoffset() is not None
        and b.tzinfo is not None and b.utcoffset() is not None
        and a == b
    )


def _has_lifecycle_history(
    connection, *, knowledge_id, operation, source_kind, source_id,
    at, required,
):
    rows = connection.execute(
        """
        SELECT timestamp, changes_json FROM history
        WHERE object_kind = 'knowledge' AND object_id = ?
          AND operation = ? AND source_kind = ? AND source_id = ?
        ORDER BY row_id
        """,
        (knowledge_id, operation, source_kind, source_id),
    ).fetchall()
    for row in rows:
        if not _same_instant(row["timestamp"], at):
            continue
        try:
            changes = json.loads(row["changes_json"])
        except (ValueError, TypeError):
            continue
        if isinstance(changes, dict) and all(
            changes.get(key) == value for key, value in required.items()
        ):
            return True
    return False


def is_authorized_supersession(connection, relation):
    """Validate persisted lifecycle authority for one supersedes Relation.

    This verifies structural/history authority, not semantic truth or a
    cryptographic guarantee that an external administrator has not altered
    SQLite/Raw. Publication-time Raw checks remain the KnowledgeLayer's job.
    """
    if (
        relation["relation_type"] != "supersedes"
        or relation["source_kind"] != "knowledge"
        or relation["target_kind"] != "knowledge"
        or relation["source_id"] == relation["target_id"]
        or not relation["source_memory_id"]
        or relation["valid_until"] is not None
    ):
        return False

    source = connection.execute(
        "SELECT status FROM knowledge WHERE public_id = ?",
        (relation["source_id"],),
    ).fetchone()
    target = connection.execute(
        "SELECT status FROM knowledge WHERE public_id = ?",
        (relation["target_id"],),
    ).fetchone()
    if (
        source is None or source["status"] == "provisional"
        or target is None or target["status"] != "superseded"
    ):
        return False

    # A stored history pointer does not make a missing evidence owner real.
    # This is a cheap structural guard, not a re-read of the entire Raw log.
    owner = connection.execute(
        "SELECT 1 FROM memories WHERE public_id = ?",
        (relation["source_memory_id"],),
    ).fetchone()
    source_event = connection.execute(
        "SELECT 1 FROM memory_sources WHERE memory_id = ? LIMIT 1",
        (relation["source_memory_id"],),
    ).fetchone()
    if owner is None or source_event is None:
        return False

    old_history = _has_lifecycle_history(
        connection,
        knowledge_id=relation["target_id"],
        operation="supersede",
        source_kind="knowledge",
        source_id=relation["source_id"],
        at=relation["created_at"],
        required={
            "status": ["challenged", "superseded"],
            "superseded_by": relation["source_id"],
            "supersedes_relation": relation["public_id"],
        },
    )
    if not old_history:
        return False

    return _has_lifecycle_history(
        connection,
        knowledge_id=relation["source_id"],
        operation="create_superseding",
        source_kind="memory",
        source_id=relation["source_memory_id"],
        at=relation["created_at"],
        required={
            "status": [None, "confirmed"],
            "supersedes": relation["target_id"],
        },
    )
