# ANIMA v0.1 Integrated — M2 live Godot VAL + Memory provenance + Core recovery

**Status:** PREDECLARED before implementation.  
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
