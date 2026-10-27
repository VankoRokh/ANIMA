from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from anima.agent.contracts import (
    Action,
    ActionProposal,
    ExecutionReceipt,
    Observation,
    VerificationResult,
    VerificationSpec,
    validate_execution_trace,
    validate_verification_trace,
)
from anima.agent.tools import ToolDescriptor, ToolInputError, ToolRegistry


NOW = "2026-10-27T18:00:00+00:00"
LATER = "2026-10-27T18:00:01+00:00"


def _id(prefix):
    return f"{prefix}{uuid4()}"


def _registry():
    return ToolRegistry(
        [
            ToolDescriptor(
                name="fs.read",
                version="1",
                description="Read one sandbox file",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string", "minLength": 1}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                    "additionalProperties": False,
                },
                effect_class="read_only",
                idempotency="repeat_safe",
                effort_hint="cheap",
                sandbox_scope=("workspace",),
            )
        ]
    )


def _proposal(**overrides):
    values = {
        "rank": 1,
        "tool": "fs.read",
        "tool_version": "1",
        "arguments": {"path": "data.txt"},
        "expected_observation": "file content is returned",
        "rationale_summary": "read the input file",
    }
    values.update(overrides)
    return ActionProposal.create(**values)


def _action(proposal=None, registry=None):
    proposal = proposal or _proposal()
    registry = registry or _registry()
    return Action.from_proposal(
        proposal,
        registry=registry,
        run_id=_id("ar_"),
        step_id=_id("ast_"),
        operation_id=_id("aop_"),
        created_at=NOW,
    )


def _receipt(action=None, **overrides):
    action = action or _action()
    values = {
        "action": action,
        "status": "succeeded",
        "output": {"content": "42"},
        "started_at": NOW,
        "finished_at": LATER,
    }
    values.update(overrides)
    return ExecutionReceipt.create(**values)


def _observation(action=None, receipt=None, **overrides):
    action = action or _action()
    receipt = receipt or _receipt(action)
    values = {
        "action": action,
        "receipt": receipt,
        "source": "tool_output",
        "kind": "file.content",
        "data": {"path": "data.txt", "content": "42"},
        "observed_at": LATER,
    }
    values.update(overrides)
    return Observation.create(**values)


def test_action_proposal_is_immutable_and_round_trips():
    arguments = {"path": "data.txt"}
    proposal = _proposal(arguments=arguments)
    arguments["path"] = "mutated.txt"

    assert proposal.public_id.startswith("ap_")
    assert proposal.arguments["path"] == "data.txt"
    with pytest.raises(TypeError):
        proposal.arguments["path"] = "other.txt"
    with pytest.raises(FrozenInstanceError):
        proposal.rank = 2

    restored = ActionProposal.from_dict(proposal.to_dict())
    assert restored.to_dict() == proposal.to_dict()


def test_action_proposal_validates_against_system_tool_registry():
    registry = _registry()
    proposal = _proposal()

    assert proposal.validate_tool_input(registry) is proposal

    invalid = _proposal(arguments={"path": "data.txt", "unsafe": True})
    with pytest.raises(ToolInputError, match="unexpected property"):
        invalid.validate_tool_input(registry)


def test_action_from_proposal_preserves_identity_chain_and_validated_arguments():
    registry = _registry()
    proposal = _proposal()
    run_id = _id("ar_")
    step_id = _id("ast_")
    operation_id = _id("aop_")

    action = Action.from_proposal(
        proposal,
        registry=registry,
        run_id=run_id,
        step_id=step_id,
        operation_id=operation_id,
        created_at=NOW,
    )

    assert action.public_id.startswith("act_")
    assert action.proposal_id == proposal.public_id
    assert action.run_id == run_id
    assert action.step_id == step_id
    assert action.operation_id == operation_id
    assert action.tool == proposal.tool
    assert action.arguments["path"] == "data.txt"
    assert Action.from_dict(action.to_dict()).to_dict() == action.to_dict()


def test_action_from_proposal_rejects_input_not_allowed_by_descriptor():
    with pytest.raises(ToolInputError):
        Action.from_proposal(
            _proposal(arguments={"path": "data.txt", "extra": 1}),
            registry=_registry(),
            run_id=_id("ar_"),
            step_id=_id("ast_"),
            operation_id=_id("aop_"),
            created_at=NOW,
        )


def test_execution_receipt_separates_success_from_error_and_round_trips():
    action = _action()
    receipt = _receipt(action)

    assert receipt.public_id.startswith("er_")
    assert receipt.action_id == action.public_id
    assert receipt.operation_id == action.operation_id
    assert receipt.status == "succeeded"
    assert receipt.output["content"] == "42"
    assert receipt.error_code is None
    assert ExecutionReceipt.from_dict(receipt.to_dict()).to_dict() == receipt.to_dict()

    failed = _receipt(
        action,
        status="failed",
        output=None,
        error_code="FILE_NOT_FOUND",
        error_message="missing file",
    )
    assert failed.status == "failed"
    assert failed.error_code == "FILE_NOT_FOUND"


def test_execution_receipt_rejects_inconsistent_error_and_time():
    action = _action()

    with pytest.raises(ValueError, match="Succeeded ExecutionReceipt cannot contain an error"):
        _receipt(action, error_code="ERR", error_message="bad")

    with pytest.raises(ValueError, match="error_code"):
        _receipt(action, status="failed", output=None)

    with pytest.raises(ValueError, match="cannot precede"):
        _receipt(action, started_at=LATER, finished_at=NOW)


def test_observation_is_factual_structured_data_bound_to_action_and_receipt():
    action = _action()
    receipt = _receipt(action)
    data = {"path": "data.txt", "content": "42"}
    observation = _observation(action, receipt, data=data)
    data["content"] = "mutated"

    assert observation.public_id.startswith("obs_")
    assert observation.action_id == action.public_id
    assert observation.receipt_id == receipt.public_id
    assert observation.data["content"] == "42"
    assert Observation.from_dict(observation.to_dict()).to_dict() == observation.to_dict()


def test_observation_rejects_receipt_from_another_action():
    action = _action()
    other_action = _action()
    other_receipt = _receipt(other_action)

    with pytest.raises(ValueError, match="does not belong"):
        _observation(action, other_receipt)


def test_verification_spec_is_run_owned_immutable_contract():
    parameters = {"path": "result.txt", "expected": "42"}
    spec = VerificationSpec.create(
        run_id=_id("ar_"),
        verifier="file_content",
        verifier_version="1",
        criterion_kind="file.content_equals",
        parameters=parameters,
    )
    parameters["expected"] = "99"

    assert spec.public_id.startswith("vs_")
    assert spec.parameters["expected"] == "42"
    with pytest.raises(TypeError):
        spec.parameters["expected"] = "99"
    assert VerificationSpec.from_dict(spec.to_dict()).to_dict() == spec.to_dict()


def test_verification_result_requires_evidence_candidate_and_success_consistency():
    observation = _observation()
    result = VerificationResult.create(
        run_id=_id("ar_"),
        step_id=_id("ast_"),
        verification_spec_id=_id("vs_"),
        observation_ids=[observation.public_id],
        outcome="success",
        criterion_satisfied=True,
        reason="expected content observed",
        importance=2,
        candidate_id=_id("ap_"),
        timestamp=LATER,
    )

    assert result.public_id.startswith("vr_")
    assert result.outcome == "success"
    assert result.criterion_satisfied is True
    assert VerificationResult.from_dict(result.to_dict()).to_dict() == result.to_dict()

    with pytest.raises(ValueError, match="true exactly for success"):
        VerificationResult.create(
            run_id=_id("ar_"),
            step_id=_id("ast_"),
            verification_spec_id=_id("vs_"),
            observation_ids=[observation.public_id],
            outcome="progress",
            criterion_satisfied=True,
            reason="partial",
            candidate_id=_id("ap_"),
            timestamp=LATER,
        )

    with pytest.raises(ValueError, match="requires at least one Observation"):
        VerificationResult.create(
            run_id=_id("ar_"),
            step_id=_id("ast_"),
            verification_spec_id=_id("vs_"),
            observation_ids=[],
            outcome="failure",
            criterion_satisfied=False,
            reason="failed",
            candidate_id=_id("ap_"),
            timestamp=LATER,
        )


def test_verification_none_can_exist_without_evidence_or_candidate():
    result = VerificationResult.create(
        run_id=_id("ar_"),
        step_id=_id("ast_"),
        verification_spec_id=_id("vs_"),
        observation_ids=[],
        outcome="none",
        criterion_satisfied=False,
        reason="no criterion-relevant evidence yet",
        timestamp=LATER,
    )

    assert result.observation_ids == ()
    assert result.candidate_id is None


def test_execution_trace_accepts_one_consistent_chain():
    registry = _registry()
    proposal = _proposal()
    action = _action(proposal, registry)
    receipt = _receipt(action)
    observation = _observation(action, receipt)

    assert validate_execution_trace(
        proposal=proposal,
        action=action,
        receipt=receipt,
        observation=observation,
    ) is True


def test_execution_trace_rejects_dangling_or_mismatched_references():
    registry = _registry()
    proposal = _proposal()
    action = _action(proposal, registry)
    receipt = _receipt(action)
    observation = _observation(action, receipt)

    wrong_action = Action(
        public_id=action.public_id,
        proposal_id=_id("ap_"),
        run_id=action.run_id,
        step_id=action.step_id,
        operation_id=action.operation_id,
        tool=action.tool,
        tool_version=action.tool_version,
        arguments=action.to_dict()["arguments"],
        created_at=action.created_at,
    )
    with pytest.raises(ValueError, match="Dangling Action proposal_id"):
        validate_execution_trace(
            proposal=proposal,
            action=wrong_action,
            receipt=receipt,
            observation=observation,
        )

    wrong_observation = Observation(
        public_id=observation.public_id,
        action_id=action.public_id,
        receipt_id=_id("er_"),
        source=observation.source,
        kind=observation.kind,
        data=observation.to_dict()["data"],
        observed_at=observation.observed_at,
    )
    with pytest.raises(ValueError, match="Dangling Observation receipt_id"):
        validate_execution_trace(
            proposal=proposal,
            action=action,
            receipt=receipt,
            observation=wrong_observation,
        )


def test_verification_trace_requires_exact_spec_run_and_evidence_refs():
    run_id = _id("ar_")
    observation = _observation()
    spec = VerificationSpec.create(
        run_id=run_id,
        verifier="file_content",
        verifier_version="1",
        criterion_kind="file.content_equals",
        parameters={"expected": "42"},
    )
    result = VerificationResult.create(
        run_id=run_id,
        step_id=_id("ast_"),
        verification_spec_id=spec.public_id,
        observation_ids=[observation.public_id],
        outcome="success",
        criterion_satisfied=True,
        reason="matched",
        candidate_id=_id("ap_"),
        timestamp=LATER,
    )

    assert validate_verification_trace(
        spec=spec,
        result=result,
        observations=[observation],
    ) is True

    with pytest.raises(ValueError, match="observation_ids do not match"):
        validate_verification_trace(
            spec=spec,
            result=result,
            observations=[_observation()],
        )


def test_record_deserializers_reject_extra_fields():
    proposal = _proposal()
    record = proposal.to_dict()
    record["goal_completed"] = True

    with pytest.raises(ValueError, match="extra: goal_completed"):
        ActionProposal.from_dict(record)


def test_contract_id_and_timestamp_validation_is_strict():
    with pytest.raises(ValueError, match="ap_UUIDv4"):
        _proposal(public_id="proposal_123")

    proposal = _proposal()
    with pytest.raises(ValueError, match="UTC offset"):
        Action.from_proposal(
            proposal,
            registry=_registry(),
            run_id=_id("ar_"),
            step_id=_id("ast_"),
            operation_id=_id("aop_"),
            created_at="2026-10-27T18:00:00",
        )
