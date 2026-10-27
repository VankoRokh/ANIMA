from pathlib import Path

from anima.agent import (
    AgentLoop,
    AgentStore,
    DeterministicGoalVerifier,
    DeterministicPlanner,
    GoalVerificationBridge,
    PlannerDecision,
    ProposalChoiceCoordinator,
    ProposalDraft,
    SandboxExecutor,
    VerificationSpec,
    build_sandbox_registry,
)
from anima.agent.events import AgentEventPublisher, AgentExperienceCapture
from anima.agent.memory_integration import AgentMemoryIntegration
from anima.agent.verification import (
    DETERMINISTIC_VERIFIER_NAME,
    DETERMINISTIC_VERIFIER_VERSION,
    FILE_CONTENT_EQUALS,
)
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore


def _proposal(tool, arguments, rationale):
    return ProposalDraft(
        tool=tool,
        tool_version="1",
        arguments=arguments,
        expected_observation="factual sandbox observation",
        rationale_summary=rationale,
    )


def _canonical_run(tmp_path):
    data_dir = Path(tmp_path)
    sandbox = data_dir / "sandbox"
    sandbox.mkdir()

    agent_store = AgentStore(data_dir / "agent.db")
    internal_store = InternalStateStore(data_dir / "internal_state.db")
    internal = InternalStateRuntime(internal_store)
    registry = build_sandbox_registry()

    def strategy(request):
        if not request.recent_observations:
            return PlannerDecision(
                status="proposals_available",
                proposals=(
                    _proposal(
                        "fs.read",
                        {"path": "missing-input.txt"},
                        "try the initially assumed input path",
                    ),
                ),
            )
        latest = request.recent_observations[-1]
        if latest["kind"] == "file.unavailable":
            return PlannerDecision(
                status="proposals_available",
                proposals=(
                    _proposal(
                        "fs.write",
                        {"path": "result.txt", "content": "42"},
                        "change strategy and write the required result",
                    ),
                ),
            )
        if latest["kind"] == "file.write":
            return PlannerDecision(
                status="proposals_available",
                proposals=(
                    _proposal(
                        "fs.read",
                        {"path": "result.txt"},
                        "read back the result for verification",
                    ),
                ),
            )
        return PlannerDecision(status="cannot_progress")

    planner = DeterministicPlanner(strategy)
    choice = ProposalChoiceCoordinator(
        registry=registry,
        choice_engine=internal.choice_engine,
    )
    executor = SandboxExecutor(
        root=sandbox,
        registry=registry,
        store=agent_store,
    )
    verifier = DeterministicGoalVerifier()
    bridge = GoalVerificationBridge(
        agent_store=agent_store,
        recovery=internal.recovery,
    )
    loop = AgentLoop(
        store=agent_store,
        registry=registry,
        planner=planner,
        choice=choice,
        executor=executor,
        verifier=verifier,
        verification_bridge=bridge,
    )
    goal = internal.create_goal(
        source="test",
        priority=1.0,
        description="write 42 to result.txt and verify it",
        success_criterion="result.txt content equals 42",
        reason="Stage 4.10 memory integration test goal",
    )
    run = loop.start_run(goal["id"])
    spec = VerificationSpec.create(
        run_id=run["id"],
        verifier=DETERMINISTIC_VERIFIER_NAME,
        verifier_version=DETERMINISTIC_VERIFIER_VERSION,
        criterion_kind=FILE_CONTENT_EQUALS,
        parameters={"path": "result.txt", "expected": "42"},
    )
    result = loop.run(run["id"], spec, max_steps=5)
    assert result.completed is True
    return data_dir, registry, agent_store, goal, result


def _integration(data_dir, registry, agent_store):
    event_log = EventLog(data_dir / "events.jsonl")
    publisher = AgentEventPublisher(store=agent_store, event_log=event_log)
    capture = AgentExperienceCapture(publisher=publisher, registry=registry)
    memory_store = MemoryStore(data_dir / "memory.db")
    link_store = LinkStore(memory_store)
    integration = AgentMemoryIntegration(
        capture=capture,
        memory_store=memory_store,
        link_store=link_store,
    )
    return event_log, memory_store, integration


def test_multi_step_agent_run_becomes_one_bounded_self_episode_with_full_provenance(tmp_path):
    data_dir, registry, agent_store, goal, result = _canonical_run(tmp_path)
    event_log, memory_store, integration = _integration(
        data_dir,
        registry,
        agent_store,
    )

    integrated = integration.integrate(result)

    assert memory_store.count() == 1
    assert integrated.memory_id.startswith("mem_")
    memory = memory_store.get_memory(integrated.memory_id)
    assert memory["type"] == "episodic"
    assert memory["domain"] == "self"
    assert memory["status"] == "open"
    assert memory["importance"] == 2
    assert len(memory["content"]) <= 512

    content = memory["content"]
    assert goal["id"] in content
    assert "Failure:" in content
    assert "NOT_FOUND" in content
    assert "Strategy changed from fs.read to fs.write" in content
    assert "Action: fs.write@1" in content
    assert "Verification: file.content produced success" in content
    assert "Result: goal_completed" in content

    raw_events = event_log.load_events()
    assert len(raw_events) == 5
    assert set(memory_store.source_events(memory["id"])) == {
        record["id"] for record in raw_events
    }

    assert [item["action"] for item in integrated.processing_results] == [
        "skip",
        "skip",
        "skip",
        "skip",
        "create",
    ]
    assert integrated.processing_results[-1]["memory_id"] == memory["id"]


def test_agent_memory_integration_replay_does_not_duplicate_event_or_memory(tmp_path):
    data_dir, registry, agent_store, _, result = _canonical_run(tmp_path)
    event_log, memory_store, integration = _integration(
        data_dir,
        registry,
        agent_store,
    )

    first = integration.integrate(result)
    second = integration.integrate(result)

    assert first.memory_id == second.memory_id
    assert memory_store.count() == 1
    assert len(event_log.load_events()) == 5
    assert second.processing_results[-1]["action"] == "already_done"
    assert second.processing_results[-1]["memory_id"] == first.memory_id
    assert all(publication.replayed for publication in second.publications)


def test_recovery_adopts_published_agent_events_and_builds_missing_episode(tmp_path):
    data_dir, registry, agent_store, _, result = _canonical_run(tmp_path)
    event_log = EventLog(data_dir / "events.jsonl")
    publisher = AgentEventPublisher(store=agent_store, event_log=event_log)
    capture = AgentExperienceCapture(publisher=publisher, registry=registry)
    publications = capture.capture(result)
    assert len(publications) == 5

    memory_store = MemoryStore(data_dir / "memory.db")
    integration = AgentMemoryIntegration(
        capture=capture,
        memory_store=memory_store,
        link_store=LinkStore(memory_store),
    )

    recovered = integration.recover()

    assert recovered["retried"] == 1
    assert recovered["finalized"] == 5
    assert memory_store.count() == 1
    memory = memory_store.list_memories()[0]
    assert memory["domain"] == "self"
    assert set(memory_store.source_events(memory["id"])) == {
        publication.event_id for publication in publications
    }


def test_agent_memory_processor_keeps_non_result_agent_events_out_of_memory(tmp_path):
    data_dir, registry, agent_store, _, result = _canonical_run(tmp_path)
    _, memory_store, integration = _integration(
        data_dir,
        registry,
        agent_store,
    )
    publications = integration.capture.capture(result)

    for publication in publications[:-1]:
        processed = integration.coordinator.process(publication.event)
        assert processed["action"] == "skip"
        assert processed["memory_id"] is None
        assert memory_store.count() == 0

    final = integration.coordinator.process(publications[-1].event)
    assert final["action"] == "create"
    assert memory_store.count() == 1
