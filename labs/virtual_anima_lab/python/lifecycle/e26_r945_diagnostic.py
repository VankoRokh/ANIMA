"""R945b single-request factorial diagnostic; no tool dispatch or retries."""
from copy import deepcopy
from pathlib import Path
import argparse
from . import e26_reproducibility as f
from . import e26_r941_experiments as h
from .e26_r944_fresh import FreshTransport,backend_check
from anima.agent.native_tools import LoopbackChatTransport

SCHEMA='anima.lab.r945_diagnostic/0.1'


def strategy(request,old,new):
    copy=deepcopy(request);message=copy['messages'][-1]
    import json
    needle='"strategy":'+json.dumps(old)
    if message['role']!='tool' or message['content'].count(needle)!=1:raise ValueError('unique strategy leaf required')
    message['content']=message['content'].replace(needle,'"strategy":'+json.dumps(new))
    return copy


def prepare(proposal_path,exchange_path,output):
    proposal=f.read_json(proposal_path);base=f.read_json(exchange_path)['request']
    if h._sha(base)!=proposal['base_request_sha256'] or proposal['blocks']!=20:raise ValueError('proposal input changed')
    root=h._new_output(output);ids=h._tool_bindings(base);mapping={key:'r945diag_tool_'+str(i) for i,key in enumerate(sorted(ids),1)}
    old,new=proposal['existing_strategy_levels'];renamed=h.id_variant(base,'I-tool',mapping)
    requests=[base,strategy(base,old,new),strategy(renamed['request'],old,new),renamed['request']]
    cells=[]
    for i,request in enumerate(requests):
        path=root/f'cell-{i}.json';f.write_json(path,request)
        cells.append({'cell':i,'request':str(path),'file_sha256':f.file_digest(path),'request_sha256':h._sha(request),'strategy':'new' if i in (1,2) else 'old','IDs':'renamed' if i in (2,3) else 'original'})
    plan={'schema':SCHEMA,'proposal':proposal,'proposal_path':str(Path(proposal_path).resolve()),'proposal_sha256':f.file_digest(proposal_path),
        'source_exchange':str(Path(exchange_path).resolve()),'source_exchange_sha256':f.file_digest(exchange_path),'mapping':mapping,'mapping_sha256':h._sha(mapping),
        'cells':cells,'order_table':proposal['order_table'],'planned':80,'concurrency':1,'tool_dispatch':False,
        'analysis':'within each block compare strategy at fixed ID and ID at fixed strategy; tool operations/typed args, text/terminal/usage separate; one context, no scenario-level causal generalization',
        'stop':'transport/backend/config failure stops; no retries/reruns; terminal length/invalid preserved; all 80 planned retained'}
    validate(plan);f.write_json(root/'manifest.json',plan);return plan


def validate(plan):
    if plan['schema']!=SCHEMA or plan['planned']!=80 or len(plan['cells'])!=4:raise ValueError('wrong design')
    if plan['order_table']!=[{'block':i,'cell_order':[0,1,2,3] if i%2==0 else [3,2,1,0]} for i in range(20)]:raise ValueError('order changed')
    base=f.read_json(plan['source_exchange'])['request'];old,new=plan['proposal']['existing_strategy_levels']
    if f.file_digest(plan['source_exchange'])!=plan['source_exchange_sha256'] or f.file_digest(plan['proposal_path'])!=plan['proposal_sha256']:raise ValueError('frozen inputs changed')
    if h._sha(plan['mapping'])!=plan['mapping_sha256']:raise ValueError('mapping changed')
    for i,cell in enumerate(plan['cells']):
        request=f.read_json(cell['request'])
        if cell['cell']!=i or f.file_digest(cell['request'])!=cell['file_sha256'] or h._sha(request)!=cell['request_sha256']:raise ValueError('cell changed')
        restored=request
        if i in (2,3):restored=h.id_variant(restored,'I-tool',{v:k for k,v in plan['mapping'].items()})['request']
        if i in (1,2):restored=strategy(restored,new,old)
        if restored!=base:raise ValueError('undeclared factor or source change')


def run(manifest,preflight,output,pid):
    implementation=f.git_snapshot();plan=f.read_json(manifest);validate(plan);pre=f.read_json(preflight)
    backend_check(pid,pre['backend'],pre['model_sha256'])
    check=lambda:backend_check(pid,pre['backend'],pre['model_sha256'],pre['model_stat'])
    root=h._new_output(output);f.write_json(root/'inputs.json',{'manifest':plan,'manifest_sha256':f.file_digest(manifest),'preflight':pre,'preflight_sha256':f.file_digest(preflight),'implementation_sha':implementation})
    samples=[];failure=None
    for block in plan['order_table']:
        for cell in block['cell_order']:
            request=f.read_json(plan['cells'][cell]['request']);label=f"{block['block']:02}-{cell}"
            wire=FreshTransport(LoopbackChatTransport('http://127.0.0.1:8085'),root/(label+'-wire'),request,check)
            record={'block':block['block'],'cell':cell,'request_sha256':h._sha(request)}
            try:
                response=wire.complete(request)
                record.update(status='RECEIVED',response_sha256=h._sha(response),response=response,signature=h.response_signature(response),
                    terminal=h._response_view(response),usage=response.get('usage'),latency_ms=wire.exchanges[0]['latency_ms'])
            except Exception as error:
                record.update(status='FAILED',error=type(error).__name__+': '+str(error));failure=record['error']
            samples.append(record);f.write_json(root/(label+'-sample.json'),record)
            print(f"received={sum(s['status']=='RECEIVED' for s in samples)}/80 block={block['block']} cell={cell}",flush=True)
            if failure:break
        if failure:break
    contrasts=[]
    for block in range(20):
        cells={s['cell']:s for s in samples if s['block']==block and s['status']=='RECEIVED'}
        if len(cells)!=4:continue
        for name,left,right in [('strategy_original_ID',0,1),('strategy_renamed_ID',3,2),('ID_old_strategy',0,3),('ID_new_strategy',1,2)]:
            a,b=cells[left],cells[right]
            operations=lambda s:[c['operations'] for c in s['signature']]
            contrasts.append({'block':block,'contrast':name,'operations_equal':operations(a)==operations(b),'signature_equal':a['signature']==b['signature'],
                'response_exact_equal':a['response']==b['response'],'left_terminal':a['terminal'],'right_terminal':b['terminal']})
    result={'planned':80,'attempted':len(samples),'received':sum(s['status']=='RECEIVED' for s in samples),'failed':sum(s['status']=='FAILED' for s in samples),
        'failure':failure,'contrasts':contrasts,'scope':'ONE_FROZEN_REQUEST; no full trajectory or generalized causal effect','tool_dispatch':False}
    f.write_json(root/'summary.json',result);return result


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('prepare');a.add_argument('proposal',type=Path);a.add_argument('exchange',type=Path);a.add_argument('--output',type=Path,required=True)
    a=sub.add_parser('run');a.add_argument('manifest',type=Path);a.add_argument('--preflight',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--pid',type=int,required=True)
    args=p.parse_args()
    if args.cmd=='prepare':prepare(args.proposal,args.exchange,args.output)
    elif run(args.manifest,args.preflight,args.output,args.pid)['failure']:raise SystemExit(1)

if __name__=='__main__':main()
