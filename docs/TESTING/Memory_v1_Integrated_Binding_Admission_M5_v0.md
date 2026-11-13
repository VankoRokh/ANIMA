# ANIMA v0.1 Integrated — M5 separate typed-binding admission (no executor)

**Status:** PREDECLARED before implementation and CI.  
**Base:** M4 owner-reported laptop PASS, commit `1c691c738228c34f4b7dd880ef412328cf7c93be`, branch `work/anima-v01-integrated-m5`. Raspberry Pi deferred.

## Rationale / central hazard

M4 confirms a source-backed proposal and materializes one unbound Goal after a **lab-host** operator decision. Core's existing `Runtime.bind_core_goal()` is **not inherently a passive operation**: with P3-C `auto_core=True`, binding can trigger scheduled execution. Binding into an action-capable runtime without a separate admission gate violates M4's execution separation.

M5 introduces **a different operator decision and an immutable admission ledger for exactly one frozen GoalCriterion and trusted ActionSpec**, backed by a registered Core sensor observation. The binding is applied **only** through a restricted Core P3-A assembly with:
- Registered P2 observation source / Belief property, frozen P3-A **trusted action registry**, GoalStore and TaskStore.
- `core_execution is None`, `core_autonomy is None`, `runtime.run_core_door_goal` unavailable. The real `CoreGoalDecision.bind` may persist a typed binding; however **no Tool implementation is installed** and no Task/effect may occur.
- Existing production `anima/` untouched. This is a laboratory binding, **not a permission token to run it later**.

## Frozen M5 acceptance contract

1. An existing, active Goal must be **exactly** the canonical Goal produced by **committed** M4 Approval Ledger; its initial Goal transition and M4 evidence/fingerprint must be intact. Other Goals, a merely reviewed ticket, altered receipt or changed memory source are denied.
2. Only the frozen registered virtual door criterion `ensure_once/world.property_equals` / expected `closed`, and exact trusted Core ActionSpec `world.door.close@0.1` for the single registered subject are allowed. Full criterion, ActionSpec and PropertyRule fingerprinted in the M5 ticket. User/LLM/M3 draft **cannot** specify tool, target, priority, operator authority or GoalCriterion.
3. Require a **new, explicitly admitted** registered sensor observation with P2 Belief `known/fresh`, exact source/producer, `observed_tick` equal to supplied live observation tick, evidence event ID included and world state `open` (known work needed). Memory/user reports and fake/unknown/disputed/stale observations are denied. The lab operator/adapter owns the sensor call, **not** the model. Re-read the sensor at binding commit and check the goal's requirement and the agreed world-state precondition again; if changed, refuse binding.
4. `stage(m4_ticket, sensor evidence)`: persist a source-backed, immutable M5 admission draft. No binding. `decide(ticket, OperatorBindingDecision(APPROVE|REJECT))` is a **second, explicit** trusted-lab-host input, unrelated to the first M4 approval. An identity string in this record is **NOT authentication**.
5. `apply(ticket, new sensor evidence)`: only for exact **APPROVE**. Verify M4 source freshness, operator receipt exact hash and typed registered action/criterion, current P2 observation. Then call the real `CoreGoalDecision.bind(GoalCriterion(...))` in the **non-executable Core assembly**. If process exits after Core binding but before M5 ledger finalization, an independent new process must find the identical existing binding and reconcile without duplicate action/Task.
6. Stage/approve/reapply of identical immutable records are idempotent. Changed receipt or proposal, changed goal ID, conflicting Core binding, corrupt M4 ticket, changed registry/allowed source, unavailable/stale sensor, changed world state, or partial Memory/Event index must fail closed.
7. **Never** create/complete a Goal, create any Task, invoke Tool, alter Belief from Memory, confirm Knowledge, or enter P3-C automatic scheduling in M5. Binding remains a *latent* execution capability if a future process opens the same Core data with an executor: **M6 must revalidate/re-authorize before any such process is allowed to act**. This gate does not provide an enforceable cross-process production capability firewall.

## Planned evidence

- `labs/virtual_anima_lab/python/m5_binding_admission.py` — isolated ledger and exact-source admission.
- `scripts/run_memory_v1_binding_gate.py` — separate subprocess per normal, pre-bind hard exit, post-bind pre-ledger exit, reject, modified source, changed world scenarios; additional negative tests.
- `tests/test_memory_v1_binding_gate.py` — injection, replay, action/criterion drift, fake sensor/Goal, unconfigured executor.
- CI Python 3.12/3.13/3.14, all earlier M0–M4 targeted plus M5, full regression, syntax/docs, JSON report.
- Local notebook x86_64/Python 3.14.4 only **after CI**. No Godot / Raspberry Pi or real SIGKILL in M5.

**Explicit nonclaims:** Host-provided `operator_ref` does not authenticate a human. `os._exit` is not real SIGKILL/power loss. Trusted sensor adapter is simulated headless SQLite world, not an authenticated external process. An independently started action-capable Core with the same persistence is **out of scope** and must be prevented by deployment rules until separately designed authorization controls exist. Do not mark Stage completion or change `docs/project.json`.

## Observed results

Pending.
