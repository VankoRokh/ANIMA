"""R9.3-C6 RED: a controlled Planner failure must close the run, not the Goal."""
import json

import pytest

from anima.agent import LLMCallResult, RecoverableAgentLoop
from anima.agent.llm_planner import LLMTransportError
from tests.test_agent_llm_planner import _build_loop, _decision
from tests.test_agent_recovery import _open_runtime


@pytest.mark.parametrize("recoverable", [False, True])
@pytest.mark.parametrize("fault,reason", [
    ("length", "planner_output_rejected"),
    (None, "planner_output_rejected"),
    ("invalid_json", "planner_output_rejected"),
    ("transport_error", "planner_transport_failure"),
])
def test_controlled_planner_failure_closes_run_without_effect(
        tmp_path, monkeypatch, recoverable, fault, reason):
    sandbox, planner, baseline, run, spec = _build_loop(tmp_path, [])
    loop = baseline
    if recoverable:
        loop = RecoverableAgentLoop(
            store=baseline.store, registry=baseline.registry,
            planner=planner, choice=baseline.choice,
            executor=baseline.executor, verifier=baseline.verifier,
            verification_bridge=baseline.verification_bridge,
        )
    goal_before = dict(loop.goal_store.get_goal(run["goal_id"]))
    requests = []

    def complete(**kwargs):
        requests.append(kwargs)
        if fault == "transport_error":
            raise LLMTransportError("synthetic unavailable backend")
        text = json.dumps(_decision(tool="fs.write", arguments={
            "path": "result.txt", "content": "42"}))
        if fault == "invalid_json":
            text = "{"
        return LLMCallResult(
            provider="test", model="test", text=text, latency_ms=1,
            input_tokens=20, output_tokens=8,
            finish_reason="stop" if fault == "invalid_json" else fault,
        )

    monkeypatch.setattr(planner.transport, "complete", complete)
    result = loop.run(run["id"], spec, max_steps=4)
    assert result.completed is False
    assert result.stop_reason == reason
    assert result.run["status"] == "failed"
    assert dict(result.goal) == goal_before
    assert result.turns == ()
    assert len(requests) == 1
    assert list(sandbox.iterdir()) == []
    store = loop.store
    steps = store.list_steps(run_id=run["id"])
    assert len(steps) == 1 and steps[0]["status"] == "failed"
    assert store.get_run(run["id"])["status"] == "failed"
    assert store.list_operations(run_id=run["id"]) == []
    assert dict(loop.goal_store.get_goal(run["goal_id"])) == goal_before
    if fault == "transport_error":
        assert not planner.call_history
    else:
        assert len(planner.call_history) == 1
        assert planner.last_call.total_tokens == 28

    if recoverable:
        artifact = loop.recovery_journal.load_step(steps[0]["id"])
        assert artifact is not None
        assert artifact.planner_turn is artifact.action is artifact.receipt is None
        assert artifact.observation is artifact.verification_result is None
        assert not artifact.goal_applied
        _, reopened_store, _, _, reopened = _open_runtime(tmp_path)
        resumed = reopened.resume(run["id"], max_steps=4)
        assert resumed.stop_reason == "run_failed"
        assert resumed.run["status"] == "failed"
        assert resumed.turns == ()
        assert dict(resumed.goal) == goal_before
        assert reopened_store.list_steps(run_id=run["id"]) == steps
        assert reopened_store.list_operations(run_id=run["id"]) == []
        assert list(sandbox.iterdir()) == []
        assert len(requests) == 1
