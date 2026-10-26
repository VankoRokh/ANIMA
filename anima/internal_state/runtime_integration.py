from copy import deepcopy

from anima.diagnostics.trace import DiagnosticTrace
from anima.internal_state.choice_engine import Candidate, ChoiceEngine
from anima.internal_state.expression_adapter import ExpressionAdapter
from anima.internal_state.goal_arbitration import GoalArbitrator
from anima.internal_state.goal_progress import GoalObservation, GoalProgressEngine
from anima.internal_state.goal_creation_recovery import GoalCreationRecovery
from anima.internal_state.goals import GoalStore
from anima.internal_state.recovery import RecoveryCoordinator
from anima.internal_state.store import InternalStateStore
from anima.internal_state.time_dynamics import TimeDynamics
from anima.internal_state.transition_engine import StateSignal, TransitionEngine


class InternalStateRuntime:
    """Compose Stage 2 Internal State components behind one runtime boundary."""

    def __init__(self, store, *, trace=None):
        if not isinstance(store, InternalStateStore):
            raise TypeError("InternalStateRuntime store must be an InternalStateStore")
        if trace is not None and not isinstance(trace, DiagnosticTrace):
            raise TypeError("InternalStateRuntime trace must be a DiagnosticTrace or null")

        self.store = store
        self.trace = trace
        self.goals = GoalStore(store)
        self.transition_engine = TransitionEngine(store)
        self.time_dynamics = TimeDynamics(store)
        self.goal_progress = GoalProgressEngine(
            self.goals,
            self.transition_engine,
        )
        self.goal_arbitrator = GoalArbitrator(self.goals)
        self.choice_engine = ChoiceEngine(
            store,
            goal_store=self.goals,
        )
        self.expression_adapter = ExpressionAdapter(store)
        self.recovery = RecoveryCoordinator(
            store,
            self.goals,
            self.transition_engine,
            self.goal_progress,
        )
        self.goal_creation_recovery = GoalCreationRecovery(
            store,
            self.goals,
        )
        self._last_choice = None

        recovered_goal_creations = self.goal_creation_recovery.recover_pending()
        recovered = self.recovery.recover_pending()
        recovered_sources = (*recovered_goal_creations, *recovered)
        if recovered_sources:
            self._trace(
                "internal_state: recovered pending sources "
                + ", ".join(recovered_sources)
            )

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)

    def create_goal(self, **kwargs):
        goal = self.goal_creation_recovery.create_goal(**kwargs)
        self._trace(
            f"internal_state: goal created {goal['id']} priority={goal['priority']}"
        )
        return goal

    def process_signal(self, signal):
        if not isinstance(signal, StateSignal):
            raise TypeError("InternalStateRuntime requires a StateSignal")
        transitions = self.recovery.process_signal(signal)
        self._trace(
            f"internal_state: signal {signal.kind} applied, "
            f"transitions={len(transitions)}"
        )
        return transitions

    def observe_goal(self, observation):
        if not isinstance(observation, GoalObservation):
            raise TypeError("InternalStateRuntime requires a GoalObservation")
        result = self.recovery.observe_goal(observation)
        self._trace(
            f"internal_state: goal observation {observation.kind} "
            f"goal={observation.goal_id} status={result.goal['status']}"
        )
        return result

    def evaluate_time(self, *, now, mode, period_started_at):
        transitions = self.time_dynamics.evaluate(
            now=now,
            mode=mode,
            period_started_at=period_started_at,
        )
        self._trace(
            f"internal_state: time evaluated mode={mode}, "
            f"transitions={len(transitions)}"
        )
        return transitions

    def choose(self, goal_id, candidates):
        result = self.choice_engine.choose(goal_id, candidates)
        self._last_choice = deepcopy(result)
        self._trace(
            f"internal_state: choice goal={goal_id} "
            f"selected={result['selected_candidate_id']} "
            f"candidates={len(result['evaluations'])}"
        )
        return deepcopy(result)

    def arbitrate_goals(self):
        result = self.goal_arbitrator.evaluate()
        self._trace(
            "internal_state: goal arbitration "
            f"selected={result.selected_goal_id} goals={len(result.entries)}"
        )
        return result

    @staticmethod
    def _choice_snapshot(choice):
        if choice is None:
            return None
        return {
            "goal_id": choice["goal_id"],
            "ruleset_version": choice["ruleset_version"],
            "state_snapshot": dict(choice["state_snapshot"]),
            "selected_candidate_id": choice["selected_candidate_id"],
            "evaluations": [
                {
                    **{
                        key: value
                        for key, value in evaluation.items()
                        if key != "modifiers"
                    },
                    "modifiers": [
                        dict(modifier)
                        for modifier in evaluation["modifiers"]
                    ],
                }
                for evaluation in choice["evaluations"]
            ],
        }

    def snapshot(self, *, transition_limit=20):
        if (
            not isinstance(transition_limit, int)
            or isinstance(transition_limit, bool)
            or transition_limit < 0
        ):
            raise ValueError(
                "Internal State snapshot transition_limit must be a non-negative integer"
            )

        states = {
            row["name"]: float(row["value"])
            for row in self.store.list_states()
        }
        arbitration = self.goal_arbitrator.evaluate()
        expression = self.expression_adapter.build_profile()

        return {
            "states": states,
            "state_transition_count": self.store.transition_count(),
            "recent_state_transitions": self.store.list_state_transitions(
                limit=transition_limit
            ),
            "goals": self.goals.list_goals(),
            "goal_arbitration": {
                "selected_goal_id": arbitration.selected_goal_id,
                "entries": [
                    {
                        "rank": entry.rank,
                        "goal_id": entry.goal_id,
                        "priority": entry.priority,
                        "created_at": entry.created_at,
                        "reason": entry.reason,
                    }
                    for entry in arbitration.entries
                ],
            },
            "last_choice": self._choice_snapshot(self._last_choice),
            "expression": {
                "ruleset_version": expression["ruleset_version"],
                "state_snapshot": dict(expression["state_snapshot"]),
                "profile": expression["profile"].as_dict(),
                "trace": [
                    dict(item)
                    for item in expression["trace"]
                ],
            },
            "recovery": self.recovery.snapshot(),
        }
