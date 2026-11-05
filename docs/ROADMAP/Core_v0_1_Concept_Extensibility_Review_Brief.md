# ANIMA Core v0.1 — Concept Fidelity & Extensibility Review

**Status:** independent architectural review requested, **not performed / not verified**.  
**Date:** 2026-11-05.  
**Immutable reviewed implementation:** `VankoRokh/ANIMA` at **`b639a52281eeaece1b5b00d8223d8f31bd492ca1`** (Git tree **`6c96904dfbf2a7f579b3eed693827c1f01419772`**).  
**Documentation branch:** `work/core-v0-1-audit-rereview`; **do not mistake docs HEAD for executable snapshot**.  
**Companion safety re-audit:** [B1–B4 independent re-review](Core_v0_1_Work_ReAudit_Brief.md). **This audit is a second, independent verdict**, not a substitute for B1–B4 correctness.

## 1. Purpose / distinction

Verify that the **deliberately restricted headless Core v0.1** (one door, `ensure_once`, external Goal, deterministic decision) **preserves the architectural seams** needed to develop ANIMA toward the original project vision. Look for future architectural dead ends, accidental duplicate owners, excessive coupling, loss of continuity, and migration barriers.

**Do not require future functionality to be implemented today.** "Missing FAST-driven self-generated Goals" is not itself a bug in v0.1. "Adding FAST requires bypassing the Goal authority or rewriting the Core event lifecycle" **would be architectural debt or a blocker**, depending on the demonstrated change radius.

Work as an independent architect/reviewer, not an advocate of the existing implementation. **Do not edit GitHub, create PRs, or silently upgrade architecture.** Optional extension spikes/repro tests may be done only in a disposable Work checkout.

## 2. Canonical sources / original concept

Use the following documents **as written at the pinned executable snapshot**, and distinguish accepted architectural principles from proposed/implemented mechanisms:

1. [Project README](../../README.md): ANIMA is a modular agent preserving experience and identity. LLM is replaceable cognition, **not** the owner of Memory, runtime, or autonomy. Evolution: software/Core → semantic lifecycle → virtual environment → hardware chosen from measured workload.
2. [Realized architecture](../ARCHITECTURE/README.md): system ownership, boundaries of FAST/DEEP/CHOICE, Event→Memory→Knowledge, Goals/Tasks, Sleep, independent Verification, recovery, UnifiedTrace. It describes **Stage 6**, not proof that each integration is already active in P3-C's one-door loop.
3. [ADRs](../DECISIONS/README.md), especially **ADR-001 portability/continuity, ADR-002 FAST/DEEP separation, ADR-003/006 Internal State and Goals, ADR-005 Cognitive Memory, ADR-008/009 model authority, ADR-010 semantic boundary**. Names/numbers must be verified against document contents; do not infer decisions from titles alone.
4. [Core v0.1 / VAL v0.1 plan](Core_v0_1_VAL_v0_1_Plan_Draft.md): Core life cycle, trusted Observation/Belief, bounded decision, authorized actions, generic future adapter, P5 independent Lab and P6 bridge. Acceptance scenario families **T0–T7**.
5. [P0 Core boundary](Core_v0_1_P0_Boundary_Draft.md) and [Stage 7 Semantic Boundary](Stage_7_Semantic_Boundary_v0.md): separation of current Belief from durable Knowledge, typed Claim/Evidence/Source/Producer, timestamps, authority, independent results. Do not invent completed Stage 7 integration.
6. [Research / Roadmap](Research.md), [Stage 6 Architecture](../ARCHITECTURE/Stage_6_Cognitive_Integration_Core.md), and authoritative status source [`project.json`](../project.json).
7. Historical dialogues/review notes may **enrich** the original intent (Syncheia, single→multi-node, learning, perception, eventual autonomy), but **must be labelled as historical design intent** if not formalized in the repository. Do not silently promote exploratory proposals to mandatory v0.1 requirements.

### Original architectural invariants to validate

- **Continuity / Syncheia:** persistent identity, events/experience/Goals and a migration-compatible instance survive restart, model swap and future hardware/role replacement, within stated compatibility limits.
- **System-owned authority:** only Core-approved services mutate canonical Memory/Knowledge/Goal/Task/Action/Verification state; models and sensors submit evidence or proposals, not global truth or tool permissions.
- **Composable capacities:** FAST, DEEP, Sleep, Perception, vision/audio, navigation, skills and future world adapters are optional interchangeable layers; absence or temporary failure degrades capability, **not identity or basic Core operation**.
- **Single accountable lifecycle:** Event→Observation→Belief→Goal/Task→Decision→Policy→Effect→Observation/Verification→Memory/Trace, without two independent incompatible authoritative loops.
- **Separable epistemic states:** raw Event ≠ Observation ≠ Belief ≠ Knowledge ≠ Hypothesis ≠ verification result; one cannot replace another via ad hoc string or duplicate store.
- **Testable independent world:** Core must not read privileged test-world ground truth, and Virtual ANIMA Lab should allow independently controlled Human + ANIMA actors.
- **Gradual scalability:** initially in-process on laptop/Pi, later optional network/distributed compute, Pico/CM modules and hardware sensors; no false claim that an SBC cluster or power-fail migration is already proven.
- **Long-term autonomy:** bounded self-generated Goals, curiosity, learning, memory/knowledge revision and reflective Sleep may be developed later **through explicit authorization and evidence**, without requiring model ownership of Core.

## 3. Actual code to inspect (at pinned SHA)

| Boundary | Minimum code review | Potential extension coupling |
|---|---|---|
| Composition and lifecycle | `anima/core/assembly.py`, `anima/runtime.py` | `auto_core=True` currently depends on `virtual_door_root`; `Runtime` uses concrete `CoreDoorExecution` / `CoreAutonomy` types. Is there a stable generic port or must every new capability edit Core? |
| Observation / Belief | `anima/core/ingress.py`, `belief.py`, `dispatch.py` | Multiple sensors, versioned meanings, mutable source registries, event causality; transition to multi-modal sensing and Stage 7 evidence |
| Goal / Task / arbitration | `anima/core/goal_decision.py`, `anima/core/autonomy.py`, Stage2 and Stage6 stores | Multiple criteria, maintain-vs-ensure_once, priority fairness, Goals created by a separately authorized producer, multi-step tasks |
| Action and verification | `anima/core/door_execution.py`, `door_world.py`, Stage6 `execution/` | Door-specific action matching, door-specific proof schema, verification port, multiple capability handlers, external process/world bridge and typed outcome |
| Cognition and choice | `anima/cognition/`, `anima/internal_state/`, `anima/tasks/` | Existing Stage6 FAST/DEEP/CHOICE route vs new deterministic one-door P3-C: **one owner** or parallel competing pipelines? Can a model propose without executing? |
| Memory / Knowledge | `anima/memory/`, `anima/core/dispatch.py` | Does a canonical observation actually reach Cognitive Memory? Are Belief and Knowledge intentionally separate with a documented conversion/authority port? |
| Sleep, recovery, traces | `anima/sleep/`, `anima/diagnostics/`, `anima/core/autonomy.py` | Can core-active pending tasks suspend/recover, can trace link source→proposal→effect→proof, and can optional Sleep be attached without extra owners? |
| System boundary | Project README, schemas, `docs/ROADMAP/` | Data versioning, backup/migration, external adapter authentication, functionality limits, test lab integration |

**Known concrete coupling to investigate (not pre-declared a bug):** `CoreAssembly` constructs `VirtualDoorWorld`/`CoreDoorExecution` directly; `CoreAutonomy` type-checks `CoreDoorExecution`; `Runtime` offers `run_core_door_goal` and concrete P3-C attachment. The question is how much production code must change to add **second** independent capability or replace VirtualDoorWorld with a versioned Lab adapter while preserving a single system owner.

## 4. Adversarial extension thought experiments / scratch spikes

For each, specify **which production modules/contracts must change**, whether existing data needs migration, how tests would prove compatibility, and which responsibilities stay with system-owned Core.

| ID | Near-future extension | Expected architectural test |
|---|---|---|
| **E1 — Second capability** | Add independently observed `light.on/off` (or similarly simple non-door state) with different typed predicate and `ensure_once` Goal | Can it register a new observer, action, independent verifier and capability manifest **without modifying core decision/scheduler/Runtime implementation**? If not, count exact changes and characterize refactor needed. |
| **E2 — Virtual Lab bridge** | Replace in-process door-world fixture with external versioned, headless Lab adapter, maintaining Human and ANIMA as separate actors | Are actor identity, time/order, observation authority, result receipts and adapter errors modeled? Does Lab remain owner of world truth, Core owner of decisions? |
| **E3 — FAST/DEEP cognition** | Plug replaceable model backend to propose/decompose tasks when deterministic path says insufficient/no direct candidate | Can model requests remain bounded and proposals validated, with no direct writes to Goals, Knowledge or Executor? Can Core continue without models? What exact interface bridges existing Stage6 Cognition and P3-C? |
| **E4 — Memory/Semantic lifecycle** | Convert selected verified observations into episodic experience, tentative Knowledge and evidence-linked revisions | Does proposed path preserve `Event → Memory → Knowledge` and Stage7 Claim/Evidence semantics instead of treating Belief as permanent Knowledge? Who authorizes writes/revisions? |
| **E5 — Goal autonomy + Internal State** | Introduce an optional, restricted Goal proposer, driven by interest/uncertainty/experience, and multi-step Tasks | Is Goal creation a controlled capability with approval/status history? Do states influence Choice without overriding safety, truth or policy? Can deterministic Core handle unapproved proposals safely? |
| **E6 — Sleep / learning** | Schedule maintenance/consolidation/checkpoint work without losing in-flight Tasks and without direct model-to-Knowledge writes | Is Sleep a consumer/service of the same persisted lifecycle, or does Core require a second scheduler and duplicate Goal state? |
| **E7 — hardware split** | Move perception, FAST/DEEP and sensor adapters to separate Pi/CM/Pico processes, with Core still owning continuity | Are transport failures/timeouts, sequence IDs/source authority and registry/capability versions explicit? Does a remote node failure reduce capability rather than destroy identity? |
| **E8 — replace model or adapter** | Swap backend/virtual world implementation while restoring an existing instance | Which config, schemas, registry fingerprints, event histories and identity values must survive unchanged? Are migrations/version compatibility defined or merely assumed? |

The reviewer may build a **throwaway E1/E2 adapter prototype** only if convenient, but cannot commit to GitHub. A conceptual claim of extendability without any call-path/contract analysis is insufficient.

## 5. Evaluation scale (avoid false blockers)

For each original principle and E1–E8, record:

- `SUPPORTED_NOW` — at least one code path or test establishes the required architecture;
- `EXTENSIBLE_WITH_ADAPTER` — concrete existing port; implementation of new layer can proceed without editing Core ownership or persistence;
- `REFACTOR_REQUIRED` — specific present coupling/assumption forces Core changes before adding a layer;
- `UNRESOLVED_DESIGN` — future policy/interface not yet specified, no justified readiness claim;
- `OUT_OF_SCOPE_FOR_V0_1` — absence is intentional and does not block narrow release.

Also assign **architecture priority**:
- `FREEZE_BLOCKER`: present design violates an accepted Core invariant or makes verified continuity/authority meaningless **even in the one-door profile**;
- `PRE_P5_OR_P6`: near-term refactor before attaching Virtual Lab, not necessarily a v0.1 freeze blocker;
- `LATER_LAYER`: implementation can remain future work as long as the port/ownership story stays coherent.

**Do not equate missing feature with missing architectural capacity**. Conversely, avoid declaring a boundary modular solely because classes live in different files.

## 6. Deliverable

Write a concise but rigorous **Russian** report, separated from the safety re-audit verdict:

1. **Concept fidelity**: table mapping each accepted principle to actual file/test evidence, status and risk; explicitly distinguish original concept from current scoped deliverable.
2. **E1–E8 extension impact matrix**: concrete integration points, required Core edits, schema/data migration, safety/authority impacts, per-case readiness status.
3. **Top three coupling risks**: prioritized, show the shortest dependency chain and likely failure mode; do not infer unobserved behavior.
4. **Minimal evolution plan**: phased recommended ports/abstractions and **when** to introduce each (`after v0.1 freeze` / `before P5/P6` / `later`); avoid premature distributed microservice architecture and needless duplication of existing Stage6 abstractions.
5. **Separate decisions**:
   - `CONCEPT_ALIGNED` / `PARTIALLY_ALIGNED` / `MISALIGNED`;
   - `EXTENSION_READY` / `EXTENSION_REFACTOR_REQUIRED` / `EXTENSION_INCONCLUSIVE`;
   - architecture-specific `FREEZE_BLOCKER` yes/no, without conflating it with open B1–B4 correctness re-audit.
6. **Provenance**: exact checked commit/tree, documents read, inspected modules, whether scratch extension actually ran; no invented passing tests or capability portability.

**No GitHub modifications. No premature change to project.json/Stage status.** Return findings to owner for prioritization and, if needed, a separate approved refactor plan before implementation.
