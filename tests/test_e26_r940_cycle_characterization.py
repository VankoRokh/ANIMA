"""R9.4.0: reproduce baseline limitations; PASS is NOT remediation.

Synthetic terminal-valid wire replies drive the real unchanged lab stack.
All evidence comes from the public captured context/services; no answer key
is supplied to the coordinator. Counts below are offline characterization.
"""
from copy import deepcopy
import json

import pytest

from labs.virtual_anima_lab.python.cognition.completion import (
    CompletionRequirement, evaluate_completion,
)
from labs.virtual_anima_lab.python.cognition.coordinator import (
    E25LabCognitiveCoordinator, _rank_memory_matches, _read_only_result,
)
from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
from labs.virtual_anima_lab.python.cognition.host_temporal_projection import project_temporal_claims
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceBudget, ResourceLimits
from labs.virtual_anima_lab.python.cognition.source_binding import admitted_source_rows
from labs.virtual_anima_lab.python.cognition.source_policy import TurnSourcePolicy
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as frozen
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import E24MemoryError
from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import assess
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion, session
from tests.test_e26_reproducibility import make_bundle

CRATE = "lab.item.crate"
OBS = CompletionRequirement("verified_observation", (CRATE,))
TEMPORAL = CompletionRequirement("historical_and_latest_observation", (CRATE,))


def lookup(event, call_id):
    return completion("lookup_raw_evidence", json.dumps({"event_ids": [event]}), call_id=call_id)


def search(call_id="search"):
    return completion("retrieve_memory", '{"query":"crate","top_k":1}', call_id=call_id)


def run(mem, tmp_path, replies, *, requirement=OBS, enabled=True, steps=4):
    wire = Fake(*replies)
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        trace_path=tmp_path / "r940-calls.jsonl", task="Check captured crate observations",
        transport=wire, temporal=True, compact_temporal=True, latest_observation=True)
    coordinator = E25LabCognitiveCoordinator(mem, max_steps=steps, ranked=True,
                                             latest_observation=True)
    report = coordinator.run_turn(adapter, turn_id="r940", memory_enabled=enabled,
        completion_requirement=requirement, resource_limits=ResourceLimits(max_calls=steps))
    records = coordinator.decision_records(report["turn_id"])
    assert len(wire.requests) == len(adapter.calls) == report["model_calls_used"]
    assert all(c["valid"] and c["transport_ok"] for c in adapter.calls)
    assert report["resource_budget"]["usage_complete"]
    assert len(mem._core.event_log.load_events()) == 3
    assert mem._core.memory_store.count() == 0 and mem._core.core_execution is None
    return coordinator, report, records, adapter, wire


def crate_event(mem):
    return next(e["last_seen_event_id"] for e in mem.world_model()["entities"]
                if e["entity_ref"] == CRATE)


def completion_at(requirement, report, records, size):
    # Diagnostic prefixes only; never feed this measurement into admission.
    prefix = {**report, "outcomes": report["outcomes"][:size]}
    return evaluate_completion(requirement, prefix, records[:size])


def test_r940_second_stop_leaves_missing_evidence_with_budget_remaining(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    _, report, records, _, _ = run(mem, tmp_path,
        [search(), completion(content="done"), completion(content="still done")])
    assert report["status"] == "STOPPED"
    assert report["model_calls_used"] == 3
    assert [d["decision"] for d in report["continuation_decisions"]] == [
        "CONTINUE", "CONTINUATION_LIMIT"]
    assert report["continuation_decisions"][-1]["model_calls_remaining"] == 1
    result = evaluate_completion(OBS, report, records)
    assert not result["information_requirement_satisfied"]
    assert result["missing_entities"] == [CRATE]
    assert result["task_completion"] == "NOT_ESTABLISHED"


def test_r940_repeated_reads_consume_budget_after_sufficiency(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    event = crate_event(mem)
    _, report, records, _, _ = run(mem, tmp_path,
        [lookup(event, f"read{i}") for i in range(4)])
    assert report["status"] == "STEP_BUDGET_EXHAUSTED"
    assert all(completion_at(OBS, report, records, n)["information_requirement_satisfied"]
               for n in range(1, 5))
    rows = [r for record in records for r in admitted_source_rows(record)]
    assert len(rows) == 4 and len({r["event_id"] for r in rows}) == 1
    assert report["continuation_decisions"] == []
    assert report["resource_budget"]["reserved_calls"] == 4
    assert report["resource_budget"]["reported_output_tokens"] == 16
    # Three further acquisition proposals, zero new sources or completion gain.
    assert [len({r["event_id"] for rec in records[:n] for r in admitted_source_rows(rec)})
            for n in range(1, 5)] == [1, 1, 1, 1]


def test_r940_cross_tool_same_source_is_not_repeated_proposal(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    latest = next(e["last_seen_event_id"] for e in mem.world_model()["entities"]
                  if e["current_observation"] == "observed")
    _, report, records, adapter, _ = run(mem, tmp_path, [
        lookup(crate_event(mem), "past"),
        completion("inspect_latest_observation", "{}", call_id="latest"),
        lookup(latest, "latest-again"), completion(content="done")], requirement=TEMPORAL)
    result = assess({"kind": "positive", "targets": [CRATE]}, report, records, adapter.calls)
    assert result["repeated_proposals"] == 0
    rows = [r for rec in records for r in admitted_source_rows(rec)]
    assert len(rows) == 3 and len({r["event_id"] for r in rows}) == 2
    assert rows[1] == rows[2]
    assert completion_at(TEMPORAL, report, records, 2)["information_requirement_satisfied"]
    assert completion_at(TEMPORAL, report, records, 3)["information_requirement_satisfied"]


def test_r940_memory_off_empty_search_is_satisfied_without_availability_verdict(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    assert crate_event(mem)  # Evaluator control: history exists, but is not available in OFF scope.
    req = CompletionRequirement("empty_search", query="crate")
    coord, report, records, _, _ = run(mem, tmp_path,
        [search(), completion(content="uncertain")], requirement=req, enabled=False)
    result = build_cognitive_result(coord, report, requirement=req)
    assert result["information"]["status"] == "SATISFIED"
    assert report["outcomes"][0]["result"]["memory_enabled"] is False
    assert report["outcomes"][0]["result"]["records"] == []
    evaluation = evaluate_completion(req, report, records)
    assert evaluation["reason_code"] == "EMPTY_SEARCH_CONFIRMED"
    assert "availability" not in evaluation
    assert result["information"]["search_outcomes"][0]["scope"] == "BOUNDED_MEMORY_SEARCH_NOT_WORLD_ABSENCE"
    assert result["presentation"]["whole_answer_verified"] is False


def test_r940_memory_off_continuation_repeats_unproductive_search(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    _, report, records, _, wire = run(mem, tmp_path, [
        search("first"), completion(content="uncertain"),
        search("again"), completion(content="still uncertain")], enabled=False)
    assert report["status"] == "STOPPED" and len(wire.requests) == 4
    assert all(o["result"]["records"] == [] for o in report["outcomes"])
    assert [d["decision"] for d in report["continuation_decisions"]] == [
        "CONTINUE", "BUDGET_EXHAUSTED"]
    assert not evaluate_completion(OBS, report, records)["information_requirement_satisfied"]
    assert all(not tuple(admitted_source_rows(r)) for r in records)
    # No hidden source/target IDs introduced by continuation feedback.
    feedback = json.loads(wire.requests[2]["messages"][-1]["content"])
    assert feedback["status"] == "INCOMPLETE" and "ev_" not in json.dumps(feedback)


@pytest.mark.parametrize("query,returned", [("crate", 1), ("box", 0), ("ящик", 0), ("cr", 0)])
def test_r940_lexical_retrieval_has_no_alias_language_or_short_token_recall(
        tmp_path, monkeypatch, query, returned):
    mem = memory(tmp_path, monkeypatch)
    result = _read_only_result(mem, kind="retrieve_memory",
        args={"query": query, "top_k": 1}, memory_enabled=True, ranked=True)
    assert result["strategy"] == "ranked_lexical_not_semantic_retrieval"
    assert result["returned"] == returned
    assert any(e["entity_ref"] == CRATE for e in mem.world_model()["entities"])


def test_r940_ranked_or_tie_and_top_k_can_omit_requested_entity():
    rows = [{"entity_ref": "lab.obstacle.aaa"}, {"entity_ref": "lab.obstacle.shortcut"}]
    ranked = _rank_memory_matches(rows, "obstacle")
    assert ranked[:1] == rows[:1]  # Shared category term does not distinguish target.
    assert ranked[1:] == rows[1:]
    assert _rank_memory_matches(rows, "lab.obstacle.shortcut")[:1] == rows[1:]


def test_r940_retrieval_can_return_only_already_exposed_source(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    policy = TurnSourcePolicy(mem.context_for_cognition())
    before = policy.exposed_bindings()
    result = _read_only_result(mem, kind="retrieve_memory",
        args={"query": "crate", "top_k": 1}, memory_enabled=True, ranked=True)
    policy.check_result("retrieve_memory", {"query": "crate", "top_k": 1}, result)
    policy.record_completed("retrieve_memory", result)
    assert result["returned"] == 1 and policy.exposed_bindings() == before
    # Retrieval metadata does not constitute an admitted Raw observation.


def test_r940_host_on_off_same_journal_changes_no_acquisition_but_rereads_raw(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord, report, records, adapter, wire = run(mem, tmp_path, [
        lookup(crate_event(mem), "past"),
        completion("inspect_latest_observation", "{}", call_id="latest"),
        completion(content="unverified prose")], requirement=TEMPORAL)
    before = deepcopy((report, records, adapter.calls, wire.requests))
    rereads = []
    original = mem.raw_evidence
    def counted(sample):
        rereads.append(sample)
        return original(sample)
    monkeypatch.setattr(mem, "raw_evidence", counted)
    off = build_cognitive_result(coord, report, requirement=TEMPORAL, research_calls=adapter.calls)
    result_rereads = len(rereads)
    host = project_temporal_claims(coord, TEMPORAL, report)
    host_rereads = len(rereads) - result_rereads
    assert result_rereads == host_rereads == 2
    assert host["status"] == "VERIFIED" and off["information"]["status"] == "SATISFIED"
    assert off["evidence"]["claim_coverage"] == "COMPLETE"
    assert len(off["evidence"]["facts"]) == 2
    assert host["model_calls"] == host["new_service_reads"] == 0
    assert (report, coord.decision_records("r940"), adapter.calls, wire.requests) == before
    assert project_temporal_claims(coord, TEMPORAL, report) == host
    assert len(rereads) == 6  # Canonical verification work, not new acquisition.
    assert off["presentation"]["whole_answer_verified"] is False


def test_r940_tool_call_id_only_difference_changes_subsequent_exact_request():
    requests = []
    for tool_id in ("alpha", "beta"):
        native, wire = session(search(tool_id), completion(content="done"))
        selected = native.next()
        native.submit_result(selected, {"kind": "working_world_memory_search",
            "strategy": "ranked_lexical_not_semantic_retrieval", "records": [],
            "returned": 0, "possible_matches": 0, "truncated": False, "memory_enabled": True})
        assert native.next() is None
        requests.append(deepcopy(wire.requests))
    assert requests[0][0] == requests[1][0]
    left, right = requests[0][1], requests[1][1]
    assert frozen.digest(frozen.canonical(left)) != frozen.digest(frozen.canonical(right))
    # Existing event/sample aliasing does not normalize native tool-call IDs.
    assert frozen.normalized_request_sha(frozen.canonical(left), {}) != (
        frozen.normalized_request_sha(frozen.canonical(right), {}))
    for request in (left, right):
        request["messages"][-2]["tool_calls"][0]["id"] = "mapped"
        request["messages"][-1]["tool_call_id"] = "mapped"
    assert left == right


def test_r940_frozen_replay_repeats_one_request_without_dispatching_new_tool(tmp_path, monkeypatch):
    bundle, request, _ = make_bundle(tmp_path, monkeypatch)
    tool = search("fresh-id")
    wire = Fake(tool, tool)
    before = {p.name: p.read_bytes() for p in bundle.iterdir() if p.is_file()}
    for _ in range(2):
        replay = frozen.replay_request(bundle, seed=7, case_id="C06", index=0, transport=wire)
        assert not replay["tool_dispatch_performed"]
        assert replay["mode"] == "EXACT_REQUEST_REPLAY_NO_SERVICE_DISPATCH"
    assert wire.requests == [request, request]
    assert {p.name: p.read_bytes() for p in bundle.iterdir() if p.is_file()} == before


def test_r940_input_limit_is_post_call_reported_boundary_not_inflight_ceiling():
    budget = ResourceBudget(ResourceLimits(), clock=lambda: 0.0)
    assert budget.reserve()
    assert budget.settle({"input_tokens": 8193, "output_tokens": 4}) == "INPUT_USAGE_EXCEEDED"
    result = budget.snapshot()
    assert result["reported_input_tokens"] == 8193 and result["reserved_calls"] == 1
    assert result["input_and_elapsed_boundary_only"] and not budget.reserve()


def test_r940_unavailable_memory_before_context_has_no_turn_result(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        trace_path=tmp_path / "unavailable.jsonl", task="Check observations", transport=Fake())
    def unavailable(**kwargs):
        raise E24MemoryError("controlled unavailable working model")
    monkeypatch.setattr(mem, "world_model", unavailable)
    with pytest.raises(E24MemoryError, match="controlled unavailable"):
        coord.run_turn(adapter, turn_id="unavailable", completion_requirement=OBS,
                       resource_limits=ResourceLimits())
    assert adapter.calls == [] and coord.decision_records("unavailable") == []
    assert mem._core.memory_store.count() == 0


def test_r940_latest_tool_does_not_satisfy_lookup_only_requirement(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    surface = next(e["entity_ref"] for e in mem.world_model()["entities"]
                   if e["current_observation"] == "observed")
    req = CompletionRequirement("verified_observation", (surface,))
    _, report, records, _, _ = run(mem, tmp_path, [
        completion("inspect_latest_observation", "{}", call_id="latest"),
        completion(content="done"), completion(content="done again")], requirement=req)
    assert surface in admitted_source_rows(records[0])[0]["entities_observed"]
    assert not evaluate_completion(req, report, records)["information_requirement_satisfied"]
    assert report["model_calls_used"] == 3
    # An explicit existing requirement boundary, not permission to silently widen it.
