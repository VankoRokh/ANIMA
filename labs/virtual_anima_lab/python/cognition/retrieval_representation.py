"""R945 host-owned lexical metadata, separate from stable model description."""
from copy import deepcopy
from .retrieval_policy import explain

PROFILE='r945/0.1'
ALGORITHM='r943/0.1'
ACTUAL_STRATEGY='r943/0.1_lexical_coverage_opaque_id_tiebreak'
MODEL_DESCRIPTION='ranked_lexical_not_semantic_retrieval'


def model_search_view(result):
    """Caller supplies a schema-checked ranked lexical result. No new data."""
    if result['kind']!='working_world_memory_search':raise ValueError('lexical search result required')
    return {**deepcopy(result),'strategy':MODEL_DESCRIPTION}


def journal_metadata(arguments,result):
    if result['strategy']!=ACTUAL_STRATEGY:raise ValueError('actual lexical algorithm mismatch')
    return {'schema':'anima.lab.retrieval_metadata/0.1','algorithm':ALGORITHM,'family':'ranked_lexical',
            'original_query':arguments['query'],'candidate_count':result['possible_matches'],
            'returned':result['returned'],'truncated':result['truncated'],'explanation_scope':'RETURNED_CANDIDATES',
            'explanations':[{'entity_ref':row['entity_ref'],**explain(row,arguments['query'])} for row in result['records']],
            'model_description':MODEL_DESCRIPTION}
