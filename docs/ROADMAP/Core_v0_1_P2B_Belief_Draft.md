# ANIMA Core v0.1 — P2-B Typed Observation / Belief Projection

**Status:** **P2-B PASS** — user-reported local regression at exact snapshot `d08e0d4b5b603ebbc22924682f7cc38b734acd68` (2026-11-05). No claim of autonomous Runtime, world actions, or full P2 completion.  
**Date:** 2026-11-05.  
**Branch:** `work/core-v0-1-p2b-belief` (derived from owner-verified P2-A).  
**Parent:** [P2-A SQLite Event Ingress](Core_v0_1_P2A_Ingress_Draft.md).  
**Contract:** [Event / Observation / Belief](Core_v0_1_Event_Belief_Contract_Draft.md).  
**Stage 7:** [Accepted semantic boundary](Stage_7_Semantic_Boundary_v0.md) has priority; P2-B does **not** grant Knowledge write/lifecycle authority.

## 1. Goal and scope

Turn registered, explicit, **typed** Core input events into persisted observation records and an independent, versioned **working Belief**. One SQLite transaction now includes:

```text
raw event admission + outbox intent
    → typed Observation + source-local order
    → BeliefSnapshot + immutable BeliefRevision
    → observation acceptance/rejection outcome
    → COMMIT (or all rollback)
```

Not yet part of P2-B: runtime wiring, dispatch ACK/outbox replay, periodic ticking, independent sensor authentication, arbitrary Knowledge semantics, external world ground-truth access, Goal/Task/Decision/Action, continuous monitoring, LLM, Godot. These remain P2-C/P3+.

## 2. Implementation

New [`anima/core/belief.py`](../../anima/core/belief.py):
- `PropertyRule` defines registered, **single-valued exact** `(subject_ref,predicate_ref)`, accepted `value_type`, `clock_domain`, allowed source refs, symbol vocabulary and logical-tick freshness limit.
- `BeliefProjection` validates state.property / sensor.unavailable payloads, persists accepted evidence, projects status and revision, and computes freshness **on read** rather than declaring observations timeless.
- `BeliefProjection.project(connection,...)` **never commits**. Caller owns transaction.

Modified [`anima/core/ingress.py`](../../anima/core/ingress.py):
- Optional `properties={...}` enables Belief. Without this parameter, P2-A raw-event mode stays available and does not mutate world Belief.
- `CoreIngress.admit` calls projector **inside** P2-A's existing `BEGIN IMMEDIATE` transaction, after event/outbox creation and before `commit` and fault-hook boundary.
- DB schema version increments from **1 → 2**, with additive table migration preserving P2-A event/outbox rows.
- Read-only `read_belief(..., as_of_tick=...)`, `belief_history(...)`, and `observation_outcome(event_id)` for test harness and later system reader.

New test module: [`tests/test_core_p2b_belief.py`](../../tests/test_core_p2b_belief.py).

**Authority boundary:** `CoreIngress` accepts only a trusted adapter source_ref; raw source labels are not authentication. PropertyRule further restricts which already-registered sources may assert a given property. Any invalid world property payload remains an auditable **raw event**, not a valid Observation, and cannot change Belief.

## 3. Typed payload v0.1

Example, registered door sensor:

```json
{
  "contract": "core.event/0.1",
  "occurrence_id": "door-a:40",
  "occurrence_version": 1,
  "kind": "state.property",
  "payload": {
    "subject_ref": "entity.door_01@registry-r1",
    "predicate_ref": "world.door_state@1",
    "observed_at": {"domain": "lab_tick", "value": 40},
    "temporal_scope": {
      "kind": "instant",
      "at": {"domain": "lab_tick", "value": 40}
    },
    "source_revision": 40,
    "value": {"type": "symbol", "value": "open"}
  }
}
```

Additional supported kind: `sensor.unavailable` with `reason` instead of `value`. Unknown is not encoded as false or a fake symbol.

P2-B accepts exact `symbol/string/boolean/integer` values only; no floats, fuzzy matching or global entity resolution. Only one logical clock domain per PropertyRule; no cross-domain time comparisons. `source_revision` is source-local, not world-global. Time is explicit point observation; **not** proof of continuous validity.

If a sensor channel has no registered PropertyRule for an entity/predicate, its raw event is accepted into the audit journal (provided P2-A envelope is valid) but marked `REJECTED_INVALID/UNREGISTERED_PROPERTY` in observation outcomes, and its claims do not enter Belief.

## 4. Belief policy (bounded exact-state profile)

- `known`: at least one accepted current observation with one noncontradictory value.
- `disputed`: conflicting accepted values for the same registered property and comparable observation tick; no source-weight winner is invented.
- `unknown`: missing or unavailable current value. `last_known` persists separately for historical context.
- `fresh/stale/undetermined`: computed on read with caller-supplied registered-clock `as_of_tick` and `PropertyRule.freshness_ticks`, independent from epistemic status.
- Delayed observations with earlier tick, or same/older source-local revision, remain historical evidence **without rolling back** current snapshot.
- Same-source same-revision redelivery under a different occurrence ID does not inflate the active support count. Exact redelivery of original occurrence ID is caught earlier in CoreIngress.
- Different source observations agreeing at the same tick add distinct evidence refs; different values at the same tick produce `disputed`.
- Later comparable observations can replace the current working state while previous versions remain in the revision history; no continuous change-time boundary is inferred.

Projection outcomes include `ACCEPTED_NEW`, `ACCEPTED_SUPPORT`, `UPDATED_LATER`, `HISTORY_ONLY`, `MARKED_DISPUTED`, `MARKED_UNKNOWN`, `REJECTED_INVALID`, `REJECTED_UNAUTHORIZED`.

**Important scope:** this is an operational view for registered direct observations, not Stage 7's general Claim relation or Knowledge acceptance. Some temporal/authority issues are deliberately handled conservatively; the verifier/action layer must never equate `known` with guaranteed current world truth.

## 5. SQLite tables and consistency

P2-B adds:

| Table | Purpose |
|---|---|
| `core_observations` | validated typed evidence, event/source/provenance, source revision and observed tick |
| `core_observation_outcomes` | per-event projection acceptance/rejection reason |
| `core_beliefs` | one current working projection per registered entity/predicate |
| `core_belief_revisions` | append-only version records tied to event IDs |

Existing `core_events` and `core_outbox` remain part of the same DB. A controlled fault after projection but before commit must roll back **all tables**. This is atomicity within the one SQLite database, not across legacy `memory.db`, `tasks.db` or an external world.

Unprocessed raw events from previous P2-A do not automatically become accepted observations by enabling the optional projection on reopen. Historical backfill/dispatch decisions belong to P2-C.

## 6. Required verification

From project root on `work/core-v0-1-p2b-belief`:

```bash
git rev-parse HEAD
bash scripts/check.sh
.venv/bin/python -m pytest -q tests/test_core_p2b_belief.py tests/test_core_p2a_ingress.py tests/test_core_p1_bootstrap.py
.venv/bin/python -m pytest -q
```

Coverage includes: atomic event+outbox+Observation+Belief, fresh/stale, new/later/replay, conflict, independent support, source-local revision, missing source authorization, unavailable sensor, crash rollback, schema upgrade from v1 and opt-in backward compatibility.

**P2-B gate: PASS** based on the owner-supplied local terminal outputs. `scripts/check.sh` PASS (89 documentation pages, 505 local links, syntax checked for 295 Python, 3 JSON, and 3 Bash files; Python 3.14.4). Targeted pytest: **44 passed in 0.75s**. Full regression: **1292 passed in 19.85s**. Verified local commit **`d08e0d4b5b603ebbc22924682f7cc38b734acd68`**. These outputs were supplied by the user, not executed by the assistant or CI. The controlled rollback is covered by the passing test suite; real power failure was not tested.

## 7. Remaining work

- **P2-C:** connect one canonical Core ingress path to Runtime, define safe outbox dispatch/ACK/replay and recovery, preserve legacy EventLog/Memory behavior. Build explicit scheduler wake signal but do not grant automatic Goal/Action side effects.
- **P3:** active Goal and typed criterion, deterministic bounded choice, system ActionAdmission, trusted world adapter and independent observer/verifier.
- Keep testing Core separately from the future Virtual Lab to avoid coupling correctness to a particular GUI/simulator.
