# ANIMA Core v0.1 — Independent Audit Remediation (B1–B4, T1–T2)

**Status:** **IMPLEMENTED / UNVERIFIED** — changes are present in `work/core-v0-1-audit-fixes`; neither local acceptance nor independent re-review has been performed on this branch. **Core v0.1 remains BLOCKED; do not freeze/merge or update project.json automatically.**  
**Date:** 2026-11-05.  
**Base:** independent-audited snapshot `aabe6553cec19d4cf1962dc4f26129eeca436328`.  
**Original independent result:** 1380/1380 stock PASS; 29 additional probes = 20 PASS / 9 FAIL; four confirmed runtime bugs B1–B4, one release-gate deficiency T1, and two tests expressing stronger than promised scheduler behavior. Full original audit and reproducible ZIP evidence were provided by the owner. Do not count stock PASS as proof that B1–B4 are repaired.

## 1. Remediation changes

| ID | Changed component | Fix and safety policy | Blocking regression |
|---|---|---|---|
| **B1** | `anima/execution/store.py`, `anima/core/door_execution.py` | Core passes the exact typed VerificationSpec into `ExecutionStore.create_operation(..., verification_spec=...)`; operation + action + spec are now inserted in **one Stage6 SQLite transaction**. Mid-transaction exception/real `os._exit(73)` must leave **no partial operation**. Old split-commit `prepared` rows missing spec are **not reconstructed** from current instructions: return `DEFERRED/INCOMPLETE_EXECUTION_INTENT` for that one Goal; other Goals may continue. Operator repair needed for quarantined legacy records. | `test_core_audit_b1_atomic_prepare_failure_rolls_back_all_rows`; `test_core_audit_b1_os_exit_inside_atomic_prepare_recovers`; `test_core_audit_b1_legacy_missing_spec_is_local_and_next_goal_progresses` |
| **B2** | `anima/core/door_execution.py`, `anima/core/autonomy.py` | Historical proof remains immutable, but if Goal is cancelled/blocked or Task is cancelled/failed, proof recovery neither transitions it to `completed` nor blocks all other Goals. `started` scheduler attempt cannot be recorded as verified when its Task is terminally cancelled. | `test_core_audit_b2_cancel_after_proof_does_not_poison_other_goals[goal/task]` |
| **B3** | `anima/core/door_execution.py` | Stage2 `GoalObservation` always reuses the original durable `core_world_proofs.verified_at` as timestamp. On same-runtime retry, Stage2 `RecoveryCoordinator.recover_pending()` completes partial source operations before any new `observe_goal` call. No new source ID, Goal or Task. | `test_core_audit_b3_same_runtime_retry_uses_identical_stage2_request` |
| **B4** | `anima/core/autonomy.py` | A `blocked` Goal is temporarily unavailable: its original `goal:` trigger is **parked pending** rather than marked `done` in `_next_attempt`. After `blocked→active` a rebind/wake/cold-restart can resume the **same** task identity. Existing finished attempts still require new external evidence to retry, per previously documented bounded contract. | `test_core_audit_b4_blocked_to_active_resumes_parked_goal` |
| **T1** | `scripts/run_core_acceptance.py` | Mandatory test identity now requires **exact JUnit module/classname + test name + parameter ID**. Fake passing tests in another module cannot satisfy required coverage. | `test_core_audit_t1_mandatory_test_identity_includes_module`; `test_core_audit_manifest_rejects_same_names_from_unrelated_module` |
| **T2** | `scripts/run_core_acceptance.py` | Capture HEAD, Git tree, clean porcelain status **before and after** tests. If missing, dirty or changed, acceptance verdict must be `FAIL`; recorded metadata remains available for diagnosis. | `test_core_audit_release_report_rejects_dirty_or_changing_checkout` |

These changes do **not** grant new tools, additional sources, continuous scheduling, unrelated Goal completion, LLM model authority or real-world device control. Stage6 legacy callers may still omit VerificationSpec under their existing contract; **P3-B Core never does**.

## 2. Distinguish modified behavior from older audit probes

The original Work ZIP contains a `crash_worker.py` that intercepts `save_verification_spec` **after** `create_operation` had already committed. Core no longer performs those two separate calls. That old hook therefore cannot be reused unmodified as a mid-commit test: **its former failure point no longer exists**. Instead `tests/core_audit_crash_worker.py` injects a hard process exit after the Stage6 operation/action INSERTs **before** the spec INSERT/commit, inside the actual transaction. A separate regression deliberately emulates the old partial data and asserts local fail-closed behavior.

Do **not** claim that the original 29 audit probes all pass unchanged. Only execute their still applicable cases (or explicitly adapt the obsolete B1 hook) and report which were adapted.

Original Work findings still tracked as **not current release blockers in scoped one-door profile**:
- R1: history scan/JSONL replay work is not globally time-bounded;
- R2: no atomic world CAS or independent physical observer;
- T4: priority window of 64 pending triggers and finished NOOP race awaiting new external evidence;
- T5: sequential seeded workload is not a multi-hour wall-clock soak, demo proof strength is limited.

If wider autonomous behavior is claimed later, reevaluate these limitations as hard gates.

## 3. Required verification

From clean checkout on `work/core-v0-1-audit-fixes`:

```bash
git rev-parse HEAD
git status --short
bash scripts/check.sh

.venv/bin/python -m pytest -q \
  tests/test_core_audit_blockers.py \
  tests/test_core_p4_report.py \
  tests/test_core_p3b_execution.py \
  tests/test_core_p3c_autonomy.py \
  tests/test_core_p4_acceptance.py \
  tests/test_core_p4c_release.py

report_dir="$(mktemp -d)"
.venv/bin/python scripts/run_core_acceptance.py \
  --suite full --output-dir "$report_dir"

sed -n '1,100p' "$report_dir/summary.md"
git rev-parse HEAD
git status --short
```

**Gate:** all new B1–B4 and T1–T2 regressions PASS, old P1–P4 PASS, mandatory matrix complete, clean/unchanged HEAD/tree and test count/trace captured. Do not expect exact baseline 1380 because new tests were added. No production release claim until new SHA is accepted and preferably an independent Work spot re-review of repaired boundaries has completed.

## 4. Remaining sign-off

If the local gate passes, check *especially*:

1. Has any source of observed Goal success been substituted for actual independent World observation? **Must remain NO.**
2. Do hard process cuts and historical partial operation records fail closed without blocking other Goals? **Must be YES.**
3. Does cancelled Goal/Task retain terminal authority even when a verified proof exists? **Must be YES.**
4. Does same-Runtime Stage2 replay preserve request identity? **Must be YES.**
5. Does `blocked→active` resume parked work with no duplicate Stage6 operation? **Must be YES.**

Only then make a separate owner decision on freezing the narrowly scoped Core v0.1 Release Candidate.
