# ANIMA Memory v1 — M6-B1 explicit Godot source migration preflight

**Status:** PREDECLARED — pending independent negative tests and real Godot CI.  
**Base:** owner-accepted M6-A `0d81fb74c07ed4c523e2a10fafd7b1fd92363b71`; branch `work/anima-v01-integrated-m6b1`.

## Why M6-B is split

**M6-A** grants a laboratory one-shot effect for `VirtualDoorWorld`, based on `M5`'s P2 source `sensor.door_01`, producer `adapter.virtual_door_sensor/0.1`, and clock `lab_tick`. **P6 Godot** exposes an independently versioned bridge observation `lab.sensor.anima.proximity` / `lab.godot` / `epoch+tick`. `VALDoorPort` translates it into Core's `sensor.door_01` / **different producer** `adapter.val_door_port/0.1`, with persistent `lab_sample` sequence. Same Core subject/predicate/ActionSpec is not equal authority.

The Core P2 SQLite state is persisted at `runtime/core_state.db`, and the existing `build_core` binds source configuration at startup. Reusing **the same P2 source ID** with a changed producer/clock in the same DB risks mixing noncomparable observation histories. We **must not** fake virtual sensor provenance, change M5 registrations behind its existing approval, or let an action-capable Godot assembler silently ingest a saved binding.

**M6-B1 scope:** real Godot 4.7.2 observation, exact source/clock/world identity mapping, explicit **separate trusted lab-host APPROVE/REJECT** on a frozen mapping, fresh live revalidation, and fail-closed negative cases. **NO Core executor or Task, NO Tool call, NO Goal completion and NO modification of P2 registrations.** This is a prerequisite, not permission to execute.

**M6-B2 gate (separate work):** design a proper isolated target-source P2 lineage or new authorization bridge and explicitly revalidate previous M4–M5 source-backed Goal against it before any Godot Tool capability is installed; install a guarded once-only pre-effect handler, prevent direct unguarded assembly and P3-C, and test live effects with independent P6 sensor Proof and two-cut recovery. Existing M6-A permission **never** transfers to Godot.

## Frozen M6-B1 acceptance contract

1. A candidate must refer to **exactly one** existing active canonical `M4` Goal whose `M5` ticket is `bound`. The original M4 raw Memory/Event provenance, immutable M5 binding and registered virtual-source ActionSpec must still validate. Any changed Memory, incomplete index, wrong Goal, corrupted binding, or unapproved M5 ticket is rejected.
2. P6 Godot is launched by the lab harness on an isolated random 127.0.0.1 port and kept alive. Only the existing `VALDoorPort` may read it. Its `hello` must satisfy the frozen scenario, world version, instance ID and capabilities; `observe` must pass the existing `validate_observation` contract and expose the visible registered door **open**.
3. The captured map records **both** provenance levels (raw Godot source/producer and P6 adapter Core-facing source/producer), source schema, clock names and values, `world_instance_id`, `epoch`, `world_revision`, adapter occurrence ID, `sample_seq`, and content SHA256. The stored adapter sample log must agree. No `lab_tick`↔`lab_sample` arithmetic conversion is allowed: both domains remain separate.
4. `stage` persists a canonical immutable mapping ticket and never grants authority. `decide(OperatorMigrationDecision)` requires an explicit separate typed lab-host `APPROVE` or `REJECT`, matching the full mapping fingerprint. Repeated identical approval is idempotent; any altered or conflicting approval is denied. The lab `operator_ref` string is **not human authentication**.
5. `revalidate` requires an approved ticket, **fresh new P6 observation sample** and unchanged world identity/epoch/revision and door `open`. It verifies original M4/M5 source again, raw sample provenance and complete mapping. Reuse of the reviewed sample, a restarted world, changed epoch or revision, closed door, replaced mapping, stale/forged source or incomplete historical Event index fails closed.
6. M6-B1 makes **zero** new Goal, Task, ExecutionOperation, Knowledge, or effect; installed `CoreExecution=None` and `CoreAutonomy=None`. Godot agent is limited to hello/observe: **no act_door and no operator write commands** in the preflight.
7. The M6-B1 ticket can **never** by itself call `build_core` with `world_port`, bind Goal, instantiate Tool handlers or authorize a side effect. No implicit fallback to the M6-A single-use permission. This is a laboratory proof-of-mapping, not a complete production capability firewall.

## Planned tests

- Unit tests: source/clock/producer mismatches, forged candidate, conflicting host approval and fingerprint, rejected ticket, duplicate same-origin changed mapping, changed original Memory/Goal/binding, stale sample and external world identity mismatch. Fail closed; zero effects.
- Independent headless **real Godot 4.7.2** gate: positive reviewed→approved→revalidated mapping across two Python processes, rejected, stale sample, and reset/replacement world negative scenarios. Assert Godot close-door event count remains exactly zero. Include exact `git SHA`, Godot version, report schema and provenance fingerprint in JSON output.
- CI Python 3.12/3.13/3.14 full repository tests + exact pinned Godot 4.7.2 live lane. Laptop acceptance only after owner's real Godot report, not from CI alone.
- Do not update `anima/`, Stage status, or `docs/project.json`.

## Trust limitations

The Godot loopback role and source ref are not cryptographic authentication; an attacker with arbitrary local socket/process/SQLite access could spoof data or bypass laboratory composition. A live freshness sample cannot stop a world changing after the check (TOCTOU). No physical sensor, Raspberry Pi, real `SIGKILL`, power loss or permission isolation is demonstrated in B1. **A green B1 cannot be described as successful M6-B executable migration.**

## Results

Pending.
