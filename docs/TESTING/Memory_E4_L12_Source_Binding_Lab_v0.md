# ANIMA — E4 L1.2 Explicit Source Binding Lab

**Status:** EXPERIMENTAL / OPT-IN / NO PRODUCTION ADMISSION.  
**Pre-implementation scope:** [Source-binding hardening plan](Memory_E4_L12_Source_Binding_Hardening_v0.md).  
**Implementation:** [source-pointer candidate assessor](../../labs/exp009/e4_l12_target_proof.py), [open raw probe](../../labs/exp009/e4_l12_source_probe.py).  
**Adversarial negative tests:** [source-pointer and cross-session alias tests](../../tests/test_memory_e4_l12_source_binding.py).

**Measured outcome:** [Source Binding Hardening Results v0](Memory_E4_L12_Source_Binding_Results_v0.md): 1606 regression PASS on Python 3.12/3.13/3.14; exact typed Event pointers produce *source-only candidate*, unverified cross-session alias targeting abstains. Not production proof.

## Why this layer exists

An ordinary `references: [{kind: event, id: ...}]` is source-supplied attribution. It can show that a user utterance explicitly refers to source Events, **but cannot verify that the user statement is true, that the projection is authoritative, or that Core has admitted a derived revision**. The laboratory separately verifies:

1. Exactly two earlier distinct Event IDs in a versioned prior projection and in the read-only L0 assignment baseline.
2. The previous L0 view grouped these two Events.
3. A caller-supplied immutable source snapshot records the projection ID/revision, exact two source IDs and SHA-256 hashes of canonical source JSON.
4. A later source-user Event in the same bounded session contains **exactly those two typed Event references**, along with a separation report. Extra, missing, duplicated or forged pointers fail closed.
5. The result is `source_pointer_candidate_only` and includes source/trigger digest provenance, always `production_admission=false`, `core_authority_verified=false`, `memory_store_unchanged=true`.

A caller-provided `expected_snapshot` is only a laboratory precondition. The real Core does **not** authenticate or sign it in this experiment. The receipt self-consistency checker re-evaluates the same candidate algorithm, not an independent Core authority verifier. The module is deliberately **not connected** to L1.2's in-memory Episode revision view or to the experimental SQLite journal.

## Cross-session alias scope

A previous-session alias definition can remain a **candidate** when the later Event mentions a shared ambient device. But it cannot select its previous target from that shared device context alone. For cross-session reuse, the *later source Event must explicitly carry the target Entity reference*. Same-session source-scoped behavior remains unchanged. Rejected decisions preserve the candidate source Event IDs.

## Run

```bash
python -m pytest -q tests/test_memory_e4_l12_source_binding.py
python -m labs.exp009.e4_l12_source_probe --output /tmp/e4-l12-source-probe.json
```

The new probes are **developer-authored synthetic variations** and not an independent unseen holdout. Frozen E4 v0 and the 15-case open challenge stay byte-identical; independent existing gold scorers are rerun on both datasets to detect regressions.

## New isolated E4 lifecycle research

[Versioned alias revocation and selective invalidation contract](Memory_E4_L12_Alias_Lifecycle_Contract_v0.md) and [isolated SQLite lifecycle implementation and test plan](Memory_E4_L12_Alias_Lifecycle_Lab_v0.md). This is separate from L1.2 source-target resolution and not connected to production Memory or its read-only evaluator.

## Required next gates

- Separate Core-owned authority for candidate admission and verified projection snapshot identity.
- Conflict-aware alias revocation and source-versioned dependency invalidation (not implemented here).
- Independent unseen challenge and real crash/replay integration, not merely Python exception injection.
- No automatic Knowledge promotion or autonomous L2 Goal/Task admission from these receipts.
