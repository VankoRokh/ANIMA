"""Offline-only paired R944 analysis; never imported by coordinator/transport."""
from collections import Counter,defaultdict
import argparse
import json
from pathlib import Path
import random
import statistics
from . import e26_reproducibility as f

METRICS=('common_completeness','redundant_acquisition_rows','post_sufficiency_research_calls','model_calls')


def interval(values,*,resamples=10000,seed=940):
    if not values:return None
    rng=random.Random(seed);n=len(values)
    boot=sorted(sum(values[rng.randrange(n)] for _ in range(n))/n for _ in range(resamples))
    def percentile(p):
        index=(len(boot)-1)*p;low=int(index);high=min(low+1,len(boot)-1)
        return boot[low]+(boot[high]-boot[low])*(index-low)
    return {'mean_delta_B_minus_A':statistics.mean(values),'ci95':[percentile(.025),percentile(.975)],'clusters':n,'resamples':resamples,'seed':seed}


def cluster_differences(rows,metric):
    # Repetitions -> context means -> equal-weight nested context cluster means.
    clusters=defaultdict(lambda:defaultdict(list))
    for row in rows:clusters[row['cluster']][row['scenario']].append(row['arms']['B'][metric]-row['arms']['A'][metric])
    return [statistics.mean(statistics.mean(v) for v in contexts.values()) for _,contexts in sorted(clusters.items())]


def analyze(manifest_path,run,output):
    plan=f.read_json(manifest_path);run=Path(run);rows=[f.read_json(p) for p in sorted(run.glob('*-pair.json'))]
    summary=f.read_json(run/'summary.json');inputs=f.read_json(run/'run-inputs.json')
    if f.file_digest(manifest_path)!=inputs['manifest_sha256']:raise ValueError('manifest changed')
    expected={(e['id'],i) for e in plan['entries'] for i in range(20)}
    actual={(r['scenario'],r['pair']) for r in rows}
    if len(actual)!=len(rows) or not actual<=expected:raise ValueError('duplicate/unregistered pair')
    per_scenario=[]
    for entry in plan['entries']:
        selected=[r for r in rows if r['scenario']==entry['id']]
        item={'scenario':entry['id'],'cluster':entry['cluster'],'context_profile':entry['context_profile'],'planned_pairs':20,'completed_pairs':len(selected),'arms':{}}
        for arm in ('A','B'):
            records=[r['arms'][arm] for r in selected]
            item['arms'][arm]={'means':{m:statistics.mean(r[m] for r in records) if records else None for m in METRICS},
                'terminal_status':dict(Counter(r['status'] for r in records)),
                'accepted_final':sum(r['accepted_final'] for r in records),'terminal_rejected_calls':sum(not c['valid'] for r in records for c in r['terminal_calls']),
                'model_calls':sum(r['model_calls'] for r in records),
                'known_input_tokens':sum(c['input_tokens'] or 0 for r in records for c in r['terminal_calls']),
                'known_output_tokens':sum(c['output_tokens'] or 0 for r in records for c in r['terminal_calls']),
                'missing_input_usage_calls':sum(c['input_tokens'] is None for r in records for c in r['terminal_calls']),
                'missing_output_usage_calls':sum(c['output_tokens'] is None for r in records for c in r['terminal_calls'])}
        item['paired_differences']={m:[r['arms']['B'][m]-r['arms']['A'][m] for r in selected] for m in METRICS}
        per_scenario.append(item)
    strata={}
    for name in ('ALL_COMPATIBILITY',*plan['availability_strata']):
        chosen=rows if name=='ALL_COMPATIBILITY' else [r for r in rows if r['availability']==name]
        intervals={m:interval(cluster_differences(chosen,m)) for m in METRICS}
        enough=len(actual)==len(expected) and all(x is not None and x['clusters']>=2 for x in intervals.values())
        ci=intervals['common_completeness'];red=intervals['redundant_acquisition_rows'];post=intervals['post_sufficiency_research_calls']
        strata[name]={'pairs':len(chosen),'intervals':intervals,
            'completeness_non_regression':'PASS_OBSERVED_PROTOCOL' if enough and ci['ci95'][0]>=0 else 'FAIL_OBSERVED_REGRESSION' if enough and ci['ci95'][1]<0 else 'INCONCLUSIVE',
            'redundancy_and_post_sufficiency_reduction':'PASS_OBSERVED_PROTOCOL' if enough and red['ci95'][1]<0 and post['ci95'][1]<0 else 'INCONCLUSIVE',
            'median_total_calls_gate':'PASS_OBSERVED_PROTOCOL' if chosen and statistics.median(r['arms']['B']['model_calls'] for r in chosen)<=statistics.median(r['arms']['A']['model_calls'] for r in chosen) else 'FAIL_OBSERVED' if chosen else 'INCONCLUSIVE',
            'median_total_calls':{a:statistics.median(r['arms'][a]['model_calls'] for r in chosen) if chosen else None for a in ('A','B')}}
    trajectories=list(run.glob('*/metrics.json'));wire=list(run.glob('*/wire/*-exchange.json'))
    exchanges=[f.read_json(p) for p in wire];metrics=[f.read_json(p) for p in trajectories]
    all_known_usage=all(c.get('input_tokens') is not None and c.get('output_tokens') is not None for m in metrics for c in m['terminal_calls'])
    divergence=dict(Counter((r['comparison']['first_divergence'] or {}).get('kind','NO_DIVERGENCE') for r in rows))
    result={'stage':'R9.4.4','planned_pairs':plan['planned_pairs'],'attempted_pairs':len({p.parent.parent.name.rsplit('-',1)[0] for p in wire}),
        'completed_pairs':len(rows),'missing_planned_pairs':[{'scenario':s,'pair':i} for s,i in sorted(expected-actual)],
        'planned_trajectories':plan['planned_trajectories'],'attempted_trajectories':len(list(run.glob('*/initial-state.json'))),'completed_trajectories':len(metrics),
        'failed_or_unfinished_trajectories':len(list(run.glob('*/initial-state.json')))-len(metrics),
        'model_requests':{'maximum_planned':plan['maximum_model_calls'],'dispatch_attempted':sum(e.get('dispatch_started',False) for e in exchanges),'received':sum('response' in e for e in exchanges),'failed':sum('failure' in e for e in exchanges),'predispatch_recorded':sum(not e.get('dispatch_started',False) for e in exchanges)},
        'terminal_statuses_all_trajectories':dict(Counter(m['status'] for m in metrics)),
        'incomplete_generations':sum(c['finish_reason']=='length' for m in metrics for c in m['terminal_calls']),
        'known_input_tokens':sum(c['input_tokens'] or 0 for m in metrics for c in m['terminal_calls']),
        'known_output_tokens':sum(c['output_tokens'] or 0 for m in metrics for c in m['terminal_calls']),
        'usage_status':'COMPLETE_BACKEND_REPORTED' if all_known_usage and metrics else 'KNOWN_SUBTOTAL_ONLY',
        'per_scenario':per_scenario,'strata':strata,'first_divergence_counts':divergence,
        'safety':{'checked_trajectories':len(metrics),'violations_in_checked_trajectories':sum(m['safety']!='CHECKED_NO_VIOLATION' for m in metrics),'harness_failures':[str(p) for p in run.glob('*/harness-failure.json')],'scope':'executable invariants/source verifier; prose truth NOT_ASSESSED'},
        'held_out':plan['held_out'],'run_status':summary,
        'causal_generalization_gate':'INCONCLUSIVE','gate_reason':'cache/template/backend defaults UNKNOWN; only 14 template-seed clusters, nested Control/Host; numeric threshold gates reported separately, no generalized causal claim',
        'latency':'EXPLORATORY_CACHE_AND_SLOT_STATE_UNKNOWN','accepted_final_and_presentation':'SEPARATE_FROM_COMPLETENESS; no model STOP fabricated',
        'secondary_detail':'all per-trajectory metrics.json and observable.json include original/common verdicts, source/fact coverage, continuation, calls, verifier I/O and latency; no automatic whole-answer semantic quality score'}
    f.write_json(output,result);return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifest',type=Path);parser.add_argument('run',type=Path);parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();analyze(a.manifest,a.run,a.output)

if __name__=='__main__':main()
