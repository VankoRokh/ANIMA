"""Pure lexical normalization contract; no sources, labels or authority."""
import re

def tokens(query):
    return tuple(sorted(set(re.findall(r'[a-z0-9]{3,}',query.lower()))))

def query_key(query):
    # Exact-reference ranking observes the original stripped lower text as
    # well as ASCII terms. casefold would incorrectly merge ß and ss.
    return (query.strip().lower(),tokens(query))

def explain(entity,query):
    ref=entity['entity_ref'].lower();terms=set(tokens(query));words=set(tokens(ref))
    hits={t for t in terms if t in ref};whole=terms & words
    terminal=re.split(r'[._:/-]',ref)[-1]
    # Structural opaque-ID penalty, no dictionary of preferred entities.
    opaque=(len(set(terminal))<=1 or bool(re.fullmatch(r'[a-f0-9]{16,}',terminal)))
    return {'exact_reference':ref==query.strip().lower(),'term_hits':len(hits),
            'whole_term_hits':len(whole),'opaque_terminal':opaque,'eligible':bool(hits)}

def rank(entities,query):
    scored=[]
    for entity in entities:
        e=explain(entity,query)
        if e['eligible']:
            scored.append(((-int(e['exact_reference']),-e['term_hits'],-e['whole_term_hits'],int(e['opaque_terminal']),entity['entity_ref']),entity))
    return [entity for _,entity in sorted(scored,key=lambda x:x[0])]
