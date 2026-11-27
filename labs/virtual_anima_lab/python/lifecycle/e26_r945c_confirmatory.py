"""Versioned execution adapter for the immutable approved R945c design.

Experimental only. No runtime policy changes, archived response substitution,
labels or retries. Legacy R944 entry points retain their original defaults.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import urllib.request
import urllib.error
from . import e26_reproducibility as f
from . import e26_r941_experiments as h
from . import e26_r944_fresh as t
from ..cognition.verified_presentation import project_verified_presentation
from anima.agent.native_tools import LoopbackChatTransport, canonical, strict_json

SCHEMA='anima.lab.r945c_execution/0.1'
APPROVED_SHA='3356b283da7fb3814c2ed4939f002f718cecdd32e4d03b3730c4cf27bcb576d6'
BASELINE='c4f4eb07984d8cc56e0d98dc76ab7014e7931421'
ARMS={'A':'baseline','B':'r945/0.1'}
FIELDS=('entries','repetitions','planned_pairs','planned_trajectories','maximum_model_calls','order_table','concurrency','resource_limits','generation_fields','analysis','held_out','primary')


class ArchivedLoopbackTransport(LoopbackChatTransport):
    """Same one-call wire contract; retain bounded raw bytes before decoding."""
    def __init__(self, base_url, archive):
        super().__init__(base_url)
        self.archive=Path(archive);self.index=0

    def complete(self, payload):
        self.archive.mkdir(parents=True,exist_ok=True)
        stem=self.archive/f'{self.index:02}'
        self.index+=1
        request_bytes=canonical(payload).encode('utf-8')
        stem.with_suffix('.request').write_bytes(request_bytes)
        request=urllib.request.Request(self.endpoint,data=request_bytes,method='POST',
            headers={'Content-Type':'application/json','Accept':'application/json'})
        try:
            response=self._opener.open(request,timeout=self.timeout)
        except urllib.error.HTTPError as error:
            raw=error.read(200001)
            stem.with_suffix('.response').write_bytes(raw)
            f.write_json(stem.with_suffix('.json'),{'status':error.code,'truncated':len(raw)>200000,'HTTP_error':True})
            raise
        with response:
            raw=response.read(200001)
            stem.with_suffix('.response').write_bytes(raw)
            f.write_json(stem.with_suffix('.json'),{'status':response.status,'truncated':len(raw)>200000,'HTTP_error':False})
        if len(raw)>200000:raise ValueError('response exceeds transport budget')
        return strict_json(raw.decode('utf-8'))


def approved(path):
    if f.file_digest(path)!=APPROVED_SHA:raise ValueError('approved plan hash mismatch')
    plan=f.read_json(path)
    if (plan['comparison']!=ARMS or plan['repetitions']!=20 or plan['planned_pairs']!=560
            or plan['planned_trajectories']!=1120 or plan['maximum_model_calls']!=4480
            or len(plan['entries'])!=28 or len({e['cluster'] for e in plan['entries']})!=14):raise ValueError('invalid approved design')
    return plan


def prepare(path,output):
    plan=approved(path);implementation=f.git_snapshot();root=h._new_output(output)
    copy=root/'approved-plan.json';copy.write_bytes(Path(path).read_bytes())
    frozen={}
    for e in plan['entries']:
        for kind in ('case','raw'):
            p=e[kind+'_path'];sha=e[kind+'_sha256']
            if f.file_digest(p)!=sha:raise ValueError('frozen source changed')
            frozen[p]=sha
    result={**{k:deepcopy(plan[k]) for k in FIELDS},'schema':SCHEMA,'stage':'R9.4.5c','baseline':BASELINE,
        'approved_plan_path':str(Path(path).resolve()),'approved_plan_sha256':APPROVED_SHA,'approved_copy':str(copy),
        'implementation_sha':implementation,'arms':ARMS,'availability_strata':plan['strata'],'id_policy':plan['ID_policy'],
        'frozen_inputs':frozen,'stopping':plan['stopping'],'status':'PREPARED_NOT_RUN'}
    validate(result);f.write_json(root/'execution-manifest.json',result);return result


def validate(manifest):
    if manifest['schema']!=SCHEMA or manifest['baseline']!=BASELINE or manifest['approved_plan_sha256']!=APPROVED_SHA:raise ValueError('execution contract mismatch')
    plan=approved(manifest['approved_plan_path'])
    if f.file_digest(manifest['approved_copy'])!=APPROVED_SHA:raise ValueError('approved copy changed')
    if manifest['arms']!=ARMS or manifest['availability_strata']!=plan['strata'] or manifest['id_policy']!=plan['ID_policy'] or manifest['stopping']!=plan['stopping']:raise ValueError('undeclared execution change')
    for key in FIELDS:
        if manifest[key]!=plan[key]:raise ValueError('approved field changed: '+key)
    expected={e[k+'_path']:e[k+'_sha256'] for e in plan['entries'] for k in ('case','raw')}
    if manifest['frozen_inputs']!=expected:raise ValueError('source inventory changed')
    for path,sha in expected.items():
        if f.file_digest(path)!=sha:raise ValueError('frozen source changed')
    for entry in plan['entries']:
        if h._sha(entry['initial_request'])!=entry['initial_request_sha256']:raise ValueError('initial request changed')


def verify_consumer(result):
    view=result.get('consumer_view')
    if view!=project_verified_presentation(result):raise ValueError('consumer reconstruction mismatch')
    if (view['global_verification']!='NOT_ESTABLISHED' or view['task_completion']!='NOT_ESTABLISHED'
            or view['unverified_model_prose']['authority']!='UNVERIFIED'
            or view['unverified_model_prose']['whole_answer_verified'] is not False):raise ValueError('consumer authority violation')
    accepted=result['reasoning']['research_final_index'] is not None
    if (view['accepted_research_final']['status']=='ACCEPTED_PROTOCOL_FINAL')!=accepted:raise ValueError('fabricated model final')
    if not accepted and view['unverified_model_prose']['research'] is not None:raise ValueError('fabricated model prose')
    for fact in view['verified_facts']+view['verified_model_claims']:
        if fact['verdict']['status']!='VERIFIED' or fact['verdict']['claim']['scope'] not in ('source_sample','latest_captured_sample'):raise ValueError('unverified fact or unbounded scope')
    return {'status':'CHECKED','facts':len(view['verified_facts']),'model_typed_claims':len(view['verified_model_claims']),
        'information':view['information']['status'],'accepted_research_final':accepted,'missing_units':view['information']['missing_units'],
        'prose_truth':'NOT_ASSESSED','external_UI':'NOT_ASSESSED','import_authentication':False}


def trajectory(entry,profile,output,transport,*,check=lambda:None):
    data=t.trajectory(entry,profile,output,transport,check=check,experiment_contract=SCHEMA,measurement_baseline=BASELINE)
    root=Path(output)
    try:
        if profile=='r945/0.1':f.write_json(root/'consumer-check.json',verify_consumer(f.read_json(root/'result.json')))
        # Research and projection have different existing wire shapes.
        report=f.read_json(root/'turn.json')
        for exchange in data['exchanges']:
            request=exchange['request']
            for key in ('model','temperature','max_tokens','chat_template_kwargs'):
                if request[key]!=entry['initial_request'][key]:raise ValueError('generation field changed')
            if 'tools' in request:
                if request['tools']!=entry['initial_request']['tools'] or request['parallel_tool_calls'] is not False:raise ValueError('tool permissions changed')
                h._tool_bindings(request)
            elif (report.get('claim_projection',{}).get('call') or {}).get('request')!=request:raise ValueError('unbound projection request')
        exported=f.read_json(root/f"case-{entry['seed']}-{entry['case']}.json")
        classes=[]
        for call in exported['model_calls']:
            phase=call.get('phase','research');proposal=call.get('proposal')
            if phase=='claim_projection':item={'phase':phase,'class':'PROJECTION','valid':call.get('valid')}
            elif proposal is not None:item={'phase':phase,'class':'TOOL_PROPOSAL','operation':proposal['operation_kind'],'arguments':proposal['arguments']}
            elif call.get('valid') and call.get('final_text'):item={'phase':phase,'class':'TEXT_STOP'}
            else:item={'phase':phase,'class':'TERMINAL_REJECTION','finish_reason':call.get('finish_reason'),'error_code':call.get('error_code')}
            classes.append(item)
        f.write_json(root/'operation-decisions.json',classes);data['operation_classes']=classes
        return data
    except Exception as error:
        f.write_json(root/'confirmatory-failure.json',{'type':type(error).__name__,'message':str(error)})
        raise


def operation_comparison(a,b):
    def operations(data):return data['operation_classes']
    aa,bb=operations(a),operations(b);prefix=0;first=None
    for i in range(max(len(aa),len(bb))):
        left=aa[i] if i<len(aa) else None;right=bb[i] if i<len(bb) else None
        if left!=right:first={'index':i,'A':left,'B':right};break
        prefix+=1
    return {'matched_operation_prefix':prefix,'first_operation_or_terminal_divergence':first,'native_response_ids_and_timing':'NOT_OPERATION_DIFFERENCES','later_matching':'NOT_CLAIMED'}


def configuration_snapshot(base_url):
    # Read-only configuration endpoint, never an inference/retry.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(base_url.rstrip('/')+'/props',timeout=10) as response:
        props=strict_json(response.read(200000).decode('utf-8'))
    keys=('default_generation_settings','total_slots','model_alias','model_path','chat_template','chat_template_caps','build_info')
    return {key:props.get(key,'UNKNOWN') for key in keys}


def execute(manifest_path,output,pid,preflight):
    plan=f.read_json(manifest_path);validate(plan);implementation=f.git_snapshot()
    if implementation!=plan['implementation_sha']:raise ValueError('implementation differs from execution manifest')
    pre=f.read_json(preflight)
    if pre['implementation_sha']!=implementation or pre['execution_manifest_sha256']!=f.file_digest(manifest_path):raise ValueError('preflight binding mismatch')
    t.backend_check(pid,pre['backend'],pre['model_sha256'])
    def check():
        t.backend_check(pid,pre['backend'],pre['model_sha256'],pre['model_stat'])
        if configuration_snapshot(plan['entries'][0]['base_url'])!=pre['configuration']:
            raise ValueError('INVALID_PAIR: backend configuration changed')
    root=h._new_output(output);f.write_json(root/'run-inputs.json',{'implementation_sha':implementation,'plan':plan,'manifest':plan,'manifest_sha256':f.file_digest(manifest_path),'preflight':pre,'preflight_sha256':f.file_digest(preflight)})
    rows=[];failure=None
    try:
        for entry in plan['entries']:
            req=t.requirement(entry)
            for block in plan['order_table']:
                label=f"{entry['id']}-{block['pair']:02}";arms={}
                for arm in block['order']:
                    check();arms[arm]=trajectory(entry,ARMS[arm],root/(label+'-'+arm),ArchivedLoopbackTransport(entry['base_url'],root/(label+'-'+arm)/'http'),check=check)
                    if arms[arm]['metrics']['wire_failures']:raise ValueError('WIRE_FAILURE_NO_RETRY')
                row={'scenario':entry['id'],'cluster':entry['cluster'],'context_profile':entry['context_profile'],'case':entry['case'],'seed':entry['seed'],'pair':block['pair'],'order':block['order'],
                    'availability':'NO_SERVICE_REQUIREMENT' if req.kind=='no_service_read' else 'MEMORY_ON' if entry['scenario']['enabled'] else 'MEMORY_OFF',
                    'arms':{key:data['metrics'] for key,data in arms.items()},'comparison':t.compare(arms['A'],arms['B']),'operation_comparison':operation_comparison(arms['A'],arms['B'])}
                if not row['comparison']['initial_request_equal']:raise ValueError('initial model requests differ')
                f.write_json(root/(label+'-pair.json'),row);rows.append(row)
                print(json.dumps({'completed_pairs':len(rows),'planned_pairs':560,'scenario':entry['id'],'pair':block['pair']}),flush=True)
    except Exception as error:
        failure={'type':type(error).__name__,'message':str(error),'invalid_pair':locals().get('label')}
        f.write_json(root/'failure.json',failure)
    finally:
        f.write_json(root/'summary.json',{'planned_pairs':560,'completed_pairs':len(rows),'planned_trajectories':1120,'status':'STOPPED_NO_RETRY' if failure else 'COMPLETED','failure':failure})
    return failure is None


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('approved_plan',type=Path);a.add_argument('--output',required=True,type=Path)
    a=sub.add_parser('run');a.add_argument('manifest',type=Path);a.add_argument('--output',required=True,type=Path);a.add_argument('--preflight',required=True,type=Path);a.add_argument('--pid',required=True,type=int)
    a=p.parse_args()
    if a.command=='prepare':prepare(a.approved_plan,a.output)
    elif not execute(a.manifest,a.output,a.pid,a.preflight):raise SystemExit(1)

if __name__=='__main__':main()
