# ANIMA v0.1 Integrated — M4 reviewed proposal → explicit operator decision → unbound Core Goal

**Status:** CI VERIFIED (Python 3.12–3.14; full regression and six-case gate PASS) + owner-reported laptop M4 PASS (Linux x86_64; Python 3.14.4). Raspberry Pi deferred.  
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

### GitHub CI — 2026-11-13

**Frozen executable snapshot:** `e6fa8f0234fc79ad8b205e00100bb742d4d61a2d`. [GitHub Actions #43444096905](https://github.com/VankoRokh/ANIMA/actions/runs/43444096905) — **SUCCESS** in three Linux x86-64 Python matrix jobs.

| Gate | Python 3.12 | Python 3.13 | Python 3.14 |
| --- | ---: | ---: | ---: |
| Targeted M0/M1/M2/P6/M3/M4 | **51 PASS** | **51 PASS** | **51 PASS** |
| Full repository regression | **1698 PASS** | **1698 PASS** | **1698 PASS** |
| Independent two-process M4 runner | `M4_APPROVED_GOAL_PASS` | `M4_APPROVED_GOAL_PASS` | `M4_APPROVED_GOAL_PASS` |
| Documentation/syntax | PASS | PASS | PASS |

**Six isolated-case expected outcomes (observed by the M4 runner):**
- `normal`: operator decision APPROVE, **one** canonical Goal/one start transition; replay leaves exactly one Goal; unbound Core door execution defers with `UNBOUND_GOAL`.
- `before_goal`: persisted approval, hard `os._exit(74)` before Goal creation; second process finds no Goal and creates exactly one with reserved IDs.
- `after_goal`: hard `os._exit(73)` after real `GoalStore.create_goal` but before approval-ledger receipt; second process finds matching Goal and reconciles ledger without creating another.
- `approval_resume`: second process initially finds ticket only in `reviewed` state; no Goal before an explicit second-process APPROVE; then one canonical Goal.
- `rejected`: terminal REJECT forbids later APPROVE or Goal creation.
- `source_modified`: historical Memory changes after persisted APPROVE, so materialization fails closed with zero Goal.

All cases assert **0 Tasks, 0 Tool effects, 0 Knowledge**, and unbound Goals remain active. Negative tests also check source/index integrity, unknown operator, changed receipt fingerprint, changed same-origin proposal, foreign operator-provided fields, occupied Goal ID, and frozen Stage 6 `ProposalValidator`.

**Exactly what this does not prove:** `os._exit` ≠ `SIGKILL` or power loss; operator `test.operator.m4` is a trusted **lab-host input convention**, **not** an authenticated human identity or security boundary against hostile local code. No LLM, live Godot, network agent, Raspberry Pi, automatic Goal approval, Task binding or action. `anima/`, official Stage statuses, and `docs/project.json` were not changed.

### Notebook acceptance — PASS (owner-provided original JSON)

From an isolated `ANIMA-M4` worktree, using local Python 3.14.4:

```bash
python -m scripts.run_memory_v1_approval_gate --report /tmp/anima-m4-PC.json
```

Runner opens six separate disposable synthetic Core worlds, forces two intentional `os._exit` interruptions in child workers, and reads Core/Goal/Memory in fresh independent Python processes; **no Godot binary needed**. It refuses to overwrite existing reports, or place the report inside the repository. The expected top-level result is `M4_APPROVED_GOAL_PASS`. Physical laptop PASS must be asserted from the owner's actual JSON, not from CI alone.

### M4 laptop result — 2026-11-13

**Evidence class:** the original uploaded file `anima-m4-PC.json` was read and independently parsed. This is an owner-provided local-run JSON, **not** an external authenticated terminal attestation. It reports `schema=anima.memory_v1.approval_m4/0.1`, `status=M4_APPROVED_GOAL_PASS`, `python=3.14.4`, `machine=x86_64`; six separate case records are in `phase=verify` and each has `status=M4_CASE_PASS`.

**Important source limitation:** the report has **no Git commit/SHA field**, so the exact local source tree cannot be proven from this JSON alone. CI on branch commit `72992d7aa242c2e0a55593ee15c86d0cc6ce2687` was separately successful; do not silently equate that CI snapshot with the unversioned local report.

| Case | Recovered Goals | Goal start transitions | Result |
| --- | ---: | ---: | --- |
| `normal` | 1 | 1 | explicit approval → one unbound active Goal |
| `before_goal` | 1 | 1 | replay after stored decision / pre-Goal cut |
| `after_goal` | 1 | 1 | reconcile existing Goal after pre-ledger cut |
| `approval_resume` | 1 | 1 | approval only in resumed phase |
| `rejected` | 0 | 0 | declined, no Goal materialization |
| `source_modified` | 0 | 0 | altered post-approval evidence rejected |

**Top-level counts:** `goals_total=4`, `tasks_created=0`, `tools_executed=0`. **Each case:** `task_count=0`, `effect_count=0`, `knowledge_count=0`, `raw_provenance_checked=true`, `index_status=complete`, `stage6_changed=false`. Each created Goal declares `goal_unbound=true`, and its initial transition count is exactly 1.

**Explicit nonclaims:** `operator_identity_authenticated=false`, `llm_used=false`, `godot_tested=false`, `pi_tested=false`, `true_sigkill_tested=false`, `production_code_changed=false`. The runner's laboratory `os._exit` cut is **not** evidence of power-loss durability, real operator authentication, malicious actor resistance, or executable Goal binding.

**Decision:** M4 **functional laptop gate accepted** (owner-reported PASS), alongside full GitHub CI matrix. This validates a replay-safe *lab-controlled unbound Goal creation bridge*, **not** production operator security. Separate independent M5 admission/binding tests are still required before approved Goals may execute. Official Stage status and `docs/project.json` unchanged.

**Next architectural dependency:** M4 only creates unbound Goals. An M5 proposal for **separate, explicit typed binding/execution authorization** should be independently designed and negatively tested before any M4-produced Goal can act. Operator identity/authentication and persistent approval security remain open production concerns.

