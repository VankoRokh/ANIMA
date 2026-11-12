# ANIMA — E4 Runner Contract v0

**Status:** L0 executable observation + design contract for future L1–L3; **not** a fully implemented E4 runner.  
**Frozen fixtures:** [E4 Freeze Record](Memory_E4_v0_Freeze_Record.md).  
**L0 code:** [`labs/exp009/e4_l0_observation.py`](../../labs/exp009/e4_l0_observation.py).

## Purpose

Separate source replay, actual adapter behavior, independent scoring, and future Core scheduling. Prevent tests from passing through fixture expectations being used to generate `decisions`. **Gold is never passed into or read by the runner/adapter.** An evaluator may read gold *after* a trace artifact has been closed/frozen. No synthetic precondition, predicted answer, or mock action may be reported as actual Core capability.

## Capability levels

| Layer | Input | Output | Status and restrictions |
| --- | --- | --- | --- |
| **L0** | Frozen Event input + Entity registry; per-case isolated temporary MemoryStore | Existing `ShadowEpisodeEncoder` raw decisions, source IDs, reasons, episodes; unsupported-control list | **Implemented** read-only baseline. Validates and observes, **does not grade** E4 and does not execute control events or simulate user/Goal/SLEEP. |
| **L1** | Same frozen Events, explicit Episode/Story/Entity decision adapter | Typed per-event association proposals, provenance refs and abstentions | **Not implemented**. Never publish Knowledge and never treat candidate as verified. |
| **L2** | Explicit `setup`, admitted Goal/Task/authority, virtual clock and control stream | Decision trace and side-effect ledger for uncertainty, queuing, due/condition review | **Not implemented**. Must not synthesize passing Task outcomes. |
| **L3** | Crash/restart/checkpoints, persistency and source version changes | Durable recovery ledger, exact event+operation identities, recovery outcomes | **Not implemented**. Require injection around before/after effect and publication. |
| **EVAL** | Closed raw trace + frozen gold | Per-check results with `PASS`/`FAIL`/`NOT_SUPPORTED`/`NOT_OBSERVED` and explanations | **Not implemented**. `NOT_SUPPORTED` never counts as PASS. |

## Deterministic L0 behavior

Use `python -m labs.exp009.e4_l0_observation --case E4-A03 --output /tmp/e4-a03.json` from repo root. Choose `--suite positive|negative`, or run all cases without `--case`. Output file must not already exist. Output contains no gold labels.

For every case the runner:

1. Confirms frozen input SHA-1 and exact file length against the immutable [manifest](Fixtures/memory_e4_frozen_manifest_v0.json).
2. Registers only the fixture Entity IDs in a **temporary local SQLite** MemoryStore used for validation. This temporary setup is not the user's production Memory.
3. Reconstructs each `Event` from its raw record (retaining Event ID/source/timestamp) and invokes the *existing* `ShadowEpisodeEncoder`. This legacy encoder intentionally skips non-`conversation.user` sources.
4. Returns `decision`, `source_event_ids`, `possible_related`, `reasons`, `event_assignments` and final shadow `episodes`, plus `ignored_setup_keys` and `unsupported_controls`.
5. Checks that the temporary MemoryStore contains no new Memories; cleans the sandbox on exit.

L0 **does not ingest actual Core Goal/Task**, does not run SLEEP, and does not assert that a `ShadowEpisodeEncoder` decision satisfies any E4 Story/Entity/Uncertainty gold. No L0 result can be counted toward E4 semantic conformance.

## Future harness ordering and source/authority rules

- The `events` list is delivered in listed input order. `Event.timestamp` is reported receipt timestamp; it is not a trusted observation timestamp.
- `controls` are virtual-harness events and must be strictly ordered by their virtual activation clock. Same-timestamp events/control collisions require a separately specified deterministic tie-break rule. **No L0 control executes.**
- If the runtime is crashed, event delivery during downtime must be explicitly queued/rejected in the future harness: do not invent silent delivery.
- Input Entity references are source observations, not automatically true identities. User reports are scoped claims of intent; model suggestions remain unverified.
- `Goal/Task` fixture preconditions must be validated against the existing Core contract before an action is *admitted*. `waiting_condition`/`scheduled` are scheduler concepts, not production Task enum values.
- Persist `occurrence_key` and effect ledger; a periodic new occurrence is a new attempt, not independent evidence; due review does not mean permission for an expensive method.

## Trace envelope for L1–L3 (future, not executable yet)

```text
case_id, adapter_name, adapter_commit, fixture_blob_sha
source_event_ids, received_at, observed_at{value, clock_domain, trusted}
decision{kind, status, scope, reason_codes, candidate_refs, evidence_refs}
uncertainty{question_id, epistemic_state, source_versions}
goal_task{goal_id, task_id, lifecycle_state, authority_refs}
investigation{attempt_id, method, budget_used, result, failure_reason}
schedule{occurrence_key, next_eligible_at, trigger, eligibility_reason}
effect{operation_id, ledger_state, verification_refs}
recovery{restart_epoch, checkpoint_revision, duplicate_guard}
unsupported{capability, reason}
```

Separate `NOT_SUPPORTED` (system cannot execute contract), `NOT_OBSERVED` (trace lacks evidence), `FAIL` (violated observable contract), and `PASS`. Store raw decisions and observations **before** opening gold. Report `no_match`, `partial`, `source_unavailable`, `ambiguous`, `budget_exhausted` distinctly when relevant.

## Next implementation gates

1. Specify a **read-only adapter protocol** for Story/Episode/Entity outputs with explicit support matrix; no production migrations.
2. Define harness control semantics / tie-breaking / virtual clock and source authorization, then write tests that would FAIL if the runner silently simulates a currently unsupported Core capability.
3. Build external scorer that loads only frozen gold and sealed raw trace, records per-case decisions and a separate coverage denominator.
4. Run original 42 + visible 15 development negatives with equal budgets; do not call this a blinded holdout or claim E4 PASS from CI alone.
