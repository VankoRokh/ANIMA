# Virtual ANIMA Lab — isolated P5-A and P5-B feasibility

**Status:** Godot real headless smoke **owner-reported PASS** (9/9 checks, 22 commands, seed 7) and **GUI dual-actor controls owner-reported PASS**. Exact tested Git SHA and independent unit/full regression output are not yet supplied; no ANIMA Core integration.  
**Branch:** `work/val-p5a-godot-feasibility`.  
**Base:** `b639a52281eeaece1b5b00d8223d8f31bd492ca1` (Core audit fixes, independently re-reviewed later).  
**Isolation:** no import of `anima`, no changes to `build_core`, Core stores, `project.json` or execution authority.

## Purpose

Establish whether a **standard Godot engine**, without custom game-engine code,
can act as an isolated 2D **world truth owner**, while a separate Python process
controls only the ANIMA actor and a user controls Human from the keyboard.

P5-A is NOT ANIMA cognition, a Core ↔ Godot integration, navigation AI or a
secure real-world device bridge. Its JSON protocol is a test harness only.

### Requirements

- **Godot 4.7.2 Stable**, standard (non-.NET) desktop binary; Linux recommended.
  The Godot executable is not bundled with ANIMA.
- Python 3.12+ standard library; no pip dependencies for the controller/smoke.
- Two terminals for visual mode. For headless mode a local Godot binary is
  required; running Python unit tests alone does not verify the engine.

Official download: https://godotengine.org/download/  
Godot is MIT-licensed. Project draws built-in geometric shapes; no art assets.

## Interactive run — two independent actors

From repository root, terminal 1:

```bash
godot --path labs/virtual_anima_lab/godot -- \
  --lab-port 46019 --lab-seed 7
```

Use **WASD or arrow keys** in the Godot window to move the **blue Human**.
Press **E** next to the door to change its state. Yellow cell is a seeded
marker. Grey cells are obstacles. Green circle is **ANIMA**.

Terminal 2:

```bash
python labs/virtual_anima_lab/python/controller.py \
  --port 46019 --auto --steps 24
```

The Python controller makes **ANIMA** move along a fixed route while Human
is still independently controlled in the Godot window. Use `controller.py`
without `--auto` for manual `w/a/s/d` movement and `o` observation.

If the binary isn't named `godot`, run the executable by its full path.
The Godot GUI does not launch ANIMA Core or any model.

## Protocol compatibility check (Godot JSON integer IDs)

**Fixed after first real Godot↔Python run:** Godot's `JSON.parse_string()`
represents JSON numeric identifiers as floats (`1.0`), while our initial
bridge mistakenly required `TYPE_INT`. The scene now validates integral
numeric IDs and normalizes them to `int`; Python accepts either `1` or
exact `1.0` on replies while rejecting fractions, booleans, NaN and
out-of-range values.

Close any running Godot window **before** testing the updated bridge, then:

```bash
godot --headless --path labs/virtual_anima_lab/godot \\
  --script res://BridgeProtocolTest.gd

.venv/bin/python -m pytest -q tests/test_val_p5a_client.py
```

Expected Godot output contains `VAL_BRIDGE_ID_CONTRACT_PASS`. The first
command uses the **real Godot parser**, while the Python tests check response
framing independently. Neither alone demonstrates the full bidirectional
world scenario; run the `smoke.py` test as the next gate.

## Headless feasibility gate

From repository root, with a Godot binary installed:

```bash
report_dir="$(mktemp -d)"

python labs/virtual_anima_lab/python/smoke.py \
  --godot "$(command -v godot)" \
  --seed 7 \
  --report-dir "$report_dir"
```

`smoke.py` starts Godot itself with `--headless` on a free loopback port,
performs negative/positive requests and shuts it down.

**Expected report:** terminal summary with `PASS`, plus
`summary.md`, `summary.json`, `trace.jsonl` (sent commands + responses)
and `godot.log` in the explicit report directory. It rejects a nonempty
report directory rather than overwriting prior experiment evidence.

Smoke verifies, against **real Godot**, all of the following:

1. Actor positions independent; an operator Human move does not move ANIMA.
2. ANIMA sees only bounded 3-cell Manhattan-radius observations, not privileged
   Human/world ground truth.
3. Agent requests for `debug_snapshot` are rejected by the P5 protocol role
   guard (this is NOT cryptographic authorization).
4. Pause stops both movements; operator `step` advances logical time.
5. Closed door blocks ANIMA; external operator opens it; new observation
   reports open; ANIMA can then pass. Door cannot close on occupied cell.
6. Both actors' actions appear in the operator event trace.
7. Reset restores initial world positions and deterministic marker for seed.

A real **keyboard Human** interaction is the companion visual gate, not
automatically proved by the operator-only `human_move` smoke surrogate.

## Bridge: `val.bridge/0.1`

Godot listens only on `127.0.0.1:<port>`; accepts newline-delimited JSON
with max **8192 bytes** per line. Simple serial request/response, one client
connection at a time, no subscription/broadcast or exactly-once semantics.

Example agent request:

```json
{"protocol":"val.bridge/0.1","id":1,"role":"agent","op":"observe"}
```

Response envelope (the inner `visible` items depend on position):

```json
{"protocol":"val.bridge/0.1","id":1,"ok":true,"tick":0,"data":{"observer":"anima","self":{"x":9,"y":5},"radius":3,"visible":[]}}
```

Agent operations: `ping`, `observe`, `move(direction=N|S|E|W)`.

Operator operations: `ping`, `debug_snapshot`, `trace`, `human_move`,
`set_door(open=bool)`, `pause`, `resume`, `step`, `reset`, `shutdown`.

**Security boundary:** the `role` field is self-declared. The operator port
is not authenticated, and the test controller can relabel itself. This is
safe only as a **private local feasibility harness**. **DO NOT connect ANIMA
Core**, open to other hosts, or treat role checks as policy enforcement.
Before P6 we must build a trusted adapter with separate operator control and
agent observation/action permissions, identity, provenance, versions and
transport failure recovery.

`debug_snapshot` exposes full world truth to the TEST OPERATOR only.
P5 agent observations contain `self`, bounded visible objects, and a world
tick. They intentionally omit exact positions of non-visible actors and
unobserved door states. No in-process Core source registry receives these yet.

## Determinism and known limitations

- Logical tick advances on movement attempts, door changes and operator step.
  GUI input arrival order relative to TCP commands is not globally deterministic;
  repeatable scripted headless command order + seed is the initial baseline.
- `--lab-seed` only selects one seeded marker; geometry and actors are fixed
  in P5-A. Reset repeats the seeded layout.
- Collision is deterministic grid-cell movement, **not** Godot physics.
- The operator trace is bounded to 256 events in memory. Python smoke records
  its own request/response timeline; this is **not** a durable Core Event journal.
- No request deduplication, actor authentication, full event provenance,
  autonomous planning, perception cameras, navigation/pathfinding or replay
  after a crash. These belong to later P5/P6 work.
- Python client tests can pass with no Godot installed; P5-A only passes when
  the **real headless smoke** and a **visual keyboard check** have both passed.

## P5-B experimental typed world contract

**Status:** implemented, **Godot execution unverified**. P5-A `val.bridge/0.1`
remains supported for the original controllers and smoke tests. The *new*
`val.bridge/0.2` must be selected explicitly through
`LabClient(protocol="val.bridge/0.2")`.

P5-B adds an **epoch** (changes on world reset), conditional **revision**,
monotonic process-local **event IDs**, a paged operator journal, an observation
record with source/producer/observer identity and spatial readings, and
`act` with a bound `operation_id`. Duplicate admitted actions replay the
original receipt without moving the agent again. A stale world precondition
fails closed; an operation ID with different content is rejected.

`val.receipt/0.1` is **not independent verification of any ANIMA Goal**.
The keyed ledger lives in Godot RAM only: do not infer crash-safe exactly-once
or actual caller authentication from these tests.

The Godot window now displays a **developer-only diagnostics panel**:
world truth, last agent observation metadata and recent event IDs. That
panel must not be treated as information available to ANIMA.

See the full [P5-B contract specification](../../docs/ROADMAP/Virtual_ANIMA_Lab_P5B_World_Contracts_Draft.md).

### P5-B verification

From the new P5-B branch:

```bash
bash scripts/check.sh
.venv/bin/python -m pytest -q tests/test_val_p5a_client.py tests/test_val_p5b_contracts.py

GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot \
  --script res://BridgeV2ContractTest.gd

report_dir="$(mktemp -d)"
.venv/bin/python labs/virtual_anima_lab/python/p5b_smoke.py \
  --godot "$GODOT_BIN" --seed 7 --report-dir "$report_dir"
cat "$report_dir/summary.md"
```

### P5-B visual inspection

Launch the same Godot GUI as P5-A and, in a second terminal:

```bash
.venv/bin/python labs/virtual_anima_lab/python/controller.py \
  --port 46019 --typed --auto --steps 24 --interval 0.65
```

The right-hand debug panel shows **World truth** independently from the
last `val.observation/0.1` sample and recent event sequence. Human still
moves on the keyboard. Without `--typed`, the controller uses the original
`val.bridge/0.1` protocol.

**No Core integration.** Run the original P5-A smoke and live GUI after the
new v0.2 tests, so a new protocol cannot silently break our established
visual/world fixtures.

## Tests and next gate

```bash
bash scripts/check.sh
.venv/bin/python -m pytest -q tests/test_val_p5a_client.py
.venv/bin/python -m pytest -q
```

Then run the headless smoke and GUI interactive tests above. Save their
version, seed, commands, exact commit and observations as a representative
result; do not add every transient log to Git.

**P5-A passes only when both headless and GUI tests pass.** Then P5-B can
evaluate versioned observation/capability ports and bridge independence.
`P6` is the first stage allowed to connect Godot with a separately audited
Core adapter; no shortcut around that gate.
