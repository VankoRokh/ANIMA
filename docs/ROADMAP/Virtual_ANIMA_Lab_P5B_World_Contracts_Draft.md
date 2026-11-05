# Virtual ANIMA Lab — P5-B Versioned World Contracts

**Status:** **P5-B real Godot↔Python headless integration PASS (owner-reported: 10/10 checks, 29 requests)** and typed GUI controller 24/24 moves PASS. Backward-compatibility P5-A smoke rerun on this branch PASS (9/9, 22 commands, seed 7). Remaining evidence gates: native Godot V2, standalone Python V3 and full-suite V8; exact tested SHA not provided. The branch is not yet formally accepted or independently audited.  
**Date:** 2026-11-05.  
**Branch:** `work/val-p5b-world-contracts` (based on last owner-observed P5-A doc commit `788a04c3d93f59e05068474572044f577f9cfcb8`).  
**Scope:** isolated P5 Lab only. **No import of `anima` and no changes to Core, Stage6 execution, Goals, Belief, Memory, or `docs/project.json`.**  
**Prior result:** P5-A Godot 4.7.2 real headless 9/9 PASS (22 commands, seed 7) and owner-reported successful GUI dual-control experiment; [P5-A evidence](Virtual_ANIMA_Lab_P5A_Feasibility_Draft.md). Exact smoke SHA and some formal P5-A gates were not supplied.

## 1. Goal and boundaries

Develop the boundary **before** P6 Core integration, not a second Core:

```text
  Godot world truth (operator-only inspection)
          │
          ├─ agent observation / val.bridge/0.2 ──► Python Lab DTO validator
          │                                               │
          └─ conditional, keyed agent step ◄───────────────┘
                         │
                         └──► receipt (effect outcome only, NOT Goal proof)
```

Godot owns the simulated world, logical time and event provenance. A future
trusted Python adapter (NOT implemented here) will own authentication, transport
identity binding, source registration, validation against Core semantics and
policy. A claimed role field on loopback JSON is **not authentication** and is
**not** valid evidence authority.

`val.bridge/0.1` remains active without a behavior-breaking migration: its
P5-A smoke and visual controller still operate on the same geometry. New
functions are enabled only with exact `val.bridge/0.2` protocol marker.

## 2. Clock and identity

- `epoch` is a positive world incarnation number. Every operator reset
  increments it and resets `revision` and `tick` to zero.
- `revision` changes with world-state mutations (actor movement, door state,
  pause/resume, operator step), **not** with pure observations or failed
  collision attempts. It is a *conditional action guard* within this process,
  not a distributed CAS guarantee.
- `tick` is the lab's logical clock (including failed movement attempts); it
  is NOT UTC, monotonic system time, or a Stage 7 Instant.
- `event_seq` is monotonic throughout one Godot process, including resets;
  each journal item has `val_evt:<event_seq>`. In-memory history retains 256
  entries and is wiped on reset; stale cursors fail with `CURSOR_EXPIRED`.
- `observation_id=val_obs:<epoch>:<monotonic_sample_seq>` uniquely labels
  samples within a process. The sample's `observed_at` is `{epoch, tick}`;
  the future Python trust adapter should record **received_at separately**.
- `operation_id` is a caller-provided bounded ASCII key (1–64 chars,
  letters/digits/`._:-`). The lab maintains an **in-process** operation
  fingerprint and original receipt. A matching redelivery returns
  `replayed=true` without another effect or event; conflicting payload
  returns `OPERATION_ID_CONFLICT`.

**Critical limit:** the action ledger is volatile and capped at **1024 known
operation IDs** per world epoch. At capacity, new actions are refused with
`LEDGER_CAPACITY` (no eviction and accidental double action). On reset or
process exit, the ledger is lost. Therefore **not crash-durable exactly-once**.
A future P6 adapter must handle uncertain effects/reconciliation and persistent
authority without treating this toy ledger as a transactional guarantee.

## 3. Wire contracts (new profile only)

The Python `LabClient(protocol="val.bridge/0.2")` uses the same sequential
bounded newline-delimited JSON transport (8192 bytes/line, single active
loopback peer) but validates `epoch`, `revision`, `event_seq` and `tick`
on each reply. The Godot parser treats integer JSON numbers as floating values;
both sides normalize only finite nonnegative **exact integers**.

### Hello

```json
{"protocol":"val.bridge/0.2","id":1,"role":"agent","op":"hello"}
```

Reply `data` announces `world_version`, `observation_schema`,
`action_schema`, `source_ref`, per-role capability list, and maximum
ledger entries. Agent capabilities are only `observe` and `act`; operator
capabilities include debug inspector, paginated event history and fixture
controls.

### Observation

```json
{"protocol":"val.bridge/0.2","id":2,"role":"agent","op":"observe"}
```

The response contains `data.schema="val.observation/0.1"`, distinct
`source_ref`, `producer_ref`, `observer_ref`, sample ID, `observed_at`,
`world_revision`, `event_cursor`, visibility radius and `readings[]`:

```json
{
  "subject_ref":"lab.door.01",
  "predicate_ref":"state",
  "typed_value":{"type":"symbol","value":"closed"},
  "position":{"x":6,"y":3}
}
```

A location is returned as `{"type":"grid_cell","x":N,"y":N}`.
**This is a Lab-only versioned value type**, not an authorized Stage7
`Value`. The source sees only Manhattan-radius 3 cells from ANIMA; an
unobserved object is omitted from `readings`, **not asserted false/absent**.
The operator's full World snapshot is exclusively via `inspect`, never
returned in the agent observation.

### Conditional action

```json
{
  "protocol":"val.bridge/0.2",
  "id":3,
  "role":"agent",
  "op":"act",
  "operation_id":"p5b:step:001",
  "action":{"schema":"val.action/0.1","direction":"W"},
  "expected_epoch":1,
  "expected_revision":0
}
```

The command requires an exact world incarnation and revision. If the operator
changed the world since the agent's last observation, it returns
`STALE_WORLD` without moving. Unknown fields, missing/wrong contracts,
invalid action ID, unauthorized operation or invalid direction fail closed.
The *first* admitted action returns `val.receipt/0.1` with `operation_id`,
`status=APPLIED/BLOCKED`, `effect_applied`, reason, position, `event_id`,
world epoch/revision/tick and `replayed=false`.

**Receipt ≠ Verification.** No `Goal.completed`, `Belief` mutation or
`Knowledge` is inferred from `APPLIED`. The future Core must observe the
world again via an independently registered source before accepting success.

### Operator diagnostics

The operator may use `inspect` for world truth plus last agent sample, and
`events(after_seq=N, limit=1..8)` for monotonic, paginated events. A stale
cursor fails closed; a page includes `next_cursor` and `has_more`.
Event `actor` is assigned by Godot handler, not trusted from a caller-provided
attribute. The GUI right-hand developer panel separately renders World truth,
last agent sample and recent event IDs. **This is debugger-only privileged
information and must not be forwarded to Core.**

The same operator fixture controls (`human_move`, `set_door`, `pause`,
`resume`, `step`, `reset`) reuse the proven P5-A world logic.

## 4. Explicit tests and expected gates

| Gate | Concrete check | Criterion |
|---|---|---|
| V1 | P5-A real Godot headless + live GUI unchanged | Backwards compatibility, no concurrent Core required |
| V2 | Godot native `BridgeV2ContractTest.gd` | Version handshake, sample, unauthorized debug, keyed replay, conflict, stale revision, epoch reset, event pagination |
| V3 | Python `test_val_p5b_contracts.py` | Typed source/clock/radius/value validation, receipt/result mismatch, event integrity, numeric v0.2 envelope |
| V4 | Godot↔Python `p5b_smoke.py` | 10+ adversarial checks in a real Godot process; reproducible report |
| V5 | Operator changes world after observed revision | Stale agent action denied; re-observation reflects new external door state |
| V6 | Re-deliver successful and blocked keyed actions | No second world effect or event; conflict detection if payload differs |
| V7 | Reset, epoch and truncated event sequence | No old-epoch action accepted, IDs not reused, bounded diagnostics |
| V8 | `scripts/check.sh` and full Python regression | Existing Core unaffected; clean checked SHA provided |

**Owner-reported on the P5-B working tree:** V4 PASS (10/10 check groups, 29 requests); smoke directly exercises V5 and V6 and the reset/epoch and paged-event portions of V7. Earlier P5-A GUI success and P5-B 24/24 typed controller moves were also reported. **V1 headless P5-A rerun is now owner-reported PASS** (9/9, 22 commands, seed 7); prior GUI success was reported separately. **Still not supported by provided output:** V2 native Godot-only contract test; V3 Python unit contracts; V7 truncation/expired cursor stress specifically; V8 full regression; exact tested SHA/clean checkout. This is not independent verification and does not imply P6 readiness.

## 4.1 First owner-side v0.2 controller result (2026-11-05)

The owner reported successful connection to the live Godot instance using
`controller.py --typed --auto --steps 24`. Console showed
`Virtual Lab: p5a-grid/0.1 / val.bridge/0.2`, followed by **24/24** accepted
moves (`E→N→S→W` repeated six times), each with `reason=ok`; the test
actor returned to `(9, 5)` after each loop. This supports **basic v0.2
transport, typed observation validation and conditional action submission**
for this deterministic route. The earlier `ConnectionRefusedError` occurred
when no Godot server was accepting the connection, and did not recur in the
successful run.

**Not established by this result:** duplicate-effect suppression, stale-world
failure, reset/epoch behavior, event paging, operator interventions during the
v0.2 run, GUI diagnostic display, standalone native Godot contract test,
full `p5b_smoke.py` run, complete `pytest` regression, or exact tested SHA.
Those gates remain open. No Core integration was present.

## 4.2 Owner-local real headless acceptance (2026-11-05)

The owner supplied the exact terminal summary and Markdown result of
`python/p5b_smoke.py` against the real `val.bridge/0.2`:

- **PASS**, 10/10 check groups, **29 requests**;
- `versioned_observation_provenance`;
- `operator_debug_separation`;
- `keyed_replay_without_duplicate_effect`;
- `collision_and_stale_preconditions`;
- `blocked_action_receipt_not_success`;
- `external_intervention_invalidates_revision`;
- `readback_is_not_execution_receipt`;
- `monotonic_paginated_event_log`;
- `epoch_prevents_old_world_actions`;
- `p5a_compatibility_profile_retained`.

These observed assertions support the **in-process** contract and successful
legacy protocol handshake within the new test. They do **not** prove
durability over Godot process termination, authentication of self-declared
roles, provenance authority within Core, independent goal verification,
bounded-log expiration, or the full set of separately defined V1/V2/V3/V8
gates. The owner has not supplied the run's `git rev-parse HEAD`,
`git status --short`, complete `trace.jsonl`/`godot.log` or native
Godot test output. Do not misstate this as a final release gate.

## 4.3 Legacy P5-A headless regression on the P5-B branch (2026-11-05)

The owner reported a fresh `smoke.py` run with `val.p5a.acceptance/0.1`,
seed `7`, world `p5a-grid/0.1`, **22 commands** and **9/9 PASS**:
independent Human/ANIMA positions; bounded observations; rejection of
agent-side operator commands; pause/step; collision and closed door; external
door opening; read-after-change observation; seeded reset; and both actors'
event history.

**Interpretation:** P5-B retained P5-A's *tested headless behavior*. This
does not independently prove the original GUI keyboard route on this exact
P5-B commit, nor native v0.2 contract tests, full Python regression or clean
checkout. The owner states the result was recorded; no `trace.jsonl`,
`godot.log` or exact tested Git SHA was supplied here.

## 5. Local verification (from repo root)

```bash
git status --short
git fetch origin
git switch --track -c work/val-p5b-world-contracts origin/work/val-p5b-world-contracts
bash scripts/check.sh
.venv/bin/python -m pytest -q \
  tests/test_val_p5a_client.py tests/test_val_p5b_contracts.py

GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot \
  --script res://BridgeV2ContractTest.gd

report_dir="$(mktemp -d)"
.venv/bin/python labs/virtual_anima_lab/python/p5b_smoke.py \
  --godot "$GODOT_BIN" --seed 7 --report-dir "$report_dir"
sed -n '1,80p' "$report_dir/summary.md"
git rev-parse HEAD
git status --short
```

After V2–V4 pass, run P5-A `smoke.py` with the same Godot executable,
and visually inspect that both actors still move independently and the debug
panel is for the **operator** only. Run complete `pytest -q` before accepting
V8. Retain representative report metadata with exact test SHA; transient full
logs need not be committed.

## 6. Not part of P5-B

- Real network authentication, attestation or source authorization.
- Durable command idempotency across Godot power loss / process crash.
- Core's Goal/Task/Policy/Belief/Verification integration, including action
  ownership and belief evidence registration.
- General navigation, pathfinding, audio/video vision, LLM and learning.
- Global deterministic replay of live interleaved GUI/OS inputs.
- Full Stage7 `Knowledge`/Claim/Evidence semantics.

**P6 gate:** first finish Core independent re-audit and concept extendability
assessment. Then design a trusted adapter that binds the originating process,
source and operation policy. Do **not** plug `LabClient` or a self-declared
`role="agent"` directly into the Core Executor and call it secure.
