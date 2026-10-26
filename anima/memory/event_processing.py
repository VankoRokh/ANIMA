import json
from datetime import datetime, timezone

from anima.core.event_bus import Event


PROCESSOR_NAME = "memory_processor"
PROCESSOR_VERSION = "1.0"
FINAL_STATUSES = {"done", "skipped"}
RETRYABLE_STATUSES = {"pending", "processing", "failed"}


class EventProcessingCoordinator:
    """Persistent exactly-once coordinator for the Stage 1 memory write path."""

    def __init__(
        self,
        *,
        memory_store,
        memory_processor,
        event_log,
        trace=None,
        fault_hook=None,
        processor_name=PROCESSOR_NAME,
        processor_version=PROCESSOR_VERSION,
    ):
        self.memory_store = memory_store
        self.memory_processor = memory_processor
        self.event_log = event_log
        self.trace = trace
        self.fault_hook = fault_hook
        self.processor_name = processor_name
        self.processor_version = processor_version

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _event_from_record(record):
        return Event(
            record["type"],
            record["payload"],
            source=record["source"],
            session_id=record["session_id"],
            references=record["references"],
            event_id=record["id"],
            timestamp=record["timestamp"],
        )

    @staticmethod
    def _row_to_record(row):
        if row is None:
            return None
        return {
            "event_id": row["event_id"],
            "processor": row["processor"],
            "processor_version": row["processor_version"],
            "status": row["status"],
            "attempts": row["attempts"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "last_error": row["last_error"],
        }

    def get(self, event_id):
        with self.memory_store.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM event_processing
                WHERE event_id = ? AND processor = ? AND processor_version = ?
                """,
                (event_id, self.processor_name, self.processor_version),
            ).fetchone()
        return self._row_to_record(row)

    def list_records(self):
        with self.memory_store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM event_processing
                WHERE processor = ? AND processor_version = ?
                ORDER BY rowid
                """,
                (self.processor_name, self.processor_version),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def finalized_count(self):
        with self.memory_store.transaction() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM event_processing
                WHERE processor = ? AND processor_version = ?
                  AND status IN ('done', 'skipped')
                """,
                (self.processor_name, self.processor_version),
            ).fetchone()
        return row["count"]

    def process(self, event):
        if not isinstance(event, Event):
            raise ValueError("EventProcessingCoordinator requires an Event")

        previous = self.get(event.event_id)
        if previous is not None and previous["status"] in FINAL_STATUSES:
            return self._replay_result(event, previous["status"])

        attempt = 1 if previous is None else previous["attempts"] + 1
        started_at = self._now()

        try:
            with self.memory_store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO event_processing(
                        event_id, processor, processor_version, status,
                        attempts, started_at, finished_at, last_error
                    ) VALUES (?, ?, ?, 'processing', ?, ?, NULL, NULL)
                    ON CONFLICT(event_id, processor, processor_version)
                    DO UPDATE SET
                        status = 'processing',
                        attempts = excluded.attempts,
                        started_at = excluded.started_at,
                        finished_at = NULL,
                        last_error = NULL
                    """,
                    (
                        event.event_id,
                        self.processor_name,
                        self.processor_version,
                        attempt,
                        started_at,
                    ),
                )

                result = self.memory_processor.process_event(
                    event,
                    connection=connection,
                    trace_result=False,
                )

                if self.fault_hook is not None:
                    self.fault_hook(event, result, connection)

                final_status = (
                    "skipped" if result["action"] == "skip" else "done"
                )
                connection.execute(
                    """
                    UPDATE event_processing
                    SET status = ?, finished_at = ?, last_error = NULL
                    WHERE event_id = ? AND processor = ? AND processor_version = ?
                    """,
                    (
                        final_status,
                        self._now(),
                        event.event_id,
                        self.processor_name,
                        self.processor_version,
                    ),
                )
        except Exception as error:
            self._record_failure(
                event.event_id,
                attempt,
                started_at,
                error,
            )
            self._trace(
                "event_processing: failed "
                f"event={event.event_id} attempt={attempt} error={error}"
            )
            raise

        self.memory_processor._trace_result(result)
        return result

    def recover(self):
        """Adopt legacy Events, retry unfinished work and surface missing raw Events."""
        records = self.event_log.load_events()
        events = {
            record["id"]: self._event_from_record(record)
            for record in records
        }
        adopted = self._bootstrap_missing(events)

        with self.memory_store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM event_processing
                WHERE processor = ? AND processor_version = ?
                  AND status IN ('pending', 'processing', 'failed')
                ORDER BY rowid
                """,
                (self.processor_name, self.processor_version),
            ).fetchall()

        recovered = []
        for row in rows:
            event_id = row["event_id"]
            event = events.get(event_id)
            if event is None:
                error = ValueError(
                    f"Missing raw event {event_id} for event_processing recovery"
                )
                self._record_failure(
                    event_id,
                    row["attempts"] + 1,
                    self._now(),
                    error,
                )
                raise error
            recovered.append(self.process(event))

        if adopted or recovered:
            self._trace(
                "event_processing: recovery "
                f"adopted={adopted} retried={len(recovered)} "
                f"finalized={self.finalized_count()}"
            )

        return {
            "adopted": adopted,
            "retried": len(recovered),
            "finalized": self.finalized_count(),
        }

    def _bootstrap_missing(self, events):
        adopted = 0
        now = self._now()

        with self.memory_store.transaction() as connection:
            existing = {
                row["event_id"]
                for row in connection.execute(
                    """
                    SELECT event_id FROM event_processing
                    WHERE processor = ? AND processor_version = ?
                    """,
                    (self.processor_name, self.processor_version),
                ).fetchall()
            }

            for event_id, event in events.items():
                if event_id in existing:
                    continue

                source = connection.execute(
                    """
                    SELECT memory_id FROM memory_sources
                    WHERE event_id = ?
                    ORDER BY rowid
                    LIMIT 1
                    """,
                    (event_id,),
                ).fetchone()
                selected, _, _ = self.memory_processor._select(event)

                if source is not None:
                    status = "done"
                    finished_at = now
                elif not selected:
                    status = "skipped"
                    finished_at = now
                else:
                    status = "pending"
                    finished_at = None

                connection.execute(
                    """
                    INSERT INTO event_processing(
                        event_id, processor, processor_version, status,
                        attempts, started_at, finished_at, last_error
                    ) VALUES (?, ?, ?, ?, 0, NULL, ?, NULL)
                    """,
                    (
                        event_id,
                        self.processor_name,
                        self.processor_version,
                        status,
                        finished_at,
                    ),
                )
                adopted += 1

        return adopted

    def _record_failure(self, event_id, attempt, started_at, error):
        with self.memory_store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO event_processing(
                    event_id, processor, processor_version, status,
                    attempts, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, 'failed', ?, ?, ?, ?)
                ON CONFLICT(event_id, processor, processor_version)
                DO UPDATE SET
                    status = 'failed',
                    attempts = excluded.attempts,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    last_error = excluded.last_error
                """,
                (
                    event_id,
                    self.processor_name,
                    self.processor_version,
                    attempt,
                    started_at,
                    self._now(),
                    str(error),
                ),
            )

    def _replay_result(self, event, status):
        if status == "skipped":
            return self.memory_processor._result(
                event,
                action="skip",
                reasons=["event_processing:already_skipped"],
            )

        with self.memory_store.transaction() as connection:
            row = connection.execute(
                """
                SELECT memory_id FROM memory_sources
                WHERE event_id = ?
                ORDER BY rowid
                LIMIT 1
                """,
                (event.event_id,),
            ).fetchone()

        return self.memory_processor._result(
            event,
            action="already_done",
            memory_id=None if row is None else row["memory_id"],
            reasons=["event_processing:already_done"],
        )

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)
