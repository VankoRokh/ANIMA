from copy import deepcopy
import json
import pytest
from tests.test_e26_r940_cycle_characterization import memory,crate_event,lookup,search,OBS,TEMPORAL
from tests.test_e26a_native_tools import Fake,completion
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits


def execute(tmp_path,mem,replies,req=OBS,enabled=True,profile='r945/0.1',task='Check captured observations'):
    wire=Fake(*replies)
    adapter=NativeLabAdapter(base_url='http://127.0.0.1:8085',model='test',trace_path=tmp_path/'calls.jsonl',task=task,transport=wire,temporal=True,compact_temporal=True,latest_observation=True,canonical_sets=True)
    coord=E25LabCognitiveCoordinator(mem,ranked=True,latest_observation=True,policy_profile=profile)
    report=coord.run_turn(adapter,turn_id=profile.replace('/','-'),memory_enabled=enabled,completion_requirement=req,resource_limits=ResourceLimits())
    assert mem._core.memory_store.count()==0 and len(mem._core.event_log.load_events())==3
    return coord,report,coord.decision_records(report['turn_id']),adapter,wire


def test_A_model_view_stable_and_lossless():
    from labs.virtual_anima_lab.python.cognition.retrieval_representation import model_search_view
    a={'kind':'working_world_memory_search','strategy':'technical-version-1','records':[{'entity_ref':'lab.item.test'}],'returned':1,'possible_matches':2,'truncated':True,'memory_enabled':True}
    b={**a,'strategy':'technical-version-2'}
    assert model_search_view(a)==model_search_view(b)
    assert a['strategy']=='technical-version-1'
    changed={**b,'records':[],'returned':0}
    assert model_search_view(a)!=model_search_view(changed)


def test_A_fixed_ids_match_old_view_actual_journal_metadata_preserved(tmp_path,monkeypatch):
    mem=memory(tmp_path,monkeypatch);wires=[]
    for profile in ('r942/0.2','r945/0.1'):
        out=tmp_path/profile.replace('/','-');out.mkdir()
        c,r,records,a,w=execute(out,mem,[search('fixed'),lookup(crate_event(mem),'raw')],profile=profile)
        wires.append(w.requests)
        if profile=='r945/0.1':
            outcome=records[0]['outcome'];meta=outcome['retrieval_metadata']
            assert outcome['result']['strategy'].startswith('r943/0.1')
            assert meta['algorithm']=='r943/0.1' and meta['original_query']=='crate'
            assert meta['explanations'][0]['entity_ref']=='lab.item.crate'
            assert json.loads(w.requests[1]['messages'][-1]['content'])['strategy']=='ranked_lexical_not_semantic_retrieval'
    assert wires[0][:2]==wires[1][:2]


def test_A_metadata_mutation_rejected(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.control_policy import verify_control
    mem=memory(tmp_path,monkeypatch)
    _,report,records,_,_=execute(tmp_path,mem,[search(),lookup(crate_event(mem),'raw')])
    verify_control(report,records)
    altered=deepcopy(records);altered[0]['outcome']['retrieval_metadata']['algorithm']='semantic-unapproved'
    altered_report={**report,'outcomes':[r['outcome'] for r in altered]}
    with pytest.raises(ValueError,match='control'):verify_control(altered_report,altered)
