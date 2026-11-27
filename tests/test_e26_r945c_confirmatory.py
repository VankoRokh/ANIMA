"""Confirmatory execution controls; all model replies synthetic."""
from copy import deepcopy
import json
import pytest
from labs.virtual_anima_lab.python.lifecycle import e26_r945c_confirmatory as c
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as f
from tests.test_e26_r945_profile import execute
from tests.test_e26_r940_cycle_characterization import memory,crate_event,lookup,search,completion,OBS
from tests.test_e26a_native_tools import Fake
from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import CASES


def entry(tmp_path,monkeypatch):
    mem=memory(tmp_path/'origin',monkeypatch);event=crate_event(mem);case=next(x for x in CASES if x['id']=='C01')
    out=tmp_path/'source';out.mkdir()
    _,report,records,adapter,_=execute(out,mem,[lookup(event,'archived'),completion(content='done')],profile='baseline',task=case['task'])
    raw=f.export_raw(mem,out,7);f.export_case(out,7,'C01',report,records,adapter.calls,raw)
    cp=out/'case-7-C01.json';rp=out/'raw-seed-7.json';first=adapter.calls[0]
    return {'id':'synthetic','cluster':'C01-7','context_profile':'control','case':'C01','seed':7,'scenario':case,
        'case_path':str(cp),'case_sha256':f.file_digest(cp),'raw_path':str(rp),'raw_sha256':f.file_digest(rp),
        'initial_request':first['request'],'initial_request_sha256':c.h._sha(first['request']),
        'adapter_flags':{'canonical_sets':True,'temporal':True,'compact_temporal':True,'latest_observation':True},
        'host_projection':False,'model':first['request']['model'],'base_url':'http://127.0.0.1:8085'},event


def test_r945_pair_independent_stores_feedback_metadata_and_consumer(tmp_path,monkeypatch):
    e,event=entry(tmp_path,monkeypatch)
    a=c.trajectory(e,'baseline',tmp_path/'A',Fake(search('Asearch'),completion(content='uncertain'),lookup(event,'Araw'),completion(content='done')))
    b=c.trajectory(e,'r945/0.1',tmp_path/'B',Fake(search('Bsearch'),completion(content='uncertain'),lookup(event,'Braw')))
    comparison=c.t.compare(a,b);assert comparison['initial_request_equal']
    assert a['context']==b['context'] and a['raw_sha256']==b['raw_sha256']
    assert b['metrics']['common_completeness']==1 and not b['metrics']['accepted_final']
    assert f.read_json(tmp_path/'B/consumer-check.json')['status']=='CHECKED'
    assert f.read_json(tmp_path/'B/journal.json')[0]['outcome']['retrieval_metadata']['algorithm']=='r943/0.1'
    feedback=json.loads(b['exchanges'][2]['request']['messages'][-1]['content'])
    assert feedback['schema']=='anima.lab.requirement_feedback/0.1' and feedback['checked_operation_prefix']==1
    assert 'Araw' not in json.dumps(b['exchanges']) and 'Braw' not in json.dumps(a['exchanges'])
    assert c.operation_comparison(a,b)['first_operation_or_terminal_divergence']['index']==3


def test_consumer_authority_mutation_rejected(tmp_path,monkeypatch):
    e,event=entry(tmp_path,monkeypatch);c.trajectory(e,'r945/0.1',tmp_path/'B',Fake(lookup(event,'fresh')))
    result=f.read_json(tmp_path/'B/result.json');result['consumer_view']['unverified_model_prose']['authority']='VERIFIED'
    with pytest.raises(ValueError,match='consumer'):c.verify_consumer(result)


def test_legacy_contract_does_not_silently_accept_new_arm(tmp_path,monkeypatch):
    e,_=entry(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='unregistered'):c.t.trajectory(e,'r945/0.1',tmp_path/'bad',Fake())


def test_initial_request_mutation_no_dispatch(tmp_path,monkeypatch):
    e,event=entry(tmp_path,monkeypatch);e['initial_request']=deepcopy(e['initial_request']);e['initial_request']['model']='different'
    wire=Fake(lookup(event,'unused'))
    # Existing native code records a rejected terminal, wire guard withholds reply.
    with pytest.raises(ValueError,match='generation field'):
        c.trajectory(e,'r945/0.1',tmp_path/'bad',wire)
    assert wire.requests==[]
    assert f.read_json(tmp_path/'bad/wire/00-exchange.json')['failure']=='ValueError: INITIAL_REQUEST_MISMATCH'


def test_terminal_incomplete_retained_without_retry(tmp_path,monkeypatch):
    e,event=entry(tmp_path,monkeypatch);reply=lookup(event,'cut');reply['choices'][0]['finish_reason']='length'
    wire=Fake(reply,lookup(event,'unused'));result=c.trajectory(e,'r945/0.1',tmp_path/'cut',wire)
    assert len(wire.requests)==1 and result['metrics']['status']=='REJECTED'
    assert f.read_json(tmp_path/'cut/consumer-check.json')['accepted_research_final'] is False


def test_execution_plan_rejects_resealed_matrix_change(tmp_path,monkeypatch):
    e,_=entry(tmp_path,monkeypatch);entries=[]
    for i in range(28):entries.append({**deepcopy(e),'id':f'context-{i}','cluster':f'cluster-{i//2}'})
    approved={'comparison':c.ARMS,'entries':entries,'repetitions':20,'planned_pairs':560,'planned_trajectories':1120,'maximum_model_calls':4480,
        'order_table':[{'pair':i,'order':['A','B'] if i%2==0 else ['B','A']} for i in range(20)],'concurrency':1,
        'resource_limits':{},'generation_fields':{},'analysis':{},'held_out':{},'primary':[],'strata':[],'ID_policy':'FRESH_ACCEPT_AND_PROPAGATE','stopping':'frozen'}
    path=tmp_path/'approved.json';f.write_json(path,approved);monkeypatch.setattr(c,'APPROVED_SHA',f.file_digest(path));monkeypatch.setattr(f,'git_snapshot',lambda:'1'*40)
    manifest=c.prepare(path,tmp_path/'plan');c.validate(manifest)
    modified=deepcopy(manifest);modified['entries'][0]['scenario']['task']='different'
    with pytest.raises(ValueError,match='approved field'):c.validate(modified)
    modified=deepcopy(manifest);modified['order_table'][0]['order'].reverse()
    with pytest.raises(ValueError,match='approved field'):c.validate(modified)
    assert path.read_bytes()==(tmp_path/'plan/approved-plan.json').read_bytes()


def test_secondary_fact_denominator_and_zero_headroom_gate(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.lifecycle import e26_r945c_analysis as analysis
    e,event=entry(tmp_path,monkeypatch);c.trajectory(e,'r945/0.1',tmp_path/'B',Fake(lookup(event,'fresh')))
    result=f.read_json(tmp_path/'B/result.json');assert analysis.fact_coverage(result)==1
    result=deepcopy(result);result['information']['completion']['requirement']['kind']='no_service_read'
    assert analysis.fact_coverage(result) is None
    interval=analysis.a.interval([0,0]);assert interval['ci95']==[0,0]
    assert not interval['ci95'][1]<0  # frozen reduction gate cannot pass at zero headroom


@pytest.mark.parametrize('body,raises',[(b'{"choices":[]}',False),(b'{broken',True)])
def test_archived_transport_retains_raw_before_decode(tmp_path,body,raises):
    from io import BytesIO
    class Response(BytesIO):
        status=200
    class Opener:
        def open(self,request,timeout):
            assert request.data==b'{"messages":[]}' and timeout==45.0
            return Response(body)
    transport=c.ArchivedLoopbackTransport('http://127.0.0.1:8085',tmp_path/'http');transport._opener=Opener()
    if raises:
        with pytest.raises(ValueError):transport.complete({'messages':[]})
    else:assert transport.complete({'messages':[]})=={'choices':[]}
    assert (tmp_path/'http/00.response').read_bytes()==body
    assert f.read_json(tmp_path/'http/00.json')['status']==200


def test_archived_transport_retains_http_failure_no_retry(tmp_path):
    from io import BytesIO
    import urllib.error
    class Opener:
        calls=0
        def open(self,*args,**kwargs):
            self.calls+=1
            raise urllib.error.HTTPError('http://127.0.0.1:8085',503,'unavailable',{},BytesIO(b'unavailable'))
    transport=c.ArchivedLoopbackTransport('http://127.0.0.1:8085',tmp_path/'http');transport._opener=Opener()
    with pytest.raises(urllib.error.HTTPError):transport.complete({'messages':[]})
    assert transport._opener.calls==1 and (tmp_path/'http/00.response').read_bytes()==b'unavailable'
