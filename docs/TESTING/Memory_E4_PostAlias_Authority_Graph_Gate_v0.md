# ANIMA E4 — Post-alias-lifecycle authority and dependency oracle gate v0

**Status:** PREDECLARED CONTRACT + MEASURED CHARACTERIZATION. **AUTHORITY FAIL / STRUCTURAL GRAPH PASS / PRODUCTION NO-GO**. No Core/Memory migrations or semantic generalization claim.

**Base:** `0841ec8867365b33ddfc62572c65b413bdf4784b`, branch `experiment/core-memory-information-baseline`.
**Scope:** isolated `AliasLifecycleLab`, read of `CoreIngress` contracts, deterministic independently computed dependency closure, and separate process-fault/resource follow-up. Frozen E4 v0/challenge corpus unchanged.

## Question A — Who may revoke a definition?

A revocation's syntactic identity (Event type, `source="user"`, matching definition Event ID, later sequence/timestamp, valid SHA-256) is not authorization. `Event.validate_record` validates shape, not provenance. In `CoreIngress`, `SourceRegistration` binds a caller to a source **only when invoked beyond a trusted adapter boundary**; a registry label itself is not authentication. `AliasLifecycleLab` currently consumes untrusted raw Event dictionaries directly and does not have such a boundary.

**Predeclared characterization:**
- A syntactically valid revocation Event self-labeling as `user`, with an exact Event ref, may be inserted by a caller who does not own the definition. The **current** lab is expected to accept it. This is a **security failure demonstration**, never an allowed production result.
- With `source="unknown.relay"` the existing check rejects; this alone does not address spoofing.
- The test must demonstrate the side effects (revoked head, stale derived views), not only test event validation.
- Do not treat a matching session ID, matching `source` string, same text, exact reference, cryptographic body checksum, or newer timestamp as user identity proof.
- Do not test with a fake external "trusted" certificate invented inside the same untrusted payload.

**Required future admission contract (not yet implemented):**
- A trusted caller/admission boundary supplies a durable principal binding **outside** the submitted Event payload. Persist exact identity of the admitted definition and revocation, immutable admission receipt IDs, policy revision, action `revoke_alias` and scoped `alias_id@revision`.
- Default deny when principal unknown, conflicting, changed or untrusted; no implicit transfer of revocation rights from `source=user` to every user. Same principal with a new session can be considered only when the authenticated identity actually matches.
- Delegation or administrator override requires explicit separately audited policy; mere authority to observe or report events never authorizes changing knowledge.
- Separate `revocation_requested` (report) from `revocation_authorized` (Core-owned decision). No derived invalidation before authorization.
- Atomic mutation + authority receipt, replay idempotence, rejected-request traceability and recovery are required before production.
- A forged `CoreIngress.source_ref` passed by an untrusted caller is **not** an identity oracle. The trusted adapter contract must be tested at its actual boundary.

## Question B — Does the dependency traversal affect precisely the right nodes?

Independent oracle = construct a DAG as a set of *logical edges* in a test-only data structure before the lab receives it; compute transitive descendants of `alias a@1` using a separate pure graph closure. Compare the lab's receipt, `invalidations` ledger and all current/stale heads against oracle, including unrelated `alias b@1` and mixed dependencies. Use fixed random seed and publish graph size and expected set. Test diamonds, chains and forks, duplicate-reachable nodes, multiple aliases, unconnected components. The oracle must never call the lab's `_downstream` implementation to compute expected results.

**Safety rule:** a node with *any* invalidated ancestor must not remain `current`. A node with no invalidated ancestor must not be marked `stale`. Old immutable revisions survive. 128 affected nodes are permitted; >128 must **fail atomically** in this current lab; assess separately whether "cannot revoke a heavily used alias" is an unacceptable denial-of-correction design.

**Limit:** a deterministic source code independent oracle is not an independently authored blind corpus. No semantic truth is inferred from correctness of a graph.

## Later gate: real process exit and resource profiling

Use subprocess/OS termination (not Python `LifecycleCut`) both before COMMIT and after COMMIT, reopen DB, verify all-or-nothing alias + invalidation ledger, stable replay, and bound cleanup; **not a power-loss/disk-flush test**. Compare selective against coarse invalidation with 100, 1k, 10k node synthetic workloads, report wall-clock median/p95, database size, WAL impact, peak RSS, graph width/depth, affected fraction, hardware and interpreter version. State over-budget behavior separately; never silently leave revoked knowledge active due to a resource cap.

## Go/no-go

- A syntactic spoof accepted for revocation makes **authority gate FAIL / production NO-GO** even when graph and SQLite tests pass.
- Graph gate passes only against independently computed reachable-set oracle; self-scored receipts alone are insufficient.
- An actual process-fault and resource conclusion requires observed subprocess and measurements, not simulated `LifecycleCut`.
- These are predeclared, visible development tests, **not blind external validation**.

## Measured run — 2026-11-12

**Code snapshot:** `e81526c7d59a4f7620484e1b8e82a17844a7b309`. **CI run:** [#43203831696](https://github.com/VankoRokh/ANIMA/actions/runs/43203831696) — **SUCCESS** on Python **3.12, 3.13 and 3.14**. 98 pre-existing targeted regression checks passed and **1634 full regression checks passed** on each Python version. The new tests execute in the **full regression** step, not in the separate 98-test targeted step. Previous baseline was 1629 full regression checks.

**A: authority — NEGATIVE CHARACTERIZATION REPRODUCED.** A caller-created `conversation.user` Event with self-declared `source="user"`, a valid `alias_control` and exact source reference was accepted by the isolated `AliasLifecycleLab`. Alias `a` became `revoked` and `story_s` / `episode_e` became `stale`, while unrelated `story_u` stayed `current`. This test intentionally documents unsafe behavior; **a green pytest result means the vulnerability was reproduced, not that authorization was passed**. No identity was authenticated at ingestion.

**B: graph — STRUCTURAL ORACLE PASS.** Separate fixed-point logic computes descendants before calling the lab's invalidation traversal. A deterministic 99-node DAG tested shared ancestors and mixed A/B dependencies. A separate 12-definition / 90-derived-node same-surface conflict corpus tested 3 sequential revocations, comparing each *new* invalidation set with incremental oracle closure, while preserving nine other active aliases. The independent logical generator calculates the expected incremental sets as 56, 3, 5 (64 total) for this fixed seeded workload; the CI test independently compares actual IDs/states, not just counts. A separate diamond graph checks once-only invalidation; exactly 128 affected nodes are accepted. The existing >128 regression confirms all-or-nothing rollback.

**Meaning:** this is deterministic, visible, same-team **structural** testing. It does not certify semantic truth, independent users, trust of real adapters, cryptographic authenticity, power-loss durability or production authority. The negative source-authentication finding is a **blocker**, regardless of 1634 green checks.

**Next:** design an admission receipt and policy-bound principal/alias-owner relation in an *isolated* study; reject untrusted claims without changing any alias or dependent views. Then separately perform actual subprocess kill/restart, overflow safety policy, and throughput/RSS/disk-size measurements. Do not enable automatic Core/L2 actions.
