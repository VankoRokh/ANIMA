# ANIMA Core v0.1 — P3-A Typed Goal → Task → Decision

**Status:** **P3-A PASS по сообщению владельца** (2026-11-05): предложенные проверки прошли успешно. Точный локальный SHA и численные итоги pytest не приложены. P3-B/P3-C и автономное исполнение остаются открытыми.  
**Date:** 2026-11-05.  
**Branch:** `work/core-v0-1-p3a-goal-decision` (derived from P2-C owner-reported PASS branch).  
**Relevant contracts:** [P0 Goal/Decision/Execution proposal](Core_v0_1_Goal_Decision_Execution_Contract_Draft.md), [P2-C Runtime](Core_v0_1_P2C_Runtime_Integration_Draft.md), [P2-B Belief](Core_v0_1_P2B_Belief_Draft.md).

## 1. Scope

The first P3 slice converts an **explicit, already-existing Goal** into a persistent Task and a **bounded deterministic proposal**, using only a registered typed criterion and a timestamp-scoped Belief snapshot.

```text
owner creates Goal (existing GoalStore)
    → bind immutable ensure_once criterion
    → GoalArbitrator selects active Goal
    → reserve Task ID in core_work.db
    → construct Task in existing TaskStore / tasks.db (recoverable)
    → read BeliefSnapshot at trusted logical as_of_tick
    → NOOP | REQUEST_OBSERVATION | PROPOSE_ACTION | DEFER
    → append decision audit record
```

**P3-A does not execute, authorize, complete or verify** actions or Goals. `PROPOSE_ACTION` is an `ActionSpec` from a trusted explicit registry, **not permission to call a tool**. `NOOP` means already-observed target condition, **not** a verified Goal success. P3-B must introduce independent ActionAdmission, adapter and readback verifier.

## 2. Components

- [`anima/core/goal_decision.py`](../../anima/core/goal_decision.py): `GoalCriterion`, `CoreDecision`, `CoreGoalDecision`.
- Existing [Stage 2 GoalStore](../../anima/internal_state/goals.py) remains owner of Goals and terminal status, [GoalArbitrator](../../anima/internal_state/goal_arbitration.py) remains owner of priority selection, and [Stage 6 TaskStore](../../anima/tasks/store.py) remains owner of task statuses.
- [`anima/core/assembly.py`](../../anima/core/assembly.py): optional `goal_actions={...}` config enables `CoreGoalDecision` alongside trusted `sources={...}` and `properties={...}`; default CLI and P1/P2 setups do not create core_work.db or tasks.db.
- [`anima/runtime.py`](../../anima/runtime.py): `bind_core_goal(criterion)`, `plan_core_step(goal_id, as_of_tick=...)`, `plan_next_core_step(as_of_tick=...)`. No background work and no implicit Goal creation.
- [`tests/test_core_p3a_goal_decision.py`](../../tests/test_core_p3a_goal_decision.py): acceptance regressions, restarts and safety gates.

## 3. Criterion binding

`GoalCriterion` is version-0.1 operational subset:
- `goal_id`: existing **active** Goal ID;
- `mode`: exactly `ensure_once`, not `maintain`;
- `kind`: exactly `world.property_equals`;
- `subject_ref`, `predicate_ref`: registered PropertyRule;
- `expected`: typed atomic value, matching registered vocabulary.

Binding is immutable once committed. Repeated binding with identical content is idempotent; a different content for the same Goal ID is rejected. Its existence is **not** inferred from the free-text `success_criterion` in Stage2 GoalStore.

`core_work.db` is a separate **sidecar** (schema v1):
- `core_goal_bindings`: immutable typed criterion (canonical serialized JSON).
- `core_task_intents`: stable reserved Task ID per Goal.
- `core_decision_log`: audit of proposal kind, reason, Belief revision, selected candidate.

The sidecar does not duplicate Stage2 Goal status, Stage6 Task status or world Belief truth. It stores only the typed binding + task intent + proposal audit.

## 4. Decision policy

| Belief / Goal | P3-A decision | Side effect |
|---|---|---|
| No active Goal | `step_next()=None` or `DEFER` for explicitly requested inactive Goal | none |
| Active Goal without typed criterion | `DEFER / UNBOUND_GOAL` | none |
| Unknown, disputed or stale observation | `REQUEST_OBSERVATION / BELIEF_NOT_ACTIONABLE` | may reserve queued Task; interrupts previously active Task, **no tool** |
| Fresh known equals expected | `NOOP / TARGET_ALREADY_OBSERVED` | Task becomes active pending independent verification |
| Fresh known differs and registered action candidate exists | `PROPOSE_ACTION / TARGET_DIFFERS` | Task active; **proposal only** |
| Fresh known differs without permitted registered candidate | `DEFER / NO_REGISTERED_ACTION` | none |

As-of logical tick is supplied by the caller for P3-A testing. This is **not** yet secure external clock authority; P3-B must derive it from a trusted observer and revalidate freshness/preconditions immediately before effect. Unknown must never be interpreted as false. `NOOP` is not an assertion that the world remained at the same value after sampling.

`step_next` uses Stage2 GoalArbitrator priority, not LLM ranking. Current first-priority selection can defer an unbound top Goal; fairness and scheduling across multiple Goals remain gated by tests and explicit policy.

## 5. Crash / persistence boundary

Task creation spans `core_work.db` and `tasks.db`, so there is **no cross-DB atomicity**. To prevent duplicate tasks during covered single-process restarts:

1. Atomically reserve a UUIDv4 task_id in `core_task_intents`.
2. Create Task with the **same** pre-reserved ID in the existing TaskStore.
3. On retry, use `TaskStore.get_task(task_id)` to resume, verifying matching Goal and owner.
4. Repeated `step()` does not allocate a different Task ID. If evidence becomes stale/disputed, an active Task transitions to `interrupted`; fresh actionable evidence reactivates that same Task via the existing TaskStore lifecycle.

A crash after task creation but before decision audit is also recoverable by rerunning `step()`. The current support is for **one task intent per ensure_once Goal**, not general multi-step work DAGs, and not multi-writer concurrent scheduling. P3-B will add persistent execution intent/reconciliation and needs stronger cross-store controls.

## 6. Test gate

From repository root:

```bash
git rev-parse HEAD
bash scripts/check.sh
.venv/bin/python -m pytest -q \
  tests/test_core_p3a_goal_decision.py \
  tests/test_core_p2c_runtime.py \
  tests/test_core_p2b_belief.py \
  tests/test_core_p2a_ingress.py \
  tests/test_core_p1_bootstrap.py
.venv/bin/python -m pytest -q
```

Checks: no implicit scheduler, typed criteria, idempotent binding, missing/disputed/stale observation requests, permitted proposal only, NOOP without goal completion, single task identity after process failure, GoalArbitrator priority, legacy runtime still preserved, interrupted→active reactivation on new evidence, no `execution.db` from P3-A. `scripts/check.sh` and full pytest are blocking.

**P3-A gate:** owner сообщает об успешном прохождении всех предложенных проверок. Это пользовательское свидетельство без приложенного терминального вывода/точного SHA, а не CI и не запуск ассистента. Для воспроизводимости при следующем прогоне сохранить `git rev-parse HEAD` и итоговое число тестов. Не объявлять P3 Complete: P3-B/P3-C не реализованы/не проверены.

## 7. Next

**P3-B:** integrate existing Stage6 ExecutionAction/ExecutionStore, policy guard, trusted virtual door adapter, independent observation-only and post-action `world.property_equals` verifier. Any successful receipt alone must never complete a Goal. Plan a fault-injection case where the world effect occurred but the receipt was lost; do not blindly retry uncertain non-idempotent actions.

**P3-C:** event-driven autonomous cycle, bounded scheduling, recovery, traces and system acceptance across multiple observations, goals and faults.
