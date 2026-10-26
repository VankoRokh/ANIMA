import json
import math
from uuid import uuid4

from anima.internal_state.goals import (
    GOAL_ID_PREFIX,
    GOAL_TRANSITION_ID_PREFIX,
    GoalStore,
    _parse_timestamp,
    _validate_prefixed_uuid4,
)
from anima.internal_state.recovery import (
    _canonical_json,
    _now,
    _request_hash,
    _require_text,
)
from anima.internal_state.store import InternalStateStore


class GoalCreationRecovery:
    """Make source-backed Goal creation replay-safe without changing GoalStore."""

    def __init__(self, store, goal_store):
        if not isinstance(store, InternalStateStore):
            raise TypeError("GoalCreationRecovery store must be an InternalStateStore")
        if not isinstance(goal_store, GoalStore):
            raise TypeError("GoalCreationRecovery goal_store must be a GoalStore")
        self.store = store
        self.goal_store = goal_store

    @staticmethod
    def _request_payload(kwargs):
        source = _require_text(kwargs.get("source"), "Goal source")
        description = _require_text(kwargs.get("description"), "Goal description")
        success_criterion = _require_text(
            kwargs.get("success_criterion"),
            "Goal success_criterion",
        )
        reason = _require_text(kwargs.get("reason"), "Goal creation reason")
        source_id = _require_text(kwargs.get("source_id"), "Goal source_id")

        priority = kwargs.get("priority")
        if (
            not isinstance(priority, (int, float))
            or isinstance(priority, bool)
            or not math.isfinite(float(priority))
            or float(priority) < 0.0
        ):
            raise ValueError("Goal priority must be a finite non-negative number")

        timestamp = kwargs.get("timestamp")
        if timestamp is not None:
            _parse_timestamp(timestamp, "Goal timestamp")

        public_id = kwargs.get("public_id")
        if public_id is not None:
            _validate_prefixed_uuid4(
                public_id,
                GOAL_ID_PREFIX,
                "Goal public_id",
            )

        transition_id = kwargs.get("transition_id")
        if transition_id is not None:
            _validate_prefixed_uuid4(
                transition_id,
                GOAL_TRANSITION_ID_PREFIX,
                "GoalTransition public_id",
            )

        return {
            "source": source,
            "priority": float(priority),
            "description": description,
            "success_criterion": success_criterion,
            "reason": reason,
            "source_id": source_id,
            "timestamp": timestamp,
            "public_id": public_id,
            "transition_id": transition_id,
        }

    @staticmethod
    def _recovery_payload(request):
        payload = dict(request)
        payload["timestamp"] = payload["timestamp"] or _now()
        payload["public_id"] = payload["public_id"] or f"{GOAL_ID_PREFIX}{uuid4()}"
        payload["transition_id"] = (
            payload["transition_id"]
            or f"{GOAL_TRANSITION_ID_PREFIX}{uuid4()}"
        )
        return payload

    @staticmethod
    def _row(row):
        if row is None:
            return None
        return {
            "source_id": row["source_id"],
            "operation_kind": row["operation_kind"],
            "request_hash": row["request_hash"],
            "payload": json.loads(row["payload_json"]),
            "status": row["status"],
        }

    def _operation(self, source_id):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM source_operations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        return self._row(row)

    def _begin(self, request, recovery_payload):
        source_id = request["source_id"]
        digest = _request_hash(request)
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM source_operations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO source_operations(
                        source_id, operation_kind, request_hash, payload_json,
                        status, started_at, completed_at
                    ) VALUES (?, 'goal_create', ?, ?, 'processing', ?, NULL)
                    """,
                    (
                        source_id,
                        digest,
                        _canonical_json(recovery_payload),
                        _now(),
                    ),
                )
                return recovery_payload

        record = self._row(row)
        if record["operation_kind"] != "goal_create":
            raise ValueError(
                f"source_id {source_id!r} is already bound to a different "
                "Stage 2 operation"
            )
        if record["request_hash"] != digest:
            raise ValueError(
                f"source_id {source_id!r} was replayed with different payload"
            )
        return record["payload"]

    def _complete(self, source_id):
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE source_operations
                SET status = 'done', completed_at = ?
                WHERE source_id = ? AND status = 'processing'
                """,
                (_now(), source_id),
            )

    def _apply_idempotent(self, payload):
        existing = self.goal_store.get_goal(payload["public_id"])
        if existing is None:
            return self.goal_store.create_goal(**payload)

        if (
            existing["source"] != payload["source"]
            or float(existing["priority"]) != float(payload["priority"])
            or existing["description"] != payload["description"]
            or existing["success_criterion"] != payload["success_criterion"]
            or existing["created_at"] != payload["timestamp"]
        ):
            raise ValueError(
                f"Goal {payload['public_id']} conflicts with recovered goal_create payload"
            )

        transitions = self.goal_store.list_goal_transitions(
            goal_id=payload["public_id"]
        )
        if not any(
            item["id"] == payload["transition_id"]
            and item["from_status"] is None
            and item["to_status"] == "active"
            and item["source_id"] == payload["source_id"]
            and item["reason"] == payload["reason"]
            for item in transitions
        ):
            raise ValueError(
                f"Goal {payload['public_id']} is missing its recovered creation transition"
            )
        return existing

    def create_goal(self, **kwargs):
        if kwargs.get("source_id") is None:
            return self.goal_store.create_goal(**kwargs)

        request = self._request_payload(kwargs)
        existing = self._operation(request["source_id"])
        if existing is not None:
            if existing["operation_kind"] != "goal_create":
                raise ValueError(
                    f"source_id {request['source_id']!r} is already bound to a different "
                    "Stage 2 operation"
                )
            if existing["request_hash"] != _request_hash(request):
                raise ValueError(
                    f"source_id {request['source_id']!r} was replayed with different payload"
                )
            payload = existing["payload"]
        else:
            payload = self._begin(request, self._recovery_payload(request))

        goal = self._apply_idempotent(payload)
        self._complete(request["source_id"])
        return goal

    def recover_pending(self):
        with self.store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM source_operations
                WHERE status = 'processing' AND operation_kind = 'goal_create'
                ORDER BY started_at, source_id
                """
            ).fetchall()

        recovered = []
        for row in rows:
            record = self._row(row)
            self._apply_idempotent(record["payload"])
            self._complete(record["source_id"])
            recovered.append(record["source_id"])
        return tuple(recovered)
