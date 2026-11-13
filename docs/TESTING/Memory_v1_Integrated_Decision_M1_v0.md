# ANIMA v0.1 Integrated — M1 Core-owned Decision / Memory Advisory (headless)

**Status:** PREDECLARED; implementation and independent CI results recorded separately below.  
**Branch:** `work/anima-v01-integrated-m1` from M0 frozen baseline `9df779d14f03ff6d0bd514ecf880547621063678`.  
**Execution platform for today's acceptance:** notebook Linux x86-64; GitHub Linux x86-64 compatibility matrix. **Pi postponed** by explicit owner decision.

## Problem / scope

M0 proved Core → Memory → Retrieval → Context → FAST on persistent data, but not its coexistence with a Core-owned, independently verified world action. M0's test query was persisted *before* FAST retrieval, so the same current query could be represented as a Memory item during its own read.

M1 tests the **smallest safe combined system** without changing production `anima/` code:
- Existing Runtime persists historical user reports, Event Retrieval indexes them and provenance resolves them.
- Build one **historical ContextBundle before processing the current request**; then persist the request via Runtime and send its real Event ID plus the frozen historical context through the existing `FastCognition`. This snapshot bridge is *test-only*: it prevents this request from becoming its own prior testimony, but does not claim to be a general production solution for concurrent writes.
- FAST receives bounded informational **advisory context only**. It cannot make or bind Goals, write Knowledge, modify Core Belief, or authorize Tool actions. A user report is not a registered sensor reading.
- Only the explicit test operator creates/binds a typed Core Goal. Existing Core P3-A/P3-B chooses the permitted door action using a newly admitted sensor observation, runs the narrow sandbox handler if needed, verifies through independent readback, and durably records proof.
- Existing `VirtualDoorWorld` provides an isolated **headless test fixture**, not the external Godot Virtual ANIMA Lab. No actual remote world, LLM or sensor hardware is exercised.

## Frozen acceptance cases

| Case | Historical user report | True door state | Expected Core result |
| --- | --- | --- | --- |
| A | "door closed" | open | One authorized close effect + independent VERIFIED_SUCCESS |
| B | "door open" | closed | NO_EFFECT_REQUIRED, zero effects + independent VERIFIED_SUCCESS |
| C | "door closed" | open + first sensor read raises | No effect while sensor unavailable; Goal remains active. When restored, one effect and VERIFIED_SUCCESS |

For each scenario: operator-unbound Goal must be deferred and cause zero effects; querying memory alone cannot create a Goal or an action. The historical FAST snapshot must contain the real historical source memory but **not** the current query Event ID, even if Runtime later stores that query. Source links remain verifiable through the derived Event Retrieval index; no Knowledge is auto-confirmed. After action, reopen Core in **a second Python interpreter** and verify retained Goal, completed Task, proof associated with registered sensor-source Event, unchanged effect ledger on replay, same historical source Event IDs and complete index after explicit sync.

## Strict boundaries

1. Never read `VirtualDoorWorld.current()` into Core's typed Belief. It is a *test operator oracle*, only used for post-run assertions.
2. Memory content is **never** converted into `CoreIngress.admit` world observations or SourceRegistration. No `source="user"` authority.
3. If `sense()` fails before effect, no action is admitted. Never replace failed sensor evidence with memory.
4. An existing goal is always explicitly operator-created and bound to the frozen `world.property_equals` criterion. FAST does not participate in this step.
5. Do not change `anima/`, Core authority, Memory schema, official Stage statuses, real data, or Git history. No SLEEP, E4 L2, new sensors/embeddings.
6. Pass is **functional proof of safe coexistence and integration sequencing**, not autonomous memory-informed planning, no automatic Goal formation, no Godot adapter validation, no true SIGKILL in this M1 test and no proof that M1 is ready for production routing.

**Artifacts:** `scripts/run_memory_v1_integrated_decision_gate.py` (three isolated cases and two-process restart), `tests/test_memory_v1_integrated_decision_gate.py`, full Python 3.12–3.14 CI regression plus laptop operator report.

## Next gate

After M1 laptop PASS: define a *reviewable read-only cognition/decision interface* if actual memory-conditioned planning is needed; forbid treating Memory as Belief. Then connect the same admitted Core behavior to the existing external Godot VAL adapter and test real recovery. Do not call M1 a full artificial personality.
