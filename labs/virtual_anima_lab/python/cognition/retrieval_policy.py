"""Pure lexical normalization contract; no sources, labels or authority."""
import re

def tokens(query):
    return tuple(sorted(set(re.findall(r'[a-z0-9]{3,}',query.lower()))))

def query_key(query):
    # Exact-reference ranking observes the original stripped lower text as
    # well as ASCII terms. casefold would incorrectly merge ß and ss.
    return (query.strip().lower(),tokens(query))
