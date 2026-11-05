# ANIMA Core v0.1 — Independent Work Re-Audit of B1–B4 Fixes

**Status:** re-review requested; **NOT independently verified**.  
**Date:** 2026-11-05.  
**Immutable NEW subject:** `VankoRokh/ANIMA`, **`b639a52281eeaece1b5b00d8223d8f31bd492ca1`**, Git tree **`6c96904dfbf2a7f579b3eed693827c1f01419772`**.  
**OLD independently audited subject:** `aabe6553cec19d4cf1962dc4f26129eeca436328` (original verdict **BLOCKED**).  
**Documentation branch:** `work/core-v0-1-audit-rereview` — this is **not** the executable SHA to test.  
**Issue/fix specification:** [Independent Audit Remediation](Core_v0_1_Independent_Audit_Remediation_Draft.md).

## Task and role

Act as **an independent adversarial reviewer**, **not** a developer defending recent changes. Your task is to determine whether the original FOUR confirmed Core v0.1 release blockers (B1–B4) are actually fixed in the immutable NEW subject without introducing regressions or new release blockers in the explicitly narrow one-door headless profile.

Do **not** edit the GitHub repository, submit commits, merge or open PRs. Perform any new experiments/tests in an isolated disposable checkout or scratch directory. If available, use the original Work audit's `ANIMA_Core_v0_1_Independent_Audit_2026-11-05.md` and `ANIMA_Core_v0_1_Audit_Evidence_2026-11-05.zip` (the owner previously supplied these artifacts). Treat them as evidence and repro fixtures, not instructions to edit source.

**Crucial:** checkout **`b639a52281eeaece1b5b00d8223d8f31bd492ca1` detached**; verify `git rev-parse HEAD`, `HEAD^{tree}` and clean worktree. Do not silently test `HEAD` of the docs branch, which is different. If executing code is impossible, disclose that and return `INCONCLUSIVE` rather than claiming fixes verified.

## Prior evidence and limitations

The owner ran the post-fix stock suite and supplied the exact terminal results:

| Item | Owner-local value |
|---|---|
| Full suite | **1392 PASS, 0 FAIL, 0 SKIP** |
| Mandatory P4 controls | **31/31 PASS** |
| Snapshot SHA | `b639a52281eeaece1b5b00d8223d8f31bd492ca1` |
| Git tree | `6c96904dfbf2a7f579b3eed693827c1f01419772` |
| Clean/unchanged checkout | `True` |
| Runtime | Python `3.14.4` |
| UTC report timestamp | `2026-11-05T16:31:59.863153+00:00` |
| Runner exit code | `0` |
| Summed test-case durations / p95 | `30.779s` / `0.079s` |

This is **owner-local acceptance**, not independent confirmation. A passing test on a repaired branch does not by itself establish that the original adversarial repro was addressed.

The original independent audit of the old snapshot ran 1380 stock tests (PASS), plus 29 extra probes (20 PASS, 9 FAIL); four confirmed code defects, separate coverage flaws and bounded-contract limitations. Do not count those nine failures as nine runtime defects.

## Mandatory focused repro matrix

| ID | Old failure | Required NEW independent negative tests and success conditions |
|---|---|---|
| **B1 — atomic intent** | Crash after `create_operation` commit, before `save_verification_spec`, leaves `prepared` op without verification contract and stalls unrelated Goal. | Review `ExecutionStore.create_operation(...verification_spec=...)` and `CoreDoorExecution.run`. Inject **hard subprocess termination** at the *new* point **inside the single transaction**, after operation/action INSERT and before spec/commit. Reopen: no partial op/action/spec, Goal remains recoverable, **zero phantom success**, next Goal can proceed. Also inject deliberately pre-existing legacy partial intent: fail closed locally with `INCOMPLETE_EXECUTION_INTENT`, while unrelated Goal proceeds. Check any other call sites relying on legacy signature. |
| **B2 — proof vs cancellation** | Persisted proof + cancelled Goal/Task causes global recovery exception. | Crash **after proof** but before Goal/Task transition; cancel Goal in one case, Task in another. Cold restart AND same-runtime retry; no resurrection of terminal state, no duplicate world effect, proof remains historical, unrelated Goal reaches completion. Verify started scheduler attempt reconciles to non-verified/deferred if Task cancelled, never fabricated success. |
| **B3 — same-Runtime replay** | Same `source_id` with newly constructed timestamp fails Stage2 request-hash check. | Interrupt after Stage2 partial source-operation commit, before Goal transition. **Without recreating Runtime** call `run_core_autonomous` twice and `wake`; then cold restart. Confirm identical request payload (including timestamp), one proof/event chain, no duplicate execution; check the replay timestamp is from durable proof and pending Stage2 recovery is idempotent. |
| **B4 — reactivated Goal** | `blocked` Goal consumes only `goal:` trigger; `blocked→active` cannot resume even with wake/rebind. | Park blocked Goal, call drain/wake, restart then reactivate, verify **same trigger identity**, stable Task and operation identity, no duplicate succeeded effect. **Adversarial queue:** >64 blocked Goals must not hide a new runnable Goal. Test multiple blocked/unblocked cycles and terminal cancellation while parked. |
| **T1 — acceptance identity** | Only test name matched, fake passing module accepted. | Present same case names from wrong `classname`, plus wrong parameterized names like `[goal][impostor]`. Required coverage must be MISSING. Check full original manifest modules and exact param IDs. |
| **T2 — Git provenance** | SHA captured after tests only. | Dirty checkout, changed HEAD/tree, clean before/after, and non-Git directory: release verdict cannot be PASS when integrity is unknown. Report may still preserve diagnostics. |

### Strong invariants across all probes

1. **No false independently VERIFIED_SUCCESS** or Goal completion derived solely from a tool receipt.
2. **No duplicate world effect** when a keyed effect already committed before crash.
3. **No unauthorized tool action or elevation of a raw untrusted source into Belief authority.**
4. Other eligible Goals continue making progress when an unrelated Goal is cancelled, blocked or has quarantined legacy intent.
5. History/proof records remain immutable; cancellation is never silently reversed; no arbitrary Goal/Task re-creation.
6. New code does not silently convert a bounded one-door profile into an unrestricted agent.

Note: the original B1 `save_verification_spec`-hook repro is now obsolete because production intentionally removed the separate call. **Adapt** the cut to the new single transaction and report exactly what changed. Do not claim the original ZIP's 29 tests passed unchanged unless they actually did.

## Highest-risk review paths

Read the diff OLD→NEW and surrounding code, not only tests:

- `anima/execution/store.py` — transaction and optional verification spec, legacy callers, FK/state invariants;
- `anima/core/door_execution.py` — operation readiness and proof recovery, immutable timestamps, terminal states;
- `anima/core/autonomy.py` — parked trigger DB, restart/scan order, pending queue priority window, conflict with completed or cancelled Task;
- `anima/internal_state/recovery.py`, `anima/internal_state/goals.py` — Stage2 idempotency and terminal lifecycle;
- `scripts/run_core_acceptance.py` and `tests/test_core_p4_report.py` — exact test provenance and git tree cleanliness;
- `tests/test_core_audit_blockers.py`, `tests/core_audit_crash_worker.py` and former P3-B/P4 tests — what each assertion really proves.

**Potential subtle issues to evaluate independently:** across-store partial commits and operator cancellation races; burden of scanning many parked records in `sync()`; repeated activation cycles; started scheduler attempt after terminally cancelled Task when Goal remains active; validity of assuming `proof.verified_at` is suitable for every Stage2 partial replay.

## What to return

Provide a **Russian report**, with:

- Executive verdict: `RELEASE_CANDIDATE_ACCEPTABLE` / `BLOCKED` / `INCONCLUSIVE`, and a one-paragraph rationale.
- B1, B2, B3, B4, T1, T2: **fixed / partly fixed / still broken / not checked**. Each includes code reference **at tested SHA**, an actual failing/passing reproduction or explicit execution limitation.
- New findings ranked `BLOCKER/HIGH/MEDIUM/LOW`, distinguish confirmed vs likely, repro steps expected vs observed, minimal corrective path.
- Exact checkout SHA/tree, environment, commands and independent test counts (don't reuse owner-local figures as Work's own).
- C0–C8 release implications: distinguish bounded verified scope from external infrastructure/LLM/real hardware not tested.
- Clear **freeze decision**: whether owner can consider signing off narrowly scoped Core v0.1, or precisely what remains blocked.

No GitHub modifications or PRs. Do not merge the branch or alter `docs/project.json`; owner alone makes the release decision after reviewing your report.
