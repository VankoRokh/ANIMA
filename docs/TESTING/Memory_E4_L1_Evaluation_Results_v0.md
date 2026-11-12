# ANIMA — E4 L1 Independent Evaluation Results v0

**Status:** MEASURED LIMITED L0/L1 DIAGNOSTIC; full E4 conformance **NOT VERIFIED**.  
**Evaluated commit:** `9c58183fce183a1e20d2bcfa1d22f8320c776e7e`.  
**CI:** [GitHub Actions #43171628756](https://github.com/VankoRokh/ANIMA/actions/runs/43171628756) — success, 1552 full regression tests on Python 3.12, 3.13, 3.14.  
**Artifact:** `e4-l1-independent-diagnostic-py314` (four JSONs: positive/negative raw L1 and independent evaluations, 14-day Actions retention).  
**Sources:** [Evaluator](Memory_E4_Independent_Evaluator_v0.md), [Freeze record](Memory_E4_v0_Freeze_Record.md), [L1 lab](Memory_E4_L1_Conservative_Lab_v0.md).

## Measured corpus verdicts

| Suite | Cases | Gold checks | PASS | FAIL | NOT_SUPPORTED | NOT_OBSERVED | Coverage | Pass among observed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Root | 42 | 94 | 30 | 2 | 62 | 0 | 32/94 = 34.0% | 30/32 = 93.8% |
| Visible development negatives | 15 | 28 | 5 | 2 | 21 | 0 | 7/28 = 25.0% | 5/7 = 71.4% |
| **Combined** | **57** | **122** | **35** | **4** | **83** | **0** | **39/122 = 32.0%** | **35/39 = 89.7%** |

**Do not call 89.7% “ANIMA E4 accuracy”.** Some passing results are **L0 Shadow Episode proxies**, and 83 of 122 criteria are untested. Gold remains frozen but *provisional*. No hidden holdout exists.

**Forbidden actions:** all **79** root prohibitions and all **20** negative prohibitions = **99 NOT_SUPPORTED**. No independent effect/authority/Knowledge ledger exists, so even absence of effects in raw traces is not evidence of safety.

**Raw trace SHA-256 fingerprints:**
- Root: `1e5fb89ec6b4682411e5a4dea15eddb001aa13013c068d06b925871e6de29859`
- Negatives: `2f766b765791b9c1cf24f8bf28d963b8c452af35b84a6c06f3bf62b12a2382f5`

## Four failures verified from raw L1

| Case | Frozen gold | Raw outcome | Meaning |
| --- | --- | --- | --- |
| **E4-D01:check:2** | Two **different** Episodes for Pi5 tests A and B | `same`: Shadow appended e2 to e1, with `raw_pair_overlap:3`, `raw_pair_ratio:1.000`, shared Entity, 120-second gap. The later correction e3 did not resegment. | High-relevance false merge in **L0 Shadow proxy**; no E4 correction capability yet. |
| **E4-U05:check:2** | Source-user `чёрная коробочка → PSU` | L1 records `чёрной коробочкой → PSU`, but does not normalize that inflection to the gold surface; evaluator returns missing. | Scoped alias **morphological normalization gap**, not missing statement or provenance. UncertaintyRegistry still unsupported. |
| **E4-N01:check:2** | Same *reported* shared outage for two distinct devices, following explicit third message | L1 returns `insufficient`; its explicit-report pattern matches “оба отказа относятся...” but not “оба устройства в одном сообщённом случае A9”. | Missed organizational Story link due to overly narrow wording; **no unsafe merge occurred**. |
| **E4-N04:check:1** | `not_same_case` for T77 in verified separate namespaces Alpha and Beta | L1 returns `insufficient`, reason `different_or_untrusted_namespaces`. | **Safe abstention** but no explicit negative classification; do not confuse known-different namespaces with unknown/unverified ones. |

Root-track coverage/observed outcome: A 9/10 observed, 9 PASS; B 14/16, 14 PASS; C 6/13, 6 PASS; D 1/10, 1 FAIL; U 1/14, 1 FAIL; R 0/18; P 1/13, 1 PASS. A/B observed-pass results reflect limited proxy semantics and do **not** imply complete Episode/Story conformance.

## Recommended next gate (not yet implemented)

1. Prepare an **E4-L1.1 error-review brief** before modifying algorithms. For each of four failures, specify a generalized remedy and negative counterexample, not a hard-coded fix for the literal gold text.
2. Prioritize preventing or revising false Episode merges (D01). Then improve contextual alias morphology and structured source-reported incident/namespace relations, always retaining provenance.
3. L2/L3 coverage needs actual scheduled Goal/Task admission, effect ledger, and recovery traces. Do not infer PASS for any of 99 forbiddens before independent instrumentation.
4. Create any blind holdout **separately** from the visible frozen E4 v0. Do not change frozen input/gold bytes to raise scores.

**Verdict:** evaluator and L1 are reproducible, but measured coverage is only **32.0%** of gold checks; full E4 remains **OPEN**.
