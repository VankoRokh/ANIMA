import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import uuid4

from anima.agent.choice_adapter import action_fingerprint
from anima.agent.store import AgentStore
from anima.agent.tools import ToolRegistry
from anima.core.event_bus import Event
from anima.memory.event_log import EventLog


_PUBLICATION_SQL = """
CREATE TABLE IF NOT EXISTS agent_event_publications (
    publication_key TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    event_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('prepared', 'published')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_event_publications_status
    ON agent_event_publications(status, created_at);
"""


SIGNIFICANT_VERIFICATION_OUTCOMES = {"failure", "progress", "blocked", "success"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _content_hash(record):
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


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


def _reference(kind, public_id):
    return {"kind": _require_text(kind, "Event reference kind"), "id": _require_text(public_id, "Event reference id")}


def _optional_reference(references, kind, value):
    if value is not None:
        references.append(_reference(kind, value))


@dataclass(frozen=True, slots=True)
class AgentEventPublication:
    publication_key: str
    event_id: str
    content_hash: str
    status: str
    replayed: bool
    event: Event

    def __post_init__(self):
        _require_text(self.publication_key, "AgentEventPublication publication_key")
        _require_text(self.event_id, "AgentEventPublication event_id")
        if (
            not isinstance(self.content_hash, str)
            or len(self.content_hash) != 64
            or any(char not in "0123456789abcdef" for char in self.content_hash)
        ):
            raise ValueError("AgentEventPublication content_hash must be lowercase SHA-256")
        if self.status != "published":
            raise ValueError("AgentEventPublication status must be published")
        if type(self.replayed) is not bool:
            raise ValueError("AgentEventPublication replayed must be boolean")
        if not isinstance(self.event, Event):
            raise TypeError("AgentEventPublication event must be an Event")


class AgentEventPublisher:
    """Crash-reconcilable publication of compact agent.* Events into the raw EventLog."""

    def __init__(self, *, store, event_log):
        if not isinstance(store, AgentStore):
            raise TypeError("AgentEventPublisher store must be an AgentStore")
        if not isinstance(event_log, EventLog):
            raise TypeError("AgentEventPublisher event_log must be an EventLog")
        self.store = store
        self.event_log = event_log
        with self.store.transaction() as connection:
            connection.executescript(_PUBLICATION_SQL)

    @staticmethod
    def _row(row):
        if row is None:
            return None
        return {
            "publication_key": row["publication_key"],
            "event_id": row["event_id"],
            "content_hash": row["content_hash"],
            "event": json.loads(row["event_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get(self, publication_key):
        publication_key = _require_text(publication_key, "publication_key")
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_event_publications WHERE publication_key = ?",
                (publication_key,),
            ).fetchone()
        return self._row(row)

    def list_publications(self, *, status=None):
        if status is not None and status not in {"prepared", "published"}:
            raise ValueError(f"Unknown agent event publication status: {status!r}")
        query = "SELECT * FROM agent_event_publications"
        values = ()
        if status is not None:
            query += " WHERE status = ?"
            values = (status,)
        query += " ORDER BY created_at, publication_key"
        with self.store.transaction() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._row(row) for row in rows]

    def _prepare(
        self,
        publication_key,
        *,
        event_type,
        payload,
        source,
        session_id,
        references,
        timestamp,
    ):
        publication_key = _require_text(publication_key, "publication_key")
        existing = self.get(publication_key)
        event_id = existing["event_id"] if existing is not None else f"ev_{uuid4()}"
        event = Event(
            event_type,
            payload,
            source=source,
            session_id=session_id,
            references=list(references),
            event_id=event_id,
            timestamp=timestamp,
        )
        record = event.to_dict()
        digest = _content_hash(record)

        if existing is not None:
            if existing["content_hash"] != digest or existing["event"] != record:
                raise ValueError(
                    f"publication_key {publication_key!r} was replayed with different Event content"
                )
            return existing, event, True

        created_at = _now()
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO agent_event_publications(
                    publication_key, event_id, content_hash, event_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'prepared', ?, ?)
                """,
                (
                    publication_key,
                    event_id,
                    digest,
                    _canonical_json(record),
                    created_at,
                    created_at,
                ),
            )
        return self.get(publication_key), event, False

    def _raw_record(self, event_id):
        matches = [
            record
            for record in self.event_log.load_events()
            if record["id"] == event_id
        ]
        if len(matches) > 1:
            raise ValueError(f"EventLog contains duplicate Event id: {event_id}")
        return matches[0] if matches else None

    def _mark_published(self, publication_key):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM agent_event_publications WHERE publication_key = ?",
                (publication_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown agent event publication: {publication_key}")
            if row["status"] == "published":
                return
            connection.execute(
                """
                UPDATE agent_event_publications
                SET status = 'published', updated_at = ?
                WHERE publication_key = ?
                """,
                (_now(), publication_key),
            )

    def publish(
        self,
        publication_key,
        *,
        event_type,
        payload,
        references,
        timestamp,
        source="agent.runtime",
        session_id=None,
    ):
        record, event, replayed = self._prepare(
            publication_key,
            event_type=event_type,
            payload=payload,
            source=source,
            session_id=session_id,
            references=references,
            timestamp=timestamp,
        )

        raw = self._raw_record(record["event_id"])
        if raw is None:
            self.event_log.write(event)
        elif raw != record["event"]:
            raise ValueError(
                f"EventLog content conflict for reserved Event id {record['event_id']}"
            )
        else:
            replayed = True

        self._mark_published(publication_key)
        published = self.get(publication_key)
        return AgentEventPublication(
            publication_key=publication_key,
            event_id=published["event_id"],
            content_hash=published["content_hash"],
            status=published["status"],
            replayed=replayed,
            event=_event_from_record(published["event"]),
        )


class AgentExperienceCapture:
    """Select significant AgentLoop facts and publish compact agent.* Events."""

    def __init__(self, *, publisher, registry):
        if not isinstance(publisher, AgentEventPublisher):
            raise TypeError("AgentExperienceCapture publisher must be an AgentEventPublisher")
        if not isinstance(registry, ToolRegistry):
            raise TypeError("AgentExperienceCapture registry must be a ToolRegistry")
        self.publisher = publisher
        self.registry = registry

    @staticmethod
    def _turn_references(run_id, goal_id, turn):
        refs = [
            _reference("agent_run", run_id),
            _reference("goal", goal_id),
            _reference("agent_step", turn.step_id),
        ]
        if turn.choice is not None:
            _optional_reference(refs, "action_proposal", turn.choice.get("selected_proposal_id"))
        if turn.action is not None:
            _optional_reference(refs, "action", turn.action.public_id)
        if turn.receipt is not None:
            _optional_reference(refs, "execution_receipt", turn.receipt.public_id)
        if turn.observation is not None:
            _optional_reference(refs, "observation", turn.observation.public_id)
        if turn.verification_result is not None:
            _optional_reference(refs, "verification_result", turn.verification_result.public_id)
        return refs

    def _publish_turn_failure(self, result, turn):
        if turn.action is None or turn.receipt is None:
            return None
        verification_outcome = (
            turn.verification_result.outcome
            if turn.verification_result is not None
            else None
        )
        failed = turn.receipt.status != "succeeded" or verification_outcome in {
            "failure",
            "blocked",
        }
        if not failed:
            return None
        timestamp = (
            turn.verification_result.timestamp
            if turn.verification_result is not None
            else turn.receipt.finished_at
        )
        return self.publisher.publish(
            f"agent.failure:{result.run['id']}:{turn.step_id}",
            event_type="agent.failure",
            payload={
                "run_id": result.run["id"],
                "step_id": turn.step_id,
                "tool": turn.action.tool,
                "tool_version": turn.action.tool_version,
                "receipt_status": turn.receipt.status,
                "error_code": turn.receipt.error_code,
                "verification_outcome": verification_outcome,
            },
            references=self._turn_references(result.run["id"], result.goal["id"], turn),
            timestamp=timestamp,
        )

    def _publish_action(self, result, turn):
        if turn.action is None or turn.receipt is None or turn.receipt.status != "succeeded":
            return None
        descriptor = self.registry.get(turn.action.tool, turn.action.tool_version)
        if descriptor.effect_class == "read_only":
            return None
        return self.publisher.publish(
            f"agent.action:{result.run['id']}:{turn.step_id}",
            event_type="agent.action",
            payload={
                "run_id": result.run["id"],
                "step_id": turn.step_id,
                "tool": turn.action.tool,
                "tool_version": turn.action.tool_version,
                "effect_class": descriptor.effect_class,
                "receipt_status": turn.receipt.status,
            },
            references=self._turn_references(result.run["id"], result.goal["id"], turn),
            timestamp=turn.receipt.finished_at,
        )

    def _publish_observation(self, result, turn):
        if turn.observation is None or turn.verification_result is None:
            return None
        if turn.verification_result.outcome not in SIGNIFICANT_VERIFICATION_OUTCOMES:
            return None
        return self.publisher.publish(
            f"agent.observation:{result.run['id']}:{turn.step_id}",
            event_type="agent.observation",
            payload={
                "run_id": result.run["id"],
                "step_id": turn.step_id,
                "observation_kind": turn.observation.kind,
                "verification_outcome": turn.verification_result.outcome,
                "criterion_satisfied": turn.verification_result.criterion_satisfied,
            },
            references=self._turn_references(result.run["id"], result.goal["id"], turn),
            timestamp=turn.verification_result.timestamp,
        )

    def _publish_strategy_change(self, result, previous_failed_turn, current_turn):
        if previous_failed_turn is None or current_turn.action is None:
            return None
        previous_action = previous_failed_turn.action
        if previous_action is None:
            return None
        before = action_fingerprint(
            previous_action.tool,
            previous_action.tool_version,
            previous_action.to_dict()["arguments"],
        )
        after = action_fingerprint(
            current_turn.action.tool,
            current_turn.action.tool_version,
            current_turn.action.to_dict()["arguments"],
        )
        if before == after:
            return None
        refs = [
            _reference("agent_run", result.run["id"]),
            _reference("goal", result.goal["id"]),
            _reference("agent_step", previous_failed_turn.step_id),
            _reference("agent_step", current_turn.step_id),
            _reference("action", previous_action.public_id),
            _reference("action", current_turn.action.public_id),
        ]
        return self.publisher.publish(
            (
                f"agent.strategy_change:{result.run['id']}:"
                f"{previous_failed_turn.step_id}:{current_turn.step_id}"
            ),
            event_type="agent.strategy_change",
            payload={
                "run_id": result.run["id"],
                "from_step_id": previous_failed_turn.step_id,
                "to_step_id": current_turn.step_id,
                "from_tool": previous_action.tool,
                "to_tool": current_turn.action.tool,
                "reason": "different action selected after a failed prior turn",
            },
            references=refs,
            timestamp=current_turn.action.created_at,
        )

    def _publish_result(self, result):
        refs = [
            _reference("agent_run", result.run["id"]),
            _reference("goal", result.goal["id"]),
            _reference("verification_spec", result.verification_spec.public_id),
        ]
        return self.publisher.publish(
            f"agent.result:{result.run['id']}",
            event_type="agent.result",
            payload={
                "run_id": result.run["id"],
                "goal_id": result.goal["id"],
                "run_status": result.run["status"],
                "goal_status": result.goal["status"],
                "stop_reason": result.stop_reason,
                "turn_count": len(result.turns),
                "completed": bool(result.completed),
            },
            references=refs,
            timestamp=result.run["updated_at"],
        )

    def capture(self, result):
        from anima.agent.runtime import AgentLoopResult

        if not isinstance(result, AgentLoopResult):
            raise TypeError("AgentExperienceCapture requires an AgentLoopResult")

        publications = []
        previous_failed_turn = None
        for turn in result.turns:
            strategy_change = self._publish_strategy_change(
                result,
                previous_failed_turn,
                turn,
            )
            if strategy_change is not None:
                publications.append(strategy_change)

            failure = self._publish_turn_failure(result, turn)
            if failure is not None:
                publications.append(failure)

            action = self._publish_action(result, turn)
            if action is not None:
                publications.append(action)

            observation = self._publish_observation(result, turn)
            if observation is not None:
                publications.append(observation)

            turn_failed = False
            if turn.receipt is not None and turn.receipt.status != "succeeded":
                turn_failed = True
            if (
                turn.verification_result is not None
                and turn.verification_result.outcome in {"failure", "blocked"}
            ):
                turn_failed = True
            previous_failed_turn = turn if turn_failed else None

        publications.append(self._publish_result(result))
        return tuple(publications)


__all__ = [
    "AgentEventPublication",
    "AgentEventPublisher",
    "AgentExperienceCapture",
    "SIGNIFICANT_VERIFICATION_OUTCOMES",
]
