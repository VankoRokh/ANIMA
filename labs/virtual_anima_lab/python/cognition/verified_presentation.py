"""Deterministic consumer boundary over an already checked Hybrid Result.

Not import authentication, a prose verifier, UI or canonical Task integration.
No service I/O or generation; never manufactures model text.
"""
from copy import deepcopy

SCHEMA='anima.lab.verified_presentation/0.1'


def _missing_units(completion):
    if completion is None:return None
    if completion['information_requirement_satisfied']:return []
    req=completion['requirement'];kind=req['kind']
    if kind=='verified_observation':return [{'kind':'verified_primary_observation','entity_ref':e,'required_operation':'lookup_raw_evidence'} for e in completion['missing_entities']]
    if kind=='historical_and_latest_observation':
        units=[{'kind':'verified_historical_observation','entity_ref':e} for e in completion['missing_entities']]
        if completion['latest_source'] is None:units.append({'kind':'verified_latest_captured_sample'})
        return units
    if kind=='empty_search':return [{'kind':'bounded_empty_search','query':req['query']}]
    return [{'kind':'no_service_read_violated','completed_service_reads':completion['completed_service_reads']}]


def project_verified_presentation(result):
    facts=result['evidence']['facts'];model_facts=result['evidence']['model_claims']['verified_candidates'];reasoning=result['reasoning'];presentation=result['presentation']
    if any(f['verdict']['status']!='VERIFIED' or f['verdict']['claim']['scope'] not in ('source_sample','latest_captured_sample') for f in facts+model_facts):
        raise ValueError('checked bounded facts required')
    completion=result['information']['completion'];research=reasoning['research_final_index'];projection=reasoning['projection_final_index']
    limitations=['CAPTURED_SAMPLE_SCOPE_ONLY','MODEL_PROSE_UNVERIFIED','NO_TASK_COMPLETION_VERDICT']
    if result['information']['status']=='INCOMPLETE':limitations.append('INCOMPLETE_INFORMATION')
    if research is None:limitations.append('NO_ACCEPTED_RESEARCH_FINAL')
    if not facts:limitations.append('NO_VERIFIED_FACTS')
    return {'schema':SCHEMA,'trust_boundary':'DERIVED_FROM_CHECKED_LAB_RESULT_NOT_IMPORT_AUTHENTICATION',
        'verified_facts':deepcopy(facts),'verified_model_claims':deepcopy(model_facts),'source_references':deepcopy(result['evidence']['source_references']),
        'information':{'status':result['information']['status'],'missing_units':_missing_units(completion),'requirement':deepcopy(completion['requirement']) if completion else None,
            'missing_entities':deepcopy(completion.get('missing_entities',[])) if completion else None,
            'missing_requirements':deepcopy(completion.get('missing_requirements',[])) if completion else None,
            'reason_code':completion['reason_code'] if completion else 'NOT_ASSESSED'},
        'limitations':limitations,'accepted_research_final':{'status':'ACCEPTED_PROTOCOL_FINAL' if research is not None else 'NO_ACCEPTED_RESEARCH_FINAL','model_call_index':research,'authority':'UNVERIFIED'},
        'projection':{'generation_status':reasoning['projection_status'],'accepted_final_status':'ACCEPTED_PROTOCOL_FINAL' if projection is not None else 'NO_ACCEPTED_PROJECTION_FINAL',
            'model_call_index':projection,'claim_assessment_phase':result['evidence']['model_claims']['phase'],'claim_assessment_status':result['evidence']['model_claims']['status']},
        'unverified_model_prose':{'research':presentation['model_text'],'projection':presentation['projection_text'],'authority':'UNVERIFIED','whole_answer_verified':False},
        'global_verification':'NOT_ESTABLISHED','task_completion':'NOT_ESTABLISHED'}
