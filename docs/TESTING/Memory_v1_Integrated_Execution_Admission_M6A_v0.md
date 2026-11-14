# ANIMA Memory v1 — M6-A executable startup + pre-effect admission

**Status:** FROZEN DESIGN — awaiting tests, CI and owner laptop gate.  
**Branch:** `work/anima-v01-integrated-m6`, based on owner-accepted M5 `1ec7674773ba2202035ecb9d013773a74dfadef5`.

## Architectural blocker: M5 vs P6/Godot provenance

**Do not silently reuse M5's typed binding with the P6 Godot port.** M5's registered virtual-world source is `sensor.door_01 / adapter.virtual_door_sensor/0.1` with `lab_tick` clock. P6 Godot's `VALDoorPort` uses `adapter.val_door_port/0.1` with `lab_sample` clock. An equivalent subject/predicate and identical `world.door.close` Tool name do **not** establish equal source authority or equivalent timeliness. Replacing registrations behind an existing bound Goal without migration review could manufacture trusted evidence.

M6-A therefore verifies the *entire* M3→M4→M5 chain through an independently approved **single-use execution admission** and an action-capable Core assembled against the **same registered VirtualDoorWorld P2 source and clock**. M6-B real Godot requires its own explicit source/clock remapping and new approval contract; no fake 'real Godot PASS' in M6-A.

## Acceptance boundary (lab-only, not production security)

- M6-A may create an action-capable `CoreAssembly` only through **opt-in lab composition**, with `auto_core=False`. It must not enable P3-C during construction or wake. Direct `build_core` by unrelated code remains a bypass: this is a *lab harness contract*, **not** a global production authorization firewall.
- The startup gate must validate exactly **one** active, source-backed, M4 committed and M5 bound Goal. The Goal, M4/M5 fingerprints, Core P3-A immutable binding, registered PropertyRule, trusted ActionSpec, and P2 sensor source are verified against their frozen contracts. A new sensor observation of `open` is required. Approval for M4 or M5 alone is insufficient.
- A **third explicit host decision**, M6 `APPROVE` or `REJECT` for one exact frozen execution ticket, is persisted in an isolated SQLite ledger. The host input's `operator_ref` is **not authenticated identity**.
- On approved tickets, the **execution adapter's actual SandboxHandler.execute** is wrapped by a second, non-bypassable-*within-this-lab-composition* pre-effect guard. It reopens M4/M5/Core records, verifies the operation's persisted `ExecutionAction` belongs to that exact Goal and Tool/arguments, requires a new registered P2 sensor reading still `open`, and **atomically claims the single approved ticket for one operation ID before calling the door Tool**.
- A claimed ticket **cannot** initiate a second effect, even with the same ID. Reconciliation remains **read-only**, never calls Tool, and Core independent sensor Proof remains the sole basis for Goal success. Crashes between claim/effect may leave an uncertain operation and require conservative deferral rather than automatic re-execution.
- The explicitly checked callable `execute_approved` must deny missing/rejected/changed approvals **before** Core Task/operation creation. A direct unauthorized call to Core (bypassing that method) may still create Task/operation metadata, but the guarded handler must refuse any Tool side effect. State this limit explicitly.
- Never grant approval from Memory/FAST, accept a model-supplied operator/action/priority field, mark Knowledge from a Tool receipt, bypass P3-B checks, or mutate `anima/`.
- `os._exit` cut points *before* physical effect and *after* effect *before receipt* must be tested in separate Core processes, with one external persistent world across Core restarts, and no duplicate effect on recovery. These are not true SIGKILL or power-loss tests.
- Additional negative cases: unapproved, rejected, forged/changed M6 decision, changed Memory source, changed M5 binding, wrong operation ID/tool/goal, stale original sensor event, world closed before admission, new world state after ticket creation, noncanonical M4/M5 source, changed Goal lifecycle, duplicate permit claim. All must fail closed with no unauthorized physical effect.
- M6-A uses **only** a headless SQLite virtual door (not Godot), no real LLM, no Raspberry Pi; M6-B is separately scoped. The consumer-run M6 CLI must never access production user data, and report files must be new and outside the repository.

## Lifecycle and crash ownership

1. Prepare synthetic historical Memory and M3 proposal, commit M4 via separate operator decision, then review and bind M5 via another separate operator decision. Exactly one active bound Goal remains.
2. `M6Admission.stage`: verify complete Memory source index and M4/M5, goal, registry and new CoreIngress sensor evidence. Fingerprint and store immutable ticket bound to Goal and M5 ticket.
3. `M6Admission.decide`: persist distinct third host APPROVE or REJECT.
4. `M6Admission.assemble`: only approved tickets may receive a fresh sensor check and construct an executable Core with `auto_core=False`, `world_port` and **wrapped World handlers**; no P3-C and no automatic run on startup. All details must match the original P2/P3-A registrations.
5. `M6Admission.execute_approved`: revalidate and explicitly call Core's bounded P3-B door Goal. Inside the Tool worker, `M6GuardedDoorHandler.execute` revalidates again, claims permit atomically, then calls canonical `door_handlers`.
6. Cold recovery reassembles **only via M6 guard** and runs bounded Core reconciling to verify independent registered sensor proof. Never repeat an ambiguous effect.

## Planned gates / stop criteria

- `labs/virtual_anima_lab/python/m6_execution_admission.py`: M6 ledger, frozen typed admission, guarded handler, restrictive executor composition.
- `scripts/run_memory_v1_execution_gate.py`: multiple isolated subprocesses for positive/negative/crash/replay; JSON `M6_EXECUTION_ADMISSION_PASS`.
- `tests/test_memory_v1_execution_gate.py`: independent negatives, source and operation ID tampering, lack of executor before M6 approval, full prior M0–M5+P6 tests.
- GitHub CI Python 3.12–3.14 targeted/full regression and `scripts/check.sh`. Owner laptop Python 3.14.4 report after CI.

**Hard FAIL:** any unauthorized Tool effect, duplicate effect, fabricated Proof or Goal completion, activation of P3-C by the M6 startup path, changed frozen P2/P3-A source under an existing binding, or production `anima/` edits. CI evidence does not imply real-Godot or hardware readiness.
