# ANIMA — E4 Pre-L2 Critical Architecture Review v0

**Status:** REVIEWED AS RESEARCH; **NO-GO** for production L1.1/Memory migration and automatic L2 admission.  
**Reviewer stance:** critical assessment of implemented laboratory behavior; **not** an external independent audit or a blinded validation.  
**Branch:** `experiment/core-memory-information-baseline`.  
**Measured Step 1:** [15-case post-L1.1 adversarial evaluation](Memory_E4_L11_Challenge_Results_v0.md), CI [#43177768483](https://github.com/VankoRokh/ANIMA/actions/runs/43177768483) (1565 full regression PASS on 3.12/3.13/3.14).  
**Measured Step 2:** [separate SQLite revision journal lab](Memory_E4_Derived_Journal_Lab_v0.md), CI [#43178402922](https://github.com/VankoRokh/ANIMA/actions/runs/43178402922) (1577 full regression PASS on 3.12/3.13/3.14; 12 new journal/probe checks).  
**Original frozen v0 baseline:** 57 cases; L1.1 41 PASS/0 FAIL/81 NOT_SUPPORTED among 122 *provisional* gold checks, with **99 prohibitions still uninstrumented**. Its four source JSONs are unchanged.

## Three intermediate stages and their genuine verdicts

| Stage | Evidence | Technical verdict | Architectural admission |
| --- | --- | --- | --- |
| **1 — novel adversarial semantics** | 15 new open cases, 36 Events, 16 scoped checks: **12 PASS, 4 FAIL** | **SEMANTIC GATE FAIL**; the original 41/41 observed PASS was selective and did not generalize to these cases | Block production association/revision |
| **2 — derived version durability** | SQLite WAL/FULL + CAS + stable operation keys, simulated before/after commit, persisted revisions, source checksum validation, stale preflight; 12 tests PASS | **ISOLATED TRANSACTION LAB PASS** | No real Core/Memory integration, physical shutdown, two-database atomicity or SLEEP publication proved |
| **3 — architectural decision** | Source/gold/trace comparison; direct review of L1.1 rules and core Goal/Task ownership | **REVIEW COMPLETE / NO-GO FOR PRODUCTION** | Safe to research an L2 contract *on synthetic inputs*, **not** to run autonomous action based on unverified derived memory |

## Blocking findings and remedies

**P0 — X11: correction applied to unrelated Episode sources.** A later statement about a colleague's experiments shares Pi5, time/session and correction words, but is not evidence that the earlier A/B tests should be split. An in-memory and even a durable version can therefore be **well stored but semantically wrong**. Require typed `CorrectionTarget` with explicit `target_projection_id`, `target_revision`, `target_source_event_ids` and `correction_event_id`, plus an independent evidence/authority decision. Without verified target scope, emit `review_candidate` or abstain; do not materialize a new head. A bare phrase pattern or “this” with no source binding is insufficient proof.

**P0 — X06: conflicting alias silently resolved by last definition.** Two source-backed meanings of `адаптер` in one session cannot be ordered into a unique global mapping. Maintain **multiple scoped candidates** (context, source Event, source version and validity); select only when a unique candidate matches verified current anchors, otherwise `ambiguous`. A later statement is not automatically an overwrite or physically verified Entity.

**P1 — X01: case-marker type lost.** Ticket `T77` and “case T77” were treated as the same reported case although identifier kind/namespace mapping was not established. Represent `Identifier(namespace,kind,token,source_authority)`, require typed cross-kind linkage evidence; same literal token never suffices.

**P2 — X10: limited Russian morphology.** A two-word suffix heuristic missed a three-word phrase. Keep exact source and generate **scored grammatical candidates**, not automatic global synonym merges; evaluate false normalizations with counterexamples, latency, CPU and abstentions.

**P1 — coverage still low:** 81/122 frozen checks unsupported and all 99 prohibited operations lack independent instrumentation. Avoid claiming “100% accuracy”; only 41/122 of known gold checks were observed. L2 Goal/Task/periodic reviews, Knowledge and SLEEP are **not** implemented by this work.

## Storage audit: successful tests versus missing evidence

1. **Supported experimentally:** unique raw Event IDs, byte-backed dependency hashes, WAL/FULL within *one isolated DB*, snapshot-head CAS, idempotent operation replay, old-revision read, simulated pre/post-commit exceptions, stale source-stream preflight refusal. Prototype `publication_guard` returns `NO_CORE_PUBLISH_PERMISSION`, not actual authorization.
2. **Unverified:** kill -9, real power loss, disk-full/corruption, multi-process contention, cross-DB commit consistency with authoritative Event store, durable SLEEP/Memory publication, real Raspberry Pi / NVMe endurance, C3 performance. Source-stream epoch invalidation is coarse and may cause needless recomputation.
3. **Critical admission gap reproduced:** the journal requires a later `conversation.user` Event but does not prove that it actually refers to the affected source Events. It can *faithfully persist* the false revision of X11. This is not a SQLite bug — semantic/evidence admission belongs upstream.
4. **Reproducibility limit:** the challenge's proposed gold and adapter came from the same engineering workflow. It is a visible adversarial **development** corpus, not blind third-party validation. An evaluator in a separate process validates referential structure, not real-world source truth.

## Required next gate before production E4 or action-enabled L2

| Gate | Required proof | Status |
| --- | --- | --- |
| **G1: correction-target authority** | Explicit target refs, independent scoping verifier, negative X11 variants; derived revision only from verified target set | **BLOCKED** |
| **G2: conflict-aware Entity Resolution** | Multi-valued scoped aliases and safe abstentions across sessions/objects, tests for conflicts and revisions | **BLOCKED** |
| **G3: typed case identity** | Identifier kinds/namespaces, source scope, cross-kind bridging/negative tests; no silent identity promotion | **BLOCKED** |
| **G4: durable production integration** | Reconcile Event + Memory + SLEEP across DBs; process kill/power tests; selective dependency invalidation; resource gate | **OPEN** |
| **G5: L2 research authority** | Core-owned Goal/Task admission, orthogonal InvestigationSchedule, stable occurrence/effect ledger, independent verifier, user interruption policy | **DESIGN ONLY** |
| **G6: independent generalization check** | New externally authored blind holdout, frozen before algorithms evaluated | **NOT DONE** |

## Engineering decision

**Do not enable L1.1 automatic correction, global alias reuse, or case-merge in production.** Preserve L0/L1/L1.1 as read-only research adapters. Continue with a conservative **L1.2 contract** emphasizing provenance and ambiguity before L2 admission. Once G1–G3 have negative tests and successful new trials, the SQLite journal can inform the durable design, but is not itself a safe integration target.

An **isolated L2 design study** can proceed without action execution by using synthetic uncertainty/Goal proposals and preserving existing Goal statuses `active|blocked|completed|cancelled` and Task statuses `queued|active|interrupted|completed|failed|cancelled`; scheduled/conditional waiting remains a separate proposed axis. Even that does not grant any tool or hardware authority.

**Disposition: all three pre-L2 research stages are assessed, but their gates do not authorize production integration or autonomous execution.**
