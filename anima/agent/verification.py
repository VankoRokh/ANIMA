from dataclasses import dataclass
from datetime import datetime

from anima.agent.contracts import (
    Observation,
    VerificationResult,
    VerificationSpec,
    validate_verification_trace,
)
from anima.agent.store import AgentStore
from anima.internal_state.goal_progress import (
    GoalObservation,
    GoalObservationKind,
    VerificationKind,
)
from anima.internal_state.recovery import RecoveryCoordinator


DETERMINISTIC_VERIFIER_NAME = "deterministic.file_content"
DETERMINISTIC_VERIFIER_VERSION = "2"
FILE_CONTENT_EQUALS = "file.content_equals"

_OUTCOME_TO_GOAL_KIND = {
    "failure": GoalObservationKind.FAILURE,
    "progress": GoalObservationKind.PROGRESS,
    "blocked": GoalObservationKind.BLOCKED,
    "success": GoalObservationKind.SUCCESS,
}


def _parse_timestamp(value, label):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _thaw(value):
    if isinstance(value, dict):
        return {key: _thaw(item) for key, item in value.items()}
    if hasattr(value, "items"):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _require_file_content_parameters(spec):
    parameters = _thaw(spec.parameters)
    if set(parameters) != {"path", "expected"}:
        raise ValueError(
            "file.content_equals parameters must contain exactly path and expected"
        )
    path = parameters["path"]
    expected = parameters["expected"]
    if not isinstance(path, str) or not path:
        raise ValueError("file.content_equals path must be a non-empty string")
    if not isinstance(expected, str):
        raise ValueError("file.content_equals expected must be a string")
    return path, expected


def _observation_data(observation):
    return _thaw(observation.data)


def _latest(observations):
    return max(
        observations,
        key=lambda item: (
            _parse_timestamp(item.observed_at, "Observation observed_at"),
            item.public_id,
        ),
    )


@dataclass(frozen=True, slots=True)
class VerificationApplication:
    goal_id: str
    applied: bool
    goal_observation: GoalObservation | None
    progress_result: object | None


class DeterministicGoalVerifier:
    """Pure baseline verifier over supplied factual Observation evidence only."""

    name = DETERMINISTIC_VERIFIER_NAME
    version = DETERMINISTIC_VERIFIER_VERSION

    def verify(
        self,
        spec,
        *,
        step_id,
        candidate_id,
        observations,
        timestamp,
        public_id=None,
    ):
        if not isinstance(spec, VerificationSpec):
            raise TypeError("DeterministicGoalVerifier requires a VerificationSpec")
        if spec.verifier != self.name or spec.verifier_version != self.version:
            raise ValueError(
                "VerificationSpec does not target this deterministic verifier"
            )
        if spec.criterion_kind != FILE_CONTENT_EQUALS:
            raise ValueError(
                f"Unsupported deterministic criterion: {spec.criterion_kind!r}"
            )

        observations = tuple(observations)
        if any(not isinstance(item, Observation) for item in observations):
            raise TypeError("observations must contain Observation values")

        path, expected = _require_file_content_parameters(spec)
        matching_content = []
        matching_unavailable = []
        matching_exists = []

        for observation in observations:
            data = _observation_data(observation)
            if data.get("path") != path:
                continue
            if observation.kind == "file.content" and isinstance(
                data.get("content"), str
            ):
                matching_content.append(observation)
            elif observation.kind == "file.unavailable":
                matching_unavailable.append(observation)
            elif observation.kind == "file.exists" and data.get("exists") is True:
                matching_exists.append(observation)

        if matching_content:
            selected = _latest(matching_content)
            actual = _observation_data(selected)["content"]
            if actual == expected:
                outcome = "success"
                criterion_satisfied = True
                reason = f"expected content observed at {path}"
            else:
                outcome = "failure"
                criterion_satisfied = False
                reason = f"observed content at {path} does not satisfy criterion"
        elif matching_unavailable:
            # An unsuccessful readback does not establish a Goal-level blocker.
            outcome = "failure"
            criterion_satisfied = False
            reason = f"target readback is unavailable at {path}"
        elif matching_exists:
            outcome = "progress"
            criterion_satisfied = False
            reason = f"target file exists at {path}, content not yet verified"
        else:
            outcome = "none"
            criterion_satisfied = False
            reason = f"no relevant evidence for {path}"

        return VerificationResult.create(
            run_id=spec.run_id,
            step_id=step_id,
            verification_spec_id=spec.public_id,
            observation_ids=[item.public_id for item in observations],
            outcome=outcome,
            criterion_satisfied=criterion_satisfied,
            reason=reason,
            importance=1,
            candidate_id=candidate_id,
            timestamp=timestamp,
            public_id=public_id,
        )


class GoalVerificationBridge:
    """Map trusted VerificationResult into the existing Stage 2 progress boundary."""

    def __init__(self, *, agent_store, recovery):
        if not isinstance(agent_store, AgentStore):
            raise TypeError("GoalVerificationBridge agent_store must be an AgentStore")
        if not isinstance(recovery, RecoveryCoordinator):
            raise TypeError(
                "GoalVerificationBridge recovery must be a RecoveryCoordinator"
            )
        self.agent_store = agent_store
        self.recovery = recovery

    def _resolve_goal(self, result):
        run = self.agent_store.get_run(result.run_id)
        if run is None:
            raise ValueError(f"Unknown AgentRun: {result.run_id}")
        step = self.agent_store.get_step(result.step_id)
        if step is None:
            raise ValueError(f"Unknown AgentStep: {result.step_id}")
        if step["run_id"] != run["id"]:
            raise ValueError("VerificationResult AgentStep does not belong to AgentRun")
        return run["goal_id"]

    @staticmethod
    def _validate_evidence_time(result, observations):
        result_time = _parse_timestamp(result.timestamp, "VerificationResult timestamp")
        for observation in observations:
            observed_at = _parse_timestamp(
                observation.observed_at,
                "Observation observed_at",
            )
            if observed_at > result_time:
                raise ValueError(
                    "VerificationResult cannot precede supplied Observation evidence"
                )

    def apply(self, *, spec, result, observations):
        if not isinstance(spec, VerificationSpec):
            raise TypeError("GoalVerificationBridge spec must be a VerificationSpec")
        if not isinstance(result, VerificationResult):
            raise TypeError(
                "GoalVerificationBridge result must be a VerificationResult"
            )
        observations = tuple(observations)
        validate_verification_trace(
            spec=spec,
            result=result,
            observations=observations,
        )
        self._validate_evidence_time(result, observations)
        goal_id = self._resolve_goal(result)

        if result.outcome == "none":
            return VerificationApplication(
                goal_id=goal_id,
                applied=False,
                goal_observation=None,
                progress_result=None,
            )

        kind = _OUTCOME_TO_GOAL_KIND[result.outcome]
        goal_observation = GoalObservation(
            goal_id=goal_id,
            kind=kind,
            source_id=result.public_id,
            reason=result.reason,
            verification=VerificationKind.CONFIRMED_RESULT,
            candidate_id=result.candidate_id,
            importance=result.importance,
            criterion_satisfied=result.criterion_satisfied,
            timestamp=result.timestamp,
        )
        progress_result = self.recovery.observe_goal(goal_observation)
        return VerificationApplication(
            goal_id=goal_id,
            applied=True,
            goal_observation=goal_observation,
            progress_result=progress_result,
        )


__all__ = [
    "DETERMINISTIC_VERIFIER_NAME",
    "DETERMINISTIC_VERIFIER_VERSION",
    "FILE_CONTENT_EQUALS",
    "DeterministicGoalVerifier",
    "GoalVerificationBridge",
    "VerificationApplication",
]
