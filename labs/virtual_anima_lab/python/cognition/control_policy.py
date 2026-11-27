"""R9.4.2 bounded host control. Pure checked-journal view, no Raw I/O.

Not an offline measurement import, semantic utility judge or parallel loop.
The coordinator owns freshness/admission/budget and all service dispatch.
"""
from .completion import evaluate_completion
from .source_binding import admitted_source_rows
from .source_policy import E25CognitionError
from anima.agent.native_tools import canonical

PROFILE='r942/0.1'

def search_key(query,profile):
    if profile=='r942/0.1':return ' '.join(query.casefold().split())
    from .retrieval_policy import query_key
    return query_key(query)
REASONS=('INFORMATION_SUFFICIENT','SOURCE_UNAVAILABLE','REDUNDANT_OPERATION','NO_SERVICE_READ_VIOLATION')

def state(requirement,context,records,profile=PROFILE):
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
            searches.add(canonical([search_key(p['arguments']['query'],profile),p['arguments']['top_k'],o['result']]))
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

def redundant(requirement,context,view,proposal,profile=PROFILE):
    kind,args=proposal['operation_kind'],proposal['arguments']
    if kind=='retrieve_memory':
        key=[search_key(args['query'],profile),args['top_k']]
        return any(k==kind and [search_key(a['query'],profile),a['top_k']]==key for k,a in view['completed_operations'])
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

def verify_control(report,records):
    """Consistency of checked imported metadata, NOT archive authenticity."""
    from .completion import CompletionRequirement
    marker=report['control']
    try:
        profile=marker['profile']
        if marker['schema']!='anima.lab.cognitive_control/0.1' or profile not in ('r942/0.1','r942/0.2','r943/0.1'):
            raise ValueError('unknown control profile')
        raw=marker['state']['completion']['requirement']
        req=CompletionRequirement(raw['kind'],tuple(raw['entities']),raw['query'])
        if not records:
            # No scope is attested by an empty journal. Accept only a
            # non-system terminal with no asserted acquisitions; completion
            # prerequisites can still be checked without inventing Context.
            evaluation=evaluate_completion(req,report,records)
            for k,v in marker['state']['completion'].items():
                if k in evaluation and v!=evaluation[k]:raise ValueError('control completion mismatch')
            if report['status']=='RESEARCH_TERMINATED' or marker['state']['identities'] or marker['state']['rows']:
                raise ValueError('control lacks checked scope')
            return
        ctx=records[0]['context_snapshot']
        expected=state(req,ctx,records,profile)
        if canonical(marker['state'])!=canonical(expected):raise ValueError('control state mismatch')
        reason=marker['reason']
        if report['status']=='RESEARCH_TERMINATED':
            if reason=='REDUNDANT_OPERATION':
                last=records[-1]
                if (last['admission']!='REJECTED' or last['outcome']['status']!='REJECTED'
                        or last['outcome']['reason_code']!='POLICY_NO_GAIN' or not last['proposal']
                        or not redundant(req,ctx,state(req,ctx,records[:-1],profile),last['proposal'],profile)):
                    raise ValueError('control redundancy not established')
            elif termination(req,expected)!=reason:raise ValueError('control termination contradiction')
        elif reason is not None:raise ValueError('control reason on non-system terminal')
    except (KeyError,TypeError,ValueError) as error:
        raise ValueError('invalid control marker: '+str(error)) from error
