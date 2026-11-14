# ANIMA v0.1 — release gap audit (working record)

**Status:** release engineering IN PROGRESS, not an ANIMA v0.1 PASS.  
**Branch:** `work/anima-v0-1-release` (draft PR #5, based on experimental M6-B2 branch).  
**Scope:** source/contract review and evidence mapping; no independent full security/code audit claimed.  
**Release definition:** [ANIMA v0.1 Release Contract](ANIMA_v0_1_Release_Contract.md).

## Evidence separation

Official Stage 6 has an earlier accepted result ([TV-0051](../TESTING/Results/TV-0051.md)). Core v0.1 PC/Pi T6–T9.7 results are recorded in [TV-0054](../TESTING/Results/TV-0054.md), with a *dirty* checkout and limited hardware claims. Integrated M0–M6-B2 are separate laboratory checks, not production release certification. The current release branch inherits research/lab files; **the release entry point imports none of the Godot/E4/M6 laboratory modules**.

The first release runtime is `anima/release_v01.py`. It invokes existing `build_core()` with production Memory and opt-in Event Retrieval; the regular local profile registers **no trusted external sensor sources or tool handlers**. An isolated, explicitly pinned `--sandbox-door` profile connects existing P3-C/VirtualDoorWorld for deterministic execution acceptance only.

## Gate status / release blockers

| Gate | Checked on the new release path? | Remaining boundary |
| --- | --- | --- |
| R-01 Boot | First 4 subprocess tests PASS on CI Python 3.12/3.13/3.14 | Final clean head + notebook acceptance |
| R-02 Multiple reports | Tested with one persistent process; Event/Memory links checked after restart | Final integrated gate |
| R-03 Raw retrieval | Search and ContextBuilder work in the new headless path | Stronger retrieval-quality corpus belongs to future Memory work |
| R-04 Fresh-process reopen | Explicit two-process release test passed | Final integrated gate |
| R-05 Untrusted input | Unsupported source/tool operations fail closed; no actuator in normal profile | No authenticated operator or malicious-local-code firewall claimed |
| R-06 Goal/Task/verification | Explicit sandbox mode tested; one keyed action + completed Goal/Task | Not generalized to arbitrary real-world effect adapters |
| R-07 SIGKILL | Release process-kill after acknowledged report tested | More diverse cuts and real power loss not automatically covered |
| R-08 Resources | Notebook-sized gate runner now exists and reports p50/p95/p99, RSS and disk | Need measured result and chosen release budget; no hardware Pi gate |
| R-09 Regression | CI full Python 3.12/3.13/3.14 regression PASS on earlier release slice (`43606870693`) | Re-run on exact candidate head including acceptance runner |
| R-10 Release | Draft PR, version remains alpha, no release tag | Final clean SHA, owner laptop run, concise limitations, release notes |

## Source-reviewed hazards and decisions

1. `main.py` / `scripts/run.sh` still launch the older one-input CLI by default. **The release profile uses an explicit new entry point**; replacing default CLI is deferred until evidence and documentation are accepted.
2. Memory's legacy composition can hide raw detail. The release profile uses derived, rebuildable Event Retrieval; `context` does not assert factual truth, and incomplete index cannot masquerade as no-match.
3. `CoreAutonomy` and Goal/Task integration are optional capabilities with strict registration; the base profile does not accept untrusted typed sensor packets or automatically convert reports to goals.
4. The persistent `release_profile.json` pins the capability set. Existing unlabelled data directories and mismatched capabilities are refused, rather than silently reinterpreting old Beliefs/Goal bindings.
5. `fcntl.flock` enforces cooperative single-writer execution for the release entry point on Linux. A malicious local process or direct database writer remains outside the security boundary.
6. The release branch is a **candidate on top of a draft laboratory branch**. Before the final tag, review ancestry and which experimental files should remain development-only; do not merge all experiment PRs just to reach a green test.

## Out of scope for v0.1

Full Stage 7 Knowledge lifecycle, LLM/FAST/DEEP training and model-quality claims, extended SLEEP consolidation, meta-memory, cameras/microphones/speakers, Godot dependence, Raspberry Pi transfer, external network authentication, arbitrary autonomous goals and physical expansion. Later releases stay conceptual.

## Next controlled actions

Complete the current release CI matrix and snapshot audit, inspect measured notebook workload, then run the exact candidate on the owner's Ubuntu laptop in a **fresh** data directory. Fix only confirmed release blockers. After an accepted v0.1 gate, create the release record/tag and restructure documentation navigation so that actual runtime, current release requirements, research, archived experiments and future concepts are distinct. Historical TV results remain immutable.
