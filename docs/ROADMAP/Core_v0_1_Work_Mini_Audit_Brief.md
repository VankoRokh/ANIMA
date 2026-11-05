# ANIMA Core v0.1 — Independent Work Mini Audit

**Статус:** independent review requested; **PENDING REVIEW**. Не production change, не разрешение на release/merge.  
**Дата:** 2026-11-05.  
**Immutable subject:** `VankoRokh/ANIMA`, Git commit **`aabe6553cec19d4cf1962dc4f26129eeca436328`** on `work/core-v0-1-p4c-release-gate`.  
**This brief:** `work/core-v0-1-independent-review` (docs-only derivative; do not accidentally audit its HEAD as the proven runtime snapshot).  
**Baseline evidence:** owner-local `full` pytest **1380 pass, 0 fail, 0 skip**, mandatory P4 **19/19 pass**, Python 3.14.4, 2026-11-05T15:30:13Z. Numbers are *user-reported*, not independent CI.

## Task / requested role

Act as **independent adversarial reviewer** of the narrowly scoped executable headless ANIMA Core v0.1. Do **not** assume green tests prove absence of logic bugs. Inspect primary source code and targeted tests at the pinned SHA. If feasible in the Work environment, run the already-defined checks on a disposable checkout and write *new targeted repro tests only in an isolated scratch workspace*. **Do not edit the GitHub repository, commit, open PRs, or merge**, unless later separately authorized.

Target question: **Is the current one-door, externally supplied `ensure_once` Goal → typed observation/Belief → bounded decision → approved action → independent verification → recovery profile safe and consistent enough to freeze as a narrowly scoped Core v0.1 baseline?**

The answer must separate:
1. **Confirmed bug** (reproducible violation of an invariant);
2. **Credible untested risk** (specific code path, but not reproduced);
3. **Documented out-of-scope limitation** (not itself a blocker for one-door profile);
4. **Test coverage deficiency** (a check that does not establish its claimed invariant).

No ungrounded claims about general intelligence, broad autonomy, real hardware safety, or reliable power-loss recovery.

## Focused review surface

| Boundary | Code / docs | What must remain true |
|---|---|---|
| Runtime / Core assembly | `anima/core/assembly.py`, `anima/runtime.py` | Opt-in autonomy only; default CLI unchanged; source/tool registries trusted; no hidden wake/action |
| Event ingress & outbox | `anima/core/ingress.py`, `anima/core/dispatch.py`, `anima/memory/event_log.py`, `anima/memory/event_processing.py` | Atomic accepted observation/Belief; duplicate/collision rejection; restart without duplicate legacy effects; receipt meaning |
| Belief | `anima/core/belief.py` | Provenance, authority, source revision, observed-time versus arrival-time, unknown/stale/disputed, no arbitrary last-write-wins |
| Goal → decision | `anima/core/goal_decision.py`, Stage2 `GoalStore` / `GoalProgressEngine`, Stage6 `TaskStore` | Typed ensure-once criterion not parsed from prose; bounded scheduling; terminal/cancelled Goal cannot silently act; stable Task ID |
| Tool / independent verifier | `anima/core/door_execution.py`, `anima/core/door_world.py`, Stage6 `ExecutionStore`, `SandboxExecutor` | Policy cannot be bypassed; receipt ≠ verified success; independent readback; exactly one keyed effect in supported fixture; lost receipt, uncertain/retry recovery |
| Scheduler / restart | `anima/core/autonomy.py` | Durable triggers/attempts, no feedback loop from internal sensor, bounded work/priority, no missing critical triggers; no fabricated evidence after crash |
| Evidence / release | `tests/test_core_p*.py`, `scripts/run_core_acceptance.py`, P0 C0–C8 and P4-C docs | Fail-closed test gating; tests really check intended invariant and not only mocks; output tied to exact SHA; honest scope |

**Especially inspect:** completion after crash across independent SQLite files; the `prepared/executing/uncertain/succeeded` operation statuses; lost scheduler attempt-result commit; source spoofing and trusted adapter boundary; changing the world between last observation and effect; starvation when pending queue contains many irrelevant/old triggers; exception propagation and re-entry around `Runtime.wake`/`run_core_autonomous`; assumptions about sensor independence when handler/observer share the same virtual-world store.

## Suggested concrete adversarial probes

Pick high-impact probes, not a broad rewrite:
- Inject exception at each meaningful commit boundary (Core event, JSONL projection, Stage6 prepared/executing, World effect, receipt, verification proof, Goal, Task, scheduler attempt finish); cold-reopen, count world effects, check no phantom verified Goal.
- Try unauthorized source, source-ref collision, malformed/late/disputed/unknown observations, duplicate occurrence with changed payload, zero/invalid or stale logical tick; verify fail-closed.
- Cancel Goal or interrupt Task between decision, last policy check and executor invocation; check observed outcome and whether an effect occurred.
- Saturate the pending trigger scan with **more than its internal scan limit** and a later high-priority Goal; determine whether prioritization makes progress or can starve. Distinguish known scheduler boundedness from fairness guarantee.
- Test a failed verification followed by external world changes and restart; ensure a `succeeded` operation is never blindly performed again and no unproven success is asserted.
- Check for a test that unintentionally uses privileged `world.current()` to decide Core success or for a reporter that mistakes test PASS for Core event evidence.

When a test fails, give a **minimal reproduction** (file, failing input/sequence, expected vs actual). Do not silently patch production code.

## Deliverable — short independent report

**Executive verdict:** `RELEASE_CANDIDATE_ACCEPTABLE` / `BLOCKED` / `INCONCLUSIVE`, with one paragraph of rationale.

**Findings table:** severity `BLOCKER/HIGH/MEDIUM/LOW`, confidence `confirmed/likely/unverified`, file+line/SHA, violated invariant, exact reproduction or why it is not yet demonstrable, minimum fix/test. Order by severity. Empty findings table is fine; do not invent defects.

**Coverage map:** C0–C8 summarized `verified in examined scope / partially verified / not verified`, with evidence test names and gaps.

**Reproduction note:** whether Work actually checked out pinned code, exact tools/commands and tests executed, results and environment; distinguish code-reading from execution. If tests cannot run, explicitly say so.

**Decision gate:** state whether the narrowly scoped Core v0.1 may be frozen **now**, or what concrete changes/tests are necessary. Note known out-of-scope limits: one-door tool, registered sources, single-process SQLite, no LLM-generated actions, no physical devices/power-loss/corruption, no continuous autonomous daemon.

**No repository modifications.** Return the audit to the user for discussion; the release decision belongs to the owner after review.
