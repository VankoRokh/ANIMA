from copy import deepcopy
import json
import pytest
from tests.test_e26_r940_cycle_characterization import memory,crate_event,lookup,search,OBS,TEMPORAL,CRATE
from tests.test_e26a_native_tools import Fake,completion
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement,evaluate_completion
from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
from labs.virtual_anima_lab.python.cognition.observable import measure_turn

def execute(tmp_path,mem,replies,req=OBS,enabled=True,task='Check captured observations'):
 wire=Fake(*replies)
 adapter=NativeLabAdapter(base_url='http://127.0.0.1:8085',model='test',trace_path=tmp_path/'calls.jsonl',task=task,transport=wire,temporal=True,compact_temporal=True,latest_observation=True,canonical_sets=True)
 coord=E25LabCognitiveCoordinator(mem,ranked=True,latest_observation=True,policy_profile='r942/0.1')
 report=coord.run_turn(adapter,turn_id='controlled',memory_enabled=enabled,completion_requirement=req,resource_limits=ResourceLimits())
 records=coord.decision_records(report['turn_id'])
 (tmp_path/'result.json').write_text(json.dumps({'report':report,'records':records,'calls':adapter.calls},ensure_ascii=False))
 assert mem._core.memory_store.count()==0 and len(mem._core.event_log.load_events())==3
 return coord,report,records,adapter,wire

def test_sufficient_first_read_no_fabricated_final(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 c,r,records,a,w=execute(tmp_path,mem,[lookup(crate_event(mem),'one')]*4)
 assert len(w.requests)==len(records)==1
 assert r['status']=='RESEARCH_TERMINATED' and r['control']['reason']=='INFORMATION_SUFFICIENT'
 result=build_cognitive_result(c,r,requirement=OBS,research_calls=a.calls)
 assert result['information']['status']=='SATISFIED' and result['evidence']['facts']
 assert result['presentation']['model_text'] is None
 assert not result['information']['completion']['model_stopped']
 assert result['execution']['task_completion']=='NOT_ESTABLISHED'
 s=measure_turn(c,r,baseline_sha='2a9cb1b202e3efcabaae0b2621320af3c431e242',case_id='sufficient',requirement=OBS,calls=a.calls)
 assert s['sufficiency']['research_calls_after']==0

@pytest.mark.parametrize('enabled', [False,True])
def test_stop_continuation_recoverability(tmp_path,monkeypatch,enabled):
 mem=memory(tmp_path,monkeypatch)
 c,r,records,a,w=execute(tmp_path,mem,[search(),completion(content='uncertain'),lookup(crate_event(mem),'raw')],enabled=enabled)
 if enabled:
  assert len(w.requests)==3 and r['control']['reason']=='INFORMATION_SUFFICIENT'
  assert r['continuation_decisions'][0]['decision']=='CONTINUE'
 else:
  assert len(w.requests)==1 and r['control']['reason']=='SOURCE_UNAVAILABLE'
  assert r['control']['state']['availability']=='DISABLED_BY_POLICY'

@pytest.mark.parametrize('tool', ['lookup','latest'])
def test_same_and_cross_tool_redundancy(tmp_path,monkeypatch,tool):
 mem=memory(tmp_path,monkeypatch)
 latest=next(e['last_seen_event_id'] for e in mem.world_model()['entities'] if e['current_observation']=='observed')
 first=completion('inspect_latest_observation','{}',call_id='a')
 second=lookup(latest,'b') if tool=='lookup' else completion('inspect_latest_observation','{}',call_id='b')
 c,r,records,a,w=execute(tmp_path,mem,[first,second],req=TEMPORAL)
 assert len(records)==2 and records[1]['admission']=='REJECTED'
 assert records[1]['outcome']['reason_code']=='POLICY_NO_GAIN'
 assert 'result' not in records[1]['outcome']
 assert r['control']['reason']=='REDUNDANT_OPERATION'
 assert sum(o['status']=='COMPLETED' for o in r['outcomes'])==1

def test_c14_same_id_lookup_is_new_requirement_fact(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 row=next(e for e in mem.world_model()['entities'] if e['current_observation']=='observed')
 req=CompletionRequirement('verified_observation',(row['entity_ref'],))
 c,r,records,a,w=execute(tmp_path,mem,[completion('inspect_latest_observation','{}',call_id='a'),lookup(row['last_seen_event_id'],'b')],req=req,enabled=False)
 assert len(records)==2 and all(x['outcome']['status']=='COMPLETED' for x in records)
 assert r['control']['reason']=='INFORMATION_SUFFICIENT'
 assert evaluate_completion(req,{**r,'outcomes':r['outcomes'][:1]},records[:1])['information_requirement_satisfied'] is False

def test_mixed_known_new_is_not_pruned(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 past=crate_event(mem);latest=next(e['last_seen_event_id'] for e in mem.world_model()['entities'] if e['current_observation']=='observed')
 c,r,records,a,w=execute(tmp_path,mem,[completion('retrieve_memory','{"query":"lab","top_k":3}',call_id='search'),lookup(past,'a'),completion('lookup_raw_evidence',json.dumps({'event_ids':[past,latest,past]}),call_id='b')],req=TEMPORAL)
 assert records[2]['proposal']['arguments']['event_ids']==[past,latest]
 assert len(records[2]['outcome']['result']['records'])==2
 assert a.calls[2]['arguments_normalized']
 assert r['control']['reason']=='INFORMATION_SUFFICIENT'

def test_repeated_stop_no_retry_loop(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 c,r,records,a,w=execute(tmp_path,mem,[completion(content='uncertain')]*4)
 assert len(w.requests)==2 and r['status']=='STOPPED'
 assert r['continuation_decisions'][-1]['decision']=='NO_CONTINUATION_GAIN'

@pytest.mark.parametrize('mode',['incomplete','missing','budget'])
def test_generation_contracts_no_retry(tmp_path,monkeypatch,mode):
 mem=memory(tmp_path,monkeypatch)
 response=lookup(crate_event(mem),'a')
 if mode=='incomplete':response['choices'][0]['finish_reason']='length'
 if mode=='missing':response.pop('usage')
 if mode=='budget':response['usage']['prompt_tokens']=8193
 c,r,records,a,w=execute(tmp_path,mem,[response]*4)
 assert len(w.requests)==1
 assert r['status'] in ('REJECTED','STEP_BUDGET_EXHAUSTED')
 assert not records or records[0]['outcome']['status']=='REJECTED'

def test_no_service_read_generation_and_violation(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 c,r,records,a,w=execute(tmp_path,mem,[search()],req=CompletionRequirement('no_service_read'))
 assert len(w.requests)==1 and r['control']['reason']=='NO_SERVICE_READ_VIOLATION'
 assert not evaluate_completion(CompletionRequirement('no_service_read'),r,records)['information_requirement_satisfied']

@pytest.mark.parametrize('change',['raw_sha256','source_ref','sample_id'])
def test_service_integrity_rejection_is_not_availability_retry(tmp_path,monkeypatch,change):
 import labs.virtual_anima_lab.python.cognition.coordinator as module
 mem=memory(tmp_path,monkeypatch);original=module._read_only_result
 def corrupt(*args,**kw):
  result=deepcopy(original(*args,**kw));result['records'][0][change]='forged';return result
 monkeypatch.setattr(module,'_read_only_result',corrupt)
 c,r,records,a,w=execute(tmp_path,mem,[lookup(crate_event(mem),'a')]*4)
 assert len(w.requests)==1 and r['status']=='REJECTED'
 assert records[0]['outcome']['reason_code']=='SERVICE_REJECTED'
 assert 'result' not in records[0]['outcome']

@pytest.mark.parametrize('event',['ev_forged','ev_foreign'])
def test_unexposed_source_no_admission(tmp_path,monkeypatch,event):
 mem=memory(tmp_path,monkeypatch)
 c,r,records,a,w=execute(tmp_path,mem,[lookup(event,'a')]*4)
 assert len(w.requests)==1 and r['status']=='REJECTED'
 assert all(x['outcome']['status']=='REJECTED' for x in records)

def test_valid_final_without_reads_still_requires_generation(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 c,r,records,a,w=execute(tmp_path,mem,[completion(content='4')],req=CompletionRequirement('no_service_read'))
 assert r['status']=='STOPPED' and len(w.requests)==1 and records==[]

def test_repeated_search_no_fabricated_success(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 c,r,records,a,w=execute(tmp_path,mem,[search('a'),search('b')])
 assert len(w.requests)==2 and r['control']['reason']=='REDUNDANT_OPERATION'
 assert records[1]['outcome']['status']=='REJECTED' and 'result' not in records[1]['outcome']

def test_unknown_path_one_bounded_continuation(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 req=CompletionRequirement('verified_observation',('lab.item.unknown',))
 c,r,records,a,w=execute(tmp_path,mem,[completion(content='uncertain')]*4,req=req)
 assert len(w.requests)==2 and r['control']['state']['recoverability']=='UNKNOWN'

def test_budget_exhaustion_no_extra_calls(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 replies=[completion('retrieve_memory',json.dumps({'query':q,'top_k':1}),call_id=str(i)) for i,q in enumerate(['box','crate','obstacle','elephant'])]
 c,r,records,a,w=execute(tmp_path,mem,replies)
 assert len(w.requests)==4 and r['status']=='STEP_BUDGET_EXHAUSTED' and r['control']['remaining_calls']==0

def test_export_and_recorded_replay_system_termination(tmp_path,monkeypatch):
 from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as f
 from labs.virtual_anima_lab.python.lifecycle.e26_r941_experiments import recorded_trajectory
 mem=memory(tmp_path,monkeypatch)
 from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import CASES,assess
 case=next(c for c in CASES if c['id']=='C01')
 c,r,records,a,w=execute(tmp_path,mem,[lookup(crate_event(mem),'a')],task=case['task'])
 out=tmp_path/'bundle';out.mkdir();raw=f.export_raw(mem,out,7)
 hybrid=build_cognitive_result(c,r,requirement=OBS,research_calls=a.calls)
 aggregate={**assess(case,r,records,a.calls),'variant':'baseline','case':'C01','seed':7,'memory_enabled':True,'task':case['task'],'cognitive_result':hybrid,'information_completion':hybrid['information']['completion']}
 f.export_case(out,7,'C01',r,records,a.calls,raw,result=aggregate)
 fixture=f.read_json(out/'case-7-C01.json');f.verify_case(fixture,raw,require_native=True,require_cognitive_result=True)
 replay=recorded_trajectory(fixture,raw,output=tmp_path/'replay',task=a.task,requirement=OBS,max_steps=4,
   adapter_flags={'temporal':True,'compact_temporal':True,'latest_observation':True,'canonical_sets':True},
   coordinator_flags={'ranked':True,'latest_observation':True},policy_profile='r942/0.1')
 assert replay['status']=='MATCHED'

def test_stale_context_never_admitted(tmp_path,monkeypatch):
 mem=memory(tmp_path,monkeypatch)
 original=mem.context_for_cognition;count=0
 def changing(*args,**kw):
  nonlocal count
  count+=1;view=original(*args,**kw)
  if count>=3:view={**view,'test_scope_changed':True}
  return view
 monkeypatch.setattr(mem,'context_for_cognition',changing)
 c,r,records,a,w=execute(tmp_path,mem,[lookup(crate_event(mem),'a')])
 assert r['status']=='REJECTED' and records[0]['outcome']['reason_code']=='STALE_CONTEXT'

def test_new_turn_status_requires_versioned_host_contract():
 from labs.virtual_anima_lab.python.cognition.turn_status import valid_turn_status
 assert not valid_turn_status({'status':'RESEARCH_TERMINATED'})
 assert not valid_turn_status({'status':'RESEARCH_TERMINATED','control':{'schema':'anima.lab.cognitive_control/0.1','profile':'baseline','reason':'INFORMATION_SUFFICIENT'}})
