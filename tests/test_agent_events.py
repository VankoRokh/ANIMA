from pathlib import Path

import pytest

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
from anima.agent.verification import (
    DETERMINISTIC_VERIFIER_NAME,
    DETERMINISTIC_VERIFIER_VERSION,
    FILE_CONTENT_EQUALS,
)
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore
from anima.memory.event_log import EventLog


T0 = "2026-10-27T18:00:00+00:00"


def _proposal(tool, arguments, rationale):
    return ProposalDraft(
        tool=tool,
        tool_version="1",
        arguments=arguments,
        expected_observation="factual sandbox observation",
        rationale_summary=rationale,
    )


def _publisher(tmp_path):
    store = AgentStore(Path(tmp_path) / "agent.db")
    event_log = EventLog(Path(tmp_path) / "events.jsonl")
    return store, event_log, AgentEventPublisher(store=store, event_log=event_log)


def _canonical_loop(tmp_path):
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
        reason="Stage 4.9 capture test goal",
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
    return data_dir, registry, agent_store, result


def test_publisher_replay_uses_same_event_id_without_duplicate_raw_event(tmp_path):
    _, event_log, publisher = _publisher(tmp_path)
    kwargs = {
        "event_type": "agent.result",
        "payload": {"run_id": "ar_test", "status": "completed"},
        "references": [{"kind": "agent_run", "id": "ar_test"}],
        "timestamp": T0,
    }

    first = publisher.publish("result:ar_test", **kwargs)
    second = publisher.publish("result:ar_test", **kwargs)

    assert first.event_id == second.event_id
    assert first.replayed is False
    assert second.replayed is True
    assert publisher.get("result:ar_test")["status"] == "published"
    assert len(event_log.load_events()) == 1


def test_publication_key_replay_with_different_content_is_rejected(tmp_path):
    _, event_log, publisher = _publisher(tmp_path)
    publisher.publish(
        "result:ar_conflict",
        event_type="agent.result",
        payload={"status": "completed"},
        references=[],
        timestamp=T0,
    )

    with pytest.raises(ValueError, match="different Event content"):
        publisher.publish(
            "result:ar_conflict",
            event_type="agent.result",
            payload={"status": "failed"},
            references=[],
            timestamp=T0,
        )

    assert len(event_log.load_events()) == 1


def test_crash_after_event_append_reconciles_without_duplicate(tmp_path, monkeypatch):
    store, event_log, publisher = _publisher(tmp_path)
    original = publisher._mark_published
    calls = 0

    def crash_once(publication_key):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated crash after raw append")
        return original(publication_key)

    monkeypatch.setattr(publisher, "_mark_published", crash_once)

    with pytest.raises(RuntimeError, match="simulated crash"):
        publisher.publish(
            "result:ar_recovery",
            event_type="agent.result",
            payload={"status": "completed"},
            references=[],
            timestamp=T0,
        )

    assert len(event_log.load_events()) == 1
    assert publisher.get("result:ar_recovery")["status"] == "prepared"

    recovered = AgentEventPublisher(store=store, event_log=event_log)
    publication = recovered.publish(
        "result:ar_recovery",
        event_type="agent.result",
        payload={"status": "completed"},
        references=[],
        timestamp=T0,
    )

    assert publication.replayed is True
    assert recovered.get("result:ar_recovery")["status"] == "published"
    assert len(event_log.load_events()) == 1


def test_canonical_agent_loop_captures_only_significant_compact_events(tmp_path):
    data_dir, registry, store, result = _canonical_loop(tmp_path)
    assert result.completed is True

    event_log = EventLog(data_dir / "events.jsonl")
    publisher = AgentEventPublisher(store=store, event_log=event_log)
    capture = AgentExperienceCapture(publisher=publisher, registry=registry)

    publications = capture.capture(result)
    records = event_log.load_events()

    assert [item.event.event_type for item in publications] == [
        "agent.failure",
        "agent.strategy_change",
        "agent.action",
        "agent.observation",
        "agent.result",
    ]
    assert [record["type"] for record in records] == [
        "agent.failure",
        "agent.strategy_change",
        "agent.action",
        "agent.observation",
        "agent.result",
    ]
    assert len(records) == 5

    # Raw file/tool payload is deliberately not copied into compact experience Events.
    serialized = "\n".join(str(record["payload"]) for record in records)
    assert "content" not in serialized
    assert "bytes_written" not in serialized

    action_event = next(record for record in records if record["type"] == "agent.action")
    assert action_event["payload"]["tool"] == "fs.write"
    assert action_event["payload"]["effect_class"] == "reversible_write"

    observation_event = next(
        record for record in records if record["type"] == "agent.observation"
    )
    assert observation_event["payload"]["verification_outcome"] == "success"
    assert observation_event["payload"]["criterion_satisfied"] is True

    result_event = records[-1]
    assert result_event["payload"]["run_status"] == "completed"
    assert result_event["payload"]["goal_status"] == "completed"
    assert result_event["payload"]["completed"] is True
    assert result_event["payload"]["turn_count"] == 3


def test_capture_replay_does_not_duplicate_agent_events(tmp_path):
    data_dir, registry, store, result = _canonical_loop(tmp_path)
    event_log = EventLog(data_dir / "events.jsonl")
    capture = AgentExperienceCapture(
        publisher=AgentEventPublisher(store=store, event_log=event_log),
        registry=registry,
    )

    first = capture.capture(result)
    second = capture.capture(result)

    assert [item.event_id for item in second] == [item.event_id for item in first]
    assert all(item.replayed for item in second)
    assert len(event_log.load_events()) == len(first) == 5


def test_publisher_ledger_survives_agent_store_reopen(tmp_path):
    data_dir = Path(tmp_path)
    store = AgentStore(data_dir / "agent.db")
    event_log = EventLog(data_dir / "events.jsonl")
    publisher = AgentEventPublisher(store=store, event_log=event_log)
    first = publisher.publish(
        "result:ar_reopen",
        event_type="agent.result",
        payload={"status": "completed"},
        references=[],
        timestamp=T0,
    )

    reopened_store = AgentStore(data_dir / "agent.db")
    reopened = AgentEventPublisher(store=reopened_store, event_log=EventLog(data_dir / "events.jsonl"))
    record = reopened.get("result:ar_reopen")

    assert record["event_id"] == first.event_id
    assert record["status"] == "published"
    assert record["content_hash"] == first.content_hash
