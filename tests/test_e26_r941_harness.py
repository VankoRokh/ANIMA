"""Positive/negative synthetic controls; no external backend."""
from copy import deepcopy
import json

import pytest

from labs.virtual_anima_lab.python.lifecycle import e26_r941_experiments as h
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as f
from tests.test_e26_r940_cycle_characterization import memory, run, crate_event, lookup, completion, TEMPORAL, OBS
from tests.test_e26a_native_tools import Fake, session


def test_c10_tool_id_bijection_preserves_other_bytes():
    native, wire = session(completion("retrieve_memory", '{"query":"crate","top_k":1}', call_id="alpha"), completion(content="done"))
    selected = native.next()
    native.submit_result(selected, {"kind":"working_world_memory_search", "strategy":"ranked_lexical_not_semantic_retrieval",
        "records":[], "returned":0, "possible_matches":0, "truncated":False,"memory_enabled":True})
    native.next()
    original = wire.requests[-1]
    arm = h.id_variant(original, "I-tool", {"alpha":"beta"})
    assert original["messages"][-2]["tool_calls"][0]["id"] == "alpha"
    assert arm["request"]["messages"][-2]["tool_calls"][0]["id"] == "beta"
    assert arm["request"]["messages"][-1]["tool_call_id"] == "beta"
    assert arm["inverse_mapping"] == {"beta":"alpha"}
    assert arm["policy"] == "BIJECTIVE_RENAME"
    assert len(arm["changed_paths"]) == 2
    assert arm["original_sha256"] != arm["variant_sha256"]
    with pytest.raises(ValueError, match="bijection|collision"):
        h.id_variant(original, "I-tool", {"alpha":"alpha"})
    bad = deepcopy(original)
    bad["messages"][-1]["tool_call_id"] = "stale"
    with pytest.raises(ValueError, match="binding"):
        h.id_variant(bad, "I-tool", {"alpha":"beta"})


@pytest.mark.parametrize("arm,key", [("I-event", "event_id"), ("I-turn", "turn_id")])
def test_nested_json_id_only_variants(arm, key):
    content = '{ "' + key + '" : "old", "text" : "old prose", "count": 2 }'
    request = {"messages":[{"role":"user", "content":content}], "model":"old"}
    variant = h.id_variant(request, arm, {"old":"new"}, known_ids={"old"})
    assert variant["request"]["messages"][0]["content"] == content.replace('"old",', '"new",')
    assert variant["request"]["model"] == "old"
    assert 'old prose' in variant["request"]["messages"][0]["content"]
    with pytest.raises(ValueError, match="unknown|binding"):
        h.id_variant(request, arm, {"old":"new"}, known_ids={"another"})


def test_id_variant_fails_closed_on_prose_and_incomplete_mapping():
    request = {"messages":[{"role":"user", "content":'{"event_id":"e1","other_event_id":"e2"}'}]}
    with pytest.raises(ValueError, match="unsupported|untyped|mapping"):
        h.id_variant(request, "I-event", {"e1":"x"}, known_ids={"e1"})
    with pytest.raises(ValueError):
        h.id_variant({"messages":[{"role":"user","content":"event e1"}]}, "I-event", {"e1":"x"}, known_ids={"e1"})


def test_c11_q_preserves_exact_request_and_does_not_dispatch(tmp_path):
    request = {"model":"test", "messages":[{"role":"user", "content":"frozen"}]}
    reply = completion(content="done")
    wire = Fake(reply, {**reply, "id":"different"})
    output = tmp_path / "q"
    result = h.repeat_request(request, wire, repetitions=2, output=output)
    assert wire.requests == [request, request]
    assert result["policy"] == "EXACT_PRESERVE" and not result["tool_dispatch_performed"]
    assert result["repetitions"][1]["choices_equal"] is True
    assert result["repetitions"][1]["response_exact_equal"] is False
    assert (output / "request.json").is_file()
    assert (output / "response-0001.json").is_file()
    with pytest.raises(FileExistsError):
        h.repeat_request(request, Fake(), repetitions=2, output=output)


def test_c09_host_pair_one_checked_journal(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord, report, records, adapter, wire = run(mem, tmp_path, [lookup(crate_event(mem), "past"),
        completion("inspect_latest_observation", "{}", call_id="latest"), completion(content="done")], requirement=TEMPORAL)
    before = deepcopy((report, records, adapter.calls, wire.requests))
    result = h.host_pair(coord, report, TEMPORAL, calls=adapter.calls)
    assert result["H0"]["result"] == result["H1"]["result"]
    assert result["H1"]["host"]["status"] == "VERIFIED"
    assert result["H0"]["cost"]["result_construction"]["raw_rereads"] == 2
    assert result["H1"]["cost"]["host_projection"]["raw_rereads"] == 2
    assert result["H1"]["cost"]["context_integrity"]["raw_rows_checked"] > 0
    assert (report, coord.decision_records(report["turn_id"]), adapter.calls, wire.requests) == before


def test_recorded_transport_stops_on_first_generated_request_difference(tmp_path):
    request = {"messages":[{"role":"user","content":"original"}]}
    wire = h.RecordedTransport([{"request":request, "raw_response":completion(content="done")}], output=tmp_path / "replay")
    with pytest.raises(h.ReplayDivergence):
        wire.complete({"messages":[{"role":"user","content":"generated different"}]})
    assert wire.index == 0
    assert wire.first_divergence["kind"] == "REQUEST_SHA_MISMATCH"
    assert json.loads((tmp_path / "replay" / "generated-request-0000.json").read_text()) != request
    assert not (tmp_path / "replay" / "delivered-response-0000.json").exists()
    with pytest.raises(h.ReplayDivergence):
        wire.complete(request)


def test_full_recorded_trajectory_rebuilds_raw_and_uses_generated_requests(tmp_path, monkeypatch):
    mem = memory(tmp_path / "original", monkeypatch)
    coord, report, trace, adapter, _ = run(mem, tmp_path / "original", [lookup(crate_event(mem), "past"),
        completion("inspect_latest_observation", "{}", call_id="latest"), completion(content="done")], requirement=TEMPORAL)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    raw = f.export_raw(mem, bundle, 7)
    fixture = f.export_case(bundle, 7, "C06", report, trace, adapter.calls, raw)
    fixture = f.read_json(bundle / "case-7-C06.json")
    result = h.recorded_trajectory(fixture, raw, output=tmp_path / "recorded", task=adapter.task,
                                  requirement=TEMPORAL, max_steps=4, adapter_flags={"temporal":True,"compact_temporal":True,"latest_observation":True},
                                  coordinator_flags={"ranked":True,"latest_observation":True})
    assert result["status"] == "MATCHED"
    assert result["matched_requests"] == 3 and result["first_divergence"] is None
    assert result["journal_equal"] and result["result_equal"]
    wrong = h.recorded_trajectory(fixture, raw, output=tmp_path / "wrong", task="changed task",
                                  requirement=TEMPORAL, max_steps=4, adapter_flags={"temporal":True,"compact_temporal":True,"latest_observation":True},
                                  coordinator_flags={"ranked":True,"latest_observation":True})
    assert wrong["status"] == "DIVERGED"
    assert wrong["matched_requests"] == 0
    assert wrong["first_divergence"]["kind"] == "REQUEST_SHA_MISMATCH"


def test_evaluator_labels_have_no_policy_or_model_context_path(tmp_path, monkeypatch):
    # Evaluator is a separate pure consumer of candidate IDs. Canary labels
    # must not enter the coordinator, requests, host result, or measurements.
    from labs.virtual_anima_lab.python.cognition.observable import measure_turn
    mem = memory(tmp_path, monkeypatch)
    coord, report, trace, adapter, wire = run(mem, tmp_path, [lookup(crate_event(mem), "r"), completion(content="done")])
    before = deepcopy((report, trace, adapter.calls, wire.requests))
    labels = {"EVALUATOR_ONLY_CANARY_SECRET": True}
    result = h.retrieval_metrics(["e"], labels, available_relevant=None)
    assert result["recall"] is None
    sidecar = measure_turn(coord, report, baseline_sha="0"*40, case_id="leak", calls=adapter.calls)
    assert "EVALUATOR_ONLY_CANARY_SECRET" not in json.dumps((sidecar, report, trace, adapter.calls, wire.requests))
    assert (report, coord.decision_records(report["turn_id"]), adapter.calls, wire.requests) == before


def test_id_only_output_comparison_inverts_typed_ids_without_prose_normalization():
    first = completion("lookup_raw_evidence",'{"event_ids":["original"]}',call_id="backend-a")
    second = completion("lookup_raw_evidence",'{"event_ids":["renamed"]}',call_id="backend-b")
    result = h.compare_id_responses(first,second,"I-event",{"original":"renamed"})
    assert result["parsed_operations_content_equal"] is True
    assert result["choices_equal"] is False
    prose = h.compare_id_responses(completion(content="original"),completion(content="renamed"),"I-event",{"original":"renamed"})
    assert prose["parsed_operations_content_equal"] is False


def test_unlabelled_candidates_are_not_false_relevance():
    metrics = h.retrieval_metrics(["unknown"],{},available_relevant=1)
    assert metrics["precision"] is None and metrics["recall"] is None


def test_unknown_or_duplicate_tool_links_and_collision_fail_closed():
    request = {"messages":[{"role":"assistant","tool_calls":[{"id":"one"},{"id":"one"}]},
                           {"role":"tool","tool_call_id":"one"}]}
    with pytest.raises(ValueError,match="binding"):
        h.id_variant(request,"I-tool",{"one":"two"})
    request = {"messages":[{"role":"user","content":'{"event_ids":["e1","e2"]}'}]}
    with pytest.raises(ValueError,match="bijection|collision"):
        h.id_variant(request,"I-event",{"e1":"x","e2":"x"},known_ids={"e1","e2"})


def test_model_and_policy_never_import_offline_measurement_or_evaluator():
    from pathlib import Path
    for path in ("labs/virtual_anima_lab/python/cognition/coordinator.py",
                 "labs/virtual_anima_lab/python/cognition/native_lab.py",
                 "anima/cognition/coordinator.py"):
        text = Path(path).read_text()
        assert "e26_r941_experiments" not in text
        import ast
        imports = [ast.unparse(node) for node in ast.walk(ast.parse(text))
                   if isinstance(node,(ast.Import,ast.ImportFrom))]
        assert not any("observable" in line or "retrieval_metrics" in line for line in imports)


def test_prepared_manifest_contains_maps_hashes_order_and_unsupported_ids(tmp_path,monkeypatch):
    from tests.test_e26_reproducibility import make_bundle
    bundle,_,_ = make_bundle(tmp_path,monkeypatch)
    before = {p.name:p.read_bytes() for p in bundle.iterdir()}
    plan = h.prepare_manifest(bundle,output=tmp_path/"plan",baseline_sha="0"*40)
    assert plan["status"] == "PREPARED_NOT_RUN"
    assert plan["repetitions"] == 20 and plan["concurrency"] == 1
    assert plan["order_table"][:2] == [{"pair":0,"order":["A","B"]},{"pair":1,"order":["B","A"]}]
    assert any(a["arm"] == "I-turn" and a["status"] == "UNSUPPORTED" for a in plan["entries"][0]["arms"])
    assert {p.name:p.read_bytes() for p in bundle.iterdir()} == before
    with pytest.raises(ValueError,match="outside frozen"):
        h.prepare_manifest(bundle,output=bundle/"illegal",baseline_sha="0"*40)


def test_full_trajectory_detects_outcome_divergence_before_next_delivery(tmp_path,monkeypatch):
    mem = memory(tmp_path/"original",monkeypatch)
    coord,report,trace,adapter,_ = run(mem,tmp_path/"original",[lookup(crate_event(mem),"r"),completion(content="done")])
    bundle = tmp_path/"bundle"
    bundle.mkdir()
    raw = f.export_raw(mem,bundle,7)
    f.export_case(bundle,7,"C06",report,trace,adapter.calls,raw)
    fixture = f.read_json(bundle/"case-7-C06.json")
    import labs.virtual_anima_lab.python.cognition.coordinator as module
    original = module._read_only_result
    def altered(*args,**kwargs):
        result = original(*args,**kwargs)
        return {**result,"diagnostic_mutation":True}
    monkeypatch.setattr(module,"_read_only_result",altered)
    result = h.recorded_trajectory(fixture,raw,output=tmp_path/"diverged",task=adapter.task,
        requirement=OBS,
        max_steps=4,adapter_flags={"temporal":True,"compact_temporal":True,"latest_observation":True},
        coordinator_flags={"ranked":True,"latest_observation":True})
    assert result["first_divergence"]["kind"] == "JOURNAL_PREFIX_MISMATCH"
    assert result["matched_requests"] == 1
    assert not (tmp_path/"diverged/transport/delivered-response-0001.json").exists()


def test_id_arm_changes_only_its_class_when_other_ids_exist():
    request = {"messages":[{"role":"user","content":'{"event_id":"event","turn_id":"turn"}'},
        {"role":"assistant","tool_calls":[{"id":"tool","function":{"name":"read","arguments":'{"event_ids":["event"]}'}}]},
        {"role":"tool","tool_call_id":"tool","content":'{"event_id":"event"}'}]}
    tool = h.id_variant(request,"I-tool",{"tool":"renamed"})
    assert tool["request"]["messages"][0] == request["messages"][0]
    assert tool["request"]["messages"][-1]["content"] == request["messages"][-1]["content"]
    event = h.id_variant(request,"I-event",{"event":"other"},known_ids={"event"})
    assert event["request"]["messages"][1]["tool_calls"][0]["id"] == "tool"
    assert '"turn_id":"turn"' in event["request"]["messages"][0]["content"]


def test_prepared_q_runner_uses_frozen_requests_and_records_runtime(tmp_path,monkeypatch):
    from tests.test_e26_reproducibility import make_bundle
    bundle,request,response = make_bundle(tmp_path,monkeypatch)
    enriched = tmp_path/"enriched"
    enriched.mkdir()
    for source in bundle.glob("*.json"):
        if source.name not in ("manifest.json","checksums.json"):
            (enriched/source.name).write_bytes(source.read_bytes())
    model_file=tmp_path/"synthetic-model"
    model_file.write_bytes(b"synthetic only")
    backend={"argv":["synthetic-backend","-m",str(model_file)],"executable_sha256":"a"*64,
             "process_start_ticks":"123","pid":1}
    manifest=f.read_json(bundle/"manifest.json")
    manifest.update(backend=backend,local_model_sha256=f.file_digest(model_file),base_url="http://127.0.0.1:8085")
    manifest.pop("complete")
    f.seal_bundle(enriched,manifest,complete=True)
    h.prepare_manifest(enriched,output=tmp_path/"plan",baseline_sha="0"*40)
    monkeypatch.setattr(f,"git_snapshot",lambda:"0"*40)
    monkeypatch.setattr(f,"backend_snapshot",lambda pid:deepcopy(backend))
    import anima.agent.native_tools as native
    wire=Fake(*[deepcopy(response) for _ in range(20)])
    monkeypatch.setattr(native,"LoopbackChatTransport",lambda url:wire)
    state={k:"UNKNOWN" for k in ("cache_state","warm_state","slot_reuse","chat_template_sha256",
                                "hardware","threads","batch","parallel_slots","external_config_hashes")}
    result=h.run_manifest(tmp_path/"plan/run-manifest.json",arm="Q",output=tmp_path/"q-run",backend_pid=1,backend_state=state)
    assert wire.requests == [request]*20
    assert len(result["summaries"][0]["repetitions"]) == 20
    assert f.read_json(tmp_path/"q-run/run-inputs.json")["backend"] == backend
    assert not result["summaries"][0]["tool_dispatch_performed"]
    changed={**backend,"process_start_ticks":"456"}
    reads=iter([deepcopy(backend),changed])
    monkeypatch.setattr(f,"backend_snapshot",lambda pid:next(reads))
    failed=h.run_manifest(tmp_path/"plan/run-manifest.json",arm="Q",output=tmp_path/"failed-run",backend_pid=1,backend_state=state)
    assert len(wire.requests) == 20
    assert failed["summaries"][0]["repetitions"][0]["status"] == "TRANSPORT_FAILED"
    assert len(failed["summaries"][0]["repetitions"]) == 1


def test_id_comparison_maps_structured_claims_but_preserves_answer_prose():
    claim={"entity_ref":"lab.item.crate","predicate":"observed_in_sample","value":True,
           "event_id":"original","sample_seq":2,"scope":"source_sample"}
    left=completion(content=json.dumps({"answer":"Captured only","claims":[claim]}))
    right=completion(content=json.dumps({"answer":"Captured only","claims":[{**claim,"event_id":"variant"}]}))
    result=h.compare_id_responses(left,right,"I-event",{"original":"variant"})
    assert result["parsed_operations_content_equal"] is True
    assert result["choices_equal"] is False
    changed=completion(content=json.dumps({"answer":"Different prose","claims":[{**claim,"event_id":"variant"}]}))
    assert h.compare_id_responses(left,changed,"I-event",{"original":"variant"})["parsed_operations_content_equal"] is False
