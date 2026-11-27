"""Isolated T-fresh controls; every model reply is synthetic."""
from copy import deepcopy
import json
import pytest
from labs.virtual_anima_lab.python.lifecycle import e26_r944_fresh as t
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as f
from tests.test_e26_r940_cycle_characterization import memory,run,crate_event,lookup,completion,OBS
from tests.test_e26a_native_tools import Fake


def entry(tmp_path,monkeypatch):
    mem=memory(tmp_path/'origin',monkeypatch);event=crate_event(mem)
    coord,report,records,adapter,_=run(mem,tmp_path,[lookup(event,'archived'),completion(content='done')])
    root=tmp_path/'fixture';root.mkdir();raw=f.export_raw(mem,root,7)
    f.export_case(root,7,'C01',report,records,adapter.calls,raw)
    cp=root/'case-7-C01.json';rp=root/'raw-seed-7.json';first=adapter.calls[0]
    e={'id':'synthetic-7-C01','cluster':'C01-7','context_profile':'control','seed':7,'case':'C01',
       'case_path':str(cp),'case_sha256':f.file_digest(cp),'raw_path':str(rp),'raw_sha256':f.file_digest(rp),
       'scenario':{'id':'C01','kind':'positive','targets':['lab.item.crate'],'enabled':True,'task':'Check captured crate observations'},
       'initial_request':first['request'],'initial_request_sha256':t.h._sha(first['request']),
       'adapter_flags':{k:first[k] for k in ('canonical_sets','temporal','compact_temporal','error_feedback')},
       'host_projection':False,'base_url':'http://127.0.0.1:8085','model':first['request']['model']}
    e['adapter_flags'].update(model_claims=False,latest_observation=True)
    return e,event


def test_independent_arms_fresh_ids_and_system_finish(tmp_path,monkeypatch):
    e,event=entry(tmp_path,monkeypatch)
    a=t.trajectory(e,'baseline',tmp_path/'a',Fake(lookup(event,'fresh-A'),completion(content='done'),completion(content='{"claims":[]}')))
    b=t.trajectory(e,'r943/0.1',tmp_path/'b',Fake(lookup(event,'fresh-B')))
    assert a['context']==b['context'] and a['raw_sha256']==b['raw_sha256']
    assert a['metrics']['common_completeness']==b['metrics']['common_completeness']==1
    assert b['metrics']['status']=='RESEARCH_TERMINATED' and not b['metrics']['accepted_final']
    assert b['metrics']['presentation']['model_text'] is None
    assert a['exchanges'][1]['request']['messages'][-1]['tool_call_id']=='fresh-A'
    assert b['exchanges'][0]['response']['choices'][0]['message']['tool_calls'][0]['id']=='fresh-B'
    comparison=t.compare(a,b)
    assert comparison['initial_request_equal']
    assert comparison['first_divergence']['index']==1
    assert comparison['first_exact_divergence']['index']==0
    assert 'fresh-B' not in json.dumps(a['exchanges'])
    assert 'fresh-A' not in json.dumps(b['exchanges'])
    # Both isolated derived stores have own traces; owner fixture is unchanged.
    assert f.file_digest(e['case_path'])==e['case_sha256']


@pytest.mark.parametrize('mode',['initial','backend','transport'])
def test_predispatch_failure_never_delivers_archived_reply(tmp_path,mode):
    source=Fake(completion(content='fresh'));expected={'model':'test'}
    def check():
        if mode=='backend':raise ValueError('backend changed')
    class Broken:
        def complete(self,request):raise ConnectionError('transport down')
    wire=t.FreshTransport(Broken() if mode=='transport' else source,tmp_path/'wire',expected,check)
    with pytest.raises((ValueError,ConnectionError)):
        wire.complete({'model':'wrong'} if mode=='initial' else expected)
    assert len(wire.exchanges)==len(wire.failures)==1
    assert not (tmp_path/'wire/00-response.json').exists()
    assert source.requests==[]


def test_received_response_retained_on_backend_change(tmp_path):
    n=0
    def check():
        nonlocal n
        n+=1
        if n==2:raise ValueError('changed after receive')
    wire=t.FreshTransport(Fake(completion(content='received')),tmp_path/'wire',{},check)
    with pytest.raises(ValueError):wire.complete({})
    assert (tmp_path/'wire/00-response.json').exists()
    assert wire.exchanges[0]['response']['choices'][0]['message']['content']=='received'


def test_incomplete_no_retry_partial_evidence_retained(tmp_path,monkeypatch):
    e,event=entry(tmp_path,monkeypatch)
    reply=lookup(event,'cut');reply['choices'][0]['finish_reason']='length'
    result=t.trajectory(e,'r943/0.1',tmp_path/'rejected',Fake(reply,lookup(event,'unused')))
    assert result['metrics']['model_calls']==1
    assert result['metrics']['common_completeness']==0
    assert result['metrics']['status']=='REJECTED'


def test_changed_frozen_bytes_rejected_before_transport(tmp_path,monkeypatch):
    e,_=entry(tmp_path,monkeypatch);source=Fake()
    e['raw_sha256']='0'*64
    with pytest.raises(ValueError,match='frozen'):t.trajectory(e,'baseline',tmp_path/'bad',source)
    assert source.requests==[]


def test_pair_initial_state_mismatch_is_not_matched():
    a={'exchanges':[],'context':{'epoch':1},'readonly':{}}
    b={**a,'context':{'epoch':2}}
    with pytest.raises(ValueError,match='INITIAL_STATE'):t.compare(a,b)


def test_labels_never_loaded_in_runtime_runner():
    from pathlib import Path
    source=Path(t.__file__).read_text()
    assert 'evaluator-only-labels' not in source
    assert "['expected']" not in source


def test_partial_verified_facts_survive_incomplete_final(tmp_path,monkeypatch):
    e,event=entry(tmp_path,monkeypatch)
    cut=completion(content='unfinished');cut['choices'][0]['finish_reason']='length'
    result=t.trajectory(e,'baseline',tmp_path/'partial',Fake(lookup(event,'raw'),cut))
    assert result['metrics']['model_calls']==2
    assert result['metrics']['common_completeness']==1
    assert result['metrics']['verified_fact_count']>0
    assert not result['metrics']['accepted_final']
    assert result['metrics']['presentation']['model_text'] is None


def test_nested_clusters_equal_weight_not_independent_contexts():
    from labs.virtual_anima_lab.python.lifecycle.e26_r944_analysis import cluster_differences,interval
    def row(cluster,context,delta):
        return {'cluster':cluster,'scenario':context,'arms':{'A':{'x':0},'B':{'x':delta}}}
    rows=[row('one','control',1)]*20+[row('one','host',-1)]*20+[row('two','control',0)]*20
    assert cluster_differences(rows,'x')==[0,0]
    result=interval(cluster_differences(rows,'x'))
    assert result['clusters']==2 and result['ci95']==[0,0]
    assert interval([]) is None


@pytest.mark.parametrize('response',[{'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':1}},[{'bad':'response'}]])
def test_malformed_terminal_is_preserved_not_harness_crash(tmp_path,monkeypatch,response):
    e,_=entry(tmp_path,monkeypatch)
    result=t.trajectory(e,'r943/0.1',tmp_path/'malformed',Fake(response))
    assert result['metrics']['model_calls']==1
    assert result['metrics']['status'] in ('REJECTED','STEP_BUDGET_EXHAUSTED')
    assert result['exchanges'][0]['response']==response
    assert result['metrics']['terminal_calls'][0]['valid'] is False


def test_policy_outcome_divergence_precedes_next_request():
    response=completion(content='same')
    exchange={'request':{},'request_sha256':t.h._sha({}),'response':response,'response_sha256':t.h._sha(response)}
    a={'exchanges':[exchange],'context':{},'readonly':{},'journals_by_call':{1:[{'status':'COMPLETED'}]}}
    b={**a,'journals_by_call':{1:[{'status':'REJECTED'}]}}
    result=t.compare(a,b)
    assert result['matched_decision_prefix']==0
    assert result['first_divergence']=={'index':0,'kind':'JOURNAL_OUTCOME','a_request':t.h._sha({}),'b_request':t.h._sha({})}
