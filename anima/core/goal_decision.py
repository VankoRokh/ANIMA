"""P3-A: persistent typed ensure-once Goal binding and bounded decisions.

This module proposes work; it NEVER executes a capability or completes a Goal.
Existing GoalStore and TaskStore remain the canonical lifecycle owners.
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from anima.core.belief import BeliefProjection, MAX_TICK
from anima.core.ingress import CoreIngress
from anima.execution.contracts import ActionSpec
from anima.internal_state.goal_arbitration import GoalArbitrator
from anima.internal_state.goals import GoalStore
from anima.tasks.store import TaskStore


_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS core_goal_bindings (
    goal_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK(mode = 'ensure_once'),
    criterion_kind TEXT NOT NULL CHECK(criterion_kind = 'world.property_equals'),
    subject_ref TEXT NOT NULL,
    predicate_ref TEXT NOT NULL,
    expected_json TEXT NOT NULL,
    bound_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS core_task_intents (
    goal_id TEXT PRIMARY KEY REFERENCES core_goal_bindings(goal_id),
    task_id TEXT NOT NULL UNIQUE,
    reserved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS core_decision_log (
    row_id INTEGER PRIMARY KEY,
    goal_id TEXT NOT NULL,
    task_id TEXT,
    decision TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    as_of_tick INTEGER NOT NULL,
    belief_revision INTEGER,
    candidate_id TEXT,
    created_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _tick(value):
    return type(value) is int and 0 <= value <= MAX_TICK


@dataclass(frozen=True, slots=True)
class GoalCriterion:
    """System-owned binding for one existing Goal; does not create a Goal."""

    goal_id: str
    subject_ref: str
    predicate_ref: str
    expected: dict
    mode: str = "ensure_once"
    kind: str = "world.property_equals"


@dataclass(frozen=True, slots=True)
class CoreDecision:
    """A proposal only. NOOP does not mean Goal success without verification."""

    goal_id: str
    task_id: str | None
    kind: str
    reason_code: str
    as_of_tick: int
    belief_revision: int | None
    evidence_event_ids: tuple[str, ...]
    candidate: ActionSpec | None


class CoreGoalDecision:
    """One bounded, deterministic scheduling decision for a registered Goal.

    Each Goal gets at most one reserved Task ID in core_work.db. If the process
    dies between reservation and TaskStore creation, the same ID is resumed.
    No claim of atomicity across core_work.db, tasks.db, internal_state.db.
    """

    def __init__(
        self,
        *,
        database_file: str | Path,
        goals: GoalStore,
        tasks: TaskStore,
        ingress: CoreIngress,
        actions: Mapping[tuple[str, str, str], ActionSpec],
    ):
        if not isinstance(goals, GoalStore) or not isinstance(tasks, TaskStore):
            raise TypeError("CoreGoalDecision requires Stage 2 GoalStore and Stage 6 TaskStore")
        if not isinstance(ingress, CoreIngress) or ingress.beliefs is None:
            raise ValueError("CoreGoalDecision requires registered Core Belief")
        if not isinstance(actions, Mapping):
            raise TypeError("actions must be a trusted registry")
        copied = dict(actions)
        for key, value in copied.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 3
                or not all(isinstance(k, str) for k in key)
                or not isinstance(value, ActionSpec)
            ):
                raise ValueError("Invalid deterministic action registry entry")
        self.actions = MappingProxyType(copied)
        self.goals = goals
        self.tasks = tasks
        self.ingress = ingress
        self.arbitrator = GoalArbitrator(goals)
        self.database_file = Path(database_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO work_schema_meta(key,value) VALUES('schema_version','1')"
                )
                row = connection.execute(
                    "SELECT value FROM work_schema_meta WHERE key='schema_version'"
                ).fetchone()
                if row["value"] != "1":
                    raise ValueError("Unsupported Core goal/work schema")

    def bind(self, criterion: GoalCriterion):
        """Idempotent immutable criterion binding for an existing active Goal."""
        if not isinstance(criterion, GoalCriterion):
            raise TypeError("Core Goal requires a typed GoalCriterion")
        if criterion.mode != "ensure_once" or criterion.kind != "world.property_equals":
            raise ValueError("Only ensure_once/world.property_equals is supported")
        goal = self.goals.get_goal(criterion.goal_id)
        if goal is None or goal["status"] != "active":
            raise ValueError("Goal must exist and be active before binding")
        rule = self.ingress.beliefs.properties.get(
            (criterion.subject_ref, criterion.predicate_ref)
        )
        if rule is None:
            raise ValueError("Goal criterion requires a registered property")
        if not BeliefProjection._atomic_value(criterion.expected, rule):
            raise ValueError("Goal criterion value violates registered type/vocabulary")
        encoded = _canonical(criterion.expected)
        fingerprint = (
            criterion.mode, criterion.kind, criterion.subject_ref,
            criterion.predicate_ref, encoded
        )
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                old = connection.execute(
                    "SELECT * FROM core_goal_bindings WHERE goal_id=?",
                    (criterion.goal_id,),
                ).fetchone()
                if old is None:
                    connection.execute(
                        "INSERT INTO core_goal_bindings("
                        "goal_id, mode, criterion_kind, subject_ref, predicate_ref,"
                        "expected_json, bound_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (criterion.goal_id, *fingerprint, _now()),
                    )
                    inserted = True
                else:
                    current = (
                        old["mode"], old["criterion_kind"], old["subject_ref"],
                        old["predicate_ref"], old["expected_json"]
                    )
                    if current != fingerprint:
                        raise ValueError("Bound Goal criterion cannot be changed in place")
                    inserted = False
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return inserted

    def _binding(self, goal_id):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM core_goal_bindings WHERE goal_id=?", (goal_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def _reserve_task(self, goal):
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT task_id FROM core_task_intents WHERE goal_id=?",
                    (goal["id"],),
                ).fetchone()
                if row is None:
                    task_id = f"task_{uuid4()}"
                    connection.execute(
                        "INSERT INTO core_task_intents(goal_id, task_id, reserved_at)"
                        " VALUES(?, ?, ?)",
                        (goal["id"], task_id, _now()),
                    )
                else:
                    task_id = row["task_id"]
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        task = self.tasks.get_task(task_id)
        if task is None:
            try:
                task = self.tasks.create_task(
                    source="core.goal",
                    source_id=goal["id"],
                    goal_id=goal["id"],
                    description=f"Evaluate ensure_once criterion for {goal['id']}",
                    reason="core typed Goal requires bounded evaluation",
                    public_id=task_id,
                )
            except ValueError:
                task = self.tasks.get_task(task_id)
                if task is None:
                    raise
        if task.goal_id != goal["id"] or task.source != "core.goal":
            raise ValueError("Reserved Task identity does not match its Goal")
        return task

    def _audit(self, decision):
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO core_decision_log("
                    "goal_id, task_id, decision, reason_code, as_of_tick,"
                    "belief_revision, candidate_id, created_at)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        decision.goal_id, decision.task_id, decision.kind,
                        decision.reason_code, decision.as_of_tick,
                        decision.belief_revision,
                        None if decision.candidate is None else decision.candidate.candidate_id,
                        _now(),
                    ),
                )

    def history(self, goal_id):
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT goal_id,task_id,decision,reason_code,as_of_tick,"
                "belief_revision,candidate_id FROM core_decision_log"
                " WHERE goal_id=? ORDER BY row_id",
                (goal_id,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def step(self, goal_id, *, as_of_tick):
        """One deterministic decision from a typed current Belief snapshot.

        Missing/old/contradictory observations always request a new read.
        A PROPOSE_ACTION never invokes a capability; P3-B must independently
        authorize and re-observe preconditions at the effect boundary.
        """
        if not _tick(as_of_tick):
            raise ValueError("as_of_tick must be an exact registered logical tick")
        goal = self.goals.get_goal(goal_id)
        if goal is None:
            raise ValueError("Unknown Core Goal")
        binding = self._binding(goal_id)
        task_id = None
        revision = None
        evidence = ()
        candidate = None

        if goal["status"] != "active":
            kind, reason = "DEFER", "GOAL_NOT_ACTIVE"
        elif binding is None:
            kind, reason = "DEFER", "UNBOUND_GOAL"
        else:
            task = self._reserve_task(goal)
            task_id = task.public_id
            snapshot = self.ingress.read_belief(
                binding["subject_ref"], binding["predicate_ref"],
                as_of_tick=as_of_tick
            )
            revision = snapshot["revision"]
            evidence = snapshot["evidence_event_ids"]
            if task.status in {"completed", "cancelled", "failed"}:
                kind, reason = "DEFER", "TASK_TERMINAL"
            elif snapshot["freshness"] != "fresh" or snapshot["status"] != "known":
                kind, reason = "REQUEST_OBSERVATION", "BELIEF_NOT_ACTIONABLE"
            elif _canonical(snapshot["value"]) == binding["expected_json"]:
                kind, reason = "NOOP", "TARGET_ALREADY_OBSERVED"
            else:
                key = (
                    binding["subject_ref"], binding["predicate_ref"],
                    binding["expected_json"],
                )
                candidate = self.actions.get(key)
                if candidate is None:
                    kind, reason = "DEFER", "NO_REGISTERED_ACTION"
                else:
                    kind, reason = "PROPOSE_ACTION", "TARGET_DIFFERS"
            if kind == "REQUEST_OBSERVATION" and task.status == "active":
                self.tasks.transition_task(
                    task_id, "interrupted",
                    reason="Core Goal awaits fresh or unambiguous observation",
                )
            elif (
                kind in {"NOOP", "PROPOSE_ACTION"}
                and task.status in {"queued", "interrupted"}
            ):
                self.tasks.transition_task(
                    task_id, "active",
                    reason="Core Goal decision requires active verification/work",
                )
        decision = CoreDecision(
            goal_id=goal_id, task_id=task_id, kind=kind,
            reason_code=reason, as_of_tick=as_of_tick,
            belief_revision=revision,
            evidence_event_ids=evidence,
            candidate=candidate,
        )
        self._audit(decision)
        return decision

    def step_next(self, *, as_of_tick):
        """Reuse Stage 2 active Goal arbitration; no invented Goal ownership."""
        ranked = self.arbitrator.evaluate()
        if ranked.selected_goal_id is None:
            return None
        return self.step(ranked.selected_goal_id, as_of_tick=as_of_tick)


__all__ = ["CoreGoalDecision", "CoreDecision", "GoalCriterion"]
