# ANIMA Memory v1 Integrated — M6-B2.3 real Godot CI evidence

## Source and scope

- Date: 2026-11-14
- Branch: `work/anima-v01-integrated-m6b2`
- PR: `#4`, draft — not merged
- GitHub Actions run: `43598681388`
- Run head commit: `5f4c585b86da621d0ad6d284e0f4e6157d9bc8b9`
- GitHub Actions PR merge checkout recorded by runner: `72839a26f05167e75c995c3b0ac56d8aa35b17cc`; this ephemeral CI ref is **not** the branch commit.
- Live job: `Real Godot 4.7.2 / Python 3.14 (headless)`
- Runner output schema: `anima.memory_v1.godot_execution_m6b2/0.1`
- Runner final status: `M6B2_GODOT_LIVE_GATE_PASS`
- Architecture: Linux x86_64 (GitHub-hosted runner), Python 3.14.10, Godot 4.7.2, official release ZIP checked against `SHA512-SUMS.txt`; headless Godot project import succeeded.
- Durable source of evidence: [GitHub Actions run](https://github.com/VankoRokh/ANIMA/actions/runs/43598681388), [uploaded JSON result](https://github.com/VankoRokh/ANIMA/actions/runs/43598681388/artifacts/14115526006). Artifact ID `14115526006`, ZIP SHA256 `883bff267fd57920200534b82c84f05e6bdb62c2907eb8ed345c0416d0ffbe14`.
- Execution: `python -m labs.virtual_anima_lab.python.m6b2_live_gate --godot <verified Godot 4.7.2 binary> --report <new file outside repo>`
- Each test case starts a new Godot world and isolated M4/M5/M6-B1/M6-B2 SQLite roots. Seed, execution and recovery run as separate Python processes while the same Godot process remains alive across a Core restart; the world-restart denial case intentionally replaces Godot.

## Observed cases

| Case | Observed disposition | Number of Godot close-door effects |
| --- | --- | ---: |
| `normal` | `M6B2_CASE_PASS`, independent target P2 proof, canonical Goal completed, repeat recovery did not duplicate operation | 1 |
| `unapproved` | Denied before executor | 0 |
| `rejected` | Denied before executor | 0 |
| `source_modified` | Denied after original M4 Memory evidence changed | 0 |
| `target_binding_modified` | Denied after target-only P3-A binding changed | 0 |
| `sample_corrupt` | Denied after persisted P6 sample provenance was altered | 0 |
| `world_restarted` | Denied after live Godot instance replacement | 0 |
| `before_effect` | Core `os._exit(74)`, operation `executing` before restart; after restart `uncertain`, Goal `active`, no proof, no replay effect | 0 |
| `after_effect` | Godot completed one close, Core `os._exit(73)` before receipt; after cold restart operation `succeeded`, Goal `completed`, independent target proof present, no second effect | 1 |

**Measured result:** 9/9 case statuses `M6B2_CASE_PASS`; `world_effect_total=2`. The recorded report includes one existing canonical Goal per case, separate target ledgers and explicit `operator_authenticated=false`, `production_firewall=false`, `true_sigkill_tested=false`, `power_loss_tested=false`, `pi_tested=false`, `llm_used=false`.

## What this proves

A full laboratory path from historical M4/M5 origin + M6-B1 source review through separate Godot target P2/P3-A and one-shot M6-B2 guarded action, read-only operation reconciliation and independent target P2 verification can succeed in a **real** Godot 4.7.2 process. Replaying a previous operation does not generate another external effect in these cases. The pre-effect fail-closed guard rejects tampered provenance and changed world identity in the tested conditions.

## What remains unproven

- Owner's Ubuntu laptop / Python 3.14.4 acceptance of this exact branch, or operation on Raspberry Pi 5/ARM64.
- True OS `SIGKILL` at an arbitrary point, power loss, disk-corruption resilience, and atomicity across several SQLite databases and Godot.
- Real authenticated operator or secure privilege isolation from code already able to open local DB files and call `build_core`.
- Autonomous planning by P3-C, real local LLM behavior, distributed/world process isolation or physical world effects.
- Memory v1 full production integration or official Stage completion.

**Acceptance boundary:** this report records a specific CI live Godot success, **not** whole-project final acceptance. Owner laptop verification comes next; Raspberry Pi smoke only after that.
