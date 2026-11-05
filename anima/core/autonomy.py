"""P3-C: bounded, durable, event-triggered Core driver for the one-door profile.

The scheduler never invokes tools directly. It delegates to P3-B's policy,
Stage6 execution ledger, independent observation and verifier. There is no
background thread, LLM-generated Goal or unrestricted environment access.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone

from anima.core.door_execution import CoreDoorExecution
from anima.core.door_world import DOOR_SUBJECT, DOOR_PREDICATE, DOOR_SOURCE
from anima.core.goal_decision import CoreGoalDecision


_SCHEMA = """
CREATE TABLE IF NOT EXISTS core_autonomy_meta (
    name TEXT PRIMARY KEY,
    integer_value INTEGER NOT NULL CHECK(integer_value >= 0)
);
CREATE TABLE IF NOT EXISTS core_auto_triggers (
    trigger_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('goal', 'event')),
    reference_id TEXT NOT NULL,
    subject_ref TEXT,
    predicate_ref TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending', 'done')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_core_auto_pending
    ON core_auto_triggers(status, created_at);
CREATE TABLE IF NOT EXISTS core_auto_attempts (
    trigger_key TEXT NOT NULL REFERENCES core_auto_triggers(trigger_key),
    goal_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('started', 'finished')),
    outcome TEXT,
    reason_code TEXT,
    operation_id TEXT,
    evidence_event_id TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(trigger_key, goal_id)
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True)
class AutoStep:
    trigger_key: str
    goal_id: str
    outcome: str
    reason_code: str
    operation_id: str | None
    evidence_event_id: str | None


@dataclass(frozen=True, slots=True)
class AutoDrain:
    turns: tuple[AutoStep, ...]
    examined_triggers: int
    pending_triggers: int
    more_input_events: bool


class CoreAutonomy:
    """Single-process system-owned trigger scanner and bounded driver.

    The Core journal is canonical; new observations are discovered by a
    persistent monotonic rowid cursor. Goal bindings are also recovered on
    restart, so a crash after binding but before notification loses no work.
    A crashed 'started' attempt remains retryable; the underlying Stage6
    operation ledger is responsible for reconciling uncertain side effects.
    """

    def __init__(self, *, decisions: CoreGoalDecision, executor: CoreDoorExecution):
        if not isinstance(decisions, CoreGoalDecision):
            raise TypeError("CoreAutonomy requires CoreGoalDecision")
        if not isinstance(executor, CoreDoorExecution):
            raise TypeError("CoreAutonomy requires CoreDoorExecution")
        if executor.decisions is not decisions:
            raise ValueError("Scheduler and executor must share Goal authority")
        self.decisions = decisions
        self.executor = executor
        with closing(self.decisions._connect()) as connection:
            connection.executescript(_SCHEMA)
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO core_autonomy_meta(name,integer_value)"
                    " VALUES ('event_cursor',0)"
                )

    def _enqueue_bound_goals(self, connection):
        # Same core_work.db as the immutable bindings. Trigger is unique and
        # remains discoverable even if bind() committed before a crash.
        connection.execute(
            "INSERT OR IGNORE INTO core_auto_triggers("
            "trigger_key,kind,reference_id,subject_ref,predicate_ref,status,created_at)"
            " SELECT 'goal:' || goal_id,'goal',goal_id,subject_ref,predicate_ref,"
            " 'pending',? FROM core_goal_bindings",
            (_now(),),
        )

    def sync(self, *, max_new_events=64):
        """Find committed Core input without assuming a transient RAM message."""
        if type(max_new_events) is not int or not 1 <= max_new_events <= 256:
            raise ValueError("max_new_events must be 1..256")
        with closing(self.decisions._connect()) as connection:
            row = connection.execute(
                "SELECT integer_value FROM core_autonomy_meta WHERE name='event_cursor'"
            ).fetchone()
            cursor = row["integer_value"]
        observations = self.decisions.ingress.observation_triggers_after(
            cursor, limit=max_new_events
        )
        with closing(self.decisions._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = connection.execute(
                    "SELECT integer_value FROM core_autonomy_meta WHERE name='event_cursor'"
                ).fetchone()["integer_value"]
                # Single-writer policy for v0.1. If another process advanced
                # the cursor, fail closed rather than skipping its work.
                if current != cursor:
                    raise RuntimeError("Core autonomous event cursor changed concurrently")
                self._enqueue_bound_goals(connection)
                for row in observations:
                    if (
                        row["rowid"] <= cursor
                        or row["kind"] != "state.property"
                        # The trusted internal readback sensor is NOT a
                        # scheduler trigger; otherwise every verification
                        # creates a self-sustaining loop of new triggers.
                        or row["source_ref"] == DOOR_SOURCE
                        or row["subject_ref"] is None
                        or row["predicate_ref"] is None
                        or row["outcome"] not in {
                            "ACCEPTED_NEW", "ACCEPTED_SUPPORT",
                            "UPDATED_LATER", "MARKED_DISPUTED",
                        }
                    ):
                        continue
                    connection.execute(
                        "INSERT OR IGNORE INTO core_auto_triggers("
                        "trigger_key,kind,reference_id,subject_ref,predicate_ref,"
                        "status,created_at) VALUES(?,?,?,?,?,'pending',?)",
                        (
                            "event:" + row["event_id"], "event", row["event_id"],
                            row["subject_ref"], row["predicate_ref"], _now(),
                        ),
                    )
                if observations:
                    connection.execute(
                        "UPDATE core_autonomy_meta SET integer_value=?"
                        " WHERE name='event_cursor'",
                        (observations[-1]["rowid"],),
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return len(observations) == max_new_events

    def _reconcile_terminal_attempts(self, connection):
        """Close orphaned 'started' attempts without running tools or inventing proof.

        Crash after verified Goal completion but before scheduler audit can
        leave a started attempt. Only an existing durable Core proof permits
        a success outcome. Cancellation is recorded as deferred, not success.
        Called under the scheduler's existing BEGIN IMMEDIATE transaction.
        """
        rows = connection.execute(
            "SELECT trigger_key, goal_id FROM core_auto_attempts"
            " WHERE status='started' ORDER BY rowid"
        ).fetchall()
        for row in rows:
            goal = self.decisions.goals.get_goal(row["goal_id"])
            if goal is None:
                raise ValueError("Autonomy attempt references missing Goal")
            if goal["status"] == "completed":
                proof = self.executor._proof(row["goal_id"])
                if proof is None:
                    # Stage2 may be completed independently by the operator.
                    # Reconcile attempt bookkeeping, but NEVER invent a
                    # successful Core verification or a sensor evidence ID.
                    connection.execute(
                        "UPDATE core_auto_attempts SET status='finished',"
                        " outcome='DEFERRED',"
                        " reason_code='COMPLETED_WITHOUT_CORE_PROOF',"
                        " operation_id=NULL, evidence_event_id=NULL, updated_at=?"
                        " WHERE trigger_key=? AND goal_id=? AND status='started'",
                        (_now(), row["trigger_key"], row["goal_id"]),
                    )
                    continue
                if proof["goal_id"] != row["goal_id"]:
                    raise ValueError("Mismatched autonomous verification proof")
                connection.execute(
                    "UPDATE core_auto_attempts SET status='finished',"
                    " outcome='RECOVERED_VERIFIED_SUCCESS',"
                    " reason_code='PERSISTED_VERIFICATION_PROOF',"
                    " operation_id=?, evidence_event_id=?, updated_at=?"
                    " WHERE trigger_key=? AND goal_id=? AND status='started'",
                    (
                        proof["operation_id"], proof["event_id"], _now(),
                        row["trigger_key"], row["goal_id"],
                    ),
                )
            elif goal["status"] == "cancelled":
                connection.execute(
                    "UPDATE core_auto_attempts SET status='finished',"
                    " outcome='DEFERRED', reason_code='GOAL_NOT_ACTIVE',"
                    " operation_id=NULL, evidence_event_id=NULL, updated_at=?"
                    " WHERE trigger_key=? AND goal_id=? AND status='started'",
                    (_now(), row["trigger_key"], row["goal_id"]),
                )

    def _next_attempt(self, connection):
        self._reconcile_terminal_attempts(connection)
        # Highest priority first according to existing Stage 2 arbitration.
        active = self.decisions.arbitrator.evaluate().entries
        rows = connection.execute(
            "SELECT trigger_key,kind,reference_id,subject_ref,predicate_ref"
            " FROM core_auto_triggers WHERE status='pending'"
            " ORDER BY rowid LIMIT 64"
        ).fetchall()
        candidates = []
        for trigger in rows:
            eligible = []
            for priority_rank, goal in enumerate(active):

                if trigger["kind"] == "goal" and goal.goal_id != trigger["reference_id"]:
                    continue
                binding = self.decisions._binding(goal.goal_id)
                if binding is None:
                    continue
                if (
                    trigger["kind"] == "event"
                    and (
                        binding["subject_ref"] != trigger["subject_ref"]
                        or binding["predicate_ref"] != trigger["predicate_ref"]
                    )
                ):
                    continue
                # P3-C only knows how to operate the one registered door.
                if (binding["subject_ref"], binding["predicate_ref"]) != (
                    DOOR_SUBJECT, DOOR_PREDICATE
                ):
                    continue
                eligible.append((priority_rank, goal.goal_id))
            outstanding = []
            for rank, goal_id in eligible:
                row = connection.execute(
                    "SELECT status FROM core_auto_attempts"
                    " WHERE trigger_key=? AND goal_id=?",
                    (trigger["trigger_key"], goal_id),
                ).fetchone()
                if row is None or row["status"] == "started":
                    outstanding.append((rank, goal_id))
            if not outstanding:
                # A blocked Goal is temporarily unavailable, not terminal.
                # Parking its original trigger preserves wake/rebind/restart
                # recovery without inventing another Goal or Task identity.
                if trigger["kind"] == "goal":
                    target = self.decisions.goals.get_goal(trigger["reference_id"])
                    if target is not None and target["status"] == "blocked":
                        continue
                connection.execute(
                    "UPDATE core_auto_triggers SET status='done'"
                    " WHERE trigger_key=?",
                    (trigger["trigger_key"],),
                )
                continue
            rank, goal_id = min(outstanding)
            candidates.append((rank, trigger["trigger_key"], goal_id))
        if not candidates:
            return None
        # Active Goal priority is authoritative across all scanned triggers,
        # not merely within the oldest event. Existing GoalArbitrator defines
        # deterministic rank (priority, creation time, ID).
        _, trigger_key, goal_id = min(candidates, key=lambda x: x[0])
        return trigger_key, goal_id

    def pending_count(self):
        with closing(self.decisions._connect()) as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM core_auto_triggers WHERE status='pending'"
            ).fetchone()[0]

    def attempts(self):
        with closing(self.decisions._connect()) as connection:
            rows = connection.execute(
                "SELECT trigger_key,goal_id,status,outcome,reason_code,"
                "operation_id,evidence_event_id FROM core_auto_attempts"
                " ORDER BY rowid"
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def drain(self, *, max_steps=4, max_triggers=32, max_new_events=64):
        """Process bounded available triggers, then return to idle.

        No polling/sleep/background work. A subsequent wake, Goal bind,
        relevant sensor event, or explicit drain resumes durable pending work.
        """
        if type(max_steps) is not int or not 1 <= max_steps <= 32:
            raise ValueError("max_steps must be 1..32")
        if type(max_triggers) is not int or not 1 <= max_triggers <= 128:
            raise ValueError("max_triggers must be 1..128")
        more = self.sync(max_new_events=max_new_events)
        turns = []
        examined = 0
        # Recover committed independent proofs BEFORE checking active Goals:
        # the Goal may already be completed while its Task transition was
        # interrupted by a crash. No sensor or world effect is required.
        for recovered in self.executor.recover_proofs(limit=max_steps):
            turns.append(
                AutoStep(
                    "proof:" + recovered.goal_id,
                    recovered.goal_id,
                    recovered.outcome,
                    recovered.reason_code,
                    recovered.operation_id,
                    recovered.evidence_event_id,
                )
            )
            if len(turns) >= max_steps:
                return AutoDrain(
                    turns=tuple(turns), examined_triggers=examined,
                    pending_triggers=self.pending_count(), more_input_events=more,
                )
        while len(turns) < max_steps and examined < max_triggers:
            with closing(self.decisions._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    selected = self._next_attempt(connection)
                    if selected is None:
                        connection.commit()
                        break
                    key, goal_id = selected
                    connection.execute(
                        "INSERT INTO core_auto_attempts("
                        "trigger_key,goal_id,status,updated_at)"
                        " VALUES(?,?,'started',?)"
                        " ON CONFLICT(trigger_key,goal_id) DO UPDATE"
                        " SET status='started',updated_at=excluded.updated_at",
                        (key, goal_id, _now()),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
            examined += 1
            # Execute outside Core scheduler transaction: external world and
            # Stage6 ledger have independent durable commit boundaries.
            turn = self.executor.run(goal_id)
            with closing(self.decisions._connect()) as connection:
                with connection:
                    connection.execute(
                        "UPDATE core_auto_attempts SET status='finished',"
                        "outcome=?,reason_code=?,operation_id=?,"
                        "evidence_event_id=?,updated_at=?"
                        " WHERE trigger_key=? AND goal_id=?",
                        (
                            turn.outcome, turn.reason_code, turn.operation_id,
                            turn.evidence_event_id, _now(), key, goal_id,
                        ),
                    )
            turns.append(
                AutoStep(
                    key, goal_id, turn.outcome, turn.reason_code,
                    turn.operation_id, turn.evidence_event_id,
                )
            )
        return AutoDrain(
            turns=tuple(turns), examined_triggers=examined,
            pending_triggers=self.pending_count(), more_input_events=more,
        )


__all__ = ["CoreAutonomy", "AutoStep", "AutoDrain"]
