from copy import deepcopy
import json
import pytest
from tests.test_e26_r942_policy import execute
from tests.test_e26_r940_cycle_characterization import memory,crate_event,lookup,OBS
from labs.virtual_anima_lab.python.cognition import control_policy as c
from labs.virtual_anima_lab.python.cognition.coordinator import _rank_memory_matches
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as f

def test_r01_casefold_collision():
 from labs.virtual_anima_lab.python.cognition.retrieval_policy import query_key
 assert query_key('ßcrate')!=query_key('sscrate')
 assert query_key(' CRATE ')==query_key('crate')

@pytest.mark.parametrize('mutation',['sufficient','redundant','unavailable','state'])
def test_r02_resealed_control_negatives(tmp_path,monkeypatch,mutation):
 mem=memory(tmp_path,monkeypatch)
 coord,report,records,adapter,wire=execute(tmp_path,mem,[lookup(crate_event(mem),'a')])
 out=tmp_path/'bundle';out.mkdir();raw=f.export_raw(mem,out,7)
 f.export_case(out,7,'C01',report,records,adapter.calls,raw)
 fixture=f.read_json(out/'case-7-C01.json')
 if mutation=='sufficient':
  from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
  fixture['turn']['control']['state']=c.state(CompletionRequirement('verified_observation',('lab.item.unseen',)),records[0]['context_snapshot'],records)
 elif mutation=='redundant':fixture['turn']['control']['reason']='REDUNDANT_OPERATION'
 elif mutation=='unavailable':fixture['turn']['control']['reason']='SOURCE_UNAVAILABLE'
 else:fixture['turn']['control']['state']['gain_key']=[999,999,999]
 # Reseal bytes/checksums, so rejection must be semantic, not hash mismatch.
 (out/'case-7-C01.json').write_text(f.canonical(fixture)+'\n')
 f.seal_bundle(out,{'schema':f.SCHEMA,'git_sha':'a'*40,'world_seeds':[7],'scenarios':[{'id':'C01'}]},complete=True)
 with pytest.raises(ValueError,match='control'):
  f.verify_bundle(out)

def test_new_ranking_exact_and_multi_terms():
 from labs.virtual_anima_lab.python.cognition.retrieval_policy import rank
 rows=[{'entity_ref':'lab.obstacle.aaa'},{'entity_ref':'lab.obstacle.shortcut'}]
 assert rank(rows,'obstacle shortcut')[0]['entity_ref']=='lab.obstacle.shortcut'
 assert rank(rows,'lab.obstacle.shortcut')[0]['entity_ref']=='lab.obstacle.shortcut'
 # Frozen category tie: prefer a whole distinctive terminal token, rather
 # than repeated-letter opaque suffix; lexical fallback remains explicit.
 assert rank(rows,'obstacle')[0]['entity_ref']=='lab.obstacle.shortcut'
 assert _rank_memory_matches(rows,'obstacle')[0]['entity_ref']=='lab.obstacle.aaa'

def test_r01_actual_search_semantics(tmp_path,monkeypatch):
 from labs.virtual_anima_lab.python.cognition.coordinator import _read_only_result
 mem=memory(tmp_path,monkeypatch)
 assert _read_only_result(mem,kind='retrieve_memory',args={'query':'ßcrate','top_k':1},memory_enabled=True,ranked=True)['returned']==1
 assert _read_only_result(mem,kind='retrieve_memory',args={'query':'sscrate','top_k':1},memory_enabled=True,ranked=True)['returned']==0
 view={'completed_operations':[['retrieve_memory',{'query':'ßcrate','top_k':1}]]}
 proposal={'operation_kind':'retrieve_memory','arguments':{'query':'sscrate','top_k':1}}
 assert c.redundant(OBS,{},view,proposal,profile='r942/0.1')
 assert not c.redundant(OBS,{},view,proposal,profile='r942/0.2')

@pytest.mark.parametrize('enabled',[False,True])
def test_profile_scope_and_metadata(tmp_path,monkeypatch,enabled):
 from labs.virtual_anima_lab.python.cognition.coordinator import _read_only_result
 mem=memory(tmp_path,monkeypatch)
 result=_read_only_result(mem,kind='retrieve_memory',args={'query':'crate','top_k':1},memory_enabled=enabled,retrieval_profile='r943/0.1')
 assert result['returned']==int(enabled)
 assert result['strategy'].startswith('r943/0.1')
 assert result['possible_matches']>=result['returned']
 if enabled:assert result['records'][0]['last_seen_event_id']==crate_event(mem)

def test_runtime_never_imports_evaluator():
 from pathlib import Path
 for name in ('retrieval_policy.py','control_policy.py'):
  text=Path('labs/virtual_anima_lab/python/cognition',name).read_text()
  assert 'evaluator' not in text and 'held-out' not in text

def test_profiles_on_identical_frozen_raw_and_requests(tmp_path,monkeypatch):
 from labs.virtual_anima_lab.python.lifecycle.e26_r941_experiments import rebuild_raw
 from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
 from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
 from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
 from labs.virtual_anima_lab.python.cognition.completion import evaluate_completion
 from tests.test_e26a_native_tools import Fake
 from pathlib import Path
 origin=memory(tmp_path/'origin',monkeypatch)
 raw=f.export_raw(origin,tmp_path/'origin',7)
 stats={};requests=[]
 for profile in ('baseline','r943/0.1'):
  mem=rebuild_raw(raw,tmp_path/profile/'stores')
  event=next(e['last_seen_event_id'] for e in mem.world_model()['entities'] if e['entity_ref']=='lab.item.crate')
  wire=Fake(*[lookup(event,str(i)) for i in range(4)])
  adapter=NativeLabAdapter(base_url='http://127.0.0.1:8085',model='test',trace_path=tmp_path/profile/'calls.jsonl',task='Verify crate',transport=wire,temporal=True,compact_temporal=True,latest_observation=True)
  coord=E25LabCognitiveCoordinator(mem,ranked=True,latest_observation=True,policy_profile=profile)
  report=coord.run_turn(adapter,turn_id='paired',completion_requirement=OBS,resource_limits=ResourceLimits())
  records=coord.decision_records('paired')
  from labs.virtual_anima_lab.python.cognition.source_binding import admitted_source_rows
  rows=[r for rec in records for r in admitted_source_rows(rec)]
  stats[profile]={'completed':len(records),'redundant_acquisition':len(rows)-len({r['event_id'] for r in rows}),
     'completeness':evaluate_completion(OBS,report,records)['information_requirement_satisfied']}
  requests.append(wire.requests[0])
 assert requests[0]==requests[1]
 assert stats['baseline']['redundant_acquisition']==3 and stats['r943/0.1']['redundant_acquisition']==0
 assert stats['baseline']['completeness'] and stats['r943/0.1']['completeness']
 (tmp_path/'paired-metrics.json').write_text(json.dumps(stats))


def test_r01_empty_search_requirement_uses_profile_query_semantics(tmp_path,monkeypatch):
 from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement,evaluate_completion
 from tests.test_e26a_native_tools import completion
 mem=memory(tmp_path,monkeypatch)
 _,report,records,_,_=execute(tmp_path,mem,[completion('retrieve_memory','{"query":"sscrate","top_k":1}',call_id='empty'),completion(content='done')],req=CompletionRequirement('empty_search',query='sscrate'))
 req=CompletionRequirement('empty_search',query='ßcrate')
 assert evaluate_completion(req,report,records)['information_requirement_satisfied']
 for profile in ('r942/0.2','r943/0.1'):
  versioned={**report,'control':{**report['control'],'profile':profile}}
  assert not evaluate_completion(req,versioned,records)['information_requirement_satisfied']
  assert not c.state(req,records[0]['context_snapshot'],records,profile)['completion']['information_requirement_satisfied']
