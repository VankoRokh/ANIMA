# ANIMA v0.1 Integrated — M4 reviewed proposal → explicit operator decision → unbound Core Goal

**Status:** PREDECLARED, awaiting CI and laptop acceptance.  
**Branch:** `work/anima-v01-integrated-m4`, starting from M3 owner-accepted `1856d00b5daed8a21feb54a30c21d36e9e7cb572`. Raspberry Pi deferred.

## Purpose

M3 proves that source-backed Memory may suggest a Goal candidate but cannot authorize anything. M4 tests the **smallest controlled authorization bridge**: a human/operator host decision over an exact, immutable M3-reviewed suggestion can create **one unbound Goal** in the real existing `GoalStore`. It **must not** bind a typed GoalCriterion, create Tasks, call the Tool, modify Belief, confirm Knowledge, or run automatic Core scheduling. Stage 6 RESPOND-only ProposalValidator must remain untouched.

**This is a lab-host operator decision, not user authentication.** A caller that can instantiate `OperatorDecision` in the same Python process can impersonate its `operator_ref`; the laboratory tests ownership and explicit separation of calls, **not cryptographic identity, secure UI approval, or access control against malicious local code**. Production authorization needs separate credentials/host integration and review.

## Frozen M4 contract

1. `stage(view, draft)`: call existing M3 reviewer; accept only `REVIEW_REQUIRED`, never `CONFLICT_REVIEW` or `REJECTED`. Persist exact `draft`, source-backed snapshot fingerprint, canonical suggestion fingerprint and a `reviewed` ticket. No Goal. Repeated stage of same bytes returns same ticket; same ticket with altered payload is rejected.
2. `decide(ticket_id, decision)`: separate trusted-test-host callback supplies typed `OperatorDecision` with explicit `APPROVE` or `REJECT`, `operator_ref`, monotonic/unique receipt ID and **exact preview fingerprint**. Persist an immutable one-time operator decision. Untrusted proposal body cannot supply priority, role, tool, Goal ID or approval. Approval does not create a Goal; rejection is terminal. Duplicate identical receipt is idempotent; modified or conflicting receipt is refused.
3. `materialize(ticket_id)`: **only** for approved ticket; re-read source Event index (raw checksum), historical Memory and M3 review and assert the exact captured fingerprint, then call existing `GoalStore.create_goal` with **frozen system-authored Goal fields**, a preallocated stable `goal_UUIDv4` and `transition_UUIDv4`. In an unavoidable post-create / pre-receipt crash window, reopen and reconcile by deterministic IDs and exact Goal properties rather than creating a second Goal. Do not silently accept a conflicting Goal occupying the ID.
4. Goal is left **active and unbound**. Calling the established Core execution route must return `DEFERRED/UNBOUND_GOAL` with zero tool operations. M4 never calls `bind_core_goal`; a future gate must authorize binding separately.
5. Independent subprocess cases: reject/no approval; approval then hard `os._exit` **before** Goal write; hard `os._exit` **after** Goal write but before ticket finalization; normal approval→Goal; duplicate/replayed same decision; changed evidence after approval (fail closed, no Goal); changed draft/receipt fingerprint; incomplete Event index; conflict and state report (no stage). Each uses separate isolated Core DB and headless VirtualDoor fixture.
6. **Stop** on unintended Goal, second Goal, missing/duplicate initial transition, non-empty Tasks/Operations/Knowledge/effects, action authority given to Memory, unbound Goal executing, accepted altered approval or partial/raw-mutated evidence.

## Persistence/recovery choice

M4 uses an **experimental SQLite decision ledger** in the same isolated Core test directory; canonical Goal lifecycle stays in the existing InternalState `goals` + `goal_transitions` tables via `GoalStore.create_goal`. These are **two separate transactions**. M4 allocates its Goal/transition IDs **before** Goal creation and persists their reservation with operator approval, so recovery can reconcile a crash at either boundary. The system owns fixed description, priority, criterion text and source. Approval receipt binds the complete candidate fingerprint; no free-text model field becomes a Goal authority field.

M4 test fixtures do not prove real `SIGKILL`, power-loss durability, multi-host security, concurrent malicious writers or stable interface for autonomous operation. M4 is an **opt-in lab service** and uses real Core stores; production `anima/` modules are left unchanged. Any later real authorization gateway requires its own security and recovery audit.

## Artifacts and gates

- `labs/virtual_anima_lab/python/m4_approval_bridge.py` — experimental approval ledger and replay-safe GoalStore bridge.
- `scripts/run_memory_v1_approval_gate.py` — synthetic independent-process crash cut and negative tests.
- `tests/test_memory_v1_approval_gate.py` — focused negative assertions + Stage 6 permissions regression.
- CI matrix Python 3.12–3.14, M0–M4 targeted + full regression, report outside repo.
- After CI: physical laptop Python 3.14.4 report; only then record local M4 PASS.
- No live Godot or Raspberry Pi in this step; those are separate future gates.

## Evidence

No claimed outcomes before running CI and notebook tests.
