# ANIMA — E4 L1.2 Measured Outcomes v0

**Status: EXPERIMENTAL RESEARCH PASS / PRODUCTION MEMORY ADMISSION STILL BLOCKED.**  
**Evaluated code snapshot:** `040b579fb31e925cfc3f85587b3280c37b4e9b1e`.  
**CI:** [GitHub Actions #43186836427](https://github.com/VankoRokh/ANIMA/actions/runs/43186836427), SUCCESS on Python 3.12/3.13/3.14.  
**Technical tests:** 1591 full-regression PASS per Python environment; 98 profile tests PASS.  
**Artifacts:** `e4-l12-scoped-lab-evaluation-py314` (raw + separate post-hoc evaluations for frozen positive/negative and open challenge; old→new deltas).  
**Sources:** [L1.2 contract](Memory_E4_L12_Contract_v0.md), [adapter and evaluators](Memory_E4_L12_Lab_v0.md), [L1.1 failure research](Memory_E4_L11_Challenge_Results_v0.md).

## Paired outcomes, no corpus relabeling

| Case set | Gold checks | L1.1 PASS | L1.1 FAIL | L1.2 PASS | L1.2 FAIL | L1.2 NOT_SUPPORTED | Interpretation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Frozen E4 v0 root (42) | 94 | 34 | 0 | **34** | **0** | 60 | Lab-only supported subset |
| Frozen E4 v0 negative (15) | 28 | 7 | 0 | **7** | **0** | 21 | Lab-only supported subset |
| **Frozen combined (57)** | **122** | **41** | **0** | **41** | **0** | **81** | **41/122 = 33.6% coverage** |
| Additional visible development challenge (15) | 16 | 12 | 4 | **16** | **0** | 0 | 16/16 on a **known** open challenge, **not** an independent holdout |

**Frozen E4 v0 has 99 forbidden-action obligations, all `NOT_SUPPORTED`.** No Core effects or authority ledger was exercised. No conclusion about full E4 correctness can follow from a 100% pass among 41 observed frozen checks.

## Four challenge regressions removed without frozen-score regression

| Check | L1.1 failure | L1.2 observed | Source/authority boundary |
| --- | --- | --- | --- |
| **E4-X01** | Different identifier kinds with same token wrongly linked | `insufficient` | `ticket T77` vs `case T77` are not the same typed case identity without a verified bridge |
| **E4-X06** | Two source-backed uses of “адаптер” silently reduced to most recent referent | `insufficient`, with two competing candidate source Event IDs | A definition does not delete another scoped meaning; ambiguous mention remains unbound |
| **E4-X10** | New three-word Russian instrumental phrase missed | `новая маленькая коробочка` while preserving raw label | Bounded morphological normalization, **not** universal Entity Resolution |
| **E4-X11** | A colleague's unrelated trial correction revised earlier A/B grouping | `rejected_unbound`, zero Episode revisions | Same Entity/nearby text does not establish that the correction targets the prior projection |

A separately added non-frozen test uses `ticket T77` reported by the same user in **two unrelated sessions with no stable namespace**. L1.2 now abstains; a session-local identifier is not global continuity. This test is **not part of the 16-check challenge gold**.

## Intermediate namespace regression and its correction

A stricter inter-session identifier rule was evaluated as snapshot `2d717826e087ce631519b20c148d521170b1bb0a`. The *actual raw differential archive*, independently inspected after that CI run, exposed two **PASS→FAIL regressions** on existing frozen cases:

| Case | Intermediate behavior | Source evidence | Final behavior |
| --- | --- | --- | --- |
| **E4-A05:check:2** | `not_same_case_reported` → `insufficient` | User explicitly says «Новая независимая поломка Pi5, случай №52», distinct from earlier №41 | `not_same_case_reported` |
| **E4-N02:check:2** | `not_same_case_reported` → `insufficient` | User explicitly says «новый независимый случай №52», distinct from earlier №41 | `not_same_case_reported` |

This is **not** a reason to merge identical unverified ticket numbers across different sessions. Instead L1.2 now distinguishes an *explicit user-reported new independent case* (with two source Event references, distinct typed IDs, and no world-truth upgrade) from an **unverified repeated number** (remains `insufficient`).

The last snapshot `040b579f...` restores frozen scores to **41 PASS / 0 FAIL / 81 NOT_SUPPORTED**, preserves **16 PASS / 0 FAIL** on the separate 15-case development challenge, and adds a focused negative unit test for user-reported independence. The final raw `positive_delta.json` and `negative_delta.json` each contain **zero changed statuses and zero regressions** relative to L1.1. This intermediate failure was discovered by inspecting the artifact, not inferred from a green `pytest`.

## Safety boundaries and missed capabilities

- `CorrectionTarget` from a bounded deictic utterance («Это были…») remains a **lab-only heuristic**, explicitly carrying `production_admission=false`. A unique local antecedent does not prove actual-world target identity or allow durable Memory rewriting.
- Aliases remain proposals describing a user's intended reference, not verified object properties. No multi-session semantic learning/forgetting policy or broad language understanding has been demonstrated.
- Typed identifiers contain source and namespace scope. A project name found in user text is **reported**, not an independently authenticated project namespace.
- All 57+15 visible experiments have been developed in the same engineering workflow. Neither frozen v0 nor the newer 15 cases constitute an external blinded holdout.
- Independent scorers read **completed traces** and pinned gold, validating referential consistency. Their implementation shares the project's design assumptions and is not independent validation of world truth.
- Durable derived Memory was tested in a **separate** SQLite lab, but is not wired into L1.2. The earlier journal could faithfully store a semantically wrong correction, so storage passing is not semantic admission.

## Next gates before L2 production integration

1. **Typed CorrectionTarget proof:** bind the exact correction to target Event IDs/projection and revision using explicit provenance and a separate authority verifier; no standalone lexical heuristics may update durable heads.
2. **Conflict-aware Entity lifecycle:** exercise revocation and scoped invalidation across sessions, contradictory later evidence and versioned dependent Story/Episode relations.
3. **Independent adversarial validation:** have an external reviewer prepare an unseen, locked corpus after code freeze. Measure under fixed budget and explicit acceptable abstentions.
4. **Real integration and resilience:** verify cross-database recovery, process kill/power failure, resource bounds and non-duplication of effects before allowing production Memory changes.
5. **L2 gating:** until all relevant Core action/Goal/Task/Knowledge checks are instrumented, permit only an isolated synthetic design study, not autonomous action from inferred memory.

**Disposition:** L1.2 is a productive read-only experiment with reduced known error rates, **not** stable production episodic memory. E4 remains partially implemented. L2 autonomous execution remains **NO-GO**.
