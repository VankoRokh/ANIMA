# Virtual ANIMA Lab — P5-C Scenario Profiles & Replay

**Status: P5-C owner-accepted / Complete for its isolated feasibility scope.** Four scripted scenarios replayed identically in two fresh Godot runs, full regression **1450/1450 PASS** on clean code commit `e995169e61385a3e1c2e44a60b27e6bf501211e2`; owner subsequently reported native Godot, P5-A/P5-B backward smoke and visual `base`/`detour`/`clutter` checks all successful. This is owner attestation, **not an independent audit**. Core/P6 remain outside scope.  
**Date:** 2026-11-05.  
**Branch:** `work/val-p5c-scenarios-replay`, based on P5-B `a512faceb4e2e12376424ad20662758f6fd82651`.  
**Scope:** only standalone Godot Lab, Python test harness, tests and documentation. No `anima/` code, no external policies or Core authority; `docs/project.json` is unchanged.  
**Previous evidence:** P5-A headless 9/9 and GUI, P5-B typed controller 24/24 and headless 10/10, P5-A headless compatibility 9/9 (all owner-reported). P5-B native Godot-only and complete pytest regression remain unconfirmed.

## 1. Objective

Prove that a **single independent virtual world** supports several spatial
variants, external changes and low-value events, and can replay a bounded
ordered command sequence with identical results on fresh Godot instances.

This is test-environment engineering, **not ANIMA cognition**. A fixed Python
runner knows the scenario; a future ANIMA Core will not receive its ground
truth, scenario schedule or operator diagnostics.

## 2. World profile and event model

The base P5-A/P5-B scene is preserved by default. P5-C adds
`--lab-scenario base|detour|clutter`:

| Profile | World variation |
|---|---|
| `base` | Original 12×8 grid, Human/ANIMA starting cells, walls/door and seed marker unchanged. |
| `detour` | One additional static wall at (7,4); path choice differs from base. |
| `clutter` | Additional static walls at (5,5) and (8,3). |

On the existing local v0.2 operator channel:
- `set_obstacle` with `at:{x:int,y:int}` and `blocked:bool` inserts/removes
  an additional cell obstacle; maximum 8. Rejects invalid coordinates,
  permanent walls, door cell, currently occupied cells and marker cell.
  A real change increments world revision; an accepted no-op does not.
- `emit_noise` with a bounded ASCII `label` appends an operator-authored
  `ambient/noise` event with monotonic event ID. It increments logical
  `tick` and event sequence but **not world revision**.
- A dynamic obstacle appears in **agent proximity readings only if visible**
  within Manhattan radius 3, as `lab.obstacle.X.Y` with typed grid-cell
  position. An out-of-range obstacle does not leak through agent observation.
- Ambient noise is **not turned into agent sensor evidence**. It exists in
  operator audit history to test mixed-event workloads; ANIMA cannot yet
  decide whether noise is important because the Core is not connected.
- `operator.inspect` and the GUI diagnostics show full world truth,
  scenario name and active obstacles. `agent.inspect` remains forbidden.

World `revision` is a **state version**, not the count of events:
noise and blocked actions may advance tick/event sequence without advancing
revision. The operator's ambient event does not create a false stale-action
failure if no world state has changed.

## 3. Declarative suite

The checked-in fixture at
`labs/virtual_anima_lab/scenarios/p5c_suite.json` uses
`val.scenario_suite/0.1`. It declares four bounded scripts (<=64 steps each):

| Scenario | World | Key assertions |
|---|---|---|
| `noise_and_obstacle` | base | Ambient noise leaves revision unchanged; injected obstacle becomes visible and blocks, old action is stale, removing it permits movement. |
| `door_intervention` | base | Agent sees closed door; operator opens it; earlier precondition rejects; new sample allows crossing; occupied door cannot close. |
| `detour_injection` | detour | Alternate wall is visible; inserted block requires new observation; independent Human movement invalidates stale action. |
| `clutter_reset` | clutter | Different walls, mixed low-value events, blocked action, reset/epoch and new observation. |

Every script consists of explicit role/op/argument/expectation records. The
Python validator rejects unknown operations, roles, out-of-range coordinates,
unbounded steps, invalid noise labels, extra keys and agent-authority
escalation. Agent `act` requests obtain conditional `epoch/revision` from
the **last actual agent observation**, never from privileged operator state.
Operator commands are scripted by the harness, not proposed by an LLM.

## 4. Replay guarantee: intentionally narrow

The `python/scenario_runner.py` executes **each fixture twice**, each time:
1. starts a fresh, headless Godot process with the same `world` profile and
   `seed`;
2. opens `val.bridge/0.2`, executes the declared commands in the same order,
   checks each expected status, error, visibility/state, revision and event
   sequence delta;
3. records each JSON request, full reply and final *operator-only* snapshot;
4. compares the exact canonical JSON trace bytes between both fresh runs and
   reports a SHA-256 digest.

It produces `summary.json`, `summary.md`, `trace.jsonl` and
`logs/<scenario>-<run>.log` in a new/empty report directory. The saved
`trace.jsonl` is an **operator/test-only record containing debug world
truth**; never use it as an ANIMA observation feed.

**Explicit non-guarantees:** no crash-durable world events, no exactly-once
external effect, no stable process IDs across restarts, no OS/GUI keyboard
interleaving replay, no determinism for uncontrolled concurrent clients, no
authentication, no Core Belief/Goal/Verification, no sensor-noise inference.
Matching command traces does not validate cognitive decisions; it validates
a deterministic isolated test fixture under fixed preconditions.

## 5. Acceptance matrix

| Gate | Pass criterion |
|---|---|
| C1 | Native Godot `BridgeP5CScenarioTest.gd` PASS: operator-only fixture permissions, obstacle sensing/collision, noise no revision, variants/reset. |
| C2 | Offline unit `tests/test_val_p5c_scenarios.py` PASS, including malformed fixtures and attempted role escalation. |
| C3 | Four manifest scenarios each PASS twice from fresh Godot; byte-for-byte equal canonical traces, digests and reports. |
| C4 | Mid-scenario Human/door/obstacle changes invalidate stale actions; noise by itself does not invalidate state revision. |
| C5 | Base P5-A 9/9 and P5-B 10/10 headless rerun pass after P5-C edits. |
| C6 | GUI base mode and optional detour/clutter modes render; Human/ANIMA remain independently controlled. |
| C7 | `scripts/check.sh`, full `pytest -q`, clean worktree and precise tested SHA recorded. |

**C1–C7: owner-reported PASS.** C2–C4/C7 include concrete console summaries (4/4 × two runs, 1450 Python tests, clean SHA); C1/C5 were subsequently affirmed collectively by the owner after running the requested native Godot and P5-A/P5-B commands, but their individual console outputs were not posted. C6 (`base`, `detour`, `clutter` GUI controls and obstacles) was explicitly affirmed by the owner. The exact tested code SHA pertains to the supplied runner/regression output; later commits only update documentation. No independent audit of Godot logs or full traces was performed; full Engine/OS timing, network auth, Core verification and restart durability remain out of scope.

## 5.1 Owner-local acceptance evidence (2026-11-05)

**Tested code commit:** `e995169e61385a3e1c2e44a60b27e6bf501211e2`  
**Worktree:** `clean=True` reported by runner  
**Runner:** `val.p5c.acceptance/0.1`; four scenarios, each run twice in a new real Godot process; canonical JSON traces compared for byte-for-byte equality.

| Scenario | Steps per run | Seed | World | SHA-256 prefix (from console) |
|---|---:|---:|---|---|
| `noise_and_obstacle` | 14 | 7 | `base` | `296e6ff9e504306b` |
| `door_intervention` | 18 | 7 | `base` | `f4639d8ce76a73c9` |
| `detour_injection` | 15 | 9 | `detour` | `f5bb251eb6b0d759` |
| `clutter_reset` | 15 | 11 | `clutter` | `ac788b96615a379e` |

**Result:** `PASS 4/4 scenarios, 2 runs each` — 8 fresh Godot processes,
62 declared steps per suite or **124 scripted steps across the two runs**.
Only the 16-character digest prefixes were provided in chat; full SHA-256
digests are available in the local report, **not** independently inspected.

**Project-level check:** `bash scripts/check.sh` reported 100 documentation
pages, 579 internal links, syntax validation of 316 Python source files,
CLI extraction and tracked-file hygiene PASS on Python 3.14.4.
`.venv/bin/python -m pytest -q` reported **1450 passed in 39.29s** with
zero failures. No new code modifications were made as part of the test.

**Subsequent owner confirmations:** native Godot P5-C/P5-B contract checks and P5-A/P5-B real-engine smoke reruns were collectively reported successful after execution; `base`, `detour` and `clutter` were then visually checked and reported functional. Individual native/legacy test transcripts and the full local `trace.jsonl`/Godot logs were not supplied. The exact pinned SHA above describes the submitted runner/regression evidence; later documentation-only commits do **not** modify the tested source. This is acceptance of the isolated P5-C feasibility gate, not a security or Core audit.

## 5.2 Final visual acceptance (owner report, 2026-11-05)

The owner opened the Lab project in Godot and verified the remaining GUI
checks for `base`, `detour` and `clutter`, including actor controls and
obstacle behavior, reporting: **«Проверил, всё работает.»** They also
confirmed that all previously requested native Godot and legacy smoke checks
passed. No video/GUI trace or full native test transcripts were supplied.
This closes P5-C **for the agreed stand-alone Lab acceptance matrix**;
`docs/project.json` is intentionally not changed and ANIMA Core is not connected.

## 6. Local commands

From the ANIMA root, with Godot 4.7.2:

```bash
git status --short
git fetch origin
git switch --track -c work/val-p5c-scenarios-replay origin/work/val-p5c-scenarios-replay
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"

.venv/bin/python -m pytest -q tests/test_val_p5c_scenarios.py

"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot \
  --script res://BridgeP5CScenarioTest.gd

report_dir="$(mktemp -d)"
.venv/bin/python labs/virtual_anima_lab/python/scenario_runner.py \
  --godot "$GODOT_BIN" --report-dir "$report_dir"
cat "$report_dir/summary.md"
```

For a single targeted scenario use `--scenario noise_and_obstacle`.
To visually inspect another geometry while leaving P5-A default untouched:

```bash
"$GODOT_BIN" --path labs/virtual_anima_lab/godot -- \
  --lab-port 46019 --lab-seed 7 --lab-scenario detour
```

In a second terminal:

```bash
.venv/bin/python labs/virtual_anima_lab/python/controller.py \
  --port 46019 --typed --auto --steps 24
```

Then run and record P5-A and P5-B smoke again, native P5-B bridge test,
`bash scripts/check.sh`, full `pytest -q`, exact
`git rev-parse HEAD` and `git status --short`.

## 7. Path to P6 (not yet started)

Independent Core audit/re-audit must be resolved before production coupling.
A later trusted bridge must bind observations to real producer authority,
observation vs receipt times and source identity, issue system-owned actions
under policy, reconcile uncertain effects, and verify actual outcomes using
independent observation. P5-C is designed to exercise such an adapter, not
to substitute for it.
