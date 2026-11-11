# ANIMA — E4-U/R/P Independent Gold Audit v0

**Status:** initial independent audit retained; **audit corrections now applied to proposed U/R/P fixtures**, not frozen and not yet E4 runtime-verified.  
**Reviewed base:** `eb2193e70ca60aead01cbc2e61e12375d77ae3e9` (U/R/P input/gold unchanged by A/B corrections).  
**Scope:** 20 root cases: six U, eight R, six P.  
**Reference:** [E4 corpus](Memory_E4_Conformance_Corpus_v0_Draft.md), [Architecture](../ROADMAP/Memory_E4_Architecture_Contract_Draft.md).

## Correction disposition (2026-11-12)

Revisions: U01 low-significance unknown may remain informational; U02 research Goal proposal optional, unsafe power action barred; U06 admitted local investigation attempt and future wake; R01/R06/R07 explicit Core-authorized Task, claim and checkpoint; R02 unlock permits **preflight**, not automatic Task; R04 new occurrence o2 after deduping o1; R05 due tick may preflight again without duplicate effect; R08 wall/control clock domains; P01 optional deferred proposal; P05 explicit derived Event source reference; P06 periodic attempts are not fresh evidence.

**Below is the historical original audit**, preserved for traceability. Labels `BLOCK/REVIEW` refer to the *prior fixture revision*; they are not a claim that the revised fixtures have passed independent semantic acceptance.

## U — uncertainties, goals, investigation

| Case | Verdict | Analysis / proposed correction |
| --- | --- | --- |
| **U01** | REVIEW | A user naming a thing with a novel word does not by itself require a Goal; recording a non-priority uncertainty may be optional depending on specific identity gap. Do not score non-registration as wrong unless the question really affects retrieval. |
| **U02** | REVIEW | Unsafe power connection without verified adapter identity must be blocked; Core may propose investigation, but proposed Goal is *not automatically required*. Specify exact action authority and why identity affects safety. |
| **U03** | PROVISIONAL | Three descriptions of the same adapter-model question should dedupe one uncertainty; ensure no duplicate Goal and no repeated unsupported answers. |
| **U04** | PROVISIONAL | User refusal means no repeated unsolicited prompt. Preserve question state and allow deferred user choice; refusal is not evidence either way. |
| **U05** | PROVISIONAL | User's explicit clarification resolves their referent in scope; must not verify physical change of PSU. |
| **U06** | BLOCK | A `method.result` harness command lacks an admitted Task, versioned method attempt and condition for further wake. Add investigation attempt identity, outcome provenance and next activation condition; `no_progress` is not `closed_unresolved`. |

## R — scheduled, conditional, durable research

| Case | Verdict | Analysis / proposed correction |
| --- | --- | --- |
| **R01** | BLOCK | Expects `Task.queued` without an admitted Goal/Task or authorization in setup. Define Core-created Goal/Task and competition from higher-priority work. |
| **R02** | BLOCK | `task=no_new_task` conflicts with later `capability.available(permission=granted)`. Assert no task **before** unlock, allow eligible review after. Time-trigger must not burn CPU while camera unavailable. |
| **R03** | PROVISIONAL | At due time even without new Events, must run **bounded preflight**; an important question must keep an appropriate review cadence. No automatic costly DEEP call. |
| **R04** | REVIEW | Two identical `occurrence_key=o1` ticks must claim at most once; `rearm` must schedule a **new future occurrence**, not run a second o1 or implicitly execute a method. |
| **R05** | BLOCK | Early evidence change may trigger one preflight, but a later due tick may still legitimately preflight; only duplicate expensive effect/claim should be forbidden. Current `dedupe_due_tick` is too strong/ambiguous. |
| **R06** | BLOCK | Crash-after-claim requires a registered Goal/Task, permitted method, and an effect ledger contract. Without those, one-effect gold is not executable or well-scoped. |
| **R07** | BLOCK | A `Task` cannot resume if no Task was created/admitted. Add checkpoint storage, claimed task identity, reactivation policy and monotonic cursor guarantee across restart. |
| **R08** | REVIEW | Time jump after occurrence o1 should not double-fire. Need explicit **wall vs monotonic vs persisted domain** and restart behavior. Tick labels alone do not establish clock semantics. |

## P — budget, authority, attention

| Case | Verdict | Analysis / proposed correction |
| --- | --- | --- |
| **P01** | REVIEW | Foreground urgent work prevents expensive research execution, but `goal=none` is too strict: Core may register a deferred legitimate investigation Goal. Permit `none` or `deferred`, never steal execution budget. |
| **P02** | PROVISIONAL | External network unavailable **by permission**, despite technical availability; no unauthorized calls. Uncertainty may remain deferred. |
| **P03** | REVIEW | A later user-available notification provides opportunity, not obligation to ask; validate max rate, grouping and opt-out. |
| **P04** | PROVISIONAL | DEEP/LLM may propose ambiguous alias, but no Knowledge authority. Scope and evidence must remain explicit. |
| **P05** | BLOCK | `setup.common_origin='e1'` relies on an untyped claim, not durable source link. Use an explicit validated derived-from Event reference, as in reviewed A04, and prohibit independent evidence votes. |
| **P06** | PROVISIONAL | Consecutive scheduled occurrences are distinct **attempts**, not corroborating evidence; run cheap preflight even without new facts, but do not rerun unchanged expensive methods automatically. |

## Cross-cutting gates

1. **Three independent axes:** epistemic question status, canonical Goal/Task lifecycle, separate schedule eligibility. Do not add invented `Task.status=scheduled` / `waiting_condition` to production enums.
2. **Admission before execution:** provide real or simulated Core authorization, `goal_id`, `task_id`, method scope, `occurrence_key`, budget and allowed evidence. Proposed Goal is not an executed Goal.
3. **Durability:** schedule / claim / method attempt / checkpoint / effect ledger must survive crash without dupes, including `after_claim_before_effect`. The same occurrence replays idempotently; new period occurrence is distinct but not new evidence.
4. **Scheduling semantics:** distinguish `due for preflight` from `approved costly investigation` and `eligible` from `executed`; ensure deferred important research still gets periodic reassessment without second-by-second polling.
5. **Resource / user boundaries:** local cheap first; skip/queue DEEP if resource-limited; allow explicit user refusal and rate-limited, context-appropriate question batching.
6. **No gold leakage:** policy/clock/effect artifacts are fixture-provided constraints; outcomes stay in gold only.

## Gate

**E4-U/R/P freeze: BLOCKED** until missing Core/Task, source link, clock and outcome preconditions are specified for the BLOCK cases. These are test-fixture design defects, not demonstrated production failures. No model, Core or memory regression claim follows from this audit.
