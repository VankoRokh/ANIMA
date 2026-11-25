# ANIMA v0.2 — E2.6 R1–R7 owner validation record

Дата: 2026-11-25. Исследовательская запись; не release acceptance и не independent audit verdict.

## Frozen scope

- Original audit: `3be32282e6452e2b99cbb1decfa7629898ef1216`, PR #45, BLOCKED.
- Release baseline: `1364e62634669ef553df0b2f2d7a1159d404383f`.
- Candidate: `508851d458cf759902aa35c9ae140780fb29c4a0`, Draft PR #51.
- Audit ref: `audit/v02-e26-r8-reaudit-candidate` (created at candidate SHA; audit by SHA).
- Documentation ref: `work/v02-e26-r8-audit-prep`; not the tested implementation.
- R8 does not admit new capabilities, change prompts, scoring or budgets, or authorize merge.

## Remediation chain

Owner results and PR descriptions below are inputs to independent review, not closure.

| Finding | PR / stage | SHA | Owner evidence |
| --- | --- | --- | --- |
| CA-01 High | #46 R1 | `b8e5d23ccf1c4da45bd0247d4a8df9009698ad59` | Persisted canonical identity before effects/finalization; 35 targeted, 2682 full; L02 zero tick/revision delta |
| CA-02 Medium | #47 R2 | `33dd8e6a63ca648287a5202fd217d4e1fe476c40` | Scoped gateway admission; 40 targeted, 2687 full; L01/L02 reject before effects |
| CA-03 Medium | #48 R3 | `7c7bd308976b7a1301f0e39be0696c0e2e2ee511` | Coordinator-owned source admission, memory OFF latest-only; 204 targeted, 2698 full |
| CA-04 Low / CA-07 Low | #49 R4 | `415c31911e3fd3dc1257e4a9fe5d13bef7f06a3a` | Pending handle identity and partial usage; 214 targeted, 2708 full |
| CA-05 Medium / CA-06 Medium | #50 R5 | `08efa20ab20e0aaa7fafd0d65cd309b845d8cb5b` | Synthetic Raw, source binding, exact request replay; 223 targeted, 2717 full; live evidence verifier PASS, exact replay responses differed |
| Temporal projection | #51 R6 | `508851d458cf759902aa35c9ae140780fb29c4a0` | Optional deterministic host projection; 233 targeted, 2727 full; targeted C06 host verified 1/2, incomplete 1/2 |

## R7 comprehensive validation

Owner execution: Python 3.14.4, Godot 4.7.2.stable.official.ed1daf0bf. Project checks passed (202 pages, 1388 local links, 449 Python files). Integration targeted 66 passed; full pytest 2727 passed in 104.56 s. VAL P5-C 4/4, M2 integrated Godot, E1.2–E1.4, E2.1–E2.5C live/integration gates PASS. Paired memory conflict 8/8: familiar memory ON/OFF 2/4 actions, relocated 4/2 on both seeds. Not a physical-world or restart durability guarantee.

| Metric | Control | Host |
| --- | ---: | ---: |
| Cases | 14 | 14 |
| Strict operation / information pass | 7 | 10 |
| Model stopped with missing information | 5 | 4 |
| Continued turns / satisfied | 6/0 | 6/2 |
| MODEL_CALL_LIMIT | 2 | 5 |
| Model claim format valid / objective pass | 6/6 | 7/7 |
| Model typed claims verified / contradicted / unsupported | 3/0/0 | 5/0/0 |
| Temporal information pass | 0/2 | 1/2 |
| Model temporal claim pass | 0/2 | 0/2 |
| Host temporal claim pass | N/A | 1/2 |
| Evidence cases / Raw samples / requests | 14/6/45 | 14/6/47 |

Both suites: E26B_OPERATION_GATE_FAIL. Both owner evidence verifiers: E26_EVIDENCE_VERIFIED, scope integrity_and_source_binding_not_backend_attestation. All 28 case records report world_unchanged and canonical_baseline_unchanged; independently confirm. Probes (not generated claim errors): Control verified/contradicted/unsupported 5/5/20, Host 8/8/14.

| Case | Control 7 | Control 8 | Host 7 | Host 8 |
| --- | --- | --- | --- | --- |
| C01 | FAIL | FAIL | PASS | PASS |
| C02 | PASS | PASS | PASS | PASS |
| C03 | PASS | PASS | PASS | PASS |
| C06 | FAIL | FAIL | PASS | FAIL |
| C09 | PASS | PASS | PASS | PASS |
| C02_OFF | FAIL | FAIL | FAIL | FAIL |
| C03_ALT | PASS | FAIL | PASS | FAIL |

C02_OFF: required empty search not confirmed in all four. C03_ALT seed 8: primary source unverified despite confident prose. C06 Host seed 7: two typed claims verified (historical observed, latest captured not observed); zero new model calls/service reads, no knowledge write, world truth not established. Seed 8: historical evidence incomplete; no claims generated. Host performance difference is observational, not causal proof; world seeds do not fix model requests.

Preliminary manual prose review: Control C01 seed 8 and Host C02_OFF seed 8 promise future action after stop; Host C01 seed 8 ambiguous absent property; Host C03 seed 8 overextends historical evidence to world presence; Host C06 seed 7 overextends latest capture to current visibility; Host C03_ALT seed 8 asserts verification not established. Empty search is bounded to accessible records. All semantic_review fields remain PENDING in original reports. Do not rewrite source reports or count empty claims as semantic success.

## Evidence inventory

Owner local bundle (not committed; inspect for secrets before sharing):
- ANIMA-E26-Audit-Evidence.zip
- ANIMA-E26-Independent-Audit-Reproduction.zip
- ANIMA-E26-R1-R6-Evidence.tar.gz (R1/R2/R5/R6 directories; no separately recovered R3/R4 directories)
- ANIMA-E26-R7-Evidence.tar.gz (610 archive entries; SHA256 `28e0a7cb1a26435c53c758e34dbf11bcc56978fe8912b242597adc5683870827`)
- SHA256SUMS.txt (owner reports all four checks OK)
- Original independent audit report and R8 audit brief supplied separately.

Archive integrity is not semantic validity or backend attestation. Raw archives not independently re-read by report author; owner summaries, retrieved result text, PR metadata only. R3/R4 targeted historical logs not recovered as separate dirs; repeat targeted tests independently. Audit must assess exact-request replay and identity variation coverage; lack of full-suite exact replay must remain explicit if unverified.

## Disposition

R7 execution COMPLETED; deterministic integration PASS; evidence verifier PASS; cognition operation FAIL (partial case success); independent semantic review PENDING. CA-01–CA-07 remediation candidates, not closed. R8 independent reaudit required: compare original and candidate SHAs, reproduce original negative tests and cross-fix interactions; reevaluate F01–F17, all claim scopes, budget, interrupted turns, trust boundaries, exact replay and provenance. Explicit NOT_RUN for unavailable tests. No merge, new model capabilities, or release promotion pending independent verdict.
