# ANIMA E4 — L1.2 Alias Lifecycle & Selective Dependency Invalidation v0

**Status:** PREDECLARED OPEN DEVELOPMENT DESIGN / NOT PRODUCTION ADMISSION.  
**Baseline:** `7e0d669c671652fd78461e989274784721115cac` on `experiment/core-memory-information-baseline`.  
**Scope:** a new isolated SQLite experimental store, no changes to `anima/`, no old L1/L1.1/L1.2 behavior changes, and no modification of the frozen E4 v0 or the pinned 15-case challenge.

## Research question

Can an explicit user-origin revocation of one prior source-backed alias invalidate exactly the **dependent** Story/Episode derived views, including transitive downstream edges, without deleting raw Events, inventing a replacement Entity, or forcing unrelated derived views to be recomputed?

## Source and authority contract

1. All raw Events must validate against `Event.validate_record`, be immutable by ID, and be persisted with a canonical SHA-256.
2. An alias definition is a **source claim** anchored by `conversation.user` and an explicit experimental `payload.alias_control = {"action":"define","alias_id":...,"surface":...,"target_entity_id":...}`, including an Entity reference to its claimed target. Multiple alias IDs may share a surface and point to competing Entities. No last-write-wins.
3. An alias revocation is a later `conversation.user` Event with `payload.alias_control = {"action":"revoke","alias_id":...,"definition_event_id":...}` and exactly one typed `kind:event` reference to the original definition Event. The reporting source must match the original. Cross-session revocation is permitted only through the exact source ID. This is a **lab harness event convention**, not a Core-authenticated message or world-truth proof.
4. Each alias ID has an immutable version history `active → revoked`; revision state changes use expected-head compare-and-swap and idempotent operation keys. Reusing an operation key with different arguments is a hard error.
5. Derived nodes are `Story` or `Episode` **proposals**. Each immutable node revision stores source Event IDs/digests plus exact dependencies `alias_id@revision` and optionally `node_id@revision`. No node can silently depend on a missing or stale head. This graph is a limited laboratory representation, not ANIMA's production knowledge graph.
6. Revocation marks only the current nodes directly dependent on the revoked alias version and their downstream dependent nodes as `stale`. Unrelated heads remain `current`. Invalidation ledger records exact affected node IDs and source revocation Event. Existing node revision bodies remain immutable.
7. Manual reevaluation of a stale derived node creates an immutable `unresolved` revision with no new alias/entity link; downstream nodes do not automatically become valid. All receipts contain `authority=LAB_ONLY`, `production_admission=false`, `memory_store_unchanged=true`.

## Adversarial acceptance cases, to be implemented before evaluation

| Scenario | Required outcome |
| --- | --- |
| A definition `A` used by Story S and Episode E depending on S, unrelated alias B used by Story U | Revoke A → only S and E stale; U current |
| Another definition with same alias surface but different Entity | Competing candidate remains; no automatic overwrite or replacement |
| Correction/revocation references a different Event ID, is missing/duplicated, arrives from relay, or targets the wrong alias | Fail closed; no invalidation |
| Stale alias head or stale node dependency, operation-key collision | Fail closed; no duplicate effects |
| Simulated crash before revocation commit | Alias active, no invalidations |
| Simulated crash after commit; reopen SQLite and replay | Alias revoked, same affected set, no duplicate ledger entry |
| Manual re-evaluation of stale Story | New unresolved revision; original source/derived history intact, Episode remains stale |
| Source Event ID replay with different bytes or direct SQLite body tampering | Integrity failure |
| An unrelated later Event | No coarse whole-stream invalidation; existing unrelated dependent heads stay current |
| Cyclic/corrupt dependency attempts and oversized dependency graph | Reject safely under a fixed resource bound |

## Non-goals and gates

No Core-owned permission, verified identity of the real-world target, source-signature attestation, autonomous retargeting, SLEEP consolidation, production Memory migration, physical power-loss proof, cross-DB durability, or L2 Goal/Task execution. Any test pass demonstrates a property of **this isolated SQLite lab only**.

Run the existing independently scored E4 v0 and open challenge unchanged alongside this new laboratory. Neither corpus has a hidden holdout. Do not treat green CI as semantic generalization.

**Exit criterion:** reproducible raw trace with source versions, exact affected IDs, untouched neighbors, idempotent replay and verified preservation of earlier versions; failing negative tests cause a blocker rather than rewriting the baseline.
