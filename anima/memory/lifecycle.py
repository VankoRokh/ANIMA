import json
from datetime import datetime, timezone

from anima.memory.composer import RuleBasedComposer
from anima.memory.memory_store import (
    _validate_memory_id,
    _validate_timestamp,
)


class MemoryLifecycle:
    """Explicit Stage 1.6 OPEN/CLOSED/MERGED lifecycle operations."""

    def __init__(self, *, memory_store, composer=None, trace=None):
        self.memory_store = memory_store
        self.composer = composer or RuleBasedComposer()
        self.trace = trace

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

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
        object_id,
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
            ) VALUES ('memory', ?, ?, ?, ?, ?, ?)
            """,
            (
                object_id,
                operation,
                timestamp,
                source_kind,
                source_id,
                MemoryLifecycle._history_payload(changes),
            ),
        )

    def close(
        self,
        memory_id,
        *,
        closed_at=None,
        source_kind="manual",
        source_id=None,
    ):
        _validate_memory_id(memory_id)
        closed_at = closed_at or self._now()
        _validate_timestamp(closed_at, "Memory closed_at")

        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE public_id = ?",
                (memory_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"Unknown memory: {memory_id}")
            if row["status"] != "open":
                raise ValueError(
                    "Only OPEN memory can be closed: "
                    f"{memory_id} is {row['status']}"
                )

            connection.execute(
                """
                UPDATE memories
                SET status = 'closed', closed_at = ?, updated_at = ?
                WHERE public_id = ?
                """,
                (closed_at, closed_at, memory_id),
            )
            self._insert_history(
                connection,
                object_id=memory_id,
                operation="close",
                timestamp=closed_at,
                source_kind=source_kind,
                source_id=source_id,
                changes={
                    "closed_at": [row["closed_at"], closed_at],
                    "status": ["open", "closed"],
                },
            )

        result = self.memory_store.get_memory(memory_id)
        self._trace(
            f"memory_lifecycle: close memory={memory_id} status=closed"
        )
        return result

    def merge(
        self,
        source_id,
        target_id,
        *,
        merged_at=None,
    ):
        _validate_memory_id(source_id)
        _validate_memory_id(target_id)
        if source_id == target_id:
            raise ValueError("Memory cannot be merged into itself")

        merged_at = merged_at or self._now()
        _validate_timestamp(merged_at, "Memory merged_at")

        with self.memory_store.transaction() as connection:
            source_row = connection.execute(
                "SELECT * FROM memories WHERE public_id = ?",
                (source_id,),
            ).fetchone()
            target_row = connection.execute(
                "SELECT * FROM memories WHERE public_id = ?",
                (target_id,),
            ).fetchone()

            if source_row is None:
                raise ValueError(f"Unknown source memory: {source_id}")
            if target_row is None:
                raise ValueError(f"Unknown target memory: {target_id}")
            if source_row["status"] == "merged":
                raise ValueError(f"Source memory is already merged: {source_id}")
            if target_row["status"] != "open":
                raise ValueError(
                    "Merge target must be OPEN: "
                    f"{target_id} is {target_row['status']}"
                )
            if source_row["type"] != target_row["type"]:
                raise ValueError("Cannot merge memories with different types")
            if source_row["domain"] != target_row["domain"]:
                raise ValueError("Cannot merge memories with different domains")

            composition = self.composer.compose_update(
                target_row["content"],
                source_row["content"],
            )
            target_content = composition["content"]

            target_events = {
                row["event_id"]
                for row in connection.execute(
                    "SELECT event_id FROM memory_sources WHERE memory_id = ?",
                    (target_id,),
                ).fetchall()
            }
            source_events = [
                row["event_id"]
                for row in connection.execute(
                    "SELECT event_id FROM memory_sources WHERE memory_id = ?",
                    (source_id,),
                ).fetchall()
            ]
            added_events = [
                event_id
                for event_id in source_events
                if event_id not in target_events
            ]

            for event_id in added_events:
                connection.execute(
                    """
                    INSERT INTO memory_sources(memory_id, event_id)
                    VALUES (?, ?)
                    """,
                    (target_id, event_id),
                )

            connection.execute(
                """
                UPDATE memories
                SET content = ?, updated_at = ?
                WHERE public_id = ?
                """,
                (target_content, merged_at, target_id),
            )
            source_closed_at = source_row["closed_at"] or merged_at
            connection.execute(
                """
                UPDATE memories
                SET status = 'merged',
                    merged_into = ?,
                    closed_at = ?,
                    updated_at = ?
                WHERE public_id = ?
                """,
                (
                    target_id,
                    source_closed_at,
                    merged_at,
                    source_id,
                ),
            )

            self._insert_history(
                connection,
                object_id=target_id,
                operation="merge_target",
                timestamp=merged_at,
                source_kind="memory",
                source_id=source_id,
                changes={
                    "content_after": target_content,
                    "content_before": target_row["content"],
                    "source_events_added": added_events,
                },
            )
            self._insert_history(
                connection,
                object_id=source_id,
                operation="merged",
                timestamp=merged_at,
                source_kind="memory",
                source_id=target_id,
                changes={
                    "closed_at": [source_row["closed_at"], source_closed_at],
                    "merged_into": [source_row["merged_into"], target_id],
                    "status": [source_row["status"], "merged"],
                },
            )

        result = {
            "source": self.memory_store.get_memory(source_id),
            "target": self.memory_store.get_memory(target_id),
            "source_events_added": added_events,
        }
        self._trace(
            "memory_lifecycle: merge "
            f"source={source_id} target={target_id} "
            f"events_added={len(added_events)}"
        )
        return result

    def history(self, memory_id):
        _validate_memory_id(memory_id)

        with self.memory_store.transaction() as connection:
            memory = connection.execute(
                "SELECT public_id FROM memories WHERE public_id = ?",
                (memory_id,),
            ).fetchone()
            if memory is None:
                raise ValueError(f"Unknown memory: {memory_id}")

            rows = connection.execute(
                """
                SELECT * FROM history
                WHERE object_kind = 'memory' AND object_id = ?
                ORDER BY row_id
                """,
                (memory_id,),
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
