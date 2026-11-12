# ANIMA — E4 L1.2 Alias Lifecycle & Selective Invalidation Results v0

**Status:** MEASURED ISOLATED LAB PASS / **PRODUCTION E4 AND ACTION-ENABLED L2 REMAIN NO-GO**.  
**Measured snapshot:** `6ba2be1c123448c2de3d68214af6aca8e0107917`.  
**CI:** [GitHub Actions #43200281569](https://github.com/VankoRokh/ANIMA/actions/runs/43200281569) — **SUCCESS** across Python 3.12 / 3.13 / 3.14; **1629 full regression PASS** and **98 targeted profile PASS** on each.  
**Contract fixed before implementation:** [Alias Lifecycle Contract](Memory_E4_L12_Alias_Lifecycle_Contract_v0.md).  
**Code:** [separate SQLite journal](../../labs/exp009/e4_alias_lifecycle_lab.py) + [raw synthetic trace](../../labs/exp009/e4_alias_lifecycle_probe.py).  
**Tests:** [isolated negative/recovery suite](../../tests/test_memory_e4_alias_lifecycle_lab.py).  
**Raw artifact:** `e4-alias-lifecycle-selective-invalidation-py314` contains `impact_recovery.json` (14-day retention).

## Observed lifecycle trace

Two distinct alias IDs (`a` and `b`) share the surface “адаптер” but point at separate speaker-reported PSU Entities. `StoryS` depends on `a@1`, `EpisodeE` on `StoryS@1` and `StoryU` on `b@1`. A second-session explicit revocation Event cites the exact original definition Event for alias `a`.

| Component | Before revocation | After reopen/replay | Scope |
| --- | --- | --- | --- |
| Alias `a` | `active@1` | `revoked@2` | Original version preserved, not deleted |
| Alias `b` | `active@1` | `active@1` | Unrelated competing definition retained |
| `StoryS` | `current@1` | `stale@1` | Direct dependency `alias a@1` |
| `EpisodeE` | `current@1` | `stale@1` | Transitive dependency `StoryS@1` |
| `StoryU` | `current@1` | `current@1` | Dependency `alias b@1` unaffected |

Raw impact receipt: `affected_nodes=["EpisodeE","StoryS"]`; `invalidation_count=2`; `invalidations` table contains exactly those nodes for the revocation operation. **No entire source stream invalidation** occurred.

The simulated **before-commit exception** left alias `a` active, all derived heads current and zero invalidations. A separate **after-commit exception** left a fully committed revocation discoverable after reopening the database. Replaying the same operation returned `idempotent_replay` with no extra writes. Immutable Story revision 1 remains readable with its source Event IDs and original `alias a@1` dependency.

A *manual* review of `StoryS` produced `unresolved@2` and no replacement Entity linkage. `EpisodeE` remained `stale` pending its own review. No automatic reactivation or self-modifying memory took place.

## Negative tests and resource gates

- Nonmatching/missing/duplicated/extra Event reference, wrong alias or unknown relay cannot revoke.
- Second-session user report requires an explicit typed Event reference and a later timestamp; matching alias text alone is insufficient.
- Raw Event replay with changed content, stored event tampering, missing dependency edge and derived revision tampering raise integrity errors.
- Revocation, seed and manual re-evaluation use stable operation keys; collision of key+different request is a hard error.
- Source and derived revisions are immutable; old versions stay queryable for audit.
- A derived node may not depend on already stale alias or derived head.
- Resource test with 130 extra dependent nodes exceeded the hard **128-node invalidation budget**: transaction rolled back, alias and dependent heads remained unchanged.
- The same alias surface with another Entity exists under a separate alias ID and remains active rather than silently overwriting the revoked definition.

## Legacy E4 comparability (no score upgrade)

| E4 source suite | Case count | Gold checks | PASS | FAIL | NOT_SUPPORTED |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen E4 v0 | 57 | 122 | **41** | **0** | **81** |
| Visible developer-authored challenge | 15 | 16 | **16** | **0** | 0 |

Old `L1.1 → L1.2` scored differentials remain **zero changed checks / zero regressions** over the unchanged frozen files. All **99 forbidden-action checks** remain `NOT_SUPPORTED`: no independent effects/authority ledger was instrumented.

Git blob SHA-1 and size for all four frozen E4 v0 JSONs and both pinned visible challenge JSONs were rechecked and matched their manifests at the measured code commit.

## Architecture limitations and strict NO-GO

1. `alias_control` is an **experimental user-supplied payload convention**, not a Core-authenticated revocation command. `source="user"` is not cryptographic proof of identity/authority.
2. A source revocation changes a **laboratory** alias head only. It is not evidence that the physical target was mislabeled or that all real-world facts about the Entity changed.
3. The storage checksum is **not tamper-evident against privileged changes to both bytes and digest**. WAL/`synchronous=FULL` plus injected Python exceptions do **not** establish real power-loss durability or cross-database recovery.
4. The separate lifecycle journal does **not** replace the older `DerivedRevisionJournal` (with whole-stream staleness); it experiments with selective graph edges and does not migrate production `MemoryStore`, Graphiti, EventBus, Core Goal/Task or SLEEP.
5. Invalidations are direct graph-traversal marks on *synthetic* Story/Episode proposals, not independent rederivation of meaning. `unresolved` deliberately abstains rather than selecting a new alias.
6. No independent blinded holdout, resource/latency endurance measurement at real ANIMA scale, verified source identity, legal production admission, autonomous action, or external effect ledger was tested.

**Verdict:** the laboratory can preserve immutable source history and invalidate *only* traceable dependents with atomic simulated recovery and idempotent replay. This is a useful engineering boundary, **not production memory correctness**.

**Next recommended gate:** source-authority and definition-lifecycle specification + an independent, previously unseen counterexample corpus; then controlled comparison of selective invalidation versus coarse stream invalidation under larger synthetic graphs and process kill/restart. L2 autonomous execution remains NO-GO.
