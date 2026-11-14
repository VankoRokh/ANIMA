# ANIMA v0.1 — release contract

**Status:** working release contract; acceptance **OPEN**, no tag or release declared.  
**Target:** Linux x86-64 notebook, Python 3.12+ (CI matrix 3.12/3.13/3.14).  
**Implementation track:** `work/anima-v0-1-release`, starting from `7465684725551188215a932dca6c42f98250c7d4`.  
**Scope:** one reproducible, persistent, deterministic **system-owned** instance. Experimental branches and later releases are outside this gate.

## 1. Product boundary

ANIMA v0.1 is a stable *foundation*, not an intelligent general-purpose assistant. It must work without a required LLM, Godot, Raspberry Pi, camera, microphone, external network or GPU. Deterministic means that the same committed state, ordered inputs and approved fixed rules produce the same semantic decisions; UUIDs, wall-clock timestamps and OS scheduling are not required to be byte-identical. Local trusted operator commands are not proof of remote identity authentication.

No claim of consciousness, autonomous learning, unrestricted self-generated goals, model reliability, real-world safety, exact-once for arbitrary external tools, power-loss durability or Stage 7 completion is part of v0.1.

## 2. Required running instance

The release entry point must use the **production** `build_core` and `Runtime`, not copy their logic into a lab. A single instance has a durable identity, state, legacy raw EventLog, MemoryProcessor/MemoryStore, provenance links, incremental read-only Event Retrieval, bounded Retrieval/Context, Internal State/GoalStore, and opt-in typed Core Event/Belief/Task interfaces. It must provide a multi-event headless operation mode and clean shutdown; absence of user input may block waiting for events without busy polling.

Core owns all source registration, decision/admission, Goal/Task status and verification. The default headless profile has **no external execution capabilities** and must not silently grant local text input trusted sensor authority. Demonstrations with a deterministic in-process world are separately opt-in and must not be needed to boot the base profile.

Pluggable FAST/DEEP/SLEEP facilities already present remain supported at their current tested contracts. Further model work, consolidation, meta-memory, graph databases, vector embeddings and sensor/peripheral modules are **not release blockers**.

## 3. Release acceptance matrix

| Gate | Required result | Evidence |
| --- | --- | --- |
| R-01 Boot | Standard entry point creates one persistent instance, no model or VAL | Clean source snapshot + subprocess report |
| R-02 Multi-event | One process processes multiple distinct ordered user reports, preserves raw Events and Memory source links | Raw journal + MemoryStore |
| R-03 Retrieval | Exact earlier source detail retrievable even when compressed Memory omits it; bounded context and explicit complete/partial coverage | Event Retrieval + ContextBuilder |
| R-04 Reopen | Fresh Python interpreter opens the same data directory, retains identity/history/links, no duplicate replay | Two-process gate |
| R-05 Boundary | Arbitrary local report cannot masquerade as registered Core sensor, create authenticated authorization, or execute tool | Negative tests |
| R-06 Core integration | Verified existing Core Goal/Task, policy, action, independent proof, and one-effect recovery tested against an *opt-in local deterministic adapter* | Existing P3-C/Core acceptance plus release-specific composition evidence |
| R-07 Failure | Abrupt process death leaves recoverable committed records; unsaved input is not claimed as durable; external side effect is never blindly replayed | Controlled SIGKILL/process-cut test, with limitations |
| R-08 Resources | Measure representative fixed notebook workload with CPU/RSS/latency/disk; decide budgets *before* verdict | Recorded baseline; no mandatory Pi |
| R-09 Compatibility | Python 3.12/3.13/3.14 regression and `scripts/check.sh`; supported migration/reopen path is explicit | CI + owner laptop verification |
| R-10 Audit | Exact clean SHA, scoped code review, unresolved risks, no secret data, release documentation | Review + release record |

A PASS for M0–M6, T6–T9 or Stage 6 is reusable **historical evidence**, not an automatic R-01–R-10 verdict for a new source snapshot. No release tag until a final end-to-end gate passes.

## 4. Blocking vs deferred

**Block:** source/provenance loss; incorrect promotion of reports to truth; unauthorised effects; lost committed state; duplicate effects on supported recovery path; non-reproducible release assembly; inability to continue in a fresh process.

**Deferred with documented limit:** CPU/SQLite optimisation that stays inside an agreed budget, Graph/Meta-memory/L2, autonomous Knowledge write lifecycle, cognitive backend training, extended SLEEP, hardware portability, GUI, mobile and physical peripherals.

## 5. Execution plan

1. Compare this contract with the real source and register only verified gaps.
2. Introduce one normal release profile without changing historical tests or production Core contracts unnecessarily.
3. Add positive, negative, restart and SIGKILL evidence; record resource budgets before interpreting timings.
4. Run full Python regression and a notebook acceptance.
5. Only after acceptance: tag the exact clean release commit and reorganise navigation into `docs/RELEASES/`, `ARCHITECTURE/`, `TESTING/`, `DECISIONS/`, `RESEARCH/`, `ARCHIVE/`. Do **not** rewrite historical experiment results.

Future versions remain conceptual until separately scoped. The official Stage history in `docs/project.json` is historical status, not the release acceptance verdict.
