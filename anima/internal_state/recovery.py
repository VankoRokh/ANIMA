import hashlib
import json
from datetime import datetime, timezone

from anima.internal_state.goal_progress import (
    GoalObservation,
    GoalObservationKind,
    GoalProgressResult,
    VerificationKind,
)
from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore
from anima.internal_state.transition_engine import (
    StateSignal,
    SignalKind,
    TransitionEngine,
    _CAUSE_TYPES,
    _SIGNAL_EFFECTS,
)


_OPERATION_KINDS = {"state_signal", "goal_observation"}

_OPERATION_SQL = """
CREATE TABLE IF NOT EXISTS source_operations (
    source_id TEXT PRIMARY KEY,
    operation_kind TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'done')),
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_operations_status
    ON source_operations(status, started_at);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _request_hash(payload):
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _enum_value(value, enum_type, label):
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as error:
        raise ValueError(f"Unknown {label}: {value!r}") from error


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


class RecoveryLedger:
    """Persistent source journal for restart-safe Stage 2 mutations."""

    def __init__(self, store):
        if not isinstance(store, InternalStateStore):
            raise TypeError("RecoveryLedger store must be an InternalStateStore")
        self.store = store
        with self.store.transaction() as connection:
            connection.executescript(_OPERATION_SQL)

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
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }

    def get(self, source_id):
        source_id = _require_text(source_id, "source operation source_id")
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM source_operations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        return self._row(row)

    def begin(self, *, source_id, operation_kind, request_payload, recovery_payload):
        source_id = _require_text(source_id, "source operation source_id")
        if operation_kind not in _OPERATION_KINDS:
            raise ValueError(f"Unknown source operation kind: {operation_kind!r}")

        digest = _request_hash(request_payload)
        payload_json = _canonical_json(recovery_payload)
        started_at = _now()

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
                    ) VALUES (?, ?, ?, ?, 'processing', ?, NULL)
                    """,
                    (
                        source_id,
                        operation_kind,
                        digest,
                        payload_json,
                        started_at,
                    ),
                )
            else:
                current = self._row(row)
                if (
                    current["operation_kind"] != operation_kind
                    or current["request_hash"] != digest
                ):
                    raise ValueError(
                        f"source_id {source_id!r} is already bound to a different "
                        "Stage 2 operation"
                    )
                return current

        return self.get(source_id)

    def verify(self, record, *, operation_kind, request_payload):
        if record["operation_kind"] != operation_kind:
            raise ValueError(
                f"source_id {record['source_id']!r} is already bound to a different "
                "Stage 2 operation"
            )
        if record["request_hash"] != _request_hash(request_payload):
            raise ValueError(
                f"source_id {record['source_id']!r} was replayed with different payload"
            )
        return record

    def complete(self, source_id):
        source_id = _require_text(source_id, "source operation source_id")
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM source_operations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown source operation: {source_id}")
            if row["status"] == "done":
                return
            connection.execute(
                """
                UPDATE source_operations
                SET status = 'done', completed_at = ?
                WHERE source_id = ?
                """,
                (_now(), source_id),
            )

    def pending(self):
        with self.store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM source_operations
                WHERE status = 'processing'
                ORDER BY started_at, source_id
                """
            ).fetchall()
        return [self._row(row) for row in rows]

    def counts(self):
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM source_operations GROUP BY status"
            ).fetchall()
        counts = {"processing": 0, "done": 0}
        for row in rows:
            counts[row["status"]] = row["count"]
        return counts


class RecoveryCoordinator:
    """Idempotent Runtime boundary for state signals and Goal observations."""

    def __init__(self, store, goal_store, transition_engine, goal_progress):
        if not isinstance(store, InternalStateStore):
            raise TypeError("RecoveryCoordinator store must be an InternalStateStore")
        if not isinstance(goal_store, GoalStore):
            raise TypeError("RecoveryCoordinator goal_store must be a GoalStore")
        if not isinstance(transition_engine, TransitionEngine):
            raise TypeError(
                "RecoveryCoordinator transition_engine must be a TransitionEngine"
            )
        self.store = store
        self.goal_store = goal_store
        self.transition_engine = transition_engine
        self.goal_progress = goal_progress
        self.ledger = RecoveryLedger(store)

    @staticmethod
    def _signal_payload(signal):
        kind = _enum_value(signal.kind, SignalKind, "Internal State signal")
        return {
            "kind": kind,
            "source_id": _require_text(signal.source_id, "StateSignal source_id"),
            "reason": _require_text(signal.reason, "StateSignal reason"),
            "importance": signal.importance,
            "goal_id": signal.goal_id,
            "candidate_id": signal.candidate_id,
            "timestamp": signal.timestamp,
        }

    @staticmethod
    def _observation_request_payload(observation):
        if not isinstance(observation, GoalObservation):
            raise TypeError("RecoveryCoordinator requires a GoalObservation")
        return {
            "goal_id": observation.goal_id,
            "kind": _enum_value(
                observation.kind,
                GoalObservationKind,
                "Goal observation kind",
            ),
            "source_id": _require_text(
                observation.source_id,
                "GoalObservation source_id",
            ),
            "reason": _require_text(observation.reason, "GoalObservation reason"),
            "verification": _enum_value(
                observation.verification,
                VerificationKind,
                "Goal verification kind",
            ),
            "candidate_id": observation.candidate_id,
            "importance": observation.importance,
            "criterion_satisfied": observation.criterion_satisfied,
            "timestamp": observation.timestamp,
        }

    @staticmethod
    def _observation_payload(observation):
        return {
            "goal_id": observation.goal_id,
            "kind": GoalObservationKind(observation.kind).value,
            "source_id": observation.source_id,
            "reason": observation.reason,
            "verification": VerificationKind(observation.verification).value,
            "candidate_id": observation.candidate_id,
            "importance": observation.importance,
            "criterion_satisfied": observation.criterion_satisfied,
            "timestamp": observation.timestamp,
        }

    @staticmethod
    def _fixed_signal(signal):
        timestamp = signal.timestamp or _now()
        return StateSignal(
            kind=signal.kind,
            source_id=signal.source_id,
            reason=signal.reason,
            importance=signal.importance,
            goal_id=signal.goal_id,
            candidate_id=signal.candidate_id,
            timestamp=timestamp,
        )

    def _existing_source_transitions(self, signal, effects):
        expected = {
            self.transition_engine._rule_id(effect): effect
            for effect in effects
        }
        existing = [
            item
            for item in self.store.list_state_transitions()
            if item["source_id"] == signal.source_id
        ]
        by_rule = {}

        for transition in existing:
            rule_id = transition["rule_id"]
            if rule_id not in expected:
                raise ValueError(
                    f"source_id {signal.source_id!r} already produced an unexpected "
                    f"StateTransition rule {rule_id!r}"
                )
            if rule_id in by_rule:
                raise ValueError(
                    f"source_id {signal.source_id!r} produced duplicate rule {rule_id!r}"
                )
            if (
                transition["goal_id"] != signal.goal_id
                or transition["candidate_id"] != signal.candidate_id
                or transition["importance"] != signal.importance
                or transition["reason"] != signal.reason
                or transition["cause_type"] != _CAUSE_TYPES[SignalKind(signal.kind)]
            ):
                raise ValueError(
                    f"source_id {signal.source_id!r} StateTransition metadata conflict"
                )
            by_rule[rule_id] = transition

        return by_rule

    def _apply_signal_idempotent(self, signal):
        signal = self.transition_engine._validate_signal(signal)
        effects = _SIGNAL_EFFECTS[SignalKind(signal.kind)]
        existing = self._existing_source_transitions(signal, effects)
        transitions = []

        for effect in effects:
            rule_id = self.transition_engine._rule_id(effect)
            if rule_id in existing:
                transitions.append(existing[rule_id])
                continue

            prior_count = self.transition_engine._prior_same_rule_count(
                effect,
                signal,
                rule_id,
            )
            repetition_factor = self.transition_engine._repetition_factor(
                effect,
                prior_count,
            )
            delta = self.transition_engine._effective_delta(
                effect,
                signal,
                repetition_factor,
            )
            transition = self.store.apply_state_transition(
                state_name=effect.state_name.value,
                delta=delta,
                cause_type=_CAUSE_TYPES[SignalKind(signal.kind)],
                source_id=signal.source_id,
                rule_id=rule_id,
                reason=signal.reason,
                importance=signal.importance,
                repetition_factor=repetition_factor,
                goal_id=signal.goal_id,
                candidate_id=signal.candidate_id,
                timestamp=signal.timestamp,
            )
            transitions.append(transition)

        return tuple(transitions)

    def process_signal(self, signal):
        normalized = self.transition_engine._validate_signal(signal)
        request_payload = self._signal_payload(normalized)
        source_id = normalized.source_id
        existing = self.ledger.get(source_id)

        if existing is None:
            fixed = self._fixed_signal(normalized)
            recovery_payload = self._signal_payload(fixed)
            record = self.ledger.begin(
                source_id=source_id,
                operation_kind="state_signal",
                request_payload=request_payload,
                recovery_payload=recovery_payload,
            )
        else:
            record = self.ledger.verify(
                existing,
                operation_kind="state_signal",
                request_payload=request_payload,
            )

        fixed = StateSignal(**record["payload"])
        transitions = self._apply_signal_idempotent(fixed)
        self.ledger.complete(source_id)
        return transitions

    def _existing_goal_transition(self, observation, target_status):
        existing = [
            item
            for item in self.goal_store.list_goal_transitions(
                goal_id=observation.goal_id
            )
            if item["source_id"] == observation.source_id
        ]
        if len(existing) > 1:
            raise ValueError(
                f"source_id {observation.source_id!r} produced multiple GoalTransitions"
            )
        if not existing:
            return None

        transition = existing[0]
        if (
            transition["to_status"] != target_status
            or transition["reason"] != observation.reason
        ):
            raise ValueError(
                f"source_id {observation.source_id!r} GoalTransition conflict"
            )
        return transition

    def _apply_observation_idempotent(self, observation):
        kind = GoalObservationKind(observation.kind)
        state_mapping = {
            GoalObservationKind.FAILURE: SignalKind.FAILURE,
            GoalObservationKind.PROGRESS: SignalKind.VERIFIED_PROGRESS,
            GoalObservationKind.BLOCKED: SignalKind.FAILURE,
            GoalObservationKind.SUCCESS: SignalKind.VERIFIED_SUCCESS,
        }
        state_transitions = ()
        signal_kind = state_mapping.get(kind)
        if signal_kind is not None:
            state_transitions = self._apply_signal_idempotent(
                StateSignal(
                    kind=signal_kind,
                    source_id=observation.source_id,
                    reason=observation.reason,
                    importance=observation.importance,
                    goal_id=observation.goal_id,
                    candidate_id=observation.candidate_id,
                    timestamp=observation.timestamp,
                )
            )

        target_status = {
            GoalObservationKind.BLOCKED: "blocked",
            GoalObservationKind.REACTIVATED: "active",
            GoalObservationKind.SUCCESS: "completed",
        }.get(kind)
        goal_transition = None

        if target_status is not None:
            goal_transition = self._existing_goal_transition(
                observation,
                target_status,
            )
            if goal_transition is None:
                current = self.goal_store.get_goal(observation.goal_id)
                if current["status"] == target_status:
                    raise ValueError(
                        f"Goal {observation.goal_id} reached {target_status!r} "
                        "without the expected source transition"
                    )
                self.goal_store.transition_goal(
                    observation.goal_id,
                    to_status=target_status,
                    reason=observation.reason,
                    source_id=observation.source_id,
                    timestamp=observation.timestamp,
                )
                goal_transition = self._existing_goal_transition(
                    observation,
                    target_status,
                )

        return GoalProgressResult(
            goal=self.goal_store.get_goal(observation.goal_id),
            state_transitions=tuple(state_transitions),
            goal_transition=goal_transition,
        )

    def observe_goal(self, observation):
        request_payload = self._observation_request_payload(observation)
        source_id = request_payload["source_id"]
        existing = self.ledger.get(source_id)

        if existing is None:
            normalized = self.goal_progress._validate(observation)
            recovery_payload = self._observation_payload(normalized)
            record = self.ledger.begin(
                source_id=source_id,
                operation_kind="goal_observation",
                request_payload=request_payload,
                recovery_payload=recovery_payload,
            )
        else:
            record = self.ledger.verify(
                existing,
                operation_kind="goal_observation",
                request_payload=request_payload,
            )

        fixed = GoalObservation(**record["payload"])
        result = self._apply_observation_idempotent(fixed)
        self.ledger.complete(source_id)
        return result

    def recover_pending(self):
        recovered = []
        for record in self.ledger.pending():
            if record["operation_kind"] == "state_signal":
                self._apply_signal_idempotent(StateSignal(**record["payload"]))
            elif record["operation_kind"] == "goal_observation":
                self._apply_observation_idempotent(
                    GoalObservation(**record["payload"])
                )
            else:
                raise ValueError(
                    f"Unknown pending source operation kind: {record['operation_kind']!r}"
                )
            self.ledger.complete(record["source_id"])
            recovered.append(record["source_id"])
        return tuple(recovered)

    def snapshot(self):
        counts = self.ledger.counts()
        return {
            "processing_operations": counts["processing"],
            "completed_operations": counts["done"],
        }
