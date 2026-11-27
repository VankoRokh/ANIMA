"""R945 bounded host feedback: checked prerequisites, never hidden answers."""
from collections import Counter
from anima.agent.native_tools import canonical
from .control_policy import state
from .source_policy import TurnSourcePolicy

SCHEMA='anima.lab.requirement_feedback/0.1'


def build_feedback(requirement,context,records,visible_ids,budget,remaining_calls):
    if requirement.kind=='no_service_read':raise ValueError('no-service-read has no research continuation')
    view=state(requirement,context,records,profile='r945/0.1');completion=view['completion']
    if completion['information_requirement_satisfied']:raise ValueError('feedback requires missing evidence')
    missing=[]
    if requirement.kind=='verified_observation':
        missing=[{'kind':'verified_primary_observation','entity_ref':e,'required_operation':'lookup_raw_evidence'} for e in completion['missing_entities']]
        required=len(requirement.entities)
    elif requirement.kind=='historical_and_latest_observation':
        missing=[{'kind':'verified_historical_observation','entity_ref':e} for e in completion['missing_entities']]
        if completion['latest_source'] is None:missing.append({'kind':'verified_latest_captured_sample'})
        required=len(requirement.entities)+1
    else:
        missing=[] if completion['information_requirement_satisfied'] else [{'kind':'bounded_empty_search','query':requirement.query}]
        required=1
    policy=TurnSourcePolicy(context)
    for record in records:
        if record['outcome']['status']=='COMPLETED':policy.record_completed(record['proposal']['operation_kind'],record['outcome']['result'])
    references=sorted(set(visible_ids)&set(policy.exposed_bindings()))
    limits=budget['limits'];lookup_only=requirement.kind=='verified_observation'
    result={'schema':SCHEMA,'type':'information_requirement_feedback','status':'INCOMPLETE',
        'reason_code':completion['reason_code'],'checked_operation_prefix':len(records),
        'lookup_only_prerequisite':lookup_only,'verified_primary_source_rows':len(view['rows']),
        'checked_coverage':{'required_units':required,'covered_units':required-len(missing),'information_requirement_satisfied':completion['information_requirement_satisfied']},
        'missing_units':missing,'missing_units_total':len(missing),'missing_units_truncated':False,
        'completed_operations':dict(Counter(k for k,_ in view['completed_operations'])),
        'permitted_visible_event_ids':references,'visible_references_total':len(references),'visible_references_truncated':False,
        'availability':{'history':'ENABLED_BOUNDED_SCOPE' if context['memory_enabled'] else 'DISABLED_BY_POLICY','missing_units_recoverability':view['recoverability']},
        'source_read_success':'NOT_ESTABLISHED_BY_METADATA',
        'remaining_budget':{'model_calls':min(remaining_calls,max(0,limits['max_calls']-budget['reserved_calls'])),
            'reported_input_tokens':max(0,limits['max_reported_input_tokens']-budget['reported_input_tokens']),
            'output_tokens':max(0,limits['max_reported_output_tokens']-budget['reported_output_tokens']),
            'elapsed_policy':'RECHECKED_BY_HOST_AT_CALL_BOUNDARIES'},
        'message':('Retrieved metadata or another operation does not satisfy the admitted lookup_raw_evidence prerequisite. ' if lookup_only else 'Required verified evidence or bounded search is still missing. ')+
                  'Only already visible permitted references may be used. You may continue with available tools or stop with uncertainty.'}
    # Preserve the existing 2048-byte NativeToolSession feedback ceiling.
    # Counts and explicit truncation survive; omitted units are never covered.
    while len(canonical(result).encode('utf-8'))>2048:
        if result['permitted_visible_event_ids']:
            result['permitted_visible_event_ids'].pop();result['visible_references_truncated']=True
        elif result['missing_units']:
            result['missing_units'].pop();result['missing_units_truncated']=True
        else:raise ValueError('bounded feedback envelope exceeds existing budget')
    return result
