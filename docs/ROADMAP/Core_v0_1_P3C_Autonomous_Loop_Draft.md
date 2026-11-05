# ANIMA Core v0.1 — P3-C Bounded Autonomous Event Loop

**Status:** implementation in isolated work branch; **UNVERIFIED** until owner-local full regression + isolated system demonstration.  
**Date:** 2026-11-05.  
**Branch:** `work/core-v0-1-p3c-autonomy`.  
**Dependency:** [P3-B Door Execution](Core_v0_1_P3B_Door_Execution_Draft.md), [P3-A Goal/Task/Decision](Core_v0_1_P3A_Goal_Decision_Draft.md), [P2-C Event/Belief Runtime](Core_v0_1_P2C_Runtime_Integration_Draft.md).

## 1. Bounded vertical slice

This is the first **event-triggered, system-initiated** Core loop. New accepted typed Goals or selected accepted sensor events can wake the Core. It then executes **at most a configured number** of work steps and returns to idle. It does not invent goals, operate without registered permissions, run a background daemon, or bypass P3-B independent verification.

```text
Owner registers a one-shot Goal
  → immutable criterion in existing CoreGoalDecision
  → persistent CoreAuto trigger in core_work.db
  → bounded CoreAutonomy.drain()
  → Stage2 active Goal arbitration + Goal TaskStore
  → P3-B policy/readback/Stage6 execution ledger
  → independently verified Goal / Task transitions
  → durable scheduler attempt result; idle

Second trigger family:
trusted EXTERNAL registered observation → P2 Core SQLite journal
  → P3-C scans journal with persistent cursor
  → typed, accepted, comparable property update → auto event trigger
  → same bounded execution and verification path
```

The **privileged internal** `sensor.door_01` used by the P3-B adapter for readback is **not an autonomous event trigger**. Its observations still update Core Belief and legacy history, but cannot feed themselves back into the scheduler indefinitely. An independent external adapter needs its **own** registered `source_ref`; the P3-C one-door profile excludes all events from the internal readback source. Raw claims rejected by P2-B and unrelated property events never reach the execution boundary.

## 2. Implemented components

- [`anima/core/autonomy.py`](../../anima/core/autonomy.py): `CoreAutonomy`, `AutoStep`, `AutoDrain`. Synchronous bounded trigger scan, repeatable Goal-bound tasks, persistent per-trigger attempts and last-committed Core journal scan cursor.
- [`anima/core/ingress.py`](../../anima/core/ingress.py): read-only `observation_triggers_after(rowid,limit)` for committed raw events and their validated observation outcomes. It neither mutates Belief nor creates triggers itself.
- [`anima/core/door_execution.py`](../../anima/core/door_execution.py): `recover_proofs(limit)` completes previously independently verified Goal/Task transitions after a crash, **including a Goal already completed while its Task was still active**. It does not invoke tool effects.
- [`anima/core/assembly.py`](../../anima/core/assembly.py): opt-in `auto_core=True` additionally requires explicit trusted source/property registries, ActionSpecs and `virtual_door_root`. Default `build_core()` remains ordinary CLI without auto execution.
- [`anima/runtime.py`](../../anima/runtime.py): new `run_core_autonomous(max_steps=4,...)`; automatic bounded drain after successful `bind_core_goal`, registered external `ingest_core_event`, and `wake()`. A failed/duplicate Goal binding can still resume pending work.
- [`anima/core/demo_p3c.py`](../../anima/core/demo_p3c.py): isolated, headless demonstration showing the registered Goal, choices, Stage6 operation ledger, durable scheduler attempts, typed Belief evidence and operator-labeled external world truth. Rejects nonempty data directories.
- [`tests/test_core_p3c_autonomy.py`](../../tests/test_core_p3c_autonomy.py), [`tests/test_core_p3c_demo.py`](../../tests/test_core_p3c_demo.py): first autonomous system and crash-recovery acceptance scenarios.

## 3. Persistence / safety contracts

`CoreAutonomy` extends **existing** `core_work.db` (no competing Goal/Task store):

| Table | Purpose |
|---|---|
| `core_autonomy_meta` | Core journal scan cursor `event_cursor` (SQLite rowid) |
| `core_auto_triggers` | Durable Goal and external-event triggers, `pending/done` |
| `core_auto_attempts` | Per-trigger/per-goal `started/finished`, decision/result evidence |

- Scan cursor and newly queued triggers commit **atomically in core_work.db**. If process fails before commit, the Core journal is rescanned. If after commit, pending triggers survive.
- `started` attempt is replayable after crash; P3-B Stage6 ExecutionStore and keyed world effect reconciliation prevent blind duplicated actions. A failed attempt remains pending until a later wake/pulse. The scheduler never directly calls a tool.
- Persisted P3-B verification proofs are resumed **before scanning active Goals**, so a completed Goal with unfinished Task is recovered without re-execution or fake new observation.
- A `finished` attempt does not rerun on the same trigger. Fresh external accepted evidence can create a **new** trigger; P3-B independently guards against incorrect side-effect retries.
- Per-drain budget defaults: **4** actual work steps, **32** candidate trigger steps, **64** new Core event journal rows (hard bounds 32/128/256 respectively). Remaining work stays in persistent tables; `AutoDrain.more_input_events` warns when another scan may be needed.
- Single-process/single-writer v0.1 only. The cursor uses Core SQLite local rowids: not a distributed Kafka offset or cross-database atomic log. No global exactly-once side-effect guarantee.
- P3-B remains the **sole** policy/effect/verification authority. Goal arbitration uses existing Stage2 priority rules but current per-trigger processing provides only limited fairness: one attempt per Goal per trigger, and a new external trigger may produce another attempt. Formal scheduler fairness/quotas across many unrelated goals are beyond this one-door profile.

### Explicitly not supported

No unrestricted autonomous Goal generation, no periodic background poller or continuous monitor Goals, no external-agent authentication, no generic multi-world ActionAdmission, no real-world device control, no Stage7 Knowledge write authority, no LLM planner, no Godot/GUI, no power-loss/disk-corruption guarantee, no distributed multi-process orchestration.

The demo is an **illustration of actual executable Core logic**, but not a substitute for unit/integration/fault/system tests.

## 4. System acceptance

Test families newly covered:

| Scenario | Expected |
|---|---|
| Auto Goal binding when door open | one authorized operation, verified completed Goal/Task |
| Auto Goal binding when door closed | observation-only success, zero world effect |
| Default CLI or P3-B without opt-in | no automatic tool execution |
| Invalid/unrelated raw events and internal readbacks | no auto action and no infinite self-triggering loop |
| New authorized external observation | a relevant bound Goal may resume, but no duplicate side effect |
| Two registered Goals, budget one | bounded step, next pulse serves other eligible Goal |
| Crash after binding, before notification | wake discovers binding and resumes |
| Effect applied, receipt lost | no repeat; Stage6 keyed reconciliation + readback |
| Verified Goal committed, Task incomplete | recovery finishes Task despite terminal Goal |
| >64 irrelevant events | bounded cursor makes measurable progress across calls |
| Invalid budgets and nonempty demo dir | reject, no instance-data overwrite |
| Demo open/closed | structured diagnostic output, only expected operation count |

Passing P3-C requires **all** listed checks and existing P3-A/P3-B/P2/P1 regressions. A successful open-door demo alone does **not** mean general-purpose autonomy.

## 5. Local acceptance commands

From repository root, with clean worktree:

```bash
git rev-parse HEAD
bash scripts/check.sh

.venv/bin/python -m pytest -q \
  tests/test_core_p3c_autonomy.py \
  tests/test_core_p3c_demo.py \
  tests/test_core_p3b_execution.py \
  tests/test_core_p3a_goal_decision.py \
  tests/test_core_p2c_runtime.py \
  tests/test_core_p2b_belief.py \
  tests/test_core_p2a_ingress.py \
  tests/test_core_p1_bootstrap.py

.venv/bin/python -m pytest -q
```

Optional, independent two-case system demonstration, **always using fresh unique directories**:

```bash
demo_open="$(mktemp -d)"
demo_closed="$(mktemp -d)"
.venv/bin/python -m anima.core.demo_p3c --data-dir "$demo_open" --initial-state open
.venv/bin/python -m anima.core.demo_p3c --data-dir "$demo_closed" --initial-state closed
```

The structured output contains `stage=bootstrap`, `goal_registered`, `decision`, `scheduler_attempt`, optional `execution_ledger`, and `result`. `operator_ground_truth` is explicitly **privileged test operator context**, not input to the Core decision system.

**Until the owner provides test output + exact SHA, P3-C stays UNVERIFIED.** GitHub write, code reading and fixture definitions alone are not evidence of successful execution.

## 6. Next after P3-C PASS

Proceed to a **Core v0.1 integrated system acceptance gate**: long-running sequences, delayed/conflicting/noisy events, restarts injected at every durable boundary, permissions, quotas, trace/diagnostic review, cross-stage regressions and recorded results. Only after this gate should the Core v0.1 baseline be called complete. The graphical Virtual ANIMA Lab is a subsequent milestone, not a dependency for the headless Core.
