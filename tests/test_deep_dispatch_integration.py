from uuid import uuid4

import pytest

from anima.cognition.deep_llm import DeepLLMBackend
from anima.cognition.fast_llm import FastLLMCallResult
from anima.cognition.proposals import CognitiveDispatcher, CognitiveProposal
from anima.cognition.routing import CognitiveDestination, CognitiveRole, CognitiveRouter
from anima.ir import CanonicalTask, Evidence
from anima.resolution import resolve
from anima.tasks.store import TaskStore


class StubTransport:
    def __init__(self, text="Newer evidence supports B.", model="SmolLM3-3B-Q8_0"):
        self.text = text
        self.model = model
        self.calls = []

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        self.calls.append((system_prompt, user_prompt, timeout_seconds))
        return FastLLMCallResult(
            provider="stub",
            model=self.model,
            text=self.text,
            thinking=False,
            latency_ms=3.0,
        )


class RecordingFastBackend:
    def __init__(self):
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        return CognitiveProposal.respond("FAST should not handle conflict")


class FailingTransport:
    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        raise RuntimeError("controlled DEEP failure")


def active_task(store):
    task = store.create_task(
        source="test",
        description="DEEP integration",
        reason="created",
    )
    return store.transition_task(task.public_id, "active", reason="activated")


def conflict_task():
    return CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation="QUERY_FACT",
        subject="device",
        predicate="location",
        evidence=(
            Evidence(
                "old",
                "A",
                "device",
                "location",
                ("mem_old",),
                0.8,
                "2026-11-01T10:00:00+04:00",
            ),
            Evidence(
                "new",
                "B",
                "device",
                "location",
                ("mem_new",),
                1.0,
                "2026-11-02T10:00:00+04:00",
            ),
        ),
    )


def test_conflict_route_reaches_deep_llm_backend_and_not_fast(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    persistent = active_task(store)
    task = conflict_task()
    resolution = resolve(task)
    decision = CognitiveRouter().route(task, resolution)
    assert decision.destination == CognitiveDestination.DEEP

    fast = RecordingFastBackend()
    transport = StubTransport()
    deep = DeepLLMBackend(transport)
    turn = CognitiveDispatcher(fast_backend=fast, deep_backend=deep).dispatch(
        decision,
        persistent_task_id=persistent.public_id,
        task=task,
        resolution=resolution,
    )

    assert turn.accepted is True
    assert turn.request.role == CognitiveRole.DEEP
    assert turn.proposal.payload["text"] == "Newer evidence supports B."
    assert fast.calls == []
    assert len(transport.calls) == 1
    assert deep.call_history[0].model == "SmolLM3-3B-Q8_0"
    assert store.get_task(persistent.public_id).status == "active"


def test_deep_transport_failure_does_not_fall_back_to_fast_or_mutate_task(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    persistent = active_task(store)
    before = store.list_transitions(persistent.public_id)
    task = conflict_task()
    resolution = resolve(task)
    decision = CognitiveRouter().route(task, resolution)
    fast = RecordingFastBackend()
    deep = DeepLLMBackend(FailingTransport())
    dispatcher = CognitiveDispatcher(fast_backend=fast, deep_backend=deep)

    with pytest.raises(RuntimeError, match="controlled DEEP failure"):
        dispatcher.dispatch(
            decision,
            persistent_task_id=persistent.public_id,
            task=task,
            resolution=resolution,
        )

    assert fast.calls == []
    assert deep.call_history == []
    assert store.get_task(persistent.public_id).status == "active"
    assert store.list_transitions(persistent.public_id) == before
