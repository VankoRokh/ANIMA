# ANIMA — E4 L1.1 Experimental Evaluation Results v0

**Status:** MEASURED L1.1 IMPROVEMENT / FULL E4 CONFORMANCE **NOT VERIFIED**.  
**Measured commit:** `3827ad5185bf6aab8344e4179d485019c0106ea2`.  
**CI:** [GitHub Actions #43175426276](https://github.com/VankoRokh/ANIMA/actions/runs/43175426276) — SUCCESS: **1561 full-regression PASS** on Python 3.12, 3.13, 3.14.  
**Raw artifact:** `e4-l11-lab-differential-py314` (two L1.1 raw traces, two separate gold evaluations and two L1→L1.1 diffs; retention 14 days).  
**Research basis:** [Pre-implementation failure research](Memory_E4_L11_Failure_Research_v0.md).  
**Frozen corpus:** unchanged, 42 root + 15 development negatives, 100 Events, 122 gold checks, gold still provisional.

## L1 vs L1.1 on identical frozen fixtures

| Suite | Checks | L1 PASS | L1 FAIL | L1 NOT_SUPPORTED | L1.1 PASS | L1.1 FAIL | L1.1 NOT_SUPPORTED |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Root (42) | 94 | 30 | 2 | 62 | **34** | **0** | 60 |
| Visible negatives (15) | 28 | 5 | 2 | 21 | **7** | **0** | 21 |
| **Combined (57)** | **122** | **35** | **4** | **83** | **41** | **0** | **81** |

Coverage: **39/122 = 32.0%** → **41/122 = 33.6%**. Among *observed* checks only: **35/39 = 89.7%** → **41/41 = 100%**. These are selective L0/L1/L1.1 **lab proxy** metrics, **not ANIMA E4 accuracy**. All **99 forbidden obligations** remain `NOT_SUPPORTED` because no independent Core authority, Knowledge, side-effect or crash-recovery ledger was exercised.

## Exactly six changed results; no gold regressions

| ID | Before → after | Mechanism |
| --- | --- | --- |
| `E4-D01:check:1` | NOT_SUPPORTED → PASS | Lab-only derived Episode resegmentation proposal, raw Events preserved |
| `E4-D01:check:2` | FAIL (`same`) → PASS (`distinct`) | Revised *temporary view* separates two explicitly independent trials; original Shadow assignment retained |
| `E4-D01:check:3` | NOT_SUPPORTED → PASS | In-memory projection version 1→2 with source Event IDs and later user correction |
| `E4-U05:check:2` | FAIL → PASS | Source-preserving bounded grammatical normalization: `чёрной коробочкой` ↔ `чёрная коробочка` |
| `E4-N01:check:2` | FAIL → PASS | Explicit reported incident ID A9 connects different devices without merging device Episodes |
| `E4-N04:check:1` | FAIL → PASS | Verified **distinct** case namespaces Alpha/Beta permit scoped `not_same_case_reported`; unknown namespaces still abstain |

Differential comparison validates matching check IDs and expected values and reports **zero PASS→non-PASS regressions** over 122 visible gold checks.

## Additional adversarial guard

A new non-frozen unit test exercises two reports repeating the same ticket number from **one unknown relay source**. L1.1 now emits `insufficient` instead of promoting the two matching strings to `same_case_reported`. This is a visible developer counterexample, **not** a blinded holdout. Other tests cover unsupported source corrections, missing prior projection, identical trial IDs, unverified namespace differences, forged revision IDs and alias canonicalization.

## Limits and next gate

1. D01 only revises a **temporary derived grouping**; production Memory was not changed and no durable crash/replay rollback was verified.
2. Alias normalization handles a **narrow grammatical pattern**, not general Russian morphology or cross-context Entity Resolution.
3. Story links are attributable reports of case continuity, not independently verified external truth. A fixture-provided trusted namespace is a simulated precondition, not automatically discovered real-world authority.
4. Gold is frozen but provisionally adjudicated; 57 visible development cases do **not** show blind generalization.
5. L2 scheduling, Goal/Task execution, SLEEP and all 99 prohibitions remain outside observed coverage.

**Recommendation:** treat L1.1 as a useful laboratory result, not a finished Memory architecture. Before applying these rules to production, probe an independently authored unseen set and test versioned revision persistence, source-dependency invalidation and restart rollback. Then specify an authority-aware L2 test harness.
