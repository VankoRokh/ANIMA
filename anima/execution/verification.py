"""Independent environment observation and Goal verification for Stage 6."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from anima.agent.executor import MAX_FILE_BYTES
from anima.internal_state.goal_progress import (
    GoalObservation,
    GoalObservationKind,
    VerificationKind,
)
from anima.internal_state.runtime_integration import InternalStateRuntime
from .contracts import (
    ExecutionAction,
    ExecutionReceipt,
    Observation,
    VerificationResult,
    VerificationSpec,
    thaw,
)


FILE_CONTENT_EQUALS = "file.content_equals"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _safe_path(root, relative_path):
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("Observation path must be a non-empty string")
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("Observation path must remain inside sandbox")
    root = Path(root).resolve()
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("Observation path escapes sandbox") from error
    return candidate


class FileObserver:
    """Observe current filesystem state independently from Executor output."""

    def __init__(self, root):
        root = Path(root).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("FileObserver root must be an existing directory")
        self.root = root

    def observe(self, action, receipt, *, path, observed_at=None):
        if not isinstance(action, ExecutionAction):
            raise TypeError("FileObserver requires ExecutionAction")
        if not isinstance(receipt, ExecutionReceipt):
            raise TypeError("FileObserver requires ExecutionReceipt")
        if receipt.action_id != action.public_id or receipt.operation_id != action.operation_id:
            raise ValueError("FileObserver receipt does not belong to ExecutionAction")
        target = _safe_path(self.root, path)
        observed_at = observed_at or _now()
        if not target.exists() or not target.is_file():
            return Observation.create(
                action=action,
                receipt=receipt,
                source="filesystem.observer",
                kind="file.unavailable",
                data={"path": path},
                observed_at=observed_at,
            )
        data = target.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            return Observation.create(
                action=action,
                receipt=receipt,
                source="filesystem.observer",
                kind="file.unavailable",
                data={"path": path, "reason": "too_large"},
                observed_at=observed_at,
            )
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            return Observation.create(
                action=action,
                receipt=receipt,
                source="filesystem.observer",
                kind="file.unavailable",
                data={"path": path, "reason": "not_utf8"},
                observed_at=observed_at,
            )
        return Observation.create(
            action=action,
            receipt=receipt,
            source="filesystem.observer",
            kind="file.content",
            data={"path": path, "content": content, "bytes": len(data)},
            observed_at=observed_at,
        )


def _latest(observations):
    return max(
        observations,
        key=lambda item: (datetime.fromisoformat(item.observed_at), item.public_id),
    )


def _validate_trace(*, spec, action, result, observations):
    if not isinstance(spec, VerificationSpec):
        raise TypeError("verification trace requires VerificationSpec")
    if not isinstance(action, ExecutionAction):
        raise TypeError("verification trace requires ExecutionAction")
    if not isinstance(result, VerificationResult):
        raise TypeError("verification trace requires VerificationResult")
    observations = tuple(observations)
    if any(not isinstance(item, Observation) for item in observations):
        raise TypeError("verification trace observations must contain Observation values")
    if spec.public_id != result.verification_spec_id:
        raise ValueError("VerificationResult does not belong to VerificationSpec")
    if spec.goal_id != action.goal_id or result.goal_id != action.goal_id:
        raise ValueError("Verification trace Goal mismatch")
    if result.candidate_id != action.candidate_id:
        raise ValueError("VerificationResult candidate does not match ExecutionAction")
    if any(item.action_id != action.public_id for item in observations):
        raise ValueError("Observation evidence does not belong to ExecutionAction")
    if tuple(item.public_id for item in observations) != result.observation_ids:
        raise ValueError("VerificationResult observation IDs do not match evidence")
    result_time = datetime.fromisoformat(result.timestamp)
    if any(datetime.fromisoformat(item.observed_at) > result_time for item in observations):
        raise ValueError("VerificationResult cannot precede Observation evidence")
    return observations


class DeterministicGoalVerifier:
    """Verify a bounded criterion only from supplied Observation evidence."""

    def verify(self, spec, *, action, observations, timestamp=None):
        if not isinstance(spec, VerificationSpec):
            raise TypeError("DeterministicGoalVerifier requires VerificationSpec")
        if not isinstance(action, ExecutionAction):
            raise TypeError("DeterministicGoalVerifier requires ExecutionAction")
        if action.goal_id != spec.goal_id:
            raise ValueError("VerificationSpec Goal does not match ExecutionAction")
        if spec.criterion_kind != FILE_CONTENT_EQUALS:
            raise ValueError(
                f"Unsupported deterministic criterion: {spec.criterion_kind!r}"
            )
        parameters = thaw(spec.parameters)
        if set(parameters) != {"path", "expected"}:
            raise ValueError(
                "file.content_equals parameters must contain exactly path and expected"
            )
        path = parameters["path"]
        expected = parameters["expected"]
        if not isinstance(path, str) or not path:
            raise ValueError("file.content_equals path must be non-empty")
        if not isinstance(expected, str):
            raise ValueError("file.content_equals expected must be text")
        observations = tuple(observations)
        if any(not isinstance(item, Observation) for item in observations):
            raise TypeError("observations must contain Observation values")
        if any(item.action_id != action.public_id for item in observations):
            raise ValueError("Observation evidence does not belong to ExecutionAction")
        relevant = [
            item for item in observations
            if thaw(item.data).get("path") == path
        ]
        content = [item for item in relevant if item.kind == "file.content"]
        unavailable = [item for item in relevant if item.kind == "file.unavailable"]
        if content:
            selected = _latest(content)
            actual = thaw(selected.data).get("content")
            if actual == expected:
                outcome = "success"
                satisfied = True
                reason = f"expected content observed at {path}"
            else:
                outcome = "failure"
                satisfied = False
                reason = f"observed content at {path} does not satisfy criterion"
        elif unavailable:
            outcome = "failure"
            satisfied = False
            reason = f"target readback is unavailable at {path}"
        else:
            outcome = "none"
            satisfied = False
            reason = f"no relevant evidence for {path}"
        timestamp = timestamp or _now()
        if observations:
            latest_time = max(datetime.fromisoformat(item.observed_at) for item in observations)
            if datetime.fromisoformat(timestamp) < latest_time:
                raise ValueError("VerificationResult cannot precede Observation evidence")
        return VerificationResult.create(
            spec=spec,
            candidate_id=action.candidate_id,
            observations=observations,
            outcome=outcome,
            criterion_satisfied=satisfied,
            reason=reason,
            timestamp=timestamp,
        )


@dataclass(frozen=True, slots=True)
class VerificationApplication:
    goal_id: str
    applied: bool
    goal_observation: GoalObservation | None
    progress_result: object | None


class GoalVerificationBridge:
    """Apply a coherent verified trace through the existing Stage 2 Goal boundary."""

    def __init__(self, runtime):
        if not isinstance(runtime, InternalStateRuntime):
            raise TypeError("GoalVerificationBridge runtime must be InternalStateRuntime")
        self.runtime = runtime

    def apply(self, *, spec, action, result, observations):
        observations = _validate_trace(
            spec=spec,
            action=action,
            result=result,
            observations=observations,
        )
        goal = self.runtime.goals.get_goal(result.goal_id)
        if goal is None:
            raise ValueError(f"Unknown Goal: {result.goal_id}")
        if result.outcome == "none":
            return VerificationApplication(
                goal_id=result.goal_id,
                applied=False,
                goal_observation=None,
                progress_result=None,
            )
        mapping = {
            "failure": GoalObservationKind.FAILURE,
            "progress": GoalObservationKind.PROGRESS,
            "blocked": GoalObservationKind.BLOCKED,
            "success": GoalObservationKind.SUCCESS,
        }
        observation = GoalObservation(
            goal_id=result.goal_id,
            kind=mapping[result.outcome],
            source_id=result.public_id,
            reason=result.reason,
            verification=VerificationKind.CONFIRMED_RESULT,
            candidate_id=result.candidate_id,
            importance=1,
            criterion_satisfied=result.criterion_satisfied,
            timestamp=result.timestamp,
        )
        progress = self.runtime.observe_goal(observation)
        return VerificationApplication(
            goal_id=result.goal_id,
            applied=True,
            goal_observation=observation,
            progress_result=progress,
        )


__all__ = [
    "DeterministicGoalVerifier",
    "FILE_CONTENT_EQUALS",
    "FileObserver",
    "GoalVerificationBridge",
    "VerificationApplication",
]
