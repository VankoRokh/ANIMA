# ANIMA — E4 L1.2 Explicit Source Binding Hardening Results v0

**Status:** MEASURED OPEN DEVELOPMENT LAB PASS; **NO production-memory admission**.  
**Tested snapshot:** `fa8d0b1eda894d37d786e2f2b764dc9543f62671`.  
**CI:** [GitHub Actions #43197148675](https://github.com/VankoRokh/ANIMA/actions/runs/43197148675) — SUCCESS, **1606 full regression tests PASS** on Python **3.12, 3.13 and 3.14** (98 targeted profile tests PASS each).  
**Design before implementation:** [Source Binding Hardening Study](Memory_E4_L12_Source_Binding_Hardening_v0.md).  
**Lab:** [L1.2 Source Binding Lab](Memory_E4_L12_Source_Binding_Lab_v0.md).  
**Artifacts:** `e4-l12-source-binding-probe-py314` (closed five-case raw probe) and `e4-l12-scoped-lab-evaluation-py314` (frozen positive/negative traces, independent scored evaluations and paired deltas, visible challenge). GitHub Actions artifact retention 14 days.

## Measured raw source-binding decisions

| Synthetic scenario | Raw status | Reason / meaning |
| --- | --- | --- |
| A correction without `kind:event` references | `rejected_or_insufficient` | `no_explicit_source_event_pointers` |
| Correction with **two exact typed Event IDs**, matching prior L0 grouping, projection ID/revision and SHA-256 snapshot | `source_pointer_candidate_only` | Scoped *source claim* targeting `proj_d01` revision 1; **not** semantic/world proof |
| Correction contains only one of the two Event IDs | `rejected_or_insufficient` | `wrong_or_ambiguous_typed_source_pointers` |
| Original source Event body changed while expected snapshot stayed fixed | `rejected_or_insufficient` | `projection_snapshot_mismatch` |
| Old-session alias inferred merely from shared Pi5 contextual Entity | `insufficient` | `cross_session_context_not_target_bound`; source candidate retained, **target not chosen** |

No raw Events, production Memory, Core authority, Goal/Task or Knowledge were changed. Every successful source-pointer receipt reports `production_admission=false`, `core_authority_verified=false`, `memory_store_unchanged=true`. All tests concern a laboratory **caller-supplied** snapshot; **Core does not sign/authenticate it** and `verify_receipt` checks consistency with the same lab method, not an independent authority policy.

## Additional negative tests

- Wrong, duplicate, missing, extra and foreign event references must fail closed.
- Wrong prior revision or changed original source SHA-256 must fail closed.
- A later source report from unknown relay, another session, stale timestamp or incompatible Event type cannot create a source-pointer candidate.
- Lack of an explicit separation report remains insufficient even when two Event pointers exist.
- Forged receipt (`production_admission=true`) or changed trigger checksum is rejected.
- A previously unmerged L0 pair or duplicate raw Event ID is rejected.
- Alias definition from another session cannot select a target merely because its ambient Pi5 anchor recurs; an explicit later reference to the target Entity is required.
- L1.2, L1.1 and the existing base E4 evaluator remain separate. No full E4 claim.

## Regression and fixture integrity

| Corpus | Cases | Gold checks | PASS | FAIL | NOT_SUPPORTED |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen E4 v0 | 57 | 122 | **41** | **0** | **81** |
| Visible 15-case challenge | 15 | 16 | **16** | **0** | 0 |

**Zero changed statuses and zero PASS→FAIL regressions** in the independent frozen L1.1→L1.2 differential files. **All 99 forbidden E4 obligations still NOT_SUPPORTED**: absence of real effect/authority ledgers is not proof of safety.

Git blob SHA-1 and sizes were separately rechecked against both manifests at this snapshot: four frozen v0 JSONs and two predeclared challenge JSONs are **byte-identical** to their pinned versions.

## Remaining architectural blockers

1. **No production provenance authority.** A source `kind:event` link and the caller-provided projection snapshot are inputs to a lab, not a Core-authenticated revision request. Core-owned admission and verifier independence remain missing.
2. **No durable application or undo.** The explicit-pointer receipt is intentionally not connected to the experimental SQLite revision journal, Episode projection heads, dependency invalidation, or production Memory.
3. **No general cross-session Entity lifecycle.** Ambiguity handling improved, but revocation, semantic versioning, contradiction and selective dependency reevaluation are not implemented.
4. **No external blind holdout.** Both this probe and earlier 15-case corpus were authored in the same development workflow. Good scores on visible cases do not demonstrate broad validity or field-ready performance.
5. **No L2 effects.** Unknown Goal/Task authority, periodic investigation and SLEEP integration remain separate research gates.

**Follow-up:** the isolated [versioned Alias Lifecycle experiment](Memory_E4_L12_Alias_Lifecycle_Results_v0.md) subsequently measured selective Story/Episode invalidation and simulated recovery; it remains outside production Memory.

**Verdict:** source-binding hardening and the separate alias lifecycle lab are reproducible limited experiments; **E4 production and action-enabled L2 remain NO-GO**.
