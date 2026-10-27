from anima.internal_state.choice_engine import Candidate
from anima.internal_state.goal_progress import GoalObservation
from anima.internal_state.transition_engine import StateSignal


class ScenarioRunner:
    def __init__(self, runtime):
        self.runtime = runtime

    def run(self, steps):
        if not isinstance(steps, list):
            raise ValueError(
                "Scenario must be a list of steps"
            )

        if not steps:
            raise ValueError(
                 "Scenario must contain at least one step"
            )

        results = []

        for index, step in enumerate(steps):
            try:
                result = self._run_step(step)
            except (TypeError, ValueError, RuntimeError) as error:
                raise ValueError(
                    f"Scenario step {index}: {error}"
                ) from error

            results.append(result)

        return results

    @staticmethod
    def _require(step, field, action):
        if field not in step:
            raise ValueError(
                f"Scenario action {action!r} must contain {field!r}"
            )
        return step[field]

    @staticmethod
    def _candidate(data):
        if not isinstance(data, dict):
            raise ValueError("Choice Candidate must be an object")
        if "candidate_id" not in data or "base_score" not in data:
            raise ValueError(
                "Choice Candidate must contain 'candidate_id' and 'base_score'"
            )
        return Candidate(
            candidate_id=data["candidate_id"],
            base_score=data["base_score"],
            effort_cost=data.get("effort_cost", 0.0),
            information_gain=data.get("information_gain", 0.0),
            irreversible_risk=data.get("irreversible_risk", 0.0),
            repeated_failure=data.get("repeated_failure", 0.0),
            alternative_value=data.get("alternative_value", 0.0),
            verified_continuation=data.get("verified_continuation", 0.0),
        )

    def _run_step(self, step):
        if not isinstance(step, dict):
            raise ValueError(
                "Scenario step must be an object"
            )

        if "action" not in step:
            raise ValueError(
                "Scenario step must contain 'action'"
            )

        action = step["action"]

        if not isinstance(action, str):
            raise ValueError(
                "Scenario action must be a string"
            )

        if action == "wake":
            events = self.runtime.wake()

        elif action == "user_input":
            if "text" not in step:
                raise ValueError(
                    "Scenario action 'user_input' "
                    "must contain 'text'"
                )

            if not isinstance(step["text"], str):
                 raise ValueError(
                    "Scenario action 'user_input' "
                    "'text' must be a string"
                )

            events = self.runtime.user_input(
                step["text"]
            )

        elif action == "sleep":
            events = self.runtime.sleep()

        elif action == "sleep_job_activate":
            job = self.runtime.activate_sleep_job(
                self._require(step, "job_id", action)
            )
            return {
                "action": action,
                "job": dict(job),
            }

        elif action == "sleep_process":
            chunks = self._require(step, "chunks", action)
            if not isinstance(chunks, list):
                raise ValueError(
                    "Scenario action 'sleep_process' chunks must be a list"
                )
            outcome = self.runtime.process_sleep_work(
                self._require(step, "work_item_id", action),
                chunks,
                max_new_chunks=step.get("max_new_chunks", 1),
            )
            return {
                "action": action,
                "work_item_id": outcome.work_item_id,
                "status": outcome.status,
                "resumed_from_sequence": outcome.resumed_from_sequence,
                "processed_chunks": outcome.processed_chunks,
                "committed_chunks": outcome.committed_chunks,
                "final_result": (
                    outcome.final_result.to_dict()
                    if outcome.final_result is not None
                    else None
                ),
            }

        elif action == "goal_create":
            goal = self.runtime.create_goal(
                source=self._require(step, "source", action),
                priority=self._require(step, "priority", action),
                description=self._require(step, "description", action),
                success_criterion=self._require(
                    step,
                    "success_criterion",
                    action,
                ),
                reason=self._require(step, "reason", action),
                source_id=step.get("source_id"),
                timestamp=step.get("timestamp"),
                public_id=step.get("goal_id"),
                transition_id=step.get("transition_id"),
            )
            return {
                "action": action,
                "goal": goal,
            }

        elif action == "state_signal":
            signal = StateSignal(
                kind=self._require(step, "kind", action),
                source_id=self._require(step, "source_id", action),
                reason=self._require(step, "reason", action),
                importance=step.get("importance", 1),
                goal_id=step.get("goal_id"),
                candidate_id=step.get("candidate_id"),
                timestamp=step.get("timestamp"),
            )
            transitions = self.runtime.process_state_signal(signal)
            return {
                "action": action,
                "transitions": [
                    dict(item)
                    for item in transitions
                ],
            }

        elif action == "goal_observation":
            observation = GoalObservation(
                goal_id=self._require(step, "goal_id", action),
                kind=self._require(step, "kind", action),
                source_id=self._require(step, "source_id", action),
                reason=self._require(step, "reason", action),
                verification=self._require(
                    step,
                    "verification",
                    action,
                ),
                candidate_id=step.get("candidate_id"),
                importance=step.get("importance", 1),
                criterion_satisfied=step.get(
                    "criterion_satisfied",
                    False,
                ),
                timestamp=step.get("timestamp"),
            )
            result = self.runtime.observe_goal(observation)
            return {
                "action": action,
                "goal": result.goal,
                "state_transitions": [
                    dict(item)
                    for item in result.state_transitions
                ],
                "goal_transition": (
                    dict(result.goal_transition)
                    if result.goal_transition is not None
                    else None
                ),
            }

        elif action == "time_evaluate":
            transitions = self.runtime.evaluate_internal_time(
                now=self._require(step, "now", action),
                mode=self._require(step, "mode", action),
                period_started_at=self._require(
                    step,
                    "period_started_at",
                    action,
                ),
            )
            return {
                "action": action,
                "transitions": [
                    dict(item)
                    for item in transitions
                ],
            }

        elif action == "choice":
            raw_candidates = self._require(
                step,
                "candidates",
                action,
            )
            if not isinstance(raw_candidates, list):
                raise ValueError(
                    "Scenario action 'choice' candidates must be a list"
                )
            result = self.runtime.choose(
                self._require(step, "goal_id", action),
                [
                    self._candidate(item)
                    for item in raw_candidates
                ],
            )
            return {
                "action": action,
                "goal_id": result["goal_id"],
                "selected_candidate_id": result[
                    "selected_candidate_id"
                ],
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
                    for evaluation in result["evaluations"]
                ],
            }

        elif action == "snapshot":
            return {
                "action": action,
                "snapshot": self.runtime.snapshot(),
            }

        else:
            raise ValueError(
                f"Unknown scenario action: {action!r}"
            )

        return {
            "action": action,
            "events": [
                event.event_type
                for event in events
            ],
        }
