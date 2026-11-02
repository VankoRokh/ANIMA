"""System-owned Stage 6.3 bridge from resolved action candidates to ChoiceEngine.

This module does not create candidates and does not ask FAST/DEEP to choose an
action. It accepts already-formed system Candidate objects, verifies that their
IDs exactly match the resolver's admissible set, then delegates bounded scoring
to the proven Stage 2 ChoiceEngine.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from anima.diagnostics.trace import DiagnosticTrace
from anima.internal_state.choice_engine import Candidate, ChoiceEngine
from anima.ir import CanonicalTask, freeze, plain
from anima.resolution import ResolutionResult, ResolutionRoute
from anima.tasks.store import TaskStore


SAFE_ACTION_CHOICE_REASON = "multiple_actions_without_policy"


@dataclass(frozen=True, slots=True)
class ActionChoiceTurn:
    persistent_task_id: str
    goal_id: str
    canonical_task_id: str
    baseline_selected_candidate_id: str
    selected_candidate_id: str
    state_changed_selection: bool
    choice: Mapping

    def __post_init__(self):
        for value, label in (
            (self.persistent_task_id, "ActionChoiceTurn persistent_task_id"),
            (self.goal_id, "ActionChoiceTurn goal_id"),
            (self.canonical_task_id, "ActionChoiceTurn canonical_task_id"),
            (self.baseline_selected_candidate_id, "ActionChoiceTurn baseline candidate"),
            (self.selected_candidate_id, "ActionChoiceTurn selected candidate"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be non-empty")
        if not isinstance(self.state_changed_selection, bool):
            raise ValueError("ActionChoiceTurn state_changed_selection must be boolean")
        if not isinstance(self.choice, Mapping):
            raise TypeError("ActionChoiceTurn choice must be a mapping")
        object.__setattr__(self, "choice", freeze(self.choice))

    def to_dict(self):
        return {
            "persistent_task_id": self.persistent_task_id,
            "goal_id": self.goal_id,
            "canonical_task_id": self.canonical_task_id,
            "baseline_selected_candidate_id": self.baseline_selected_candidate_id,
            "selected_candidate_id": self.selected_candidate_id,
            "state_changed_selection": self.state_changed_selection,
            "choice": plain(self.choice),
        }


class ActionChoiceCoordinator:
    """Validate the Stage 6.3 boundary and invoke the existing ChoiceEngine.

    Authority remains system-owned:
    - resolver owns admissibility and hard-constraint rejection;
    - persistent Task supplies the Goal reference;
    - caller supplies bounded Candidate features;
    - ChoiceEngine applies bounded Internal State modifiers;
    - this coordinator mutates neither Task nor Goal.
    """

    def __init__(self, *, task_store, choice_engine, trace=None):
        if not isinstance(task_store, TaskStore):
            raise TypeError("ActionChoiceCoordinator task_store must be TaskStore")
        if not isinstance(choice_engine, ChoiceEngine):
            raise TypeError("ActionChoiceCoordinator choice_engine must be ChoiceEngine")
        if trace is not None and not isinstance(trace, DiagnosticTrace):
            raise TypeError("ActionChoiceCoordinator trace must be DiagnosticTrace or null")
        self.task_store = task_store
        self.choice_engine = choice_engine
        self.trace = trace

    def choose(self, persistent_task_id, task, resolution, candidates):
        persistent = self.task_store.get_task(persistent_task_id)
        if persistent is None:
            raise ValueError(f"Unknown Task: {persistent_task_id}")
        if persistent.status != "active":
            raise ValueError(
                f"Action choice requires active Task, got {persistent.status!r}"
            )
        if persistent.goal_id is None:
            raise ValueError("Action choice requires Task linked to Goal")

        if not isinstance(task, CanonicalTask):
            raise TypeError("Action choice requires CanonicalTask")
        if task.operation != "CHOOSE_ACTION":
            raise ValueError("Action choice requires CHOOSE_ACTION CanonicalTask")
        if not isinstance(resolution, ResolutionResult):
            raise TypeError("Action choice requires ResolutionResult")
        if resolution.route != ResolutionRoute.COGNITIVE_REQUIRED:
            raise ValueError("Action choice requires COGNITIVE_REQUIRED resolution")
        if resolution.reason != SAFE_ACTION_CHOICE_REASON:
            raise ValueError(
                "Action choice requires fully verified admissible candidates without formal policy"
            )
        if len(resolution.remaining) < 2:
            raise ValueError("Action choice requires at least two admissible candidates")

        if not isinstance(candidates, (list, tuple)) or not candidates:
            raise ValueError("Action choice requires system Candidate objects")
        if not all(isinstance(item, Candidate) for item in candidates):
            raise TypeError("Action choice requires system Candidate objects")

        candidate_ids = [item.candidate_id for item in candidates]
        if not all(isinstance(item, str) and item.strip() for item in candidate_ids):
            raise ValueError("Action choice Candidate IDs must be non-empty strings")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Action choice Candidate IDs must be unique")
        if set(candidate_ids) != set(resolution.remaining):
            raise ValueError(
                "Action choice Candidate IDs must exactly match resolver remaining candidates"
            )

        choice = self.choice_engine.choose(persistent.goal_id, candidates)
        evaluations = choice["evaluations"]
        baseline = sorted(
            evaluations,
            key=lambda item: (-item["base_score"], item["candidate_id"]),
        )[0]["candidate_id"]
        selected = choice["selected_candidate_id"]
        changed = selected != baseline

        self._trace(
            "action_choice: "
            f"task={persistent.public_id} goal={persistent.goal_id} "
            f"canonical={task.task_id} baseline={baseline} selected={selected} "
            f"state_changed_selection={str(changed).lower()} "
            f"ruleset={choice['ruleset_version']}"
        )
        return ActionChoiceTurn(
            persistent_task_id=persistent.public_id,
            goal_id=persistent.goal_id,
            canonical_task_id=task.task_id,
            baseline_selected_candidate_id=baseline,
            selected_candidate_id=selected,
            state_changed_selection=changed,
            choice=choice,
        )

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)


__all__ = [
    "ActionChoiceCoordinator",
    "ActionChoiceTurn",
    "SAFE_ACTION_CHOICE_REASON",
]
