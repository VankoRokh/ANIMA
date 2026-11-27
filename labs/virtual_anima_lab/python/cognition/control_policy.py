"""R9.4.2 bounded host control. Pure checked-journal view, no Raw I/O.

Not an offline measurement import, semantic utility judge or parallel loop.
The coordinator owns freshness/admission/budget and all service dispatch.
"""
from .completion import evaluate_completion
from .source_binding import admitted_source_rows
from .source_policy import E25CognitionError
from anima.agent.native_tools import canonical

PROFILE='r942/0.1'
REASONS=('INFORMATION_SUFFICIENT','SOURCE_UNAVAILABLE','REDUNDANT_OPERATION','NO_SERVICE_READ_VIOLATION')

def state(requirement,context,records):
    report={'turn_id':records[0]['turn_id'] if records else 'unused',
            'context_snapshot_id':context['context_snapshot_id'],
            'status':'STEP_BUDGET_EXHAUSTED','outcomes':[r['outcome'] for r in records]}
    completion=evaluate_completion(requirement,report,records)
    rows={};lookups=set();searches=set();operations=[]
    for record in records:
        p=record['proposal'];o=record['outcome']
        if not p or o['status']!='COMPLETED':continue
        operations.append([p['operation_kind'],p['arguments']])
        if p['operation_kind']=='retrieve_memory':
            searches.add(canonical([' '.join(p['arguments']['query'].casefold().split()),p['arguments']['top_k'],o['result']]))
        for row in admitted_source_rows(record):
            if row['event_id'] in rows and rows[row['event_id']]!=row:
                raise E25CognitionError('INCONSISTENT_SOURCE_READS')
            rows[row['event_id']]=row
            if p['operation_kind']=='lookup_raw_evidence':lookups.add(row['event_id'])
    available='UNKNOWN';recoverable='UNKNOWN'
    if context['memory_enabled'] is False:
        available='DISABLED_BY_POLICY'
        latest_entities={e['entity_ref'] for e in context['entities'] if e['last_seen_sample']==context['latest_sample_id']}
        if requirement.kind=='historical_and_latest_observation':recoverable='UNAVAILABLE'
        elif requirement.kind=='verified_observation':
            recoverable='AVAILABLE' if set(completion['missing_entities'])<=latest_entities else 'UNAVAILABLE'
    else:
        exposed={e['entity_ref'] for e in context['entities']}
        if set(completion['missing_entities'])<=exposed:recoverable='AVAILABLE'
        if operations:available='AVAILABLE_IN_SCOPE'
    # Checked metadata may reveal a permitted source path without asserting
    # the answer. Missing units absent from this view remain UNKNOWN.
    if context['memory_enabled'] and any(p[0]=='retrieve_memory' for p in operations):
        for record in records:
            if record['outcome']['status']=='COMPLETED' and record['proposal']['operation_kind']=='retrieve_memory':
                if record['outcome']['result']['truncated']:available='PARTIAL_OR_TRUNCATED'
    completion.pop('model_stopped');completion.pop('turn_status')
    covered=len(requirement.entities)-len(completion['missing_entities'])
    if requirement.kind=='historical_and_latest_observation':covered+=int(completion['latest_source'] is not None)
    if requirement.kind in ('empty_search','no_service_read'):covered=int(completion['information_requirement_satisfied'])
    return {'completion':completion,'rows':rows,'lookup_events':sorted(lookups),
            'identities':[ [context['world_instance_id'],context['epoch'],r['source_ref'],r['event_id'],r['sample_id'],r['raw_sha256']] for r in rows.values()],
            'completed_operations':operations,'availability':available,'recoverability':recoverable,
            'gain_key':[covered,len(rows),len(searches)]}

def termination(requirement,view):
    if requirement.kind=='no_service_read':
        return 'NO_SERVICE_READ_VIOLATION' if view['completion']['completed_service_reads'] else None
    if view['completion']['information_requirement_satisfied']:return 'INFORMATION_SUFFICIENT'
    if view['recoverability']=='UNAVAILABLE':return 'SOURCE_UNAVAILABLE'
    return None

def redundant(requirement,context,view,proposal):
    kind,args=proposal['operation_kind'],proposal['arguments']
    if kind=='retrieve_memory':
        key=[' '.join(args['query'].casefold().split()),args['top_k']]
        return any(k==kind and [' '.join(a['query'].casefold().split()),a['top_k']]==key for k,a in view['completed_operations'])
    if kind=='lookup_raw_evidence':
        if not all(e in view['rows'] for e in args['event_ids']):return False
        # C14: same identity can newly meet the lookup-only requirement.
        if requirement.kind=='verified_observation':
            missing=set(view['completion']['missing_entities'])
            if any(e not in view['lookup_events'] and missing.intersection(view['rows'][e]['entities_observed']) for e in args['event_ids']):return False
        return True
    if kind=='inspect_latest_observation':
        return any(r['sample_id']==context['latest_sample_id'] for r in view['rows'].values())
    # Belief reads and other tools may expose different predicates with the
    # same source ID. No identity-only veto across different semantics.
    return False
