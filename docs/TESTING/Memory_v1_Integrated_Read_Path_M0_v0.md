# ANIMA — Memory v1.0 / Integrated Read Path M0 (acceptance contract)

**Status:** PREDECLARED, implementation not yet verified.
**Research branch:** `experiment/core-memory-information-baseline`.
**Baseline:** `89b536bdacdf0d41223314cb3f110fb303fbc65d`.
**Goal:** begin **ANIMA v0.1 Integrated** using existing Core and Memory interfaces; stop adding E4 research features. This is **M0 read-side acceptance**, not a new Stage, Stage 7 closure or full autonomous agent.

## Problem solved

The current components exist separately (Core Runtime, MemoryProcessor/MemoryStore, Event Retrieval FTS5, RetrievalEngine, ContextBuilder and FAST), but a *single reproducible instance* using all of them and surviving a process restart is not yet independently demonstrated. An isolated alias lab PASS does not prove working retrieval in Core.

## Minimum execution path

```text
CoreAssembly / Runtime.user_input
    -> immutable EventLog (legacy JSONL)
    -> EventProcessingCoordinator -> MemoryStore source links
    -> opt-in EventRetrieval.sync (SQLite FTS5, derived)
    -> exact raw Event retrieval + ProvenanceResolver (source IDs)
    -> RetrievalEngine + bounded ContextBuilder
    -> FastCognition with a deterministic, zero-LLM mock backend
```

Run `seed` and `verify` in **different Python processes** sharing an isolated temporary workdir. No external calls, no real tools or action effects. The test's second process calls `build_core` again; no fake in-memory store or manually created Memory rows. Use seeded reports with deliberately different values for one subject, so evidence is preserved even when legacy encoding merges episodes.

## Gate: required observations

1. **Write/link (A):** `Runtime.user_input` produces two real `conversation.user` source Events; both appear as source links in persisted Memory, without manually injecting a Memory row.
2. **Strict coverage (D):** after new raw Events, opt-in Event Retrieval reports `partial`; a complete-required search **must reject**, not silently claim absence. After `sync`, status is `complete`.
3. **Raw detail (C):** exact earlier numeric values from *both* conflicting reports are retrievable by Event IDs from source-verified raw bytes, irrespective of whether composed Memory text kept those values.
4. **Conflict/authority (E):** both reports remain individually addressable; neither is silently selected as `confirmed Knowledge`. A report is **not** a fact about the world and a `source="user"` label is **not** authentication.
5. **Process restart (B/G, baseline):** a new Python process reloads the same durable stores, executes normal `Runtime.wake`/recovery, re-syncs the derived index, and retrieves both original Events, without duplicating their IDs or source links. This is normal restart, **not SIGKILL**.
6. **FAST boundary:** `RetrievalEngine` and `ContextBuilder` construct a bounded `consumer=FAST` ContextBundle; a replaceable test FAST backend receives it. FAST has no production authorization and does not write Memory or Knowledge.
7. **No-match:** after complete sync, a unique absent marker has zero Event search results and empty Memory search, not a fabricated answer; on partial index, no-match cannot be inferred.
8. **Cross-platform:** script runs with standard Python on Linux x86-64 / ARM64, can write a machine-readable result with OS, architecture, Python, event/source counts, selected Memory IDs, budgets, and gate verdict. Identical fixture and code on PC and Pi, no real-world user data.

**Do not** automatically enable Event Retrieval in production, modify `anima/`, alter `docs/project.json`, integrate the untrusted E4 alias gate, add embeddings/LLM/sensors/SLEEP features or issue Goal/Task/Tool actions for this read-only milestone.

## Evidence and interpretation

- `scripts/run_memory_v1_integrated_read_gate.py` is the standalone opt-in repeatable runner.
- `tests/test_memory_v1_integrated_read_gate.py` proves real child-process restart and negative/fail-closed cases.
- GitHub CI Python 3.12/3.13/3.14: all tests plus the new gate runner must PASS; a CI PASS is not Raspberry Pi validation.
- User's local PC/Pi tests: run the same frozen command and preserve both JSON reports with platform metadata. Distinct hardware/OS/storage/Python configurations are reported, not conflated.
- This M0 gate is **insufficient** for v0.1 Integrated overall: trusted Core ingress, typed decisions, independent verification, true power-loss, p95 scaling, and Stage 7 read-only Claim/Evidence policy must be admitted separately. Next M1 integrates only a *proven* safe Core-owned decision route and VAL adapter with the existing boundary.

**Stop rule:** if the existing interfaces can deliver the M0 path without a production change, do not invent another intermediary service. If there is a blocker, describe it explicitly and patch only that blocker in a separate reviewed step.
