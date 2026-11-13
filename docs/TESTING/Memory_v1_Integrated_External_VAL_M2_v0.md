# ANIMA v0.1 Integrated — M2 live Godot VAL + Memory provenance + Core recovery

**Status:** CI VERIFIED — real Godot 4.7.2 (hosted Linux x86_64), full Python 3.12–3.14 regression PASS. Owner's physical laptop M2 gate remains OPEN.  
**Base commit:** `2b4463596c7422a8243fce6e71258896188e5363` (M1 laptop PASS).  
**Execution target:** only laptop Linux x86-64 / installed Godot 4.7.2; GitHub-hosted Linux x86-64 CI also allowed. Raspberry Pi deferred by owner.

## Problem

M0 proved the persisted Core→Memory→Retrieval→bounded FAST read path. M1 proved that untrusted historical Memory cannot override registered sensor Belief, but its world was a local SQLite headless fixture. P6 separately proved Core↔external Godot door adapter and independent readback, including deliberately aborted Core processes. **No previous gate establishes that the same Core process can sustain all three subsystem boundaries together with historical memory preserved across a Core hard exit.**

## Frozen M2 integrated contract

- Spawn **real Godot 4.7.2** `p6_door` scenario as a child process on dynamically allocated `127.0.0.1` port, seed 7. Never connect a production data directory or open network interfaces.
- Compose the **existing** `labs/virtual_anima_lab/python/run_core_demo.make_core` with opt-in Event Retrieval. No `anima/` modifications. Memory and P6 WorldPort remain distinct modules.
- In a fresh isolated Core data directory: `runtime.wake()`; receive an **unverified and false historical user report** saying the virtual door is closed; index and retrieve that immutable raw user Event; build the bounded historical Memory context before storing the current question; use test-only FAST stub. Verify current question ID absent from prior snapshot; FAST and historical user reports do not bind goals or authorize tools.
- Test operator explicitly creates and binds the existing `world.property_equals(closed)` Goal; automatic, **bounded Core P3-C** uses the registered Godot `VALDoorPort` sensor, not historical Memory, to decide and execute. Count actual Godot `close_door` event via external test harness; verify independent registered Core sensor proof and its mirrored raw Event index entry.
- Reassemble Core in a **second Python interpreter** against same persisted Core/VAL adapter data while **same Godot instance stays alive**. Check source-backed history, event index `complete`, Goal/Task/operation ledger, no new effect, no auto-created Knowledge.
- Two additional cases inject a hard `os._exit` in Core's pre-receipt worker at an already-persisted `executing` operation: **before** Godot action and **after** exactly one Godot action. After restart, before-cut must remain `active/uncertain` with **zero** effects and **no fabricated success**. After-cut must reconcile one effect, show `completed/succeeded` and registered sensor proof without issuing a duplicate effect.
- Godot's privileged `operator events` endpoint is **test-only external oracle**. It never enters the Core action path; Core P6 port communicates as `agent` and is not authenticated against a malicious local process.

## Acceptance table

| Case | Cut | Real door effects | Goal after cold reload | Proof |
| --- | --- | ---: | --- | --- |
| normal | none | 1 | completed | registered independent sensor |
| before | hard exit before tool executes | 0 | active; operation uncertain | none |
| after | hard exit after tool executes, pre-receipt | 1 | completed; operation succeeded | registered independent sensor |

**Mandatory:** memory context and raw source references survive all three cases, FAST snapshot excludes current query, automatic Knowledge count zero, no repeated effect, world instance ID unchanged, no unregistered tool, no data outside isolated temporary directory.

## Evidence boundaries

This gate runs live **Godot**, not fake P6 nor the M1 SQLite door. Hard `os._exit` is **not true SIGKILL**, power loss, kernel fault, or network authentication. It does **not** prove general memory-informed autonomous planning or autonomous Goal creation. Only a test operator creates a typed Goal; FAST is a deterministic stub, not an LLM. Core continues to make tool decisions from registered current world Belief, *not* arbitrary Memory text.

## Artifacts and review

- Runner: `labs/virtual_anima_lab/python/m2_integrated_gate.py`.
- Existing port and crash gate reused: `labs/virtual_anima_lab/python/core_port.py`, `p6_core_crash_recovery_gate.py`.
- Offline tests: `tests/test_m2_external_val_memory.py` (guard and source-only checks). Online gate: three `--headless` actual Godot instances launched and shut down by runner.
- CI: Python 3.12–3.14 full suite; Godot 4.7.2 pinned official GitHub release with SHA256 verified on one Linux runner, plus M2 gate.
- Manual run on notebook after CI: `python -m labs.virtual_anima_lab.python.m2_integrated_gate --godot "$GODOT_BIN" --report /tmp/anima-m2-PC.json`. Runner must never overwrite an existing report.

**Stop condition:** any false success, effect replay, foreign or lost Event/Memory sources, wrong world instance, unbounded trigger, missing proof, or client invocation requiring operator rights is a failure. Update this document only with observed test evidence, not inferred correctness. Official `docs/project.json` stays unchanged.

## CI acceptance result — 2026-11-13

**Tested implementation commit:** `9f58074444c38895f7f3d571bc5d31fbc98cd267` (last code/test commit, before this docs record).  
**Primary source:** [GitHub Actions run #43423339900](https://github.com/VankoRokh/ANIMA/actions/runs/43423339900): **SUCCESS** — four green jobs.

| Gate | Result | Evidence |
| --- | --- | --- |
| Python 3.12 targeted M0/M1/M2/P6 | **20 PASS** | CI matrix logs |
| Python 3.12 full suite | **1667 PASS** | CI matrix logs |
| Python 3.13 targeted / full | **20 PASS / 1667 PASS** | CI matrix logs |
| Python 3.14 targeted / full | **20 PASS / 1667 PASS** | CI matrix logs |
| Real Godot engine | **4.7.2 PASS** | Official `godotengine/godot-builds` release zip SHA256 `cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4` |
| Native Godot P6 bridge GDScript | **PASS** | `BridgeP6DoorTest.gd` in same job |
| Live M2 all cases | **M2_INTEGRATED_GODOT_PASS** | `anima-m2-live-godot-py314` JSON artifact in same run |

**Case evidence** (actual separate Godot world process per case):
- `normal`: one close_door effect, `completed/succeeded`, independent Core sensor proof in raw source-backed Event index.
- `before`: hard exit after durable `executing` operation, before executing Godot command; **0 effects**, `active/uncertain`, **no proof**, no effect replay on Core recovery.
- `after`: hard exit after **1** Godot close_door effect but before executor receipt; `completed/succeeded` with independent sensor proof, **no repeated effect**.
- Each scenario: historical false user claim indexed, linked to actual Memory, preserved across restart; FAST historical snapshot excludes current question; `index_status=complete`; `knowledge_count=0`; Godot process instance remains unchanged across Core cold restart. All world effects counted externally by the test harness, not by a tool-reported success claim.
- M2's main CLI now *checks the actual executable version* `--headless --version` and refuses binaries other than Godot 4.7.2. CI pinned SHA256 prevents an unverified engine swap.

**Initial regression finding and remediation:** An earlier M2 full-suite attempt had three documentation-test failures because the index Markdown linked to a lab file intentionally omitted from restricted source-tree fixtures. The README now references the lab runner by literal code path; no Core/Memory/VAL logic was changed for this repair. Final run #43423339900 is fully green.

**Meaning of PASS:** real external world, historical retrieval context and Core-owned action/recovery can coexist safely in this *bounded, operator-configured* test. Not evidence of automatic memory-conditioned goal formation or full autonomous cognition. `os._exit` is **not** `SIGKILL`, and this gate does not simulate power failure, corrupted disks, malicious loopback peers, or end-user deployment.

### Laptop reproduction (owner gate OPEN)

From a fresh checkout/worktree of M2 branch and repository root, with an existing local Godot 4.7.2 binary:

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
python -m labs.virtual_anima_lab.python.m2_integrated_gate \
  --godot "$GODOT_BIN" \
  --report /tmp/anima-m2-PC.json
```

Runner starts and stops **three** headless Godot children itself; **do not start a separate Lab** for this gate. Each case uses a random free loopback port and disposable temporary Core/VAL data, not the user's existing ANIMA instance. Report path must be absent and outside repository; choose a new name on retry. Declare owner laptop PASS only after an observed local `M2_INTEGRATED_GODOT_PASS` report.

**Next engineering decision:** identify the smallest read-only cognition→goal proposal contract so actual remembered context can influence *proposals* without granting `Memory` authority to declare sensor truth or invoke tools. This requires its own negative/admission gates; do not silently edit `anima/`, `docs/project.json`, or the existing typed Core binding rules.
