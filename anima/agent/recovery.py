import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from anima.agent.contracts import (
    Action,
    ExecutionReceipt,
    Observation,
    VerificationResult,
    VerificationSpec,
)
from anima.agent.planner import PlannerTurn
from anima.agent.store import AgentStore


_RECOVERY_SQL = """
CREATE TABLE IF NOT EXISTS agent_recovery_runs (
    run_id TEXT PRIMARY KEY,
    verification_spec_json TEXT NOT NULL,
    verification_spec_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES agent_runs(public_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_recovery_steps (
    step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    planner_turn_json TEXT,
    action_json TEXT,
    receipt_json TEXT,
    observation_json TEXT,
    verification_result_json TEXT,
    goal_applied INTEGER NOT NULL DEFAULT 0 CHECK (goal_applied IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (step_id) REFERENCES agent_steps(public_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES agent_runs(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_recovery_steps_run
    ON agent_recovery_steps(run_id, created_at, step_id);
"""

_ARTIFACT_COLUMNS = {
    "planner_turn": "planner_turn_json",
    "action": "action_json",
    "receipt": "receipt_json",
    "observation": "observation_json",
    "verification_result": "verification_result_json",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RecoveryStepArtifacts:
    step_id: str
    run_id: str
    planner_turn: PlannerTurn | None
    action: Action | None
    receipt: ExecutionReceipt | None
    observation: Observation | None
    verification_result: VerificationResult | None
    goal_applied: bool


class AgentRecoveryJournal:
    """Persistent validated artifacts used to resume AgentLoop after interruption."""

    def __init__(self, store):
        if not isinstance(store, AgentStore):
            raise TypeError("AgentRecoveryJournal store must be an AgentStore")
        self.store = store
        with self.store.transaction() as connection:
            connection.executescript(_RECOVERY_SQL)

    def ensure_run(self, verification_spec):
        if not isinstance(verification_spec, VerificationSpec):
            raise TypeError("ensure_run requires a VerificationSpec")
        run = self.store.get_run(verification_spec.run_id)
        if run is None:
            raise ValueError(f"Unknown AgentRun: {verification_spec.run_id}")

        encoded = _canonical_json(verification_spec.to_dict())
        digest = _sha256_text(encoded)
        now = _now()
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_recovery_runs WHERE run_id = ?",
                (verification_spec.run_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO agent_recovery_runs(
                        run_id, verification_spec_json, verification_spec_hash,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        verification_spec.run_id,
                        encoded,
                        digest,
                        now,
                        now,
                    ),
                )
            elif (
                row["verification_spec_hash"] != digest
                or row["verification_spec_json"] != encoded
            ):
                raise ValueError(
                    "AgentRun recovery VerificationSpec cannot change after persistence"
                )
        return verification_spec

    def get_verification_spec(self, run_id):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT verification_spec_json FROM agent_recovery_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return VerificationSpec.from_dict(json.loads(row["verification_spec_json"]))

    def ensure_step(self, run_id, step_id):
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown AgentRun: {run_id}")
        step = self.store.get_step(step_id)
        if step is None:
            raise ValueError(f"Unknown AgentStep: {step_id}")
        if step["run_id"] != run_id:
            raise ValueError("Recovery step does not belong to supplied AgentRun")

        now = _now()
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT run_id FROM agent_recovery_steps WHERE step_id = ?",
                (step_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO agent_recovery_steps(
                        step_id, run_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (step_id, run_id, now, now),
                )
            elif row["run_id"] != run_id:
                raise ValueError("Recovery journal step/run ownership conflict")
        return self.load_step(step_id)

    def _store_artifact(self, step_id, kind, artifact):
        column = _ARTIFACT_COLUMNS[kind]
        if kind == "planner_turn" and not isinstance(artifact, PlannerTurn):
            raise TypeError("planner_turn artifact must be PlannerTurn")
        if kind == "action" and not isinstance(artifact, Action):
            raise TypeError("action artifact must be Action")
        if kind == "receipt" and not isinstance(artifact, ExecutionReceipt):
            raise TypeError("receipt artifact must be ExecutionReceipt")
        if kind == "observation" and not isinstance(artifact, Observation):
            raise TypeError("observation artifact must be Observation")
        if kind == "verification_result" and not isinstance(artifact, VerificationResult):
            raise TypeError("verification_result artifact must be VerificationResult")

        encoded = _canonical_json(artifact.to_dict())
        with self.store.transaction() as connection:
            row = connection.execute(
                f"SELECT run_id, {column} FROM agent_recovery_steps WHERE step_id = ?",
                (step_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown recovery step: {step_id}")
            if row[column] is not None and row[column] != encoded:
                raise ValueError(
                    f"Recovery artifact {kind} for {step_id} cannot be replaced"
                )
            if row[column] is None:
                connection.execute(
                    f"UPDATE agent_recovery_steps SET {column} = ?, updated_at = ? WHERE step_id = ?",
                    (encoded, _now(), step_id),
                )
        return artifact

    def save_planner_turn(self, step_id, planner_turn):
        return self._store_artifact(step_id, "planner_turn", planner_turn)

    def save_action(self, step_id, action):
        return self._store_artifact(step_id, "action", action)

    def save_receipt(self, step_id, receipt):
        return self._store_artifact(step_id, "receipt", receipt)

    def save_observation(self, step_id, observation):
        return self._store_artifact(step_id, "observation", observation)

    def save_verification_result(self, step_id, verification_result):
        return self._store_artifact(
            step_id,
            "verification_result",
            verification_result,
        )

    def mark_goal_applied(self, step_id):
        with self.store.transaction() as connection:
            row = connection.execute(
                """
                SELECT verification_result_json, goal_applied
                FROM agent_recovery_steps WHERE step_id = ?
                """,
                (step_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown recovery step: {step_id}")
            if row["verification_result_json"] is None:
                raise ValueError(
                    "Cannot mark Goal application before VerificationResult persistence"
                )
            if not row["goal_applied"]:
                connection.execute(
                    """
                    UPDATE agent_recovery_steps
                    SET goal_applied = 1, updated_at = ?
                    WHERE step_id = ?
                    """,
                    (_now(), step_id),
                )

    @staticmethod
    def _decode(row):
        def load(column, factory):
            value = row[column]
            if value is None:
                return None
            return factory(json.loads(value))

        return RecoveryStepArtifacts(
            step_id=row["step_id"],
            run_id=row["run_id"],
            planner_turn=load("planner_turn_json", PlannerTurn.from_dict),
            action=load("action_json", Action.from_dict),
            receipt=load("receipt_json", ExecutionReceipt.from_dict),
            observation=load("observation_json", Observation.from_dict),
            verification_result=load(
                "verification_result_json",
                VerificationResult.from_dict,
            ),
            goal_applied=bool(row["goal_applied"]),
        )

    def load_step(self, step_id):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_recovery_steps WHERE step_id = ?",
                (step_id,),
            ).fetchone()
        return None if row is None else self._decode(row)

    def list_steps(self, run_id):
        with self.store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_recovery_steps
                WHERE run_id = ?
                ORDER BY created_at, step_id
                """,
                (run_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]


__all__ = ["AgentRecoveryJournal", "RecoveryStepArtifacts"]
