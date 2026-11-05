# ANIMA Core v0.1 — P4-A Integrated Acceptance & Readable Diagnostics

**Status:** implementation + scenario tests in isolated branch, **UNVERIFIED** until owner-local evidence. This is **P4-A**, not a declaration of full P4/Core v0.1 Complete.  
**Date:** 2026-11-05.  
**Branch:** `work/core-v0-1-p4-acceptance`.  
**Upstream:** [P3-C event loop](Core_v0_1_P3C_Autonomous_Loop_Draft.md), [P0 system acceptance contracts](Core_v0_1_P0_Boundary_Draft.md), [Core/VAL roadmap](Core_v0_1_VAL_v0_1_Plan_Draft.md).

## 1. Owner feedback and agreed reporting direction

Owner reports all P3-C tests passed and supplies two real local JSONL demo outputs:

| Scenario | Decision | Execution | Verification | Final |
|---|---|---|---|---|
| Initial door `open` | two `PROPOSE_ACTION` decisions | one `keyed` operation, `succeeded` | `VERIFIED_SUCCESS / GOAL_SATISFIED` | Goal/Task `completed`, Belief `closed`, operator ground truth `closed`, pending 0 |
| Initial door `closed` | `NOOP` | **zero** operations | `VERIFIED_SUCCESS / NO_EFFECT_REQUIRED` | same completion, zero effect, pending 0 |

These exact observations are **user-reported**, not CI, not synthetic fixtures, and not independent execution by the assistant. The user did not provide a numeric pytest summary or exact local commit. Owner specifically requested future demonstration results be **human-readable**.

**Decision:** machine-readable causal evidence remains available; the default display prioritizes legibility. Reporting is a view over persisted data, **never** a new authority for Goal or Belief state.

## 2. Readable P3-C demo (backwards-compatible opt-in JSON)

New [`anima/core/demo_report.py`](../../anima/core/demo_report.py) turns the same trace records into a Russian terminal timeline and a Markdown report. Updated [`anima/core/demo_p3c.py`](../../anima/core/demo_p3c.py):

- `--format text` (default) produces a concise Russian report, chronological decisions, tool/verification outcomes, Goal/Task/Belief state, pending triggers and **PASS/FAIL checks**. Return code is nonzero for a failing acceptance assertion.
- `--format json` reproduces the previous **JSONL stage records** for consumers and existing tests.
- `--report-md <path>` writes a portable Markdown report **only if the path does not already exist**.
- `--snapshot "$(git rev-parse HEAD)"` optionally places the exact Git commit in the Markdown report.
- Privileged `operator_ground_truth` remains marked as operator-only; it is never passed to ANIMA Core's decision logic. The report counts **Execution ledger operations**, not a scientifically measured number of physical effects.

Example (always a new empty/absent demonstration instance directory):

```bash
demo_dir="$(mktemp -d)"
.venv/bin/python -m anima.core.demo_p3c \
  --data-dir "$demo_dir" \
  --initial-state open \
  --report-md "$demo_dir-report.md" \
  --snapshot "$(git rev-parse HEAD)"
```

Machine-mode option:

```bash
demo_json="$(mktemp -d)"
.venv/bin/python -m anima.core.demo_p3c \
  --data-dir "$demo_json" --initial-state closed --format json
```

**Security / scope:** demo refuses nonempty input data directories and overwriting existing Markdown reports. This is still a **one-door** demonstration, not the full P4 acceptance gate.

## 3. First P4-A multi-event integration scenarios

New [`tests/test_core_p4_acceptance.py`](../../tests/test_core_p4_acceptance.py) adds separate end-to-end tests that exercise all **composed** production components and real isolated temporary SQLite/JSONL stores, not just isolated fake connectors.

| Family | Scenario | Blocking property |
|---|---|---|
| T0/T4 | two active Goals with priorities, bounded step budget, third one-shot Goal after restart | ordered selection + stable identity + no redundant effect |
| T2/T4 | redelivered observation, rejected noise, older observation before Goal | dedupe, provenance, history-only and no effect before Goal |
| T1/T3 | successful executor receipt but world changed back; external observation later completes Goal | no false-positive verification, no repeat action |
| T3 | crash after world effect but before receipt; restart | reconcile, one keyed world effect, Goal/Task complete |
| T3 / Policy | unregistered action tool with active Goal, restart | zero unauthorized side effects |
| T3 | verified Goal persisted, Task completion interrupted; restart | complete missing transition without replay |
| T4 | 130 irrelevant reports and bounded journal cursor scanning | no feedback loop and no redundant world effect |

Previously accepted P2/P3 suites continue to verify original atomic ingest, stale/conflicting Belief, crash after append/projection, operation binding, independent verifier, receipt uncertainty and NOOP paths. **The first P4-A suite is intentionally narrower than full P4:** remaining work includes multi-hour soak, failpoint coverage accounting, formal no-progress budgets under adversarial event streams, and recorded performance baselines.

**Priority fix:** P3-C `CoreAutonomy._next_attempt` now chooses by Stage2 Goal priority **across** pending triggers rather than arbitrarily preferring the oldest Goal-specific trigger; added integrated test creates a low-priority Goal first and requires the higher-priority Goal to run first. This change is a proposed correction and requires local test confirmation; previous P3-C PASS does not validate it automatically.

## 4. Unified acceptance launcher

New [`scripts/run_core_acceptance.py`](../../scripts/run_core_acceptance.py) runs selected `pytest` suites synchronously, capturing:

- `junit.xml` — machine-readable per-test status/duration;
- `summary.json` — versioned machine summary, exact `git rev-parse HEAD`, Python version, timestamps;
- `summary.md` — readable case-by-case Markdown report, failures with short diagnostics;
- `pytest.log` — complete terminal output.

**These are test-runner reports**, not replacements for Core causal event/Belief/action records. For causal timeline use `demo_p3c --format json` or the persisted Core journals. The launcher returns a nonzero exit status when the selected suite fails or produces no tests.

Three supported suites:

- `--suite p4`: newly introduced P4-A and reporter checks;
- `--suite core`: P4-A plus P3-C/B/A, P2-C/B/A and P1 regression modules;
- `--suite full`: all repository tests.

Example:

```bash
report_dir="$(mktemp -d)"
.venv/bin/python scripts/run_core_acceptance.py \
  --suite core --output-dir "$report_dir"
```

Reports are written **only to an explicitly provided empty/new directory**. Existing nonempty directories are rejected to avoid overwriting previous evidence. The project `./data` directory is not touched by these isolated pytest scenarios.

## 5. Required tests and acceptance gate

From a clean local checkout of the P4 branch:

```bash
git rev-parse HEAD
bash scripts/check.sh

.venv/bin/python -m pytest -q \
  tests/test_core_p4_acceptance.py \
  tests/test_core_p4_report.py \
  tests/test_core_p3c_demo.py \
  tests/test_core_p3c_autonomy.py \
  tests/test_core_p3b_execution.py \
  tests/test_core_p3a_goal_decision.py \
  tests/test_core_p2c_runtime.py \
  tests/test_core_p2b_belief.py \
  tests/test_core_p2a_ingress.py \
  tests/test_core_p1_bootstrap.py

.venv/bin/python -m pytest -q
```

Then optionally generate one **separate** readable regression report with the acceptance runner. A green script/report does not replace the full regression run unless `--suite full` was executed.

**P4-A PASS gate:** `scripts/check.sh`, new P4 tests, exact committed HEAD, targeted Core modules and full pytest reported green by owner. No claim is made about these results before they are supplied.

## 6. Remaining Core v0.1 release gate

This is the **first P4 integrated slice**, not the final sign-off. Before marking the Core v0.1 baseline Complete:

1. Execute and retain representative T0–T4 scenarios across perturbed event order, unknown/stale/disputed, failures at durability boundaries and repeated cold restarts.
2. Verify zero unauthorized world effects and zero false-positive Goal completions in the measured fixture set, with trace evidence.
3. Verify no unbounded retry/feedback at configured budgets, and quantify any remaining starvation and throughput constraints.
4. Retain a representative owner-reproducible result in the established documentation/reporting system; transient logs in isolated output directories, not committed indiscriminately.
5. Record explicit out-of-scope limits: real power-loss/corrupted disk, multi-writer concurrency, external authentication, general-world actions, LLM, continuous maintain-goals, and graphical lab.
