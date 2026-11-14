# ANIMA Memory v1 — M6-B2.1 Godot target-source isolation and execution contract

**Status:** DESIGN FROZEN FOR IMPLEMENTATION REVIEW — documentation-only; **NO B2 executable gate or live effect has passed**.  
**Parent:** `work/anima-v01-integrated-m6b1`; **branch:** `work/anima-v01-integrated-m6b2`.  
**Prerequisite:** M6-B1 real Godot 4.7.2 mapping preflight and owner-provided `anima-m6b1-PC.json` (`M6B1_GODOT_SOURCE_PREFLIGHT_PASS`, commit `66a25ef4a0d0d02506c354e62fe00758d1173b70`, eight cases, zero effects). This report is owner-provided, not cryptographically attested.  
**Scope:** design + frozen negative contracts only. Do **not** change `anima/`, official Stage status, `docs/project.json`, or install Godot execution during B2.1.

## 1. Why a simple source swap is unsafe

Primary code reviewed in the parent branch:

- `anima/core/assembly.py`: `build_core` creates P2 at `<data_dir>/core_state.db`, P3-A at `core_work.db`, Task at `tasks.db`, execution at `execution.db`. It can install a `world_port` + handlers directly and does **not** enforce a global M6 permission firewall.
- `anima/core/belief.py`: `PropertyRule` has **one** `clock_domain`; the current working P2 snapshot is keyed by `(subject_ref, predicate_ref)`, not a separate world / producer / clock lineage. Revision and tick comparison cannot safely mix `lab_tick` and `lab_sample`.
- `anima/core/ingress.py`: `SourceRegistration` binds a registered `source_ref` to one `producer_ref`, but an `admit(raw, source_ref=...)` caller is assumed to be trusted; a source string is not authentication.
- `anima/core/goal_decision.py`: the immutable P3-A `core_goal_bindings` row stores criterion and expected value, **not** source ID, producer, clock, world instance, or a provenance fingerprint. Reusing the old binding in a changed registry would grant it new meaning.
- `anima/core/door_execution.py`: P3-B admits an exact Goal/Task/action and performs independent registered P2 readback. Its proof is persisted in the `core_work.db` family and its `_verified`/`_recover_proof` logic checks a fixed `DOOR_SOURCE`, **not** a world-instance/producer attestation.
- `labs/virtual_anima_lab/python/m5_binding_admission.py`: M5 origin expects `sensor.door_01` + `adapter.virtual_door_sensor/0.1` + `lab_tick`, and refuses mutation of its trusted registry.
- `labs/virtual_anima_lab/python/m6b1_godot_migration.py`: B1 records separate raw Godot and P6-adapter provenance, requires reviewed host approval and fresh `world_instance_id`/`epoch`/`world_revision` validation, and issues **no** execution capability.
- `labs/virtual_anima_lab/python/core_port.py`: `VALDoorPort` produces `adapter.val_door_port/0.1` `lab_sample` observations; it has a durable sample ledger, world-instance/epoch pinning, `act_door` with expected revision, and read-only `door_operation_status` reconciliation.

**Decision:** reject replacing old M5 P2 registrations in `runtime/core_state.db`, mixing Godot events into that projection, cloning the canonical M4 Goal, or treating B1 approval / M6-A single-use permission as executable authority.

## 2. Selected laboratory design: one Goal, two disjoint P2/P3 ledgers

Exactly one M4 canonical Goal remains in the **existing** `root/runtime/internal_state.db`, with original Memory/Event/index, M4 ticket, M5 ticket, and M5 binding left unchanged. The target Godot path uses **new separate ledgers**:

| Location | Ownership / semantics |
| --- | --- |
| `root/runtime/core_state.db` | Original M5 P2, `lab_tick`, never remapped |
| `root/runtime/core_work.db` | Original M5 P3-A binding and historical source lineage, never rewritten |
| `root/runtime/internal_state.db` | **Only** canonical M4 GoalStore; shared by the new target decision instance |
| `root/p6_port/val_p6_port.db` | Existing P6/Godot world binding and original sample/provenance log |
| `root/m6b1_migration.db` | Frozen reviewed **nonexecuting** source mapping |
| `root/m6b2_target/core_state.db` | **New** target-only P2 CoreIngress and Belief, `lab_sample` |
| `root/m6b2_target/core_work.db` | **New** target-only P3-A binding, decision log, verified Proof |
| `root/m6b2_target/tasks.db` | **New** target-only Task ledger |
| `root/m6b2_target/execution.db` | **New** target-only Operation/Action/VerificationSpec ledger |
| `root/m6b2_admission.db` | **New** action-scoped approval + single-use claim, independent of B1/M6-A |

Construct the target graph using existing `CoreIngress`, `CoreGoalDecision`, `GoalCriterion`, `TaskStore`, `CoreDoorExecution`, `ExecutionStore`, `SandboxExecutor` and `VALDoorPort`, **only in an opt-in lab factory**; never point generic `build_core(..., world_port=...)` at the original runtime DB. The target `CoreGoalDecision` must reference the **same original GoalStore object/database**, but a separate target TaskStore, target P2 and target P3-A DB. Do not construct a second canonical Goal.

Target-only registration (subject/predicate/action remain the frozen M5 values):

- `SourceRegistration(source_ref="sensor.door_01", producer_ref="adapter.val_door_port/0.1", allowed_kinds=("state.property", "sensor.unavailable"))`. The equal `source_ref` is allowed **only because the P2 DBs are isolated**.
- `PropertyRule(..., clock_domain="lab_sample", allowed_sources=("sensor.door_01",), freshness_ticks=2, allowed_symbols=("open", "closed"))`. The proposed freshness budget is laboratory-only and must be tested, not inferred from Godot `tick`.
- `ActionSpec`, `GoalCriterion` and `ToolRegistry` exactly match the frozen M5 target/action contract; target `GoalCriterion` is persisted as an **additional target-specific P3-A row**, not an in-place rewrite of M5.
- A B2 source-authorization record explicitly binds the target P3-A row to `M4 fingerprint + M5 fingerprint + B1 fingerprint + source/producer/clock + world_instance_id + epoch + immutable action spec + exact goal_id`. Existing P3-A schema does not carry this information, so the **lab gate** must enforce it on every execution admission.

This is not a production-wide authorization boundary. Arbitrary trusted code capable of opening SQLite databases or constructing direct executors can still bypass the laboratory factory.

## 3. New action-scoped consent and state machine

M4 Goal approval, M5 binding approval, B1 mapping approval, and B2 execution approval are **distinct** decisions. A B2 ticket begins in `staged`, then is durably `approved` or terminally `rejected`; a permitted action transitions `approved -> claimed` atomically with exactly one persisted `operation_id` and latest checked target P2 evidence ID. No second claim, changed decision, ticket replacement, or duplicate operation is allowed. B2 has its own immutable typed host decision and fingerprint; a string `operator_ref` is **not** human authentication.

Before **any** action-capable target assembly or Task/Operation creation:

1. Re-open original restricted M4/M5 Core; require exactly one active canonical Goal, original raw Memory/Event/index completeness, unchanged M4/M5 decisions and binding, and no old M6-A permit transfer.
2. Validate the exact B1 reviewed ticket and separate typed `APPROVE`; call B1 `revalidate` **while the Goal is active, Task-free and the door remains open**. Its fresh Godot sample, original `world_instance_id`, `epoch`, `world_revision`, mapping and ledger SHA are evidence, **not permission**.
3. Register target-only P2; capture a **new live Godot sample** via the existing `VALDoorPort`; admit only under the target producer/clock. Verify CoreIngress outcome, fresh Belief, exact source/producer, original Godot sample provenance and approved world identity/epoch. Do not manufacture an observation under M5 producer or convert `lab_tick` to `lab_sample`.
4. Persist the target-specific new P3-A binding and a B2 fingerprint tying this authorization to the reviewed original and target lineages. Do not mutate the original P3-A row. Refuse pre-existing target Tasks/Operations/Proofs at initial admission.
5. Require the new, explicit B2 `APPROVE` before constructing an action-capable target executor; always `auto_core=False` and **no P3-C**.

Actual Tool-worker guard (not merely a caller-side check):

- Verify handler root, action/argument identity, Goal/Task lifecycle, persisted canonical `ExecutionAction` + `VerificationSpec`, exact `operation_id`, B2 decision and target binding/registry against the frozen fingerprints.
- Take a **new** Godot observation via P6 and admit it in target P2. Check it is later than the reviewed/admission samples, belongs to the same world instance/epoch, is open/fresh, has an accepted authoritative Belief, and is supported by the unmodified P6 sample ledger.
- Atomically claim the B2 single-use ticket for this operation before calling `VALDoorPort.execute`. `VALDoorPort.execute` itself observes again and sends `expected_epoch` + `expected_revision` to Godot; an intervening world change must reject, not force a close.
- Invoke **exactly one** `act_door` at most. Do not auto-reissue an ambiguous side effect.
- Keep `reconcile` and `replay_output` read-only (no `act_door`); only independent target P2 evidence can complete the canonical Goal. Tool receipt alone never implies success.

## 4. Recovery protocol: B1 preflight is not a post-effect check

B1 `revalidate` deliberately requires the **original open-door world revision**, an active Task-free Goal, and a fresh open observation. After a legitimate Godot action the world revision changes and a Task exists; **B1 must not be invoked as a post-effect recovery gate**.

Instead, after `claimed`, a separate B2 recovery-only path must:

- Validate immutable B1/B2 decision/provenance **records** and target ledger ownership without requiring the pre-action door state/revision or B1's `_origin` pre-execution lifecycle check.
- Reassemble the exact **target-only** P2/P3/Task/Execution stores with the original canonical GoalStore, with the guarded handler installed solely for compatibility; its `execute` must refuse a consumed/claimed permit.
- Require the same Godot `world_instance_id` and `epoch` before trusting live readback or `door_operation_status`. A restarted/replaced world is **unknown**, not evidence of success.
- Reconcile an `executing`/`uncertain` operation through **read-only** `door_operation_status` and then independent fresh P6 target P2 Proof. If the world has already closed, do not execute again; if evidence remains ambiguous, defer.
- Permit replay of an already-persisted *verified* target-only proof to finish Goal/Task commits (with provenance checks) but never turn a mere Tool receipt, stale M5 evidence, or old B1 mapping sample into successful Goal Proof.
- Preserve the original single canonical Goal and ensure no second Task/Operation is created on recovery.

The SQLite B2 permit ledger and Godot effect are **not globally atomic**. Crash after claim but before the effect can consume permission with zero effects; this conservative defer is intentional. All fault-cut tests must count actual Godot effect events, not infer them from text or receipt status.

## 5. Implementation sequence and acceptance gates

### M6-B2.1 — design only (this document)

- Check the above source/clock/binding limits in real code.
- Review independent source, authorization and recovery contracts; explicitly freeze the target-only factory strategy and negative tests.
- No executable Godot capability or claim of B2 test PASS.

### M6-B2.2 — lab implementation, no premature live effect claim

- Build an opt-in factory for **target-only** P2/P3/Task/Execution and a B2 admission/guard/recovery path, without touching `anima/`.
- Add isolated deterministic tests for: missing/rejected/changed B1 or B2 approval; M4/M5 fingerprint and index drift; stale/replayed/corrupt P6 sample; changed producer/clock; copied original M5 Belief/Proof; target-store contamination; mismatched Goal/Task/Operation/ActionSpec/VerificationSpec; duplicate claim; changed world identity/epoch/revision; unguarded composition and P3-C denial; missing tool receipt; no unauthorized Task/effect.
- Explicitly test the **after-effect B1 revalidate impossibility** and use only B2 recovery for that path.
- No production edits, no LLM-generated consent.

### M6-B2.3 — real Godot acceptance on laptop before Raspberry Pi

- Run fixed Godot 4.7.2 on random loopback ports with **fresh isolated per-case fixtures**.
- Positive: one actual Godot door effect, new target P2 independent sensor Proof, the **original** canonical Goal completed, exactly one target Task/Operation, no duplicate effect.
- Negative: unapproved/rejected, stale/mutated producer/source/map/index, changed world, replayed sample, duplicate claim or operation, and closed-world/NOOP distinctions. All denied action paths have **zero** effects.
- Process cuts: `before_effect` and `after_effect_before_receipt` with **one continuing external Godot world per case across Core restarts**; never retry an uncertain effect. `before_effect` may remain uncertain with zero effects, `after_effect` may finish via read-only keyed reconciliation + independently observed closed state with one effect.
- Python 3.12/3.13/3.14 full regression + pinned Godot lane + owner notebook Python 3.14.4 report. JSON must include commit, Python/Godot versions, per-case world-effect counts, source lineage, Goal/Task IDs, world identity, target P2 evidence and explicit nonclaims.
- Only **after** laptop/Godot acceptance, run a **separately scoped** Raspberry Pi ARM64 smoke/regression where feasible. Pi tests must not be misrepresented as equivalent to x86_64 Godot without a real Pi Godot lane.

## 6. Hard FAIL / bounded trust

**Hard FAIL:** mixing original and Godot P2 in one Belief snapshot; mutating original M5 registration or binding; cloning the M4 Goal; promoting B1 approval or M6-A ticket to Godot authority; any Tool call without separately approved B2 claim; effect duplication; using Tool receipt or old-world evidence as independent Goal Proof; resurrecting an action after ambiguous failure; effect-capable P3-C; undisclosed production modifications.

**Not proven by B2:** global `build_core`/process capability firewall, authenticated human operator, adversarial arbitrary local DB/socket/process isolation, atomicity across SQLite and Godot, true `SIGKILL`/power-loss durability, LLM autonomy, physical actuation, Pi parity or official Stage completion. Those need independent gates.

**Exit decision:** A B2 implementation may begin only if the target factory can share the **original GoalStore** while isolating **all** target P2/P3-A/Task/Execution/Proof state; if this cannot be done safely with current public Core classes, **stop and reopen the design** rather than silently weakening the boundaries.
