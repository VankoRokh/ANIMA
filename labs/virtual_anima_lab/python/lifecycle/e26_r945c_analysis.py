"""Confirmatory offline supplement; unchanged R944 numeric gates are reused."""
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
import argparse
from . import e26_reproducibility as f
from . import e26_r944_analysis as a
from . import e26_r945c_confirmatory as c
from .e26_r944_fresh import requirement
from ..cognition.source_binding import admitted_source_rows


def fact_coverage(result):
    completion=result['information']['completion'];req=completion['requirement'];kind=req['kind']
    if kind not in ('verified_observation','historical_and_latest_observation'):return None
    claims=[item['verdict']['claim'] for item in result['evidence']['facts'] if item['verdict']['status']=='VERIFIED']
    historical={x['entity_ref'] for x in claims if x['predicate']=='observed_in_sample' and x['value'] is True and x['scope']=='source_sample'}
    covered=len(set(req['entities'])&historical);required=len(req['entities'])
    if kind=='historical_and_latest_observation':
        required+=1;covered+=int(any(x['scope']=='latest_captured_sample' for x in claims))
    return covered/required


def analyze(manifest_path,run,output):
    plan=f.read_json(manifest_path);c.validate(plan);run=Path(run);root=c.h._new_output(output)
    core=a.analyze(manifest_path,run,root/'r944-protocol-analysis.json')
    rows=[f.read_json(p) for p in sorted(run.glob('*-pair.json'))];entries={e['id']:e for e in plan['entries']}
    costs={};fact_rows=deepcopy(rows);f02=[]
    for row in fact_rows:
        for arm in ('A','B'):
            d=run/f"{row['scenario']}-{row['pair']:02}-{arm}";result=f.read_json(d/'result.json')
            row['arms'][arm]['verified_fact_coverage']=fact_coverage(result)
    eligible=[r for r in fact_rows if all(r['arms'][arm]['verified_fact_coverage'] is not None for arm in ('A','B'))]
    for arm in ('A','B'):
        count=Counter();io=defaultdict(Counter);details=[]
        for path in sorted(run.glob(f'*-{arm}/metrics.json')):
            d=path.parent;metrics=f.read_json(path);turn=f.read_json(d/'turn.json');result=f.read_json(d/'result.json')
            import json
            research=[json.loads(line) for line in (d/'calls.jsonl').read_text().splitlines()]
            for call in research:
                count['tool_proposals' if call.get('proposal') is not None else 'text_stop_attempts' if call.get('valid') and call.get('final_text') else 'rejected_or_incomplete_research']+=1
            count['claim_projection_calls']+=int(turn.get('claim_projection',{}).get('call') is not None)
            count['accepted_research_finals']+=int(result['reasoning']['research_final_index'] is not None)
            count['presentation_available']+=int(result['presentation']['model_text'] is not None)
            count['model_calls']+=metrics['model_calls']
            count['verified_host_facts']+=len(result['evidence']['facts']);count['unique_verified_sources']+=metrics['unique_verified_sources']
            for phase,values in metrics['verification_cost'].items():io[phase].update(values)
            if arm=='B':
                check=c.verify_consumer(result)
                check.update(trajectory=d.name,partial_facts=result['information']['status']=='INCOMPLETE' and bool(result['evidence']['facts']))
                if not (d/'consumer-check.json').exists():raise ValueError('consumer check missing')
                f02.append(check)
        costs[arm]={'counts':dict(count),'verification_IO':{k:dict(v) for k,v in io.items()}}
    focused=[]
    for pair in range(20):
        path=run/f'control-7-C03-{pair:02}-pair.json'
        if not path.exists():focused.append({'pair':pair,'status':'NOT_COMPLETED_RETAINED_IN_DENOMINATOR'});continue
        record=f.read_json(path);arms={}
        for arm in ('A','B'):
            d=run/f'control-7-C03-{pair:02}-{arm}';turn=f.read_json(d/'turn.json');journal=f.read_json(d/'journal.json');result=f.read_json(d/'result.json')
            raw=[row for rec in journal if rec['proposal'] and rec['proposal']['operation_kind']=='lookup_raw_evidence' for row in admitted_source_rows(rec)]
            budget=turn['resource_budget'];limits=budget['limits']
            arms[arm]={'common_verdict':record['arms'][arm]['common_verdict'],'common_completeness':record['arms'][arm]['common_completeness'],
                'required_Raw_acquisitions':[row for row in raw if set(row['entities_observed'])&set(entries['control-7-C03']['scenario']['targets'])],
                'continuation_decisions':turn.get('continuation_decisions',[]),'resource_budget':budget,
                'remaining_budget':{'calls':max(0,limits['max_calls']-budget['reserved_calls']),'reported_input_tokens':max(0,limits['max_reported_input_tokens']-budget['reported_input_tokens']),
                    'output_tokens':max(0,limits['max_reported_output_tokens']-budget['reported_output_tokens']),'elapsed_ms_boundary_only':max(0,limits['max_elapsed_ms']-budget['elapsed_ms'])},
                'accepted_final':record['arms'][arm]['accepted_final'],'presentation':result['presentation'],'consumer_view':result.get('consumer_view'),
                'artifact':str(d),'result_sha256':f.file_digest(d/'result.json')}
        focused.append({'pair':pair,'order':record['order'],'arms':arms,'exact_and_journal_comparison':record['comparison'],'operation_comparison':record['operation_comparison']})
    result={**core,'stage':'R9.4.5c','analysis_contract':'anima.lab.r945c_analysis/0.1','approved_plan_sha256':c.APPROVED_SHA,'cost_decomposition':costs,
        'verified_fact_coverage':{'applicable_pairs':len(eligible),'excluded_scope':'empty_search/no_service have no required fact denominator, NOT_APPLICABLE',
            'paired_cluster_delta':a.interval(a.cluster_differences(eligible,'verified_fact_coverage'))},
        'F01_all20':focused,'historical_F01':'R944 control-7-C03: 20 A complete, 0 B complete; SEPARATE_HISTORICAL_GROUP_NOT_POOLED',
        'F02_consumer_checks':f02,'F02_scope':'consumer source/authority/scope/final reconstruction only; model prose truth and external UI NOT_ASSESSED; no hallucination elimination claim',
        'consumer_failures':[str(p) for p in run.glob('*/confirmatory-failure.json')],
        'stable_adoption_recommendation':'REMAIN_OPT_IN; do not adopt solely on focused case/cost reduction; frozen gates and uncertainty govern review'}
    f.write_json(root/'analysis.json',result);return result


def main():
    p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();analyze(args.manifest,args.run,args.output)

if __name__=='__main__':main()
