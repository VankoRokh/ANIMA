# ANIMA — E4 L1 Conservative Association Lab v0

**Status:** executable experimental read-only L1 slice; **not** E4 conformance.  
**Sources:** [Frozen baseline](Memory_E4_v0_Freeze_Record.md), [Runner contract](Memory_E4_Runner_Contract_v0.md), [L1 adapter](../../labs/exp009/e4_l1_association.py).

## Contract

This stage extends existing Shadow episode raw observations without changing their decisions. It produces **reported Story case relation proposals**, **explicit source-user intent aliases**, and **typed Event-source pointers**. It does not create or rewrite Story/Memory/Entity stores, does not write Knowledge, does not invoke LLM, Core or tools, and does not grade itself on frozen gold.

Input: frozen raw Event records and fixture Entity registry, one isolated case at a time. Gold JSON is never opened.

Output:
- \`episode_baseline\`: existing Shadow decisions, groups and event assignments, not new E4 Episode segmentation.
- \`story_pair_assessments\`: every pair receives \`same_case_reported\`, \`not_same_case_reported\`, \`candidate_only\` or \`insufficient\` with source Event IDs and reasons. Matching explicit ticket/case numbers require same reporter and namespace; a later explicit multi-component incident message can link two earlier local Event sources but never establish physical causality.
- \`alias_records\`: only an explicit definition by the originating user with one typed Entity source ref can confirm **that speaker's intended referent**, in session/entity context. \`alias_mentions\` records limited reuse with provenance, or abstention. No global synonym map; lexical rules are deliberately narrow.
- \`source_origin_links\`: typed Event parent-pointer records, never a second independent witness.
- \`unsupported_controls\` and \`unsupported_capabilities\`: missing scheduling, Goal/Task, SLEEP, crash/replay and semantic NLP remain visible.
- \`semantic_conformance=NOT_ASSESSED\`: no oracle score or PASS claim.

## Run

\`\`\`bash
python -m labs.exp009.e4_l0_observation --level L1 --case E4-B03 --output /tmp/e4-b03-l1.json
python -m labs.exp009.e4_l0_observation --level L1 --suite negative --case E4-N04
\`\`\`

L0 is default, \`--level L0\`; L1 is a separate optional path. The runner reads pinned inputs only and creates temporary SQLite in a sandbox. Outputs are user-visible raw decisions, not benchmark results.

## Failure boundaries

A recognized ticket ID may still be an unsupported claim from an unknown source, or the same ID in a different namespace. Repeated words do not establish a same-case relation. The small label parser is neither general Russian lemmatization nor trained Entity Resolution; it only recognizes limited explicit phrases. Source-reference validation is fixture-specific, and fixture Entity keys are not an autonomous ontology.

Next gate: an **independent external evaluator** must compare sealed raw traces against frozen provisional gold and distinguish \`PASS\`, \`FAIL\`, \`NOT_OBSERVED\`, \`NOT_SUPPORTED\`. Its denominator must reflect supported capabilities and abstentions; the frozen 57-case suite is visible development data, not a blinded holdout.
