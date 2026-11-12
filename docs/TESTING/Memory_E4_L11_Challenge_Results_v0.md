# ANIMA — E4 Pre-L2 Stage 1: Novel Development Challenge Results

**Status:** MEASURED OPEN ADVERSARIAL TESTS, NOT BLINDED HOLDOUT.  
**Tested snapshot:** `3d44f7cb37d0741d732756a3ba2940970b8f2804` (L1.1 unchanged from previous measured version).  
**CI:** [GitHub Actions #43177768483](https://github.com/VankoRokh/ANIMA/actions/runs/43177768483), SUCCESS on Python 3.12/3.13/3.14; **1565 full regression tests PASS** per environment.  
**Source:** [15 pinned synthetic cases](Fixtures/memory_e4_l11_challenge_inputs_v0.json), [separate predeclared gold](Fixtures/memory_e4_l11_challenge_gold_v0.json), [manifest](Fixtures/memory_e4_l11_challenge_manifest_v0.json), [independent post-hoc scorer](../../labs/exp009/e4_l11_challenge_evaluator.py).

## Measured results

- **15 new cases**, **36 unique Events**, **16 scoped gold checks**.
- **12 PASS, 4 FAIL, 0 NOT_SUPPORTED, 0 NOT_OBSERVED.** Coverage of *this tiny developer-defined contract*: 16/16, PASS among observed = 75.0%.
- The earlier frozen E4 v0 still has **41 PASS, 0 FAIL, 81 NOT_SUPPORTED**, 99 additional forbidden obligations uninstrumented. These are distinct denominators; **never combine to claim general E4 quality**.

## Four actual failure modes from closed raw trace

| Check | Gold | Actual | Why it matters |
| --- | --- | --- | --- |
| **E4-X01** | `insufficient` | `same_case_reported` | Ticket and incident/case markers share text `T77`, but the identifier *kind* and namespace were never proven equivalent. False Story link. |
| **E4-X06** | `insufficient` | `scoped_alias_reuse` | Same speaker gives two different physical referents for `адаптер`, then uses unanchored alias. Current same-session last-definition-wins is unsafe. **High severity.** |
| **E4-X10** | `новая маленькая коробочка` | `новой маленькой коробочкой` | Two-word grammar heuristic fails a new three-word inflection; a missed recall, not false physical identity. |
| **E4-X11** | 0 revisions | 1 revision | A later statement about a *colleague's* unrelated experiments has trigger words and shared Pi5 context, so L1.1 wrongly revises earlier A/B Episode. **High severity.** |

The tests also cover verified distinct namespaces, an unverified relay, explicitly scoped alias reuse, a source-backed female adjective/noun form, and negative revision triggers. Those other checks passed **in this finite set**.

## Findings

1. **Block production Story/Entity auto-merge and Episode revision from current L1.1 rules.** A green regression on frozen v0 was not sufficient.
2. Before attempting a generalized fix, introduce explicit *identifier type + namespace*, a conflict-aware alias resolution policy, and a correction-to-target reference contract. A new regex targeting X11 wording alone is not acceptable.
3. Keep the challenge inputs/gold pinned and unchanged. A future revision of algorithm should be compared against the original 16 requirements and new counterexamples, not scored using silently modified gold.
4. Because the scenario authors knew the implementation and supplied the gold, this is a **visible development challenge**, not an independently authored blinded generalization test.

## Step 2 boundary

A separate SQLite-derived-view journal can test recovery/idempotent revisions without touching production Memory. This does not cure the semantic failures above; it only studies the durability of any subsequently accepted derived decision.
