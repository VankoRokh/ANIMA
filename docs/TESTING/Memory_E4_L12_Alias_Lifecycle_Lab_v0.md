# ANIMA — E4 L1.2 Alias Lifecycle / Targeted Invalidation Lab v0

**Status:** EXPERIMENTAL ISOLATED STORAGE LAB; **NOT** production Core/Memory approval.  
**Pre-implementation contract:** [selective alias revocation v0](Memory_E4_L12_Alias_Lifecycle_Contract_v0.md).  
**Storage code:** [alias lifecycle SQLite journal](../../labs/exp009/e4_alias_lifecycle_lab.py).  
**Raw trace:** [alias lifecycle recovery probe](../../labs/exp009/e4_alias_lifecycle_probe.py).  
**Adversarial tests:** [source-target, crash/replay, selective impact tests](../../tests/test_memory_e4_alias_lifecycle_lab.py).

**Measured results:** [Alias Lifecycle Selective Invalidation Results v0](Memory_E4_L12_Alias_Lifecycle_Results_v0.md): 1629 regression PASS on Python 3.12/3.13/3.14, two exactly affected nodes, unaffected competing Story, simulated crash/replay and source history. Not production E4 acceptance.

## Model and constraints

The prototype is a **separate SQLite database**, rejecting filenames `memory.db` and `core_state.db`, with WAL/`synchronous=FULL` and explicit `BEGIN IMMEDIATE` transactions. It never opens ANIMA production Memory.

- Raw Event IDs and canonical bytes are immutable with SHA-256 stored per event; duplicate identical ID+bytes is a replay, different bytes are an integrity error.
- Source-user `alias_control` is **experimental structured input** attached to a normal Event payload; it is not a signed source, a new production Event schema, or proof of real-world user identity. The user must explicitly reference the original definition Event when revoking; a coincidental lexical match or a new definition cannot revoke it.
- Each `alias_id` has immutable `active@1` and `revoked@2` versions. Multiple active alias IDs may share the same surface with different targets; no last-write-wins or replacement.
- `Story` and `Episode` are synthetic **derived nodes**, not production entities. Immutable node revisions store exact raw source Event ID/digest dependencies and typed graph edges `alias_id@rev` or `node_id@rev`.
- Revocation follows only current dependency edges, recursively marks directly and transitively dependent heads `stale`, and appends an operation-keyed impact ledger. It **does not** automatically choose another Entity, issue a Goal or Task, or revise Memory.
- A separate manual `reassess_unresolved` appends an immutable version with no approved alias binding and `unresolved` status. A downstream Episode stays stale until separately reevaluated; it does not silently become current.
- The number of affected nodes is bounded at 128; budget overflow raises an error and rolls back the **entire** revocation transaction.

## Test and interpretation

```bash
python -m pytest -q tests/test_memory_e4_alias_lifecycle_lab.py
python -m labs.exp009.e4_alias_lifecycle_probe --output /tmp/e4_alias_lifecycle_impact.json
```

The CI experiment on Python 3.14 saves source Event and impact IDs, before-commit / after-commit simulated cuts, post-restart idempotent replay, old Story dependencies, manual unresolved reassessment and unchanged neighboring Story.

**Caution:** a stored SHA-256 detects inadvertent bytes changing when only one field is corrupted; it is not an authenticated hash chain or defense against a privileged writer that can change both data and digest. Python-injected exceptions are not a real power-loss test. The alias-control convention remains **lab-only** without Core admission. No change to frozen E4 v0, pinned challenge gold, L1.2 automatic behavior, or real SLEEP/Knowledge handling.

## Next unsolved gates

Core-owned user/source authentication, legitimate lifecycle admission, provenance-aware rebind/confirmation, real crash/replay and multi-DB repair, selective dependencies at scale, independent unseen holdout, and the previously unsupported 99 forbidden E4 obligations. **L2 autonomous execution remains blocked.**
