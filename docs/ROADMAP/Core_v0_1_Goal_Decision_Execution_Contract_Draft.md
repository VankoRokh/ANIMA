# ANIMA Core v0.1 — Belief → Goal / Task → Decision → Execution / Verification (P0)

**Status:** Proposed for owner review; **not** production implementation and **not** P0 Complete.  
**Date:** 2026-11-05.  
**Code baseline:** `e2a1e6bfdb6126b82ac36873dce92e7c6876aa4b`.  
**Related:** [P0 reuse audit](Core_v0_1_P0_Boundary_Draft.md), [Event/Observation/Belief](Core_v0_1_Event_Belief_Contract_Draft.md), [Core/VAL plan](Core_v0_1_VAL_v0_1_Plan_Draft.md), [Stage 6 baseline](Stage_6_Cognitive_Integration_Core.md).

## 1. Goal of this contract

Enable the autonomous no-LLM flow:

`Belief snapshot → typed externally supplied Goal criterion → persistent Task evaluation → bounded decision → independent policy admission → durable operation record → trusted capability action → receipt → independent observation → verification → Goal/Task transitions → next event`.

Core owns goal/task/action authority. External tools, virtual environments, navigation, LLM and other capabilities **never** directly complete Goal, mutate Belief or grant themselves permission. In P1–P4 the reference environment is a minimal in-process door adapter (not Godot).

**Decision authority versus execution mechanics:** Core chooses what bounded operation should be attempted and whether it is allowed; a capability executes a registered method. Core does not implement spatial pathfinding or simulator geometry.

## 2. Evidence from actual Stage 6 code

| Path | Existing behavior | Proposed usage and specific gap |
|---|---|---|
| [`internal_state/goals.py`](../../anima/internal_state/goals.py) | `GoalStore` persists priorities, descriptions, free-text `success_criterion`, `active/blocked/completed/cancelled`; `completed` is terminal | **Reuse** GoalStore; add versioned typed criterion binding, preserve human-readable description |
| [`internal_state/goal_arbitration.py`](../../anima/internal_state/goal_arbitration.py) | deterministic active-Goal ordering (priority desc, created_at asc, ID asc) | **Reuse** for first selection; no hidden state/LLM ownership |
| [`internal_state/goal_progress.py`](../../anima/internal_state/goal_progress.py) | rejects UNVERIFIED, success requires `criterion_satisfied`; on success sets Goal completed and emits internal-state signals | **Reuse** verified lifecycle with careful compatibility; optional state signals must not become mandatory action authority |
| [`tasks/contracts.py`](../../anima/tasks/contracts.py), [`tasks/store.py`](../../anima/tasks/store.py) | persistent Task `queued→active→interrupted/completed/failed/cancelled`; Task links Goal ID | **Reuse**; require idempotent task derivation from one outstanding Goal/condition |
| [`resolution/resolver.py`](../../anima/resolution/resolver.py) | deterministic `QUERY_FACT/CALCULATE/COMPARE/POWER_COMPATIBILITY/CHOOSE_ACTION` | **Reuse** supported primitives, **not** a general world-policy engine |
| [`cognition/action_choice.py`](../../anima/cognition/action_choice.py) | ActionChoiceCoordinator requires `CHOOSE_ACTION` + a particular multiple-candidates/no-formal-policy resolution | **Reuse only when appropriate**, not mandatory for single obvious action |
| [`execution/coordinator.py`](../../anima/execution/coordinator.py) | prepares from `ActionChoiceTurn` and requires `SandboxExecutor`; rechecks active Task/Goal | **Preserve guards**, adapt one generic authorized Action preparation boundary; do not bypass task/goal check |
| [`execution/store.py`](../../anima/execution/store.py), [`execution/contracts.py`](../../anima/execution/contracts.py) | typed `ExecutionAction`/`Receipt`, operation ledger and idempotency classes `repeat_safe/keyed/none` | **Reuse** existing contract wherever viable |
| [`execution/verification.py`](../../anima/execution/verification.py) | FileObserver + verifier support `file.content_equals`; `GoalVerificationBridge` needs action-associated evidence | Add **registered** `world.property_equals` verifier; also allow observation-only success when **no action** was necessary |
| [`cognition/recovery.py`](../../anima/cognition/recovery.py) | Stage6RecoveryCoordinator persists trace and normalizes `executing→uncertain`, but requires TaskSleepCoordinator | Compose optional-Sleep recovery for Core; preserve operation reconciliation semantics |
| [`diagnostics/unified_trace.py`](../../anima/diagnostics/unified_trace.py) | persistent task-scoped causal trace | **Reuse**, expand correlation for BeliefRevision + admission outcome |

**Do not claim Stage 6 already delivers ordinary autonomous operation.** The current default CLI does not compose these into a live world-action loop.

## 3. One-shot Goal versus maintained condition — important explicit distinction

The existing Goal contract has a terminal `completed` state and no supported `completed→active` transition. The example «поддерживать дверь закрытой» is **not** equivalent to a one-shot «убедиться, что дверь закрыта».

### v0.1 normative scope proposal

- **First-class v0.1:** externally supplied `ensure_once` Goal. Example: `door_01.state == closed`. Goal is completed only when system-authorized verification has confirmed the required condition, **even if no action was needed**.
- **Outside v0.1 mandatory loop:** `maintain/monitor` Goal. This remains active across success and triggers new checks on change. It requires separate policy, recurring task lifecycle, and suppression of duplicate actions; defer to later gated capability rather than silently treating completed Goal as perpetual.
- The virtual-lab recurring-door scenario can later be implemented as explicit monitor capability or repeated one-shot test goals, but these two are not semantically interchangeable.

**No automatic task generation without a Goal/authorized policy.** Tasks can be derived mechanically from a given Goal, but the Core does not invent open-ended goals.

## 4. Typed goal criterion and binding

GoalStore `success_criterion` is human-readable. Proposal: store a **versioned typed criterion binding** keyed to the canonical Goal ID via an explicit system-owned registry/sidecar (avoid breaking existing Stage 2 Goal records). The binding has one owner; storing a copy elsewhere is not a second editable source.

### v0.1 criterion

```json
{
  "contract": "core.goal_criterion/0.1",
  "goal_id": "goal_<uuid4>",
  "mode": "ensure_once",
  "criterion_kind": "world.property_equals",
  "subject_ref": "entity.door_01@registry-r1",
  "predicate_ref": "world.door_state@1",
  "expected": {"type": "symbol", "value": "closed"},
  "scope": {"kind": "registered_current_state"},
  "verification": {
    "method": "registered_observer",
    "max_age_ticks": 1
  }
}
```

Conceptual payload, not yet a production JSON Schema. Registered context `registered_current_state` is an explicit *test/decision policy*, **not** a Stage 7 claim of unbounded world-valid time. Time domains and evidence scope must match the Event/Belief contract. Criterion cannot be created or silently modified by an untrusted module.

Goal creation and criterion binding may span existing `internal_state.db` and new Core SQLite; until a unified storage decision, require recoverable `pending/bound` state and block scheduling any unbound Goal. No unguarded cross-DB atomicity claim.

## 5. Persistent Task derivation and lifecycle

For each scheduled authorized Goal and unsatisfied criterion:

- `OBSERVE`: gather current condition when no eligible fresh observation exists.
- `OPERATE`: apply registered admissible action when target condition is known not satisfied.
- `VERIFY`: request independent postcondition readback, also covers no-op already-satisfied case.
- `DEFER`: wait for data, capability, explicit wakeup, or recovery.

These are **semantic task kinds**, not required new `TaskStore` statuses. Existing Task statuses remain canonical. `DEFER` may map to `interrupted` or scheduler wait metadata under a policy to be frozen before P1; never create unbounded duplicate queued tasks for the same trigger.

Proposed idempotency scope: `(goal_id, criterion_version, work_kind, observed_belief_revision, trigger_occurrence_id)` or documented equivalent, with one active equivalent task per Goal/step. This is **not** a claim that every task will have the same key across changing observations.

### Conditions

- Registered active Goal and criterion required for side effects.
- Only **independent observation/verification** can satisfy criterion. Textual description or receipt cannot.
- A Goal already satisfied by eligible fresh observation → `NOOP + VERIFY`, then terminal complete, with **zero tool effects**.
- Missing/ambiguous/stale belief → `REQUEST_OBSERVATION` or `DEFER`; never assume `false` or `open`.
- Unavailable capability / permission denied → bounded reasoned failure/defer; not model invention.
- Task and Goal status transitions have explicit reason codes, correlate to event/decision/evidence IDs.

## 6. Decision vs Policy

### 6.1. Proposed deterministic decision result

```text
CoreDecision/0.1
  goal_id, task_id, criterion_ref
  belief_key + belief_revision + evidence_refs + freshness
  choice = NOOP | REQUEST_OBSERVATION | PROPOSE_ACTION | DEFER
  reason_code
  candidate_action: registered action type/version/args or null
  max_followups/deadline logical budget
```

Decision reads a snapshot. It **cannot write Belief, Goal, Task, permissions or ExecutionStore**. It may propose one eligible operation, but only the next policy boundary can authorize it. Multiple eligible operations can be delegated to the existing ChoiceEngine/ActionChoiceCoordinator where contracts fit; v0.1 must not force all cases through `multiple_actions_without_policy`.

### 6.2. Independent ActionAdmission

System-owned Admission checks **again at execution boundary**, not only at decision time:

1. Credential/actor/capability authorization and **registered action kind/version**.
2. Persistent Task active; Goal active; criterion and action intent are bound.
3. Inputs and target reference valid; quotas/iteration guards not exceeded.
4. Action type is permitted and within configured effects class.
5. **Freshness and precondition** satisfy this action's rule; if belief revision changed since decision, re-evaluate.
6. Operation ID/request fingerprint/idempotency class correct; no unresolved duplicate uncertain side effect.
7. Critical world preconditions are reobserved or checked by trusted adapter immediately before effect when needed; local Belief version matching is **not enough** for external-world freshness.

`Denied/Deferred` must be persisted/auditable; no fallback direct world mutation.

## 7. Execution, independent observation and verification

**Capability** is a port with `manifest/0.1`, `action schema`, `effect class`, `idempotency class`, `precondition check`, `execute` and `observe/readback`. Not a plug-in that can mutate Core stores.

Expected flow:

```text
(1) Goal+typed criterion active
(2) Scheduler reads Belief
(3) Decision proposes NOOP / OBSERVE / ACTION / DEFER
(4) Policy rechecks authorization/preconditions and records verdict
(5) When ACTION: prepare persistent ExecutionOperation
(6) Trusted adapter attempts operation; record ExecutionReceipt
(7) Independently request new registered Observation (even when receipt says success)
(8) System-owned verifier evaluates world.property_equals from eligible evidence
(9) Verified criterion satisfied → Goal completed; Task completed
    Otherwise → unresolved/failed/deferred as policy allows, no false completion
```

**No-op completion:** Stage 6 `GoalVerificationBridge` expects action-associated `Observation`. Therefore v0.1 needs an explicit observation-only verified-criterion path, without fabricating a fake successful action or passing `criterion_satisfied=True` as an unchecked caller assertion. Reuse `GoalProgressEngine` only *after* verifier validation, or adapt a safe bridge preserving that guard.

**Failure/unavailability:** Under existing Stage 6 `VerificationResult` an outcome `none` means no decisive observation, not success. For `world.property_equals`, a registered `unsatisfied`, `unavailable` and `not_observed` must stay distinct until mapped into compatible existing result/Goal transition semantics.

**Side effects and replay:** Preserve `ExecutionStore` ledger with `prepared/executing/succeeded/failed/uncertain` and `repeat_safe/keyed/none`. `executing` after crash is `uncertain`; non-idempotent ambiguous action is not silently retried. Receipt status and verification evidence must be separately persisted and causally linked. Postcondition checker never trusts just the executor's return code.

## 8. Bounded scheduler, fairness and lifecycle

- One event-driven system-owned driver; subscribe to durable committed observations and operation outcomes; optional clock ticks, retry deadlines and explicit wakeups.
- Idle means blocking/waiting rather than tight `while True` polling or model inference.
- Limit per-turn new tasks, operations, retries and verification checks; record `max_steps`/`max_age`/`no_progress` exhaustion.
- For v0.1 choose existing deterministic active-Goal priority order via `GoalArbitrator`. Multi-goal fairness requires bounded test and explicit policy before calling it guaranteed.
- Module errors do not silently convert to success, and error events do not flood their own queue indefinitely.
- Recovery can run without Sleep: normalize operations, reconstruct pending tasks and attach traces; if external operation outcome is uncertain, reconcile/observe before retry. Existing Stage6RecoveryCoordinator's required Sleep dependency must be abstracted or split without replacing TaskStore authority.

## 9. Risk boundaries and checks

Existing standalone stores currently include `core_state.db` (proposed), `internal_state.db`, `tasks.db`, `execution.db` and trace store. The approved **single SQLite transaction** from Event/Observation/Belief applies to **that projection only**. It does not cover arbitrary Task/Goal/Action writes in separate databases.

For P3–P4 select a **durable coordination protocol** using outbox/work-intent and recovery reconciliation; no global transaction or exactly-once side effects claimed. The exact journal-to-task/work dispatch order must be fixed and fault-tested before implementation.

### Additional execution-level acceptance fixtures

| ID | Situation | Expected |
|---|---|---|
| DX-01 | fresh eligible observation already equals target | NOOP, independent verification, Goal completed, no effect |
| DX-02 | fresh eligible observation != target | one admitted action, persisted operation, independent verification, Goal completed |
| DX-03 | stale or unknown belief | observation/defer, no unauthorized assumption/action |
| DX-04 | belief changes between decision and effect | no stale unsafe effect; re-evaluate |
| DX-05 | action receipt succeeded but observer says unchanged | Goal not completed |
| DX-06 | executor error/timeout; effect uncertain | no false success; bounded recovery/reconciliation |
| DX-07 | restart after effect before verification | persisted pending verification; no blind action replay |
| DX-08 | forged proposal / unregistered capability | rejection, no effects or permission mutation |
| DX-09 | inactive Goal or Task; mismatched IDs | deny at prepare and immediately before effect |
| DX-10 | two active Goals with different priorities | deterministic ordering and trace, starvation limitation measured |
| DX-11 | two independent events create same work | one equivalent active Task and bounded effects |
| DX-12 | request `maintain` against `ensure_once` contract | explicit unsupported/reject, not silently mark permanent monitoring |
| DX-13 | verified unsatisfied/no observation | keep Goal unresolved, honest reason |
| DX-14 | legacy Stage 6 acceptance and recovery regressions | no contract regression |
| DX-15 | event flood plus one relevant change | bounded scheduling, no duplicate action, relevant work eventually considered under tested budget |

These fixtures extend existing C0–C8 and S01–S10; not a third separate acceptance authority. Fault-injection at DB boundaries and test adapter effects must include traces showing exactly where a failure was induced.

## 10. Decisions proposed to owner before P1/P3

**E1 — Goal lifecycle (Accepted in principle, 2026-11-05):** v0.1 implements `ensure_once`, not open-ended `maintain`; finish Goal from independently checked condition even when no action was needed.

**E2 — Criterion binding (Accepted in principle, 2026-11-05):** keep Stage 2 `GoalStore` canonical, add versioned typed criterion sidecar/registry, reject/unbound Goals from active work until reconciliation; no silent DB migration.

**E3 — Decision / policy separation (Accepted in principle, 2026-11-05):** bounded deterministic `NOOP/REQUEST_OBSERVATION/PROPOSE_ACTION/DEFER` + separate non-bypassable system policy; existing ChoiceEngine reused only for supported multiple-candidate cases.

**E4 — World execution/verification (Accepted in principle, 2026-11-05):** keep Stage 6 ExecutionAction/Store/Receipt semantics; add registered world adapter and `world.property_equals` independent verifier, including observation-only completion; no faux successful action for NOOP.

**E5 — Recovery (Accepted in principle, 2026-11-05):** Core recovery without hard Sleep dependency, explicit post-crash `uncertain` and reconciliation before retry, no arbitrary exactly-once claim.

**E6 — Cross-store persistence (Accepted in principle, 2026-11-05):** adopt journal/work-intent/outbox and idempotent reconciliation protocol spanning Core journal→Task/Goal→Execution. Only Core Event/Observation/Belief changes are atomically committed in single SQLite DB; no cross-DB transaction guarantee.

Owner has agreed to E1–E6 as architectural direction. Exact wire schemas, readback semantics and fault-test details remain implementation gates; baseline regression remains unmeasured in this session. Agreement is not a passing P0 gate or proof of operational reliability. A separate P1 bootstrap slice can be developed without enabling any of the P2–P4 semantics prematurely.
