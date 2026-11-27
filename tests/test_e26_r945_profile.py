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


def test_B_controlled_F01_productive_bounded_continuation(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
    from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
    import tests.test_e25a_cognition as fixture
    original=fixture.view
    def two_entities(seq,*,visible):
        v=original(seq,visible=visible).as_dict()
        if visible:v['readings'].append({'entity_ref':'lab.obstacle.shortcut','category':'obstacle','bearing_mdeg':0,'range_milli_cells':3000,'properties':{}})
        return fixture.EgocentricView(v)
    monkeypatch.setattr(fixture,'view',two_entities)
    mem=memory(tmp_path,monkeypatch);event=crate_event(mem)
    req=CompletionRequirement('verified_observation',('lab.item.crate','lab.obstacle.shortcut'))
    class Controlled:
        def __init__(self):self.requests=[]
        def complete(self,request):
            self.requests.append(deepcopy(request));index=len(self.requests)-1
            if index==0:return completion('retrieve_memory','{"query":"crate shortcut","top_k":2}',call_id='search')
            if index==1:return completion(content='Search metadata is enough?')
            feedback=json.loads(request['messages'][-1]['content'])
            assert feedback['schema']=='anima.lab.requirement_feedback/0.1'
            assert feedback['lookup_only_prerequisite'] is True
            assert len(feedback['missing_units'])==2 and event in feedback['permitted_visible_event_ids']
            assert feedback['source_read_success']=='NOT_ESTABLISHED_BY_METADATA'
            return lookup(event,'verify')
    wire=Controlled();a=NativeLabAdapter(base_url='http://127.0.0.1:8085',model='test',trace_path=tmp_path/'controlled.jsonl',task='Find and verify previous captured observations',transport=wire,temporal=True,compact_temporal=True,latest_observation=True,canonical_sets=True)
    coord=E25LabCognitiveCoordinator(mem,ranked=True,latest_observation=True,policy_profile='r945/0.1')
    report=coord.run_turn(a,turn_id='productive',completion_requirement=req,resource_limits=ResourceLimits())
    assert len(wire.requests)==3 and report['control']['reason']=='INFORMATION_SUFFICIENT'
    result=build_cognitive_result(coord,report,requirement=req,research_calls=a.calls)
    assert result['information']['status']=='SATISFIED' and len(result['evidence']['facts'])==2
    assert result['presentation']['model_text'] is None


def test_B_repeated_stop_bounded_and_no_future_coverage(tmp_path,monkeypatch):
    mem=memory(tmp_path,monkeypatch)
    c,r,records,a,w=execute(tmp_path,mem,[search(),completion(content='uncertain'),completion(content='still uncertain'),lookup(crate_event(mem),'unused')])
    assert len(w.requests)==3 and r['continuation_decisions'][-1]['decision']=='NO_CONTINUATION_GAIN'
    feedback=json.loads(w.requests[2]['messages'][-1]['content'])
    assert feedback['checked_operation_prefix']==1 and feedback['verified_primary_source_rows']==0
    assert feedback['remaining_budget']['model_calls']==2
    assert feedback['missing_units']==[{'kind':'verified_primary_observation','entity_ref':'lab.item.crate','required_operation':'lookup_raw_evidence'}]


@pytest.mark.parametrize('enabled',[False,True])
def test_B_feedback_filters_nonvisible_and_policy_disabled_sources(tmp_path,monkeypatch,enabled):
    from labs.virtual_anima_lab.python.cognition.requirement_feedback import build_feedback
    from dataclasses import asdict
    mem=memory(tmp_path,monkeypatch);ctx=mem.context_for_cognition(memory_enabled=enabled)
    ctx['context_snapshot_id']='ctx_test';event=crate_event(mem)
    latest=next(row['last_seen_event_id'] for row in ctx['entities'] if row['last_seen_sample']==ctx['latest_sample_id'])
    budget={'limits':asdict(ResourceLimits()),'reserved_calls':2,'reported_input_tokens':100,'reported_output_tokens':10,'elapsed_ms':20}
    visible={event,'ev_forged'} if enabled else {event,latest,'ev_forged'}
    feedback=build_feedback(OBS,ctx,[],visible,budget,2)
    expected=[event] if enabled else [latest]
    assert feedback['permitted_visible_event_ids']==expected
    assert 'ev_forged' not in json.dumps(feedback)
    if not enabled:assert event not in json.dumps(feedback)


def test_B_unknown_path_does_not_invent_source(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.requirement_feedback import build_feedback
    from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
    from dataclasses import asdict
    mem=memory(tmp_path,monkeypatch);ctx=mem.context_for_cognition();ctx['context_snapshot_id']='ctx_test'
    budget={'limits':asdict(ResourceLimits()),'reserved_calls':1,'reported_input_tokens':10,'reported_output_tokens':4,'elapsed_ms':1}
    f=build_feedback(CompletionRequirement('verified_observation',('lab.unknown',)),ctx,[],set(),budget,3)
    assert f['availability']['missing_units_recoverability']=='UNKNOWN' and f['permitted_visible_event_ids']==[]


def test_B_feedback_fits_existing_limit_without_fabricating_coverage(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.requirement_feedback import build_feedback
    from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
    from anima.agent.native_tools import canonical
    from dataclasses import asdict
    mem=memory(tmp_path,monkeypatch);ctx=mem.context_for_cognition();ctx['context_snapshot_id']='ctx_test'
    req=CompletionRequirement('verified_observation',tuple('lab.unknown.'+str(i)+'x'*250 for i in range(20)))
    budget={'limits':asdict(ResourceLimits()),'reserved_calls':1,'reported_input_tokens':10,'reported_output_tokens':4,'elapsed_ms':1}
    f=build_feedback(req,ctx,[],set(),budget,3)
    assert len(canonical(f).encode())<=2048 and f['missing_units_truncated']
    assert f['missing_units_total']==20 and f['checked_coverage']['covered_units']==0
    assert 'elapsed_ms_boundary_only' not in f['remaining_budget']


def test_D_incomplete_accepted_prose_not_global_knowledge(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
    mem=memory(tmp_path,monkeypatch)
    c,r,records,a,w=execute(tmp_path,mem,[search(),completion(content='They are absent and verified.'),completion(content='All verified.')])
    result=build_cognitive_result(c,r,requirement=OBS,research_calls=a.calls,claim_phase='claim_projection')
    view=result['consumer_view']
    assert view['schema']=='anima.lab.verified_presentation/0.1'
    assert view['information']['status']=='INCOMPLETE' and view['verified_facts']==[]
    assert view['information']['missing_units'][0]['required_operation']=='lookup_raw_evidence'
    assert view['accepted_research_final']['status']=='ACCEPTED_PROTOCOL_FINAL'
    assert view['unverified_model_prose']['research']=='All verified.'
    assert view['projection']['accepted_final_status']=='NO_ACCEPTED_PROJECTION_FINAL'
    assert view['global_verification']=='NOT_ESTABLISHED' and view['task_completion']=='NOT_ESTABLISHED'


def test_D_system_termination_keeps_facts_without_fake_final(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
    mem=memory(tmp_path,monkeypatch)
    c,r,records,a,w=execute(tmp_path,mem,[lookup(crate_event(mem),'one')])
    view=build_cognitive_result(c,r,requirement=OBS,research_calls=a.calls)['consumer_view']
    assert view['verified_facts'] and view['information']['status']=='SATISFIED'
    assert view['accepted_research_final']['status']=='NO_ACCEPTED_RESEARCH_FINAL'
    assert view['unverified_model_prose']['research'] is None
    assert view['verified_facts'][0]['verdict']['claim']['scope']=='source_sample'


def test_D_partial_facts_preserved_after_incomplete_generation(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
    mem=memory(tmp_path,monkeypatch);cut=completion(content='cut');cut['choices'][0]['finish_reason']='length'
    c,r,records,a,w=execute(tmp_path,mem,[lookup(crate_event(mem),'hist'),cut],req=TEMPORAL)
    result=build_cognitive_result(c,r,requirement=TEMPORAL,research_calls=a.calls)
    assert len(w.requests)==2 and result['consumer_view']['verified_facts']
    assert result['consumer_view']['information']['status']=='INCOMPLETE'
    assert result['consumer_view']['unverified_model_prose']['research'] is None


def test_D_new_profile_export_reconstruction_and_exact_replay(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as f
    from labs.virtual_anima_lab.python.lifecycle.e26_r941_experiments import recorded_trajectory
    from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import CASES
    from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
    case=next(c for c in CASES if c['id']=='C01');mem=memory(tmp_path,monkeypatch)
    c,r,records,a,w=execute(tmp_path,mem,[search(),completion(content='uncertain'),lookup(crate_event(mem),'raw')],task=case['task'])
    result=build_cognitive_result(c,r,requirement=OBS,research_calls=a.calls,claim_phase='claim_projection')
    aggregate={'variant':'temporal_completion','case':'C01','seed':7,'memory_enabled':True,'task':case['task'],
               'model_calls':len(a.calls),'total_model_calls':len(a.calls),'turn_status':r['status'],
               'cognitive_result':result,'information_completion':result['information']['completion'],'model_claims':result['evidence']['model_claims']['evaluation']}
    out=tmp_path/'bundle';out.mkdir();raw=f.export_raw(mem,out,7)
    f.export_case(out,7,'C01',r,records,a.calls,raw,result=aggregate)
    fixture=f.read_json(out/'case-7-C01.json');f.verify_case(fixture,raw,require_native=True,require_cognitive_result=True)
    replay=recorded_trajectory(fixture,raw,output=tmp_path/'replay',task=case['task'],requirement=OBS,max_steps=4,
        adapter_flags={'canonical_sets':True,'temporal':True,'compact_temporal':True,'latest_observation':True},
        coordinator_flags={'ranked':True,'latest_observation':True},claim_phase='claim_projection',policy_profile='r945/0.1')
    assert replay['status']=='MATCHED' and replay['matched_requests']==3
    forged=deepcopy(fixture);forged['result']['cognitive_result']['consumer_view']['global_verification']='VERIFIED'
    with pytest.raises(ValueError,match='reconstruction'):f.verify_case(forged,raw,require_cognitive_result=True)


def _existing_contract_cases():
    # Reuse historical assertions unchanged, selecting the new profile only
    # in a test-local constructor. Includes native normalization and source faults.
    import tests.test_e26_r942_policy as contracts
    for name,fn in vars(contracts).items():
        if not name.startswith('test_'):continue
        marks=[m for m in getattr(fn,'pytestmark',[]) if m.name=='parametrize']
        if not marks:yield pytest.param(name,{},id=name)
        else:
            assert len(marks)==1
            names=marks[0].args[0].split(',')
            for value in marks[0].args[1]:
                values=(value,) if len(names)==1 else value
                yield pytest.param(name,dict(zip(names,values)),id=name+'-'+str(value))


@pytest.mark.parametrize('name,arguments',list(_existing_contract_cases()))
def test_r945_existing_safety_contracts(tmp_path,monkeypatch,name,arguments):
    import inspect
    import tests.test_e26_r942_policy as contracts
    original=E25LabCognitiveCoordinator.__init__
    def select(self,*args,**kwargs):
        if kwargs.get('policy_profile')=='r942/0.1':kwargs['policy_profile']='r945/0.1'
        original(self,*args,**kwargs)
    monkeypatch.setattr(E25LabCognitiveCoordinator,'__init__',select)
    fn=getattr(contracts,name);fixtures={'tmp_path':tmp_path,'monkeypatch':monkeypatch}
    fn(**{k:fixtures[k] for k in inspect.signature(fn).parameters if k in fixtures},**arguments)


def test_no_evaluator_dependency_in_new_runtime_contracts():
    from pathlib import Path
    root=Path('labs/virtual_anima_lab/python/cognition')
    for name in ('retrieval_representation.py','requirement_feedback.py','verified_presentation.py'):
        source=(root/name).read_text()
        assert 'CASES' not in source and 'evaluator' not in source and 'held-out' not in source


@pytest.mark.parametrize('profile,should_continue',[('r943/0.1',False),('r945/0.1',True)])
def test_feedback_uses_current_profile_coverage_and_preserves_legacy(tmp_path,monkeypatch,profile,should_continue):
    from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
    mem=memory(tmp_path,monkeypatch)
    replies=[completion('retrieve_memory','{"query":"sscrate","top_k":1}',call_id='ss'),completion(content='done'),
             completion('retrieve_memory','{"query":"ßcrate","top_k":1}',call_id='eszett'),completion(content='uncertain')]
    _,r,records,a,w=execute(tmp_path,mem,replies,req=CompletionRequirement('empty_search',query='ßcrate'),profile=profile)
    assert bool(r['continuation_decisions']) is should_continue
    assert r['control']['state']['completion']['information_requirement_satisfied'] is False
    if should_continue:
        feedback=json.loads(w.requests[2]['messages'][-1]['content'])
        assert feedback['missing_units']==[{'kind':'bounded_empty_search','query':'ßcrate'}]
