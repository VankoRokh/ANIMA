"""R9.4.4 experimental trajectories. No policy, prompt or tool authority.

Frozen task/requirement scopes only; labels are never loaded here. Independent
Raw restoration per arm, original native IDs propagated by the existing stack.
"""
from copy import deepcopy
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import time

from anima.agent.native_tools import LoopbackChatTransport
from . import e26_reproducibility as f
from . import e26_r941_experiments as h
from .e26b_cognitive_suite import information_requirement
from ..cognition.coordinator import E25LabCognitiveCoordinator
from ..cognition.native_lab import NativeLabAdapter
from ..cognition.resource_budget import ResourceLimits
from ..cognition.cognitive_result import build_cognitive_result
from ..cognition.host_temporal_projection import project_temporal_claims
from ..cognition.completion import evaluate_completion
from ..cognition.observable import measure_turn, _coverage

SCHEMA='anima.lab.r944_fresh/0.1'
BASELINE='15be9a55f7d18eec289d177d2008f4eccb190079'
PROFILES={'A':'baseline','B':'r943/0.1'}


def prepare(plans,held_out,output):
    root=h._new_output(output);entries=[];inputs={}
    for path in plans:
        path=Path(path);plan=f.read_json(path);f.verify_bundle(plan['bundle'])
        inputs[str(path.resolve())]=f.file_digest(path)
        manifest=plan['archived_manifest']
        if manifest['variant']!='temporal_completion' or manifest['max_steps']!=4:
            raise ValueError('unsupported frozen profile')
        context_profile='host' if manifest.get('host_temporal_projection') else 'control'
        for source in plan['entries']:
            fixture=f.read_json(source['case_path']);raw=f.read_json(source['raw_path'])
            for kind in ('case','raw'):
                if f.file_digest(source[kind+'_path'])!=source[kind+'_sha256']:raise ValueError('changed frozen input')
            f.verify_case(fixture,raw)
            first=fixture['model_calls'][0]
            entry={k:deepcopy(source[k]) for k in ('case','seed','scenario','case_path','case_sha256','raw_path','raw_sha256')}
            entry.update(id=f"{context_profile}-{source['seed']}-{source['case']}",cluster=f"{source['case']}-{source['seed']}",context_profile=context_profile,
                initial_request=first['request'],initial_request_sha256=h._sha(first['request']),
                adapter_flags={**{k:first[k] for k in ('canonical_sets','temporal','compact_temporal','error_feedback')},'model_claims':False,'latest_observation':True},
                host_projection=bool(manifest.get('host_temporal_projection') and source['case']=='C06'),
                base_url=manifest['base_url'],model=manifest['model_alias'])
            entries.append(entry)
    if len(entries)!=28 or len({e['cluster'] for e in entries})!=14:raise ValueError('compatibility matrix must contain 28 contexts / 14 clusters')
    held=f.read_json(held_out);inputs[str(Path(held_out).resolve())]=f.file_digest(held_out)
    result={'schema':SCHEMA,'stage':'R9.4.4','baseline':BASELINE,'arms':PROFILES,'diagnostic_arm':'NOT_SELECTED',
        'id_policy':'FRESH_ACCEPT_AND_PROPAGATE','frozen_inputs':inputs,'entries':entries,'repetitions':20,
        'order_table':[{'pair':i,'order':['A','B'] if i%2==0 else ['B','A']} for i in range(20)],
        'concurrency':1,'planned_pairs':560,'planned_trajectories':1120,'maximum_model_calls':4480,
        'resource_limits':asdict(ResourceLimits()),'generation_fields':{k:entries[0]['initial_request'][k] for k in ('temperature','max_tokens','parallel_tool_calls','chat_template_kwargs')},
        'held_out':{'inputs':held,'fresh_status':'UNSUPPORTED_NO_FROZEN_TASK_AND_COMPLETION_REQUIREMENT','supported':'OFFLINE_RETRIEVAL_AND_SYNTHETIC_FAULTS_ONLY'},
        'primary':['common_completeness','redundant_acquisition_rows','post_sufficiency_research_calls'],
        'availability_strata':['MEMORY_ON','MEMORY_OFF','NO_SERVICE_REQUIREMENT'],
        'analysis':{'cluster':'template_seed; Control/Host nested, equal weight per context and scenario','resamples':10000,'seed':940,'percentiles':[2.5,97.5],'completeness_margin':0,
            'non_regression':'lower CI >= 0 in each availability stratum','reduction':'upper CI < 0 for redundancy AND post-sufficiency in >=1 same predeclared stratum','model_calls':'median total B <= A','unknown_backend_or_insufficient_basis':'INCONCLUSIVE'},
        'stopping':'no retries/reruns; stop series on transport/config change, safety violation or harness defect; terminal rejections/incomplete/budget exhaustion retained; all planned denominators retained',
        'presentation':'accepted final separate; no semantic prose quality claim',
        'labels':'offline only; no additional tasks/hints or request fields'}
    f.write_json(root/'manifest.json',result)
    return result


def requirement(entry):
    case=entry['scenario'];return information_requirement({**case,'targets':tuple(case.get('targets',()))},temporal_completion=True)


def backend_check(pid,expected,model_sha,model_stat=None):
    actual=f.backend_snapshot(pid)
    if any(actual[k]!=expected[k] for k in ('pid','process_start_ticks','executable_sha256','argv')):
        raise ValueError('INVALID_PAIR: backend changed')
    argv=actual['argv']
    if '-m' not in argv:raise ValueError('INVALID_PAIR: missing model')
    path=Path(argv[argv.index('-m')+1]);stat=path.stat()
    actual_stat={k:getattr(stat,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')}
    if model_stat is not None:
        if actual_stat!=model_stat:raise ValueError('INVALID_PAIR: model stat changed')
    elif f.file_digest(path)!=model_sha:raise ValueError('INVALID_PAIR: model hash changed')
    return actual


class FreshTransport:
    """Append-only wire evidence, including failures before adapter handling."""
    def __init__(self,transport,output,initial,check=lambda:None):
        self.transport=transport;self.root=Path(output);self.root.mkdir();self.initial=initial;self.check=check
        self.exchanges=[];self.failures=[]
    def complete(self,request):
        index=len(self.exchanges);row={'index':index,'request':deepcopy(request),'request_sha256':h._sha(request),'monotonic_start':time.monotonic()}
        self.exchanges.append(row);f.write_json(self.root/f'{index:02}-request.json',row)
        try:
            if index==0 and request!=self.initial:raise ValueError('INITIAL_REQUEST_MISMATCH')
            self.check()
            row['dispatch_started']=True
            started=time.perf_counter();response=self.transport.complete(request)
            row.update(response=deepcopy(response),response_sha256=h._sha(response),latency_ms=(time.perf_counter()-started)*1000)
            # Persist the received response BEFORE checking backend stability.
            f.write_json(self.root/f'{index:02}-response.json',row)
            self.check()
            return response
        except Exception as error:
            row.update(failure=type(error).__name__+': '+str(error));self.failures.append(row['failure'])
            raise
        finally:
            row['monotonic_end']=time.monotonic();f.write_json(self.root/f'{index:02}-exchange.json',row)


def _readonly(memory):
    return {'events':h._sha(memory._core.event_log.load_events()),'knowledge_count':memory._core.memory_store.count(),'execution':memory._core.core_execution}


def terminal_call(call):
    response=call.get('raw_response');choices=response.get('choices') if isinstance(response,dict) else None
    choice=choices[0] if isinstance(choices,list) and choices and isinstance(choices[0],dict) else {}
    return {'valid':call.get('valid'),'finish_reason':choice.get('finish_reason'),
            'input_tokens':call.get('input_tokens'),'output_tokens':call.get('output_tokens')}


def decision_signature(response):
    try:return h.response_signature(response)
    except (AttributeError,TypeError,ValueError,IndexError):return {'unparseable_response_sha256':h._sha(response)}


def trajectory(entry,profile,output,transport,*,check=lambda:None,experiment_contract=SCHEMA,measurement_baseline=BASELINE):
    # Legacy calls retain the original profiles and serialized artifacts.
    if experiment_contract==SCHEMA:allowed=tuple(PROFILES.values())
    elif experiment_contract=='anima.lab.r945c_execution/0.1':allowed=('baseline','r945/0.1')
    else:raise ValueError('unknown experimental contract')
    if profile not in allowed:raise ValueError('unregistered arm')
    root=h._new_output(output)
    for kind in ('case','raw'):
        if f.file_digest(entry[kind+'_path'])!=entry[kind+'_sha256']:raise ValueError('frozen source changed')
    fixture=f.read_json(entry['case_path']);raw=f.read_json(entry['raw_path']);f.verify_case(fixture,raw)
    memory=h.rebuild_raw(raw,root/'stores');before=_readonly(memory)
    enabled=entry['scenario']['enabled'];base=memory.context_for_cognition(memory_enabled=enabled)
    context={**base,'context_snapshot_id':'ctx_'+h._sha(base)}
    if fixture['trace'] and context!=fixture['trace'][0]['context_snapshot']:raise ValueError('frozen Context mismatch')
    f.write_json(root/'initial-state.json',{'context':context,'readonly':before,'raw_sha256':entry['raw_sha256'],'source_identity_policy':'EXACT_PRESERVE'})
    wire=FreshTransport(transport,root/'wire',entry['initial_request'],check)
    adapter=NativeLabAdapter(base_url=entry['base_url'],model=entry['model'],trace_path=root/'calls.jsonl',task=entry['scenario']['task'],transport=wire,**entry['adapter_flags'])
    coord=E25LabCognitiveCoordinator(memory,max_steps=4,ranked=True,error_feedback=True,latest_observation=True,policy_profile=profile)
    req=requirement(entry);turn=fixture['turn']['turn_id']
    # Instrument successful service/verification I/O separately from offline costs.
    try:
        with h.verification_cost(memory) as (cost,stack):
            stack[-1]='runtime_service_and_policy_verification'
            report=coord.run_turn(adapter,turn_id=turn,memory_enabled=enabled,completion_requirement=req,resource_limits=ResourceLimits(),project_result_claims=not entry['host_projection'])
            records=coord.decision_records(turn)
            f.write_json(root/'research-turn.json',report);f.write_json(root/'journal.json',records)
            if entry['host_projection']:
                stack[-1]='host_projection';report['host_temporal_projection']=project_temporal_claims(coord,req,report)
                report['claim_projection']={'status':'NOT_REQUESTED_HOST_PROFILE','call':None}
            stack[-1]='result_construction'
            result=build_cognitive_result(coord,report,requirement=req,research_calls=adapter.calls,claim_phase='claim_projection')
            f.write_json(root/'result.json',result);f.write_json(root/'turn.json',report)
            all_calls=adapter.calls+([report['claim_projection']['call']] if report.get('claim_projection',{}).get('call') is not None else [])
            stack[-1]='offline_measurement'
            measured=measure_turn(coord,report,baseline_sha=measurement_baseline,case_id=entry['id'],requirement=req,calls=all_calls,frozen_context=context,claim_phase='claim_projection')
            f.write_json(root/'observable.json',measured)
            stack[-1]='offline_export_verification'
            aggregate=None
            if experiment_contract=='anima.lab.r945c_execution/0.1':
                aggregate={'variant':'temporal_completion','case':entry['case'],'seed':entry['seed'],
                    'memory_enabled':enabled,'task':entry['scenario']['task'],'model_calls':len(adapter.calls),
                    'total_model_calls':len(all_calls),'turn_status':report['status'],'cognitive_result':result,
                    'information_completion':result['information']['completion'],
                    'model_claims':result['evidence']['model_claims']['evaluation']}
            f.export_case(root,entry['seed'],entry['case'],report,records,adapter.calls,raw,result=aggregate)
            exported=f.read_json(root/f"case-{entry['seed']}-{entry['case']}.json")
            f.verify_case(exported,raw,require_native=True,require_cognitive_result=experiment_contract=='anima.lab.r945c_execution/0.1')
        if before!=_readonly(memory) or memory.context_for_cognition(memory_enabled=enabled)!=base:raise ValueError('READ_ONLY_OR_CONTEXT_CHANGED')
        if len(all_calls)!=len(wire.exchanges) or len(all_calls)>4:raise ValueError('CALL_ACCOUNTING_MISMATCH')
        if result['execution']['task_completion']!='NOT_ESTABLISHED':raise ValueError('FALSE_TASK_SUCCESS')
        if any(fact['verdict']['status']!='VERIFIED' for fact in result['evidence']['facts']):raise ValueError('UNVERIFIED_FACT')
        common=evaluate_completion(req,{**report,'control':{**report.get('control',{}),'profile':'r943/0.1'}},records)
        # No final verdict is propagated backward: each common prefix is evaluated.
        sufficient=None
        for p in measured['prefixes']:
            n=p['operation_prefix'];prefix={**report,'status':'STEP_BUDGET_EXHAUSTED','outcomes':report['outcomes'][:n],'control':{'profile':'r943/0.1'}}
            if evaluate_completion(req,prefix,records[:n])['information_requirement_satisfied']:
                sufficient=p['call_prefix'];break
        after=[c for c in all_calls[sufficient:] if c.get('phase','research')=='research'] if sufficient is not None else []
        final=measured['prefixes'][-1]
        metrics={'common_completeness':_coverage(req,common)['ratio'],'common_verdict':common,'original_verdict':final['completion'],
            'redundant_acquisition_rows':final['redundancy']['same_tool']+final['redundancy']['cross_tool'],
            'post_sufficiency_research_calls':sum(c.get('proposal') is not None for c in after),'post_sufficiency_all_research_model_calls':len(after),
            'unique_verified_sources':final['evidence']['unique_sources'],'verified_fact_count':final['verified_fact_count'],
            'model_calls':len(wire.exchanges),'usage':final['resources'],'verification_cost':cost,'continuation':measured['continuation'],
            'premature_stop':measured['premature_stop'],'accepted_final':report['status']=='STOPPED','presentation':result['presentation'],
            'status':report['status'],'control_reason':report.get('control',{}).get('reason'),'outcomes':[r['outcome']['status'] for r in records],
            'terminal_calls':[terminal_call(c) for c in all_calls],
            'wire_failures':wire.failures,'safety':'CHECKED_NO_VIOLATION','semantic_prose_quality':'NOT_ASSESSED','retrieval_quality':'NOT_ASSESSED_NO_FROZEN_LABELS_FOR_ADAPTIVE_QUERIES','rejected_duplicates_with_missing_path':'NOT_ASSESSED_NOT_A_SEMANTIC_PATH_ORACLE'}
        f.write_json(root/'metrics.json',metrics)
        return {'metrics':metrics,'exchanges':wire.exchanges,'context':context,'readonly':before,'raw_sha256':entry['raw_sha256'],'journals_by_call':{p['call_prefix']:records[:p['operation_prefix']] for p in measured['prefixes']}}
    except Exception as error:
        f.write_json(root/'harness-failure.json',{'type':type(error).__name__,'message':str(error),'wire':wire.exchanges})
        raise


def compare(a,b):
    exact=0;decision=0;first=None;first_exact=None
    for i in range(max(len(a['exchanges']),len(b['exchanges']))):
        aa=a['exchanges'][i] if i<len(a['exchanges']) else None;bb=b['exchanges'][i] if i<len(b['exchanges']) else None
        same_request=aa is not None and bb is not None and aa['request']==bb['request']
        same_decision=aa is not None and bb is not None and decision_signature(aa.get('response',{}))==decision_signature(bb.get('response',{}))
        same_journal=a.get('journals_by_call',{}).get(i+1)==b.get('journals_by_call',{}).get(i+1)
        if first is None and same_request and same_decision and same_journal:decision+=1
        same_exact=same_request and aa.get('response_sha256')==bb.get('response_sha256')
        if first_exact is None:
            if same_exact:exact+=1
            else:first_exact={'index':i,'kind':'WIRE_BYTES_OR_LENGTH'}
        if first is None and not (same_request and same_decision and same_journal):first={'index':i,'kind':'TRAJECTORY_LENGTH' if aa is None or bb is None else 'REQUEST' if not same_request else 'RESPONSE_DECISION' if not same_decision else 'JOURNAL_OUTCOME','a_request':aa.get('request_sha256') if aa else None,'b_request':bb.get('request_sha256') if bb else None}
    if (a['context']!=b['context'] or a.get('raw_sha256')!=b.get('raw_sha256')
            or any(a['readonly'].get(k)!=b['readonly'].get(k) for k in ('knowledge_count','execution'))):raise ValueError('PAIR_INITIAL_STATE_MISMATCH')
    return {'initial_request_equal':bool(a['exchanges'] and b['exchanges'] and a['exchanges'][0]['request']==b['exchanges'][0]['request']),
        'matched_decision_prefix':decision,'exact_response_prefix':exact,'first_exact_divergence':first_exact,'first_divergence':first,'later_requests_matched':'NOT_CLAIMED','opaque_id_canonicalization':'NOT_USED_FOR_EXACT_EQUALITY'}


def validate_plan(plan):
    if (plan['schema']!=SCHEMA or plan['arms']!=PROFILES or plan['repetitions']!=20
            or plan['planned_pairs']!=560 or plan['planned_trajectories']!=1120 or plan['maximum_model_calls']!=4480
            or len(plan['entries'])!=28 or len({e['id'] for e in plan['entries']})!=28
            or plan['resource_limits']!=asdict(ResourceLimits())
            or plan['order_table']!=[{'pair':i,'order':['A','B'] if i%2==0 else ['B','A']} for i in range(20)]):
        raise ValueError('unregistered design')
    for e in plan['entries']:
        if h._sha(e['initial_request'])!=e['initial_request_sha256']:raise ValueError('initial request hash mismatch')


def execute(manifest_path,output,pid,preflight_path):
    implementation=f.git_snapshot();plan=f.read_json(manifest_path);pre=f.read_json(preflight_path)
    validate_plan(plan)
    for path,sha in plan['frozen_inputs'].items():
        if f.file_digest(path)!=sha:raise ValueError('frozen input changed')
    root=h._new_output(output);f.write_json(root/'run-inputs.json',{'implementation_sha':implementation,'manifest':plan,'manifest_sha256':f.file_digest(manifest_path),'preflight':pre,'preflight_sha256':f.file_digest(preflight_path)})
    backend_check(pid,pre['backend'],pre['model_sha256'])
    check=lambda:backend_check(pid,pre['backend'],pre['model_sha256'],pre['model_stat'])
    check();rows=[];failure=None
    try:
        for entry in plan['entries']:
            req=requirement(entry)
            for block in plan['order_table']:
                label=f"{entry['id']}-{block['pair']:02}";arms={}
                for arm in block['order']:
                    check()
                    arms[arm]=trajectory(entry,PROFILES[arm],root/(label+'-'+arm),LoopbackChatTransport(entry['base_url']),check=check)
                    if arms[arm]['metrics']['wire_failures']:raise ValueError('WIRE_FAILURE_NO_RETRY')
                row={'scenario':entry['id'],'cluster':entry['cluster'],'context_profile':entry['context_profile'],'case':entry['case'],'seed':entry['seed'],'pair':block['pair'],'order':block['order'],
                    'availability':'NO_SERVICE_REQUIREMENT' if req.kind=='no_service_read' else 'MEMORY_ON' if entry['scenario']['enabled'] else 'MEMORY_OFF',
                    'arms':{k:v['metrics'] for k,v in arms.items()},'comparison':compare(arms['A'],arms['B'])}
                f.write_json(root/(label+'-pair.json'),row);rows.append(row)
                print(json.dumps({'completed_pairs':len(rows),'planned_pairs':plan['planned_pairs'],'scenario':entry['id'],'pair':block['pair']}),flush=True)
    except Exception as error:
        failure={'type':type(error).__name__,'message':str(error),'invalid_pair':label if 'label' in locals() else None}
        f.write_json(root/'failure.json',failure)
    finally:
        f.write_json(root/'summary.json',{'planned_pairs':plan['planned_pairs'],'completed_pairs':len(rows),'planned_trajectories':plan['planned_trajectories'],'status':'STOPPED_NO_RETRY' if failure else 'COMPLETED','failure':failure})
    return failure is None


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('prepare');p.add_argument('--plans',nargs=2,type=Path,required=True);p.add_argument('--held-out',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('run');p.add_argument('manifest',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--pid',type=int,required=True);p.add_argument('--preflight',type=Path,required=True)
    args=parser.parse_args()
    if args.cmd=='prepare':prepare(args.plans,args.held_out,args.output)
    elif not execute(args.manifest,args.output,args.pid,args.preflight):raise SystemExit(1)

if __name__=='__main__':main()
