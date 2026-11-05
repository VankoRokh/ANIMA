# Virtual ANIMA Lab — P5-A Independent Godot Feasibility

**Status:** **IMPLEMENTED IN WORK BRANCH / UNVERIFIED IN GODOT**. This is NOT P5 Complete, NOT P6, and does not change the accepted Core v0.1 release status.  
**Date:** 2026-11-05.  
**Branch:** `work/val-p5a-godot-feasibility`, branched from the exact Core audit-fixes owner-tested snapshot `b639a52281eeaece1b5b00d8223d8f31bd492ca1`. Production `anima/`, Core stores, `docs/project.json` and official Stage statuses remain untouched.  
**Plan:** [Core v0.1 / VAL v0.1](Core_v0_1_VAL_v0_1_Plan_Draft.md) §4 P5/P6; independent prototype: [`labs/virtual_anima_lab/README.md`](../../labs/virtual_anima_lab/README.md).

## 1. Engine choice

**Candidate for feasibility:** Godot **4.7.2 Stable**, standard GDScript build, on Linux with Compatibility renderer (OpenGL) and optional `--headless` mode. Source: official Godot download/archive and command-line documentation, verified 2026-11-05. Godot 4.8 was beta at that date. Official downloads: `https://godotengine.org/download/`; stable command-line guide: `https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html`.

Why test it first:
- Mature 2D editor and visual debugging, built-in cross-platform geometry and keyboard input.
- Built-in TCPServer/StreamPeerTCP and JSON simplify initial Python↔Godot experiment without libraries or a third-party networking addon.
- Standard Linux binary supports interactive and headless operation.
- MIT license; no Godot engine internals or custom renderer are maintained by ANIMA.

**Not yet established by testing:** correct Godot runtime import/parser, local Linux visual behavior, headless bridge interoperability or deterministic replay; those are the P5-A owner-run gates below. Alternative MultiGrid remains fallback if Godot fails required P5 acceptance, not an implementation target now.

## 2. Isolated implementation

P5-A adds source under `labs/virtual_anima_lab/` only, plus small non-Godot client tests under `tests/test_val_p5a_client.py`.

| Component | Responsibility |
|---|---|
| `godot/project.godot`, `Main.tscn`, `Main.gd` | Fixed 12×8 world, obstacle/door collision, deterministic seed marker, blue Human (keyboard), green ANIMA (Python). Full state stays in Godot. |
| `python/lab_client.py` | Python-only bounded JSONL transport over loopback with request IDs and explicit errors. Role checks in Godot are testing controls **not security**. |
| `python/controller.py` | Interactive/manual or deterministic auto movement of ANIMA. Godot window remains independently controllable by Human. |
| `python/smoke.py` | Starts real Godot in `--headless` on an ephemeral port, checks event flow/collisions/observations, produces terminal and optional structured report. |
| `tests/test_val_p5a_client.py` | Tests client framing/rejected responses without engine; does **not** prove Godot interoperability. |

**Separation rule:** this implementation does **not** import ANIMA, alter `build_core()` or call Stage6 Executor. A Python *test controller* acts as a stand-in for future model-driven decisions. Avoid claiming ANIMA autonomous behavior from this experiment.

## 3. P5-A bounded world and actions

Logical clock `tick` changes on movement attempts, door actions and operator step. World contains Human, ANIMA, walls, a door and a marker selected by seed. Human keyboard arrows/WASD moves Human only; E toggles a nearby door. ANIMA moves only after a Python `agent.move` request; collision rejects walls, the closed door and a cell occupied by the other actor.

The `agent.observe` response includes only the ANIMA location and visible objects within Manhattan radius 3. The debug operator has a separate `debug_snapshot` command that can see World truth. The agent cannot access `debug_snapshot` under a self-declared agent role.

Test-operator commands `human_move` and `set_door` enable deterministic headless scenarios without pretending this models true keyboard interaction. The GUI Human + Python ANIMA live-control test remains mandatory separately.

Pause blocks Human and ANIMA movement; explicit `step` increments logical time; `reset` restores the seed-based marker and fixed initial actors. The operator history is a bounded last-256-event in-memory buffer; `trace` sends only the last 20 for frame-size bounds. The Python smoke recorder logs commands/responses to a new isolated directory.

## 4. P5-A test matrix

| Gate | Check | Expected |
|---|---|---|
| F1 | Godot standard 4.7.x opens standalone 2D scene | Human and ANIMA are visible; no ANIMA Core dependency |
| F2 | Human keyboard vs autonomous Python-control route | Blue Human and green ANIMA move independently; no keyboard takeover |
| F3 | headless Godot launches with loopback JSON bridge | `val.bridge/0.1` ping succeeds; incompatible version rejected |
| F4 | Agent observation is spatially bounded | No out-of-range Human/world state in agent output |
| F5 | Walls/closed door reject movement, opening door permits motion | Commands return structured reasons; no overlapping occupied door |
| F6 | Operator changes world while ANIMA runs | Subsequent observation reflects new door condition |
| F7 | pause/resume/step | Movement prohibited when paused; step increments logical clock |
| F8 | repeatable seed and reset | Fixed scripted initial layout and marker after reset |
| F9 | headless trace/report | Human readable PASS/FAIL, JSON trace saved with explicit report dir |
| F10 | Python framing unit tests and existing regression | No imported Core coupling; no unexpected Core tests regressed |

**P5-A acceptance is blocked until F1–F10 pass on a real local Godot binary.** Passing `pytest` alone is insufficient.

## 5. Run locally

```bash
git fetch origin
git switch --track -c work/val-p5a-godot-feasibility origin/work/val-p5a-godot-feasibility

bash scripts/check.sh
.venv/bin/python -m pytest -q tests/test_val_p5a_client.py
```

GUI, two terminals:

```bash
godot --path labs/virtual_anima_lab/godot -- --lab-port 46019 --lab-seed 7
```

```bash
.venv/bin/python labs/virtual_anima_lab/python/controller.py --port 46019 --auto --steps 24
```

Headless acceptance and readable report:

```bash
report_dir="$(mktemp -d)"
.venv/bin/python labs/virtual_anima_lab/python/smoke.py \
  --godot "$(command -v godot)" \
  --seed 7 --report-dir "$report_dir"
cat "$report_dir/summary.md"
```

Use explicit `--godot /path/to/binary` when the binary is named differently or is an AppImage. No external networking or npm/pip requirements.

## 6. Known gates before P6

The P5 JSON bridge **does not authenticate** `role`: any local client can claim `operator`. This is acceptable **only** as a same-machine throwaway feasibility test and would be a serious authority flaw if reused as a production ANIMA bridge.

Before connecting Core (P6):
1. Separate trusted operator/test-harness channel from agent observation/action channel; pin source/producer and actor identities at the adapter boundary, not in caller-supplied JSON.
2. Define versioned schemas with occurrence IDs, observed_at vs arrival time, world revision, action idempotency/reconciliation and transport failure behavior.
3. Keep Godot as owner of World truth and ANIMA Core as owner of Belief/Goal/Task/Policy/Action; do not expose `debug_snapshot` to Core.
4. Introduce navigation as a separately registered capability, not as hardwired Godot pathfinding in Core.
5. Test equivalence between P3-B in-process fixture and P6 Lab bridge under matched observations; no automatic promotion of test-world ground truth to evidence.
6. Prove both GUI and headless runs, collision/actor identity and readable incident traces; no dependency on graphics for Core.

**No claim yet that P5 or Core v0.1 has been accepted/released.** Existing independent Core audit re-review remains separate and unfinished.
