# ANIMA Core v0.1 — P3-B Door Execution / Independent Verification

**Status:** **P3-B PASS по сообщению владельца** (2026-11-05): предложенные проверки прошли успешно. Точное число тестов и SHA локального прогона не приложены; это не CI и не запуск ассистента. P3-C и автономный Core пока не подтверждены.  
**Date:** 2026-11-05.  
**Branch:** `work/core-v0-1-p3b-execution` (based on owner-reported P3-A PASS).  
**Upstream:** [P3-A Typed Goal/Task/Decision](Core_v0_1_P3A_Goal_Decision_Draft.md), [P2-C Runtime/Dispatch](Core_v0_1_P2C_Runtime_Integration_Draft.md), [P0 Execution Contracts](Core_v0_1_Goal_Decision_Execution_Contract_Draft.md).

## 1. Scope

Implement an **explicitly triggered**, end-to-end `ensure_once` **one-door** loop that can perform one bounded operation under a trusted policy and can complete an existing Goal **only after independently admitted sensor readback**.

```text
Explicit Goal + typed binding
  → trusted door sensor → CoreIngress/Belief (P2)
  → CoreGoalDecision (P3-A)
  → fresh pre-effect reobservation + independent ActionAdmission
  → Stage6 ExecutionAction/ExecutionStore + VerificationSpec
  → Stage6 SandboxExecutor (registered world.door.close@0.1)
  → independent virtual-door sensor (not tool receipt)
  → typed Core Observation + Core Belief evidence check
  → durable Core proof → existing GoalProgressEngine + TaskStore completion
```

**No generic autonomous cycle, unrestricted tools, LLM, Godot, maintain/monitor Goals or true multi-Goal scheduling here.** Those belong to P3-C and later.

## 2. Production reuse

- [`anima/core/door_world.py`](../../anima/core/door_world.py): deterministic, isolated SQLite world fixture. `VirtualDoorWorld.seed()` is explicit and never overwrites existing world state; `sense()` reads the world independently of action receipts and emits a registered typed observation. `change_by_environment()` is strictly a privileged test-operator method.
- `door_tool_registry()`: one exact-target `world.door.close@0.1` ToolDescriptor with `reversible_write` and `keyed` idempotency. No path/shell/tool inference. The handler writes a keyed effect record and door state **in one world DB transaction**.
- [`anima/core/door_execution.py`](../../anima/core/door_execution.py): `CoreDoorExecution` bridges existing typed Goals/Tasks, Stage6 execution ledger and independent typed world observations. It does **not** take arbitrary caller-supplied ActionSpec at effect boundary; it re-derives proposals from registered Belief and deterministic config.
- [`anima/core/assembly.py`](../../anima/core/assembly.py): optional `virtual_door_root=...` adds P3-B when `sources`, `properties` and `goal_actions` are provided. Default CLI remains no world tool and no extra ExecutionStore.
- [`anima/runtime.py`](../../anima/runtime.py): `run_core_door_goal(goal_id)` explicitly invokes one bounded P3-B turn and reconciles Core→legacy observations.
- [`tests/test_core_p3b_execution.py`](../../tests/test_core_p3b_execution.py): full vertical-slice and failure tests.

**Stage6 contracts reused:** `ActionSpec`, `ExecutionAction`, `ExecutionStore`, `SandboxExecutor`, `ExecutionReceipt`, `VerificationSpec`, `Observation`, `VerificationResult`. Goal status remains owned by Stage2 `GoalStore/GoalProgressEngine` and Task status by Stage6 `TaskStore`. Stage6's existing `file.content_equals` verifier remains untouched: `world.property_equals` is implemented as a narrow independent Core Belief/evidence check rather than pretending the file verifier supports it.

## 3. Decision and effect admission

The driver only accepts registered `ensure_once / world.property_equals` Goals with expected exact `door_01.state=closed`. World properties and source authority must be registered **before** composition. The `source_ref` is supplied internally by the trusted adapter; **registration is not remote authentication**.

Allowed flow:

1. `CoreDoorExecution.run(goal_id)` checks Goal status and immutable typed criterion.
2. The sensor reads the world. Only the resulting accepted `CoreIngress` record may update Belief.
3. P3-A produces `REQUEST_OBSERVATION | DEFER | NOOP | PROPOSE_ACTION`.
4. `NOOP`: a **second independent readback** is required before any Goal completion. No fake action or successful receipt is manufactured.
5. `PROPOSE_ACTION`: reobserve/re-evaluate, verify active Goal + Task, frozen candidate tool/version/arguments, registered target, exact Belief revision, admissible preconditions. Prepare `ExecutionAction`, persist operation and typed `VerificationSpec` **before** calling Stage6 executor. Recheck Goal+Task immediately before effect.
6. Execute via `SandboxExecutor`. The return code is **not** a Goal success indicator.
7. Post-effect: sensor reads world without consulting receipt. Verifier cross-checks accepted original `event_id`, authorized source, observation acceptance outcome, Belief evidence reference, freshness, registered subject/predicate and typed expected value.
8. Only verified result leads to a durable proof, then a Stage2 Goal transition and Stage6 Task transition.

### Residual limitation

The exact single-door handler is transactionally idempotent and can only close its known target. A world-state change between last reobservation and process invocation cannot authorize other arbitrary actions; the handler remains restricted. General-world compare-and-swap effect guards and multi-step transactional preconditions are **not** implemented by P3-B.

## 4. Durable journals / crash behavior

Persistence remains split across `core_state.db` (events and Belief), `core_work.db` (typed binding, task intent, decision log and **new `core_world_proofs`**), `tasks.db`, `internal_state.db` and Stage6 `execution.db`. No global transaction is claimed.

- The Stage6 `ExecutionStore` holds the canonical operation and exact validated Action/VerificationSpec. Duplicate execution attempts must first consult this ledger.
- The virtual world holds one keyed effect row per operation ID. If process crashes after effect but before receipt, restarting turns `executing` into `uncertain`; P3-B **reads keyed effect state without invoking Executor's retry path**. Reconciliation can mark it succeeded, but uncertain missing effects are **not** executed blindly.
- A succeeded operation is never executed a second time by P3-B. Instead a new sensor read may confirm success or leave the Goal unresolved.
- If an operation was only `prepared` and the door was closed independently, the operation is marked `cancelled` **after verified readback**; no redundant effect.
- Once a sensor confirms success, `core_world_proofs` stores the `event_id` and Goal/Task/action identity *before* Goal and Task transitions. On restart it finishes those transitions without generating another effect or a new proof.
- No-op verified success is recorded by a proof with `operation_id=NULL`. It is **not** represented by a fabricated `ExecutionReceipt`.
- Stage6 `Observation/VerificationResult` is generated for post-action readback in this iteration, while the durable cross-DB proof and Core source observation are the canonical evidence; a general persisted multi-tool verification result store remains for later stages.

This is **bounded single-process crash recovery** in a controlled fixture, not exactly-once execution across arbitrary external systems, nor a guarantee under disk corruption or malicious DB edits.

## 5. Acceptance scenarios and local commands

Run from project root:

```bash
git rev-parse HEAD
bash scripts/check.sh
.venv/bin/python -m pytest -q \
  tests/test_core_p3b_execution.py \
  tests/test_core_p3a_goal_decision.py \
  tests/test_core_p2c_runtime.py \
  tests/test_core_p2b_belief.py \
  tests/test_core_p2a_ingress.py \
  tests/test_core_p1_bootstrap.py
.venv/bin/python -m pytest -q
```

Acceptance cases:

- open→authorize→execute once→readback→verified Goal+Task success;
- already closed→NOOP→second sensor read→verified success without operation;
- unbound/inactive Goals and unregistered candidate→no effect;
- succeeded receipt but actual door reopened→Goal stays active; no blind retry;
- cancellation between preparation and effect→deny;
- crash before effect→restore prepared operation with identical ID;
- effect applied but receipt lost→reconcile keyed effect; never repeat;
- receipt committed but verification missing→read back on restart, no repeat;
- proof persisted before Goal completion and Goal completed before Task completion→both resume without another effect;
- missing persisted VerificationSpec→fail closed rather than inventing one;
- external close cancels unnecessary prepared operation;
- default `build_core()` remains without world adapter;
- old Stage6/P2/P3-A regression tests remain passing.

**P3-B acceptance evidence:** пользователь сообщил «Все проверки прошли успешно» после выполнения предложенных `scripts/check.sh`, прицельного и полного pytest; числовой вывод и `git rev-parse HEAD` в сообщении отсутствуют. Это owner-reported PASS, не независимая проверка exact snapshot. Перед финальным release gate рекомендуется повторный тест с сохранением точного SHA. Реализация P3-C получает отдельный gate и не наследует PASS автоматически.

## 6. Next: P3-C

After P3-B passes: drive Goal scheduling from durable events/wakeup (rather than explicit one-turn call); bounded retries, fairness, traces, refusal cases and long multi-step system scenarios. Then run the full Core v0.1 acceptance suite. Virtual ANIMA Lab integration remains a subsequent milestone.
