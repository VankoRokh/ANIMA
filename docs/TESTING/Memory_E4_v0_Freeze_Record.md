# ANIMA — Memory E4 v0 Frozen Design Baseline

**State:** **FROZEN DESIGN FIXTURES**, semantic oracle **PROVISIONAL**, production E4 conformance **NOT ASSESSED**.  
**Date:** 2026-11-12.  
**Manifest:** [`memory_e4_frozen_manifest_v0.json`](Fixtures/memory_e4_frozen_manifest_v0.json).  
**Adjudication:** [E4 Gold Adjudication v0](Memory_E4_Gold_Adjudication_v0.md).  
**Runtime plan:** [E4 Runner Contract v0](Memory_E4_Runner_Contract_v0.md).

## Frozen scope

| Suite | Cases | Synthetic Events | Gold checks |
| --- | ---: | ---: | ---: |
| E4 root | 42 | 75 | 94 |
| E4 visible development negatives | 15 | 25 | 28 |
| **Total** | **57** | **100** | **122** |

Both inputs and the *proposed* gold labels are pinned by exact Git blob SHA-1 plus byte length. Four ambiguous cases have accepted **bounded alternatives** for experimental scoring: `B02` (candidate/abstain), `U01` (register/leave in raw), `U02` (propose research/no Goal), `P01` (no research/deferred proposal). No inferred tool authority, actual hardware action or Knowledge confirmation results.

**Freeze is a reproducibility boundary**: these E4 v0 source bytes shall not be silently edited to improve algorithm scores. Changes require a new explicitly named fixture revision/corpus v0.1, a before/after diff, re-adjudication, and updated hashes. This does not prevent adding *new* independent fixtures or executors in separate files.

## Truth and approval distinctions

- Conversation author has authorized **proceeding** with this baseline workflow and previously agreed to the principles; this is **not** a claim that they individually audited every label.
- Gold is **assistant-proposed and technically reviewed**, but no independent second annotator/blinded assessor has checked all 122 assertions.
- `FROZEN_DESIGN_BASELINE_V0` is **not** `E4_PASSED`, `verified_knowledge`, `production_ready` or `owner_approved_gold`.
- No blinded holdout exists. The 15 negatives are **development-visible** and count as a negative regression suite only.
- The `candidate_manifest` from the previous commit documents the predecessor snapshot and is **superseded** for current-branch verification by the frozen manifest.

## Status of execution

Existing GitHub CI (last confirmed baseline `906229bcc2c3d12103c686028360c791100dc703`) passed 1533 regression tests on Python 3.12, 3.13 and 3.14. A future CI run is required to verify this exact freeze commit. Those tests verify static source integrity and regression, not semantic capability. L0 Shadow observations are read-only and are not Story, investigation or scheduling proofs.

## Remaining research gates

1. Explicit owner/independent detailed gold adjudication of contentious cases.
2. L1 Episode/Story/Entity read-only E4 adapter and external trace scorer.
3. L2 schedule virtual-time and Core authority contracts.
4. L3 interruption/transaction/crash replay conformance.
5. New hidden independent holdout, then Raspberry Pi resource and power-loss trials.

**Production stores, Core authority and MemoryProcessor were not changed.**
