# ANIMA — Independent E4 L1 Evaluator v0

**Status:** executable, post-hoc diagnostic only; **not** an E4 conformance PASS.  
**Frozen corpus:** [E4 design freeze](Memory_E4_v0_Freeze_Record.md).  
**Input runner:** [E4 L1 conservative association lab](Memory_E4_L1_Conservative_Lab_v0.md).  
**Independent scorer:** [\`labs/exp009/e4_evaluator.py\`](../../labs/exp009/e4_evaluator.py).

## Separation

L1 **runs first**, reads only frozen input JSON, and writes a closed raw trace. The evaluator **does not import or call L0/L1**. Invoked in a separate process later, it loads the raw trace, verifies Event IDs, source pointers, case order, control declarations, and frozen manifest SHA-1 + byte counts before comparing against proposed gold. It records SHA-256 of the exact trace bytes. These are reproducibility fingerprints, **not a cryptographic attestation**. Output files are created exclusively (no silent overwrite), and raw traces are not modified.

\`\`\`bash
mkdir -p e4-results
python -m labs.exp009.e4_l0_observation --level L1 --suite positive --output e4-results/e4_l1_positive_raw.json
python -m labs.exp009.e4_l0_observation --level L1 --suite negative --output e4-results/e4_l1_negative_raw.json
python -m labs.exp009.e4_evaluator --suite positive --trace e4-results/e4_l1_positive_raw.json --output e4-results/e4_positive_evaluation.json --print-summary
python -m labs.exp009.e4_evaluator --suite negative --trace e4-results/e4_l1_negative_raw.json --output e4-results/e4_negative_evaluation.json --print-summary
\`\`\`

## Verdicts — per gold check

| Status | Precise meaning |
| --- | --- |
| \`PASS\` | Observed *narrow L0/L1* trace meets the supported gold sub-contract. **Not** E4 acceptance. |
| \`FAIL\` | An actually observed and supported trace contradicts that scoped gold condition. |
| \`NOT_SUPPORTED\` | No implemented L1 capability for that requirement, or Shadow skipped the source Event. |
| \`NOT_OBSERVED\` | An observable capability exists but the required record is missing (e.g. a Story pair). |

**Critical denominators:** \`coverage=(PASS+FAIL)/total_gold_checks\`, \`observed_pass_rate=PASS/(PASS+FAIL)\`. Show **both**, separately for root and development negatives. Never report observed pass rate alone as E4 quality. Every \`forbidden\` obligation is emitted separately and remains \`NOT_SUPPORTED\` pending independent authority/effect/Knowledge instrumentation. Lack of effect logs never proves an action was correctly prevented.

## Supported diagnostic subcontracts

- \`episode_pair same|distinct\`: compare L0 Shadow assignments if both Events were consumed; report \`L0_SHADOW_PROXY\`, **not** E4 Episode segmentation.
- \`story_pair\`: compare scoped L1 source-reported link labels and frozen bounded alternatives. Source-reported \`not_same_case_reported\` may satisfy case-scoped \`not_same_case\` without upgrading to externally verified truth.
- \`alias confirmed_in_scope|known_reuse|unresolved\`: explicit speaker-intent record, source-backed limited reuse, or *positive* lexical abstention. Absent mention never counts as a correct unknown.
- \`evidence same_origin_not_independent|no_duplicate_evidence\`: typed parent Event pointer only; **authenticity of an external source remains unverified**.
- \`budget no_expensive_method\`: only for a traced explicit alias-cache reuse counter. Not a Goal/Task budget check.

Other gold dimensions (UncertaintyRegistry, long-running Goal/Task, scheduler, sleep publication, recovery, actual effects, real-world temporal resolution) are \`NOT_SUPPORTED\` until an independent, instrumented interface exists. No full E4 score is computed.

## Measured snapshot

[Independent E4 L1 Evaluation Results v0](Memory_E4_L1_Evaluation_Results_v0.md) records the 57-case assessment: **35 PASS, 4 FAIL, 83 NOT_SUPPORTED** among 122 gold checks, plus all 99 forbidden obligations unsupported. This is a limited L0/L1 diagnostic, not E4 conformance.

## Integrity safeguards

Reject invalid manifest hashes, unknown/duplicate cases, wrong Event sequence or assignment, fabricated Story evidence IDs, aliases without source-backed Entity references, made-up source Event pointers, missing synthetic control declarations or L1 claiming semantic conformance. A missing Story pair is \`NOT_OBSERVED\` rather than a PASS for \`insufficient\`.

The CLI exits nonzero for integrity/IO failures. An actual \`FAIL\` on a valid research case is an **experimental observation**, not a CI failure. CI publishes the independent score reports and raw traces for the 42+15 **visible** cases, under the single Python 3.14 matrix job to avoid unnecessary artifact duplication.

The frozen gold is still provisional. Neither a green CI nor observed PASS on a subset establishes E4 conformance, a successfully integrated Memory, or a blinded holdout.
