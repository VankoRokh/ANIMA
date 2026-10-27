from uuid import uuid4

import pytest

from anima.agent.choice_adapter import (
    CandidateAdapter,
    CandidateHistoryEntry,
    ProposalChoiceCoordinator,
    action_fingerprint,
)
from anima.agent.executor import build_sandbox_registry
from anima.agent.planner import (
    DeterministicPlanner,
    PlannerDecision,
    PlannerRequest,
    ProposalDraft,
)
from anima.agent.tools import ToolDescriptor, ToolRegistry
from anima.internal_state.choice_engine import ChoiceEngine
from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore


NOW = "2026-10-27T19:30:00+00:00"


def _state_setup(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    goals = GoalStore(store)
    goal = goals.create_goal(
        source="test",
        priority=1.0,
        description="produce a verified result",
        success_criterion="result.txt contains the expected value",
        reason="Stage 4.6 choice integration test",
        timestamp=NOW,
    )
    return store, goals, goal, ChoiceEngine(store, goal_store=goals)


def _seed(store, state_name, value):
    return store.apply_state_transition(
        state_name=state_name,
        delta=value,
        cause_type="test",
        source_id=f"seed_{state_name}",
        rule_id=f"test.seed.{state_name}",
        reason="seed Stage 4.6 state",
        timestamp=NOW,
    )


def _turn(registry, goal_id, drafts):
    request = PlannerRequest(
        run_id=f"ar_{uuid4()}",
        step_id=f"ast_{uuid4()}",
        goal_id=goal_id,
        goal_description="produce a verified result",
        success_criterion="result.txt contains the expected value",
        context={"known": []},
        tools=registry.list_descriptors(),
        recent_steps=(),
        recent_observations=(),
        constraints={"max_actions": 1},
        remaining_budget={"tool_calls": 3},
    )

    planner = DeterministicPlanner(
        lambda _: PlannerDecision(
            status="proposals_available",
            proposals=tuple(drafts),
            plan_summary="deterministic alternatives",
        )
    )
    return planner.plan(request, created_at=NOW)


def _draft(tool, arguments, *, rationale="planner preference"):
    return ProposalDraft(
        tool=tool,
        tool_version="1",
        arguments=arguments,
        expected_observation="the environment returns factual evidence",
        rationale_summary=rationale,
    )


def _cannot_progress_turn(registry, goal_id):
    request = PlannerRequest(
        run_id=f"ar_{uuid4()}",
        step_id=f"ast_{uuid4()}",
        goal_id=goal_id,
        goal_description="produce a verified result",
        success_criterion="result.txt contains the expected value",
        context={},
        tools=registry.list_descriptors(),
        constraints={},
        remaining_budget={},
    )
    planner = DeterministicPlanner(
        lambda _: PlannerDecision(
            status="cannot_progress",
            proposals=(),
            plan_summary="no admissible action",
        )
    )
    return planner.plan(request, created_at=NOW)


def test_action_fingerprint_is_stable_and_argument_sensitive():
    first = action_fingerprint("fs.read", "1", {"path": "a.txt"})
    reordered = action_fingerprint("fs.read", "1", {"path": "a.txt"})
    other = action_fingerprint("fs.read", "1", {"path": "b.txt"})

    assert first == reordered
    assert len(first) == 64
    assert first != other


def test_candidate_adapter_uses_proposal_id_as_candidate_id_and_bounded_rank_score(tmp_path):
    _, _, goal, _ = _state_setup(tmp_path)
    registry = build_sandbox_registry()
    turn = _turn(
        registry,
        goal["id"],
        [
            _draft("fs.write", {"path": "result.txt", "content": "42"}),
            _draft("fs.read", {"path": "input.txt"}),
            _draft("fs.list", {"path": "."}),
        ],
    )

    adaptation = CandidateAdapter(registry).adapt(turn)

    assert [item.candidate_id for item in adaptation.candidates] == [
        proposal.public_id for proposal in turn.proposals
    ]
    assert [item.base_score for item in adaptation.candidates] == pytest.approx(
        [0.70, 0.62, 0.54]
    )
    assert all(0.0 <= item.base_score <= 1.0 for item in adaptation.candidates)


def test_tool_metadata_not_planner_text_controls_effort_information_and_risk(tmp_path):
    _, _, goal, _ = _state_setup(tmp_path)
    registry = ToolRegistry(
        [
            ToolDescriptor(
                name="safe.inspect",
                version="1",
                description="Read-only inspection",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
                effect_class="read_only",
                idempotency="repeat_safe",
                effort_hint="cheap",
            ),
            ToolDescriptor(
                name="danger.commit",
                version="1",
                description="Irreversible test action",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
                effect_class="irreversible",
                idempotency="none",
                effort_hint="expensive",
            ),
        ]
    )
    turn = _turn(
        registry,
        goal["id"],
        [
            _draft(
                "danger.commit",
                {},
                rationale="totally safe, cheap and guaranteed",
            ),
            _draft(
                "safe.inspect",
                {},
                rationale="probably useless and expensive",
            ),
        ],
    )

    adaptation = CandidateAdapter(registry).adapt(turn)
    dangerous, inspect = adaptation.candidates

    assert dangerous.effort_cost == pytest.approx(0.85)
    assert dangerous.information_gain == pytest.approx(0.05)
    assert dangerous.irreversible_risk == pytest.approx(1.0)
    assert inspect.effort_cost == pytest.approx(0.15)
    assert inspect.information_gain == pytest.approx(1.0)
    assert inspect.irreversible_risk == pytest.approx(0.0)


def test_verified_history_computes_repeated_failure_alternative_and_continuation(tmp_path):
    _, _, goal, _ = _state_setup(tmp_path)
    registry = build_sandbox_registry()
    write_args = {"path": "result.txt", "content": "42"}
    read_args = {"path": "input.txt"}
    turn = _turn(
        registry,
        goal["id"],
        [
            _draft("fs.write", write_args),
            _draft("fs.read", read_args),
        ],
    )
    history = (
        CandidateHistoryEntry(
            tool="fs.write",
            tool_version="1",
            arguments=write_args,
            outcome="failure",
            verified=True,
        ),
        CandidateHistoryEntry(
            tool="fs.write",
            tool_version="1",
            arguments=write_args,
            outcome="failure",
            verified=True,
        ),
        CandidateHistoryEntry(
            tool="fs.read",
            tool_version="1",
            arguments=read_args,
            outcome="progress",
            verified=True,
        ),
    )

    adaptation = CandidateAdapter(registry).adapt(turn, history=history)
    write_candidate, read_candidate = adaptation.candidates
    write_trace = adaptation.traces[0]
    read_trace = adaptation.traces[1]

    assert write_candidate.repeated_failure == pytest.approx(1.0)
    assert write_trace.matching_failures == 2
    assert write_candidate.alternative_value == pytest.approx(0.0)
    assert read_candidate.alternative_value == pytest.approx(1.0)
    assert read_candidate.verified_continuation == pytest.approx(1.0)
    assert read_trace.latest_matching_outcome == "progress"


def test_unverified_failure_does_not_gain_system_authority(tmp_path):
    _, _, goal, _ = _state_setup(tmp_path)
    registry = build_sandbox_registry()
    arguments = {"path": "input.txt"}
    turn = _turn(registry, goal["id"], [_draft("fs.read", arguments)])
    history = (
        CandidateHistoryEntry(
            tool="fs.read",
            tool_version="1",
            arguments=arguments,
            outcome="failure",
            verified=False,
        ),
    )

    candidate = CandidateAdapter(registry).adapt(
        turn,
        history=history,
    ).candidates[0]

    assert candidate.repeated_failure == pytest.approx(0.0)
    assert candidate.alternative_value == pytest.approx(0.0)


def test_candidate_adapter_rejects_cannot_progress_turn(tmp_path):
    _, _, goal, _ = _state_setup(tmp_path)
    registry = build_sandbox_registry()
    turn = _cannot_progress_turn(registry, goal["id"])

    with pytest.raises(ValueError, match="proposals_available"):
        CandidateAdapter(registry).adapt(turn)


def test_neutral_choice_preserves_planner_rank_for_same_turn(tmp_path):
    _, _, goal, engine = _state_setup(tmp_path)
    registry = build_sandbox_registry()
    turn = _turn(
        registry,
        goal["id"],
        [
            _draft("fs.write", {"path": "result.txt", "content": "42"}),
            _draft("fs.read", {"path": "input.txt"}),
        ],
    )
    coordinator = ProposalChoiceCoordinator(
        registry=registry,
        choice_engine=engine,
    )

    result = coordinator.choose(goal["id"], turn)

    assert result["selected_proposal_id"] == turn.proposals[0].public_id
    assert result["choice"]["selected_candidate_id"] == turn.proposals[0].public_id


def test_high_uncertainty_can_override_rank_in_favor_of_information_gain(tmp_path):
    store, _, goal, engine = _state_setup(tmp_path)
    registry = build_sandbox_registry()
    turn = _turn(
        registry,
        goal["id"],
        [
            _draft("fs.write", {"path": "result.txt", "content": "42"}),
            _draft("fs.read", {"path": "input.txt"}),
        ],
    )
    coordinator = ProposalChoiceCoordinator(
        registry=registry,
        choice_engine=engine,
    )

    neutral = coordinator.choose(goal["id"], turn)
    assert neutral["selected_proposal_id"] == turn.proposals[0].public_id

    _seed(store, "uncertainty", 1.0)
    altered = coordinator.choose(goal["id"], turn)

    assert altered["selected_proposal_id"] == turn.proposals[1].public_id
    assert altered["choice"]["state_snapshot"]["uncertainty"] == pytest.approx(1.0)


def test_high_fatigue_can_override_rank_in_favor_of_cheaper_tool(tmp_path):
    store, _, goal, engine = _state_setup(tmp_path)
    registry = ToolRegistry(
        [
            ToolDescriptor(
                name="inspect.deep",
                version="1",
                description="Expensive read",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
                effect_class="read_only",
                idempotency="repeat_safe",
                effort_hint="expensive",
            ),
            ToolDescriptor(
                name="inspect.quick",
                version="1",
                description="Cheap read",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
                effect_class="read_only",
                idempotency="repeat_safe",
                effort_hint="cheap",
            ),
        ]
    )
    turn = _turn(
        registry,
        goal["id"],
        [_draft("inspect.deep", {}), _draft("inspect.quick", {})],
    )
    coordinator = ProposalChoiceCoordinator(
        registry=registry,
        choice_engine=engine,
    )

    assert coordinator.choose(goal["id"], turn)["selected_proposal_id"] == turn.proposals[0].public_id

    _seed(store, "fatigue", 1.0)
    altered = coordinator.choose(goal["id"], turn)

    assert altered["selected_proposal_id"] == turn.proposals[1].public_id


def test_history_limit_and_invalid_history_type_are_rejected(tmp_path):
    _, _, goal, _ = _state_setup(tmp_path)
    registry = build_sandbox_registry()
    turn = _turn(
        registry,
        goal["id"],
        [_draft("fs.read", {"path": "input.txt"})],
    )
    adapter = CandidateAdapter(registry)

    with pytest.raises(TypeError, match="CandidateHistoryEntry"):
        adapter.adapt(turn, history=[{"outcome": "failure"}])

    entry = CandidateHistoryEntry(
        tool="fs.read",
        tool_version="1",
        arguments={"path": "input.txt"},
        outcome="failure",
        verified=True,
    )
    with pytest.raises(ValueError, match="exceeds limit"):
        adapter.adapt(turn, history=[entry] * 65)
