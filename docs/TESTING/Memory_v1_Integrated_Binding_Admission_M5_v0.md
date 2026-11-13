# ANIMA v0.1 Integrated — M5 separate typed-binding admission (no executor)

**Status:** CI VERIFIED (M5 seven-case gate and full Python 3.12–3.14 regression PASS) + owner-reported laptop M5 PASS (Python 3.14.4, Linux x86_64). Raspberry Pi deferred.  
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

## Observed results — GitHub CI 2026-11-13

**Executable snapshot:** `534c7d1fe37f13bea888a3890a30abac440ff6af`.  
**Primary run:** [GitHub Actions #43448293220](https://github.com/VankoRokh/ANIMA/actions/runs/43448293220) — **SUCCESS** all three Linux x86_64 jobs, including syntax/docs.

| Gate | Python 3.12 | Python 3.13 | Python 3.14 |
| --- | ---: | ---: | ---: |
| Targeted M0–M5 + P6 | **70 PASS** | **70 PASS** | **70 PASS** |
| Standalone seven-case runner | `M5_TYPED_BINDING_PASS` | `M5_TYPED_BINDING_PASS` | `M5_TYPED_BINDING_PASS` |
| Full repository regression | **1717 PASS** | **1717 PASS** | **1717 PASS** |
| Docs / syntax | PASS | PASS | PASS |

**Acceptance corpus in observed runner:** `normal` and `before_bind`, `after_bind`, `resume_approval` each result in one real typed P3-A Core binding of the existing canonical M4 Goal. `rejected`, `source_modified`, and `world_changed` preserve the Goal in its **unbound** state. No scenario creates a new Goal beyond the single preexisting M4 Goal. Every case reports **0 Tasks, 0 Effects, 0 Knowledge**. The restricted `CoreAssembly` has `core_execution=None`, `core_autonomy=None`, and a direct Core run call must fail without a configured executor. Real `CoreIngress` evaluates the door sensor's registered producer, value, tick, evidence event and P2 freshness. Core action registry/criterion are system-owned, never provided by the memory draft.

**Replay and negative tests:** record a second M5-specific operator decision; refuse unapproved/rejected receipts, conflicting replays, unregistered sensor ID, closed instead of open world, changed source after M5 approval, mismatched trusted ActionSpec, same origin re-stage with a new sensor, conflicting existing Core binding, and the *same stage sensor event replayed as an allegedly new observation*. A fresh event with **strictly larger sensor tick** is required on apply. `before_bind` hard-exits after durable admission and before `CoreGoalDecision.bind`; `after_bind` hard-exits after binding and before receipt, recovering the exact existing binding rather than creating a different one.

**Observed CI issues and corrections (no production code changed):**
1. Initial M5 setup exposed a partial Event Retrieval index after `Runtime.sleep()`. Lab runner now explicitly syncs before opening M4. M4's existing strict source-complete check remains enforced.
2. Stage snapshot serializes `PropertyRule` tuples as JSON arrays. Comparing Python tuple to parsed list produced false mismatch; system-owned registry is now compared through the *same canonical JSON* on both sides.
3. Review identified a time-of-check concern: simply replaying the first admissible sensor Event with its original tick must not count as a new observation. Added a strictly increasing sensor-tick gate and negative test before final green matrix.

### Scope limitations

This is **not** general execution authorization or autonomous action. The written P3-A binding is still a *latent capability*; a **different** future CoreAssembly with an executor and P3-C enabled could act on it. M5 does **not** provide a cross-process firewall that protects against such a future configuration. Never open the M5 lab database with executor-enabled Core until an independently reviewed M6 revalidation/admission design exists. P2 adapter names and operator `operator_ref` strings are **not** transport/human authentication. Registered sensor freshness is a logical-tick property, not proof that the physical world cannot change after observation. `os._exit` is not actual SIGKILL, device power loss, data corruption, or durable multi-process security. No LLM, Godot, Raspberry Pi, production `anima/` changes, official Stage status, or `docs/project.json` changes in M5.

### Notebook acceptance — owner-reported PASS

On a separate `ANIMA-M5` worktree using the owner's Python 3.14.4:

```bash
python -m scripts.run_memory_v1_binding_gate --report /tmp/anima-m5-PC.json
```

The script runs **seven** isolated synthetic headless Core/VirtualDoor scenarios, each with two independent Python processes and two intentional `os._exit` cuts. No Godot process must be started. The report file must be new and external to the repository; use a different name for retries. Expected overall `status=M5_TYPED_BINDING_PASS`. **Do not call the notebook gate PASS until the owner supplies its actual report.**

### Notebook result — owner-provided JSON, 2026-11-13

**Source:** the original uploaded file `anima-m5-PC.json`, parsed directly. Evidence class: owner-provided local result; **not** a remote terminal attestation. The JSON declares `schema=anima.memory_v1.binding_admission_m5/0.1`, `status=M5_TYPED_BINDING_PASS`, `python=3.14.4`, `machine=x86_64`. It contains **no Git SHA**, so the local source revision cannot be established solely from this file. The CI-tested snapshot `534c7d1fe37f13bea888a3890a30abac440ff6af` is separately verified, and branch documentation snapshot `02cb7cdcb2ceee09934207068ec6a4bf168fcff4` passed GitHub Actions #43449185168.

| Case | Final bound Goal count | Source / approval note |
| --- | ---: | --- |
| `normal` | 1 | Registered sensor + distinct M5 approval; one bound M4 Goal |
| `before_bind` | 1 | Child-process `os._exit` before write; recovered and bound |
| `after_bind` | 1 | Child-process `os._exit` after Core bind; replay reconciled |
| `resume_approval` | 1 | Distinct M5 host approval after restart |
| `rejected` | 0 | Rejection leaves existing M4 Goal unbound |
| `source_modified` | 0 | Changed M4 source rejected; `m4_source_checked=false` is expected **denial**, not successful source verification |
| `world_changed` | 0 | New sensor reading prevents binding |

Each case reports `status=M5_CASE_PASS`, `phase=verify`, `goal_count=1`, `goal_start_transitions=1`, `task_count=0`, `effect_count=0`, `knowledge_count=0`, `registered_sensor_checked=true`, `no_executor_installed=true`, `auto_core_enabled=false`. Top level: `bound_goals=4`, `tasks_created=0`, `tools_executed=0`, `executor_installed=false`.

**Nonclaims from laptop report:** `operator_authenticated=false`, `llm_used=false`, `godot_tested=false`, `pi_tested=false`, `true_sigkill_tested=false`, `production_code_changed=false`. Only the `before_bind` and `after_bind` records indicate deliberate `os._exit` cut testing. This gate does **not** establish executor security, live Godot authorization, real operator identity, SIGKILL/power loss recovery, or natural-language goal formation.

**Decision:** **M5 accepted for owner-reported functional laptop gate**, consistent with all-green CI. The **latent binding** must remain isolated from executor-enabled Core; M6 must independently design and test an enforceable admission/revalidation boundary before any action-capable Core may consume it. No Stage completion and no production `anima/` change.

**Next dependency:** M6 should separately design the safe transition from latent binding to execution-capable Core, including how *every* pending bound Goal is rechecked under fresh registered observation and explicit execution authorization before enabling Tool/P3-C. The desired experimental scope is a real Godot VAL with existing independent Proof and replay guard; production operator authentication remains a separate unsolved problem.

