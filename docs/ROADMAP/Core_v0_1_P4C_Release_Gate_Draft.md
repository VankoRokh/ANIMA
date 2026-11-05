# ANIMA Core v0.1 — P4-C Release Candidate Acceptance

**Статус:** **P4-C PASS по локальному полному прогону владельца** на точном SHA `aabe6553cec19d4cf1962dc4f26129eeca436328` (2026-11-05). **Core v0.1 Release Candidate; independent audit and explicit owner release sign-off pending.** Не считать Core Complete.  
**Дата:** 2026-11-05.  
**Предыдущий gate:** [P4-B — verified owner-local](Core_v0_1_P4B_Endurance_Recovery_Draft.md), exact tested commit `f6536f32c825897ef96168caa52ac45ece514b75`.  
**Acceptance baseline:** [P0 boundary & C0–C8 matrix](Core_v0_1_P0_Boundary_Draft.md); [P4-A integrated tests](Core_v0_1_P4_Integrated_Acceptance_Draft.md).

## 1. Evidence already established

Owner provided readable output of `scripts/run_core_acceptance.py --suite full` for exact `f6536f32c825897ef96168caa52ac45ece514b75`:

| Field | Owner-local result |
|---|---|
| Python | `3.14.4` |
| UTC | `2026-11-05T15:06:19.321542+00:00` |
| All tests | **1373 passed / 0 failed / 0 skipped** |
| Required P4 evidence | **12/12 PASS** (including P4-B restart `[2]` and `[4]`) |
| Sum of individual case durations | **22.620s** |
| Observed per-case p95 | **0.069s** |
| Full runner exit code | **0** |

This is an **owner-local result**, not independently executed by an assistant or CI. Owner supplied terminal output and a rendered excerpt of `summary.md`, not the underlying JSON/JUnit files. It validates **P4-B**, not this new P4-C branch. The exact `f6536f3` tested tree remains an immutable reference; the P4-C branch includes new tests and documentation, and requires a fresh run.

## 2. P4-C additional measured workload

New [`tests/test_core_p4c_release.py`](../../tests/test_core_p4c_release.py) adds a deterministic, parameterized system acceptance fixture that uses **the same production composition path** `build_core(..., auto_core=True)` with real temporary SQLite stores.

- Seeds **7**, **31**, **73**.
- **24 sequential one-shot Goal episodes per seed**, for **72 separately verified Goals and Tasks** across three isolated runs.
- Restart the same instance from disk **every five episodes**, plus one final cold reopen for reconciliation.
- Test-world state drawn from deterministic `random.Random(seed)`, alternating possibilities between an already-closed NOOP and an open→close authorized operation according to the seed.
- Up to three registered-but-invalid noise events per episode. A subset is redelivered under the same occurrence ID; Core must dedupe these without mutating Belief.
- At every episode: assert Goal=completed, Task=completed, one independent accepted evidence event per Goal, ground truth=closed only in the test operator, exact expected 0/1 operations, zero pending scheduler triggers. After restart: check instance ID unchanged, exactly one Stage6 operation ID per effect, all attempts finished and no pending work.
- Two additional **independent 8-episode runs** with seed 101 must produce identical aggregate results regardless of random Goal/Task UUIDs.
- Negative C0/C8 controls: idle Core without goals has zero world mutations; a registered source lacking property-level authority may still be admitted as a raw event but cannot insert a `known` Belief or satisfy a Goal.

**Important quantitative meaning:** this is **72 test episodes** and seeded restart/negative checks, **not 72 wall-clock hours or a long-lived background service**. Since only one `world.door.close@0.1` is registered, these tests do not establish reliability for other capabilities or general decision planning.

The seeds, episode count, restart cadence and zero-duplicate requirement are fixed **before** running the new branch.

## 3. Requirement matrix C0–C8

The matrix maps to **existing named checks** and additional P4-C cases. P4-C checks have **owner-local PASS evidence** on the pinned snapshot; independent audit and explicit release decision remain pending.

| ID | Required behavior | Strongest bounded evidence | Scope / unresolved gap |
|---|---|---|---|
| C0 | Boot/restart, idle, no LLM/GUI | P1 bootstrap, P3-C demo, P4-C idle and 72-episode cold reopens | No real power-cycle test |
| C1 | Open→action→independent verification; already closed→NOOP | `test_p3b_open_door_close_via_stage6_executor_and_independent_verifier`; `test_p3b_closed_door_completes_by_two_independent_sensor_reads_without_action`; P4-C seeded cases | One registered door/capability |
| C2 | Redelivery/out-of-order and identity conflicts | P2-A ingress, P2-B source revisions, P4-A late/dedupe, P4-C seeded replay | No distributed delivery reorder across writers |
| C3 | Missing/stale/conflicting/unavailable observations | P2-B conflicts, freshness, unavailable; P3-A `REQUEST_OBSERVATION`; P4-C unknown before input | No probabilistic sensor confidence |
| C4 | Changes between proposal and effect | P3-B pre-effect cancellation/recheck, P4-A false-world-change tests | No general-world compare-and-swap atomic precondition |
| C5 | Receipt != verified Goal success | P3-B false receipt + independent world readback; P4-A false success, P4-C readback per episode | Real external sensors not tested |
| C6 | Crash before/during/after effect, result/Goal/Task recovery | P3-B crash injection, P3-C restart, P4-B attempt reconciliation, P4-C cold restarts | No disk corruption or actual power removal |
| C7 | Irrelevant events, priority/budgets, no infinite loop | P3-C bounded scan/priority, P4-B multi-episode noise, P4-C up to three random noise events per episode | No multi-hour adversarial soak; no multi-process scheduler |
| C8 | Unregistered tool / forged source | P3-B denied tool, P4-A restart/denial, P4-C unauthorized registered source test | No network transport auth or untrusted LLM action pipeline |

**Gate interpretation:** C0–C8 have planned bounded checks, but this matrix is **not a 100% coverage claim** or proof that all possible negative/permutation cases exist. General unauthorized proposed tools, random prompt injection, alternative action arbitration and external authentication are out of this one-door release profile. Remaining gaps must be carried into P5+ or flagged as blockers if the scope is expanded.

## 4. Reporting and mandatory gate

Existing [`scripts/run_core_acceptance.py`](../../scripts/run_core_acceptance.py) now includes all P4-C tests in `--suite p4`, `--suite core`, `--suite full`.

The mandatory coverage manifest checks:
- all previously mandatory P4-A and P4-B cases;
- the **three** seeded 24-episode variants individually, not just the shared test name;
- same-seed replay of two 8-episode fixtures;
- idle no-goal and initial unknown Belief;
- unauthorized source false-success rejection.

If even one required case is missing, skipped, or failed, the acceptance runner returns `FAIL`. The saved `summary.json`, `summary.md`, `junit.xml`, `pytest.log` include exact tested HEAD, process exit and observed case durations. These files do **not** contain an automatic Core causal trace for all episodes; persistent SQLite Core journals remain the canonical mechanism.

## 5. Local commands

Switch to `work/core-v0-1-p4c-release-gate` only with clean worktree:

```bash
git status --short
git fetch origin
git switch --track -c work/core-v0-1-p4c-release-gate origin/work/core-v0-1-p4c-release-gate

git rev-parse HEAD
bash scripts/check.sh
```

First, the new acceptance fixtures:

```bash
.venv/bin/python -m pytest -q \
  tests/test_core_p4c_release.py \
  tests/test_core_p4_acceptance.py \
  tests/test_core_p4_report.py
```

Then full regression with a **human-readable** and machine-readable report:

```bash
report_dir="$(mktemp -d)"
.venv/bin/python scripts/run_core_acceptance.py \
  --suite full --output-dir "$report_dir"

sed -n '1,85p' "$report_dir/summary.md"
```

Keep the `report_dir` path and exact `git rev-parse HEAD` in the acceptance message. Do not commit each temporary JUnit/log or Core instance snapshot to GitHub.

## 5.1. P4-C actual local evidence (owner-supplied)

On 2026-11-05, owner supplied a human-readable excerpt of the `--suite full` acceptance report and the exact tested HEAD: `aabe6553cec19d4cf1962dc4f26129eeca436328` (not the prior P4-B commit). Report metadata: Python `3.14.4`, timestamp `2026-11-05T15:30:13.005526+00:00`, process exit code `0`.

- **1380 passed, 0 failed, 0 skipped** (full suite).
- Mandatory P4 evidence **19/19 PASS**, including seeds **7, 31, 73**, same-seed repetition, no-work idle, initial unknown Belief, unauthorized sensor negative case, and all P4-A/B controls.
- Sum of per-test durations **29.213 s**, observed per-test p95 **0.071 s**. These are **not** the complete process elapsed wall time or a platform-wide performance SLO.
- Tests and `scripts/check.sh` were reported successful by the owner. No independent assistant/CI execution; raw JUnit/JSON files were **not** supplied in this conversation.

P4-C test gate is accepted **for the pinned one-door Core profile**. This is not a declaration of immunity to disk corruption, real device failures, hostile IPC, multiple concurrent writers, autonomous self-created Goals, or LLM-derived actions.

**Independent review brief:** [Core v0.1 — Work Mini Audit](Core_v0_1_Work_Mini_Audit_Brief.md). The review must target the **immutable tested commit**, not later documentation-only changes.

## 6. Final release decision (not yet made)

After P4-C PASS, a separate owner-visible sign-off will decide whether to **freeze a narrowly scoped headless Core v0.1** with the following explicit properties:

- registered typed observation/Belief with freshness, revisions and evidence;
- externally provided `ensure_once` Goal; reusable TaskStore;
- bounded deterministic decision + approved one-door capability;
- world effect idempotency/recovery in the tested fixture;
- independent post-action verification before Goal completion;
- persisted Core event journal/outbox/Goal/Task/Execution and bounded scheduler;
- three test levels (unit/integration/system), recorded exact SHA, zero false-verified Goals and unauthorized world effects in tested cases.

**Not frozen as proven:** generic multi-capability planner; self-generated Goals; LLM/DEEP; Stage7 Knowledge lifecycle; continuous monitoring Goals; physical sensors; device control; concurrent writers; long wall-time soak; abrupt hardware power-loss safety; corruption recovery; operational SLOs; Virtual ANIMA Lab.

Only a **confirmed P4-C run**, explicit gap acknowledgement and owner sign-off can mark this scoped Core v0.1 RC as accepted. Do **not** update `docs/project.json` or merge the release branch automatically as a side effect of adding tests.
