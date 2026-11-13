# ANIMA — E4 Memory v1.0 Crash/Scale Exit Gate (isolated)

**Status:** MEASURED ISOLATED SIGKILL + SYNTHETIC SCALE PASS / PC+PI MEMORY GATE STILL OPEN / NOT PRODUCTION ADMISSION.
**Baseline:** `31cd283c3af7517aa36381f89d2cef2a2ab98150` (`experiment/core-memory-information-baseline`).
**Purpose:** close only the remaining isolated source-authority journal safety unknowns; **do not** widen the memory-graph design. Then return to the pre-existing [Memory Architecture v1 Roadmap](../ROADMAP/Memory_Architecture_v1_Roadmap.md) and the Integrated ANIMA v0.1 milestone.

## Why this gate is on the critical path

A correctly authorized correction must survive real process failure and must not make a Pi-sized graph unusable. T9.5/T9.6 already measured actual SIGKILL for Core **on PC and Pi**, but do not cover `AuthorizedAliasLifecycleLab`. We must not substitute Core evidence for experimental Memory evidence.

## A: real SIGKILL (not a Python exception)

- Use a separate OS child process and `os.kill(os.getpid(), signal.SIGKILL)`; parent verifies child ended with signal 9, then a **fresh Python process** opens the same SQLite file.
- **Before COMMIT:** inject a kill *after* the authorized alias revocation + derived invalidations + operation receipt have all been written within one uncommitted transaction. On reopening: alias still active, all dependent/unrelated nodes current, zero invalidations, zero allowed-revocation receipts, no operation receipt.
- **After COMMIT:** kill after `revoke()` has returned. Reopening: alias revoked, exactly expected descendants stale, allowed decision and operation receipt each present once; idempotent replay creates no new effect.
- Reproduce with a stable synthetic source set and an unrelated conflicting alias. Tests must reject missing kill marker, a normal child exit, a partial state, a duplicate or absent receipt.
- Entire experiment uses a separate ephemeral `*.db` per scenario; no Core/Memory production files.
- **Not tested:** real power loss, SSD write-cache loss, host kernel crash, multi-database atomicity, concurrent authenticated adapters. No inference of those properties.

## B: bounded scale in one synthetic SQLite lab

- Fixed synthetic graph workloads at **100 / 1000 / 10000 nodes**, including a small alias-A affected subgraph and unrelated alias-B/current subgraph. Keep affected count **<=128** so we can measure a *successful* selective revoke; high-fanout overflow remains a separate known blocker.
- Use one transaction for **direct synthetic database seeding**, not per-node production write API. Explicitly distinguish seed cost from revoke cost. Check exact affected IDs and untouched nodes by independent logical oracle, and preserve old revisions and raw evidence.
- Report wall-clock elapsed, seed duration, peak RSS via OS process metric (process-level high-water mark, not operation-only), and DB/WAL size; identify Python/CPU/OS. This is an **exploratory baseline** rather than a universal latency guarantee.
- Compare `affected/count` with coarse stream-wide invalidation *mathematically*, never call it a measured coarse SQL competitor.
- Reproduce on **the same code/workload on PC and Pi 5**, record hardware and Python versions. A PC CI smoke is necessary but **not sufficient** for a cross-platform gate.
- The existing >128 case remains NO-GO for unbounded correction; do **not** raise the cap without policy. A durable pending-block/reader-deny design is a **future minimal solution**, not scope of this smoke.

## Integration route: minimum ANIMA v0.1 Integrated

Follow the unchanged official `docs/project.json` progression; no new Stage. Stage 6/Core already works on PC/Pi in hardware tests; Stage 7 is Planned and Stage 8 is only a separate virtual lab. For the first integrated cross-device ANIMA:

1. **Memory v1.0 first**: land minimum functional Event Retrieval / source-backed episode grouping / read-only semantic provenance / bounded context **only after A–E/G integration acceptance**; no autonomous Knowledge approval.
2. **One end-to-end path**: trusted Event → immutable store → Memory/Index → Retrieval/Context → Core decision; recover/replay; one representative virtual environment read-only observation/action interface when authorized by Core.
3. **Run the same reproducible workload on notebook and Raspberry Pi** with Python/hardware/storage reported; test restart, raw history, conflicting reports, no unauthorized effects, CPU/RSS/disk/latency. The user-visible proof is an instance that keeps working, not just a green research lab.
4. **Defer** L2 autonomous investigations, exotic graph engines, embeddings/rerank, Meta-memory, training/LoRA, physical sensors, complex SLEEP semantics (Memory v1.1), cluster/peripheral hardware until integrated v0.1 passes.

**Stop rule:** one successful isolated experiment does not add a new side mechanism. If the measured Memory gate passes, hand off to integration acceptance; if it fails, fix only the failing invariant. Do not modify production routing or Stage statuses before end-to-end acceptance.

## Measured outcome — 2026-11-13

**Implementation snapshot:** `901a49b8346a672b2cb44057f96878d8fcaef420`. **CI:** [#43415469572](https://github.com/VankoRokh/ANIMA/actions/runs/43415469572), completed **SUCCESS** in Python 3.12 / 3.13 / 3.14 matrix; **98 targeted PASS** and **1653 full regression PASS** on each.

**Real SIGKILL gate:** `tests/test_memory_e4_process_kill.py` runs separate child processes killed with Linux `SIGKILL` (exit code `-9`), followed by independent fresh interpreter reopen/replay. The before-COMMIT cut occurs after the alias/graph/authorization receipts have been staged but before the SQLite transaction commits, proving rollback within **one isolated DB**. The after-COMMIT cut preserves an authorized decision, exactly two invalidations and idempotent replay. No post-crash partial heads, duplicate effects or loss of original version were observed in these cases. These tests are **not** real power-loss or multi-store recovery.

**Synthetic selective invalidation scale (GitHub-hosted Linux x86-64, Python 3.14, 3 independent lab databases per size):**

| Nodes total | Expected/actual stale nodes | Coarse theoretical touches | Median revoke wall time | Observed process high-water RSS |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 8 | 100 | 2.184 ms | up to 24,788 KiB |
| 1,000 | 50 | 1,000 | 3.724 ms | up to 25,480 KiB |
| 10,000 | 64 | 10,000 | 4.531 ms | up to 30,308 KiB |

`LAB_BENCHMARK_ONLY`: these are **not** production Memory throughput, p95 estimates, or time for invalidating 10,000 descendants. The largest graph has 64 *affected* nodes and 9,936 *unaffected* nodes; the fixed policy budget remains 128. Graph construction used a single synthetic SQL transaction rather than the public node-creation API. The coarse-wide count is mathematical, not separately timed SQL. `ru_maxrss` reflects the process high-water mark, not incremental RSS of a single revoke. Three samples are insufficient for reliable tail percentiles. Raw CI artifact: `e4-selective-invalidation-scale-py314` (14-day retention).

**Reproduce on Linux laptop and Pi 5 (use the same branch and fixture):**

```bash
python -m pytest -q tests/test_memory_e4_process_kill.py tests/test_memory_e4_scale_probe.py
python -m labs.exp009.e4_scale_probe --sizes 100 1000 10000 --repeat 3 --output /tmp/anima-e4-scale-PROFILE.json
```

Use distinct profile output filenames per device; the runner refuses to overwrite an existing report. Record Python version, CPU/architecture, storage medium and thermal conditions. The GitHub-hosted benchmark is **not** a Raspberry Pi measurement. The earlier Core PC/Pi T9.5/T9.6 SIGKILL evidence cannot substitute for E4 Memory parity.

**Decision:** complete the **isolated safety research** for this bounded profile, while keeping **production E4 revocation and action-enabled L2 NO-GO**. High-fanout >128 alias revocation still rolls back atomically and represents a correction-availability blocker if that feature is later enabled. Do **not** add pending-invalidation machinery now merely to unblock the *first read-only integrated ANIMA*. Next work item: implement/validate the already approved Memory v1.0 Event→Memory→Retrieval→Context→Core A–E/G integration path, then compare the same instance on PC/Pi. No additional E4 graph features are authorized by this result.
