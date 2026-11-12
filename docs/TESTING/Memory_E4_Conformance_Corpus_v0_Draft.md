# ANIMA — Memory E4 Conformance Corpus v0 (design draft)

**Status:** **FROZEN DESIGN BASELINE** — exact input and proposed gold bytes locked; semantic gold still provisional, E4 execution not verified.  
**Repository branch:** `experiment/core-memory-information-baseline`.  
**Date:** 2026-11-12.  
**Architecture:** [Memory E4 Architecture Contract (draft)](../ROADMAP/Memory_E4_Architecture_Contract_Draft.md).  
**Inputs:** [memory_e4_inputs_v0.json](Fixtures/memory_e4_inputs_v0.json).  
**Independent proposed gold:** [memory_e4_gold_v0.json](Fixtures/memory_e4_gold_v0.json).
**Gold audits:** [E4-A/B independent audit](Memory_E4_AB_Gold_Audit_v0.md) · [E4-C/D audit](Memory_E4_CD_Gold_Audit_v0.md) · [E4-U/R/P audit](Memory_E4_URP_Gold_Audit_v0.md).  
**Baseline:** [Memory E1 Results](../ROADMAP/Memory_Encoding_E1_Results.md); E2/E3 have separate validation gates.

## Purpose and non-goals

This corpus is a **design-time set of synthetic situations** to probe E4's Event → Episode → Story structure, Entity Resolution, uncertainty, investigation planning, time/condition-triggered scheduling, replay and authority. It does **not** assert that current Shadow/Core passes these cases. Existing Goal/Task statuses are not redefined; a scheduler/UncertaintyRegistry is not yet a production capability.

**Critical distinction:** the proposed gold describes **the safe permitted decision given source-visible evidence**, not hidden objective truth, a promise that the model can solve a semantic ambiguity, or a Knowledge commit. In an underdetermined case, `candidate_only`, `insufficient` or an unresolved question can be the correct behavior.

## Corpus composition

There are **42 independent root cases**, each executed with a fresh state. Case IDs and counts:

| Track | Count | Purpose |
| --- | ---: | --- |
| E4-A | 5 | Within-session episode boundaries, interleaving, distinct device, duplicate evidence |
| E4-B | 6 | Multi-day/multi-session Story continuity and explicitly uncertain chronology |
| E4-C | 6 | Context-specific aliases, RU/EN, mistaken identities and corrections |
| E4-D | 5 | Re-segmentation, revision, replay and stale-derived publication |
| E4-U | 6 | Unknown → policy decision → bounded investigation, refusal and scoped clarification |
| E4-R | 8 | Queue, time/condition triggers, periodic preflight, crash and checkpoints |
| E4-P | 6 | Authority, compute budget, user interruptions, LLM/SLEEP provenance |

**Data model:** `inputs.cases[*].events[*].raw` is an exact valid `Event.to_dict()` record (UUIDv4 ID, type, source, received timestamp, session, payload, Entity references). The wrapper `key` is a **test locator**, not part of an Event. `controls` are synthetic harness commands (e.g. `time.tick`, `execution.crash`, `user.available`), **not claims that these are already executable Core APIs**. `setup` establishes explicit test preconditions, not inferred truth. Each input case is isolated, and the global `entities` dictionary supplies a test entity registry. Fields `checks` and `forbidden` live **only** in the gold file.

The generated `Event.timestamp` is a deterministic simulation of **receipt time**. It must not be silently used as `observed_at` or world-valid time; when the case lacks normalized clock context, `unknown_world_order` is intentional. User statements are evidence that the user made a statement; even explicit correction or confirmation of a nickname does not prove a physical property of hardware.

## Gold semantics

`episode_pair`: `same` means belonging to one limited episode; `distinct` requires separate episodes; `insufficient` means no safe identity inference.

`story_pair`: `same_case_reported` means source-reported common case (not physical causality); `not_same_case` means case-scoped distinction; `insufficient` means no defensible required same-case relation; `candidate_only` is a non-authoritative possible link. `same_topic` is a separate broader grouping; legacy `linked_distinct_episodes`/`independent` labels must not be conflated with case identity. When present, `acceptable` lists alternative **safe** results scored independently of the algorithm.

`alias` requires exact source/context-scoped disposition: `known_reuse`, `confirmed_in_scope`, `unresolved`, `rejected`, `candidate_only` or `scope_limited`. User confirmation resolves *speaker intent in that scope*, not all world Claims.

`uncertainty`, `goal`, `task`, `schedule` and `investigation` labels describe **allowed system-side outcomes**, not new Task/Goal enums. For example `periodic_preflight` is due-tick evaluation **without** automatic expensive work, and `single_claim` requires one idempotent occurrence despite repeated ticks/restart. `replay`, `authority`, `publication`, `budget`, `revision`, `user`, `evidence`, `temporal` likewise assert their own specific invariant. Every case lists prohibited inferences in `forbidden`.

**A PASS for a check must be based on exact raw trace/provenance and allowed transitions.** Do not collapse `candidate_only` and `linked_distinct_episodes`, or `Task.completed` and `Uncertainty.resolved_in_scope`. Do not use one aggregate E4 accuracy number.


### Gold review update (2026-11-12)

The E4-A/B review applied **explicit episode scope** and **typed Story semantics** to the *proposed* gold. Story labels for reviewed cases now include `same_case_reported` (source-reported grouping), `not_same_case` (case-specific distinction) and `insufficient` (no required link); these are **not** claims of verified physical causation. `same_topic` is a separate optional relation, not a same-case Story. `E4-B02` accepts `candidate_only` **or** abstaining with `insufficient`; `acceptable` lists are evaluation constraints, not an instruction to the algorithm.

For E4-A04, an explicit Event provenance reference in the derived record replaces string-matching `reading_id` as the independence guard. A source reference is a test precondition with a distinct authority contract; it must not make derived content an independent witness. The original E4-A/B review gold was **unfrozen and owner-adjudication pending**, and no implementation was trained or scored against it.

### C/D and U/R/P adjudication corrections (2026-11-12)

All 42 root cases now include the audit-driven **proposed** fixture corrections. This is an editorial/contract repair, **not** a demonstration of E4 runtime conformance and **not** an owner-frozen gold.

- C/D: nickname clarification resolves speaker intent without forcing a Story edge; prior user-clarification Event for cached PSU alias; actual two supply Entity IDs; explicitly versioned dependent derived links before correction; typed sensor records with untrusted observed-time domains; derived snapshot source-revision mismatch at publication.
- U/R/P: Core-admitted Goal/Task preconditions where a runnable task is asserted; time/condition eligibility stays separate from Task enum; periodic `preflight` is not mandatory DEEP rerun or user interruption; a repeated occurrence is idempotent but a later occurrence is distinct. User refusal and uncertain identity remain acceptable outcomes.
- Gold `acceptable` is used only to permit multiple **bounded safe outputs**, not to mark an unsupported merge as correct. A generic `Goal` proposal never grants permission to execute a tool. Synthetic fixture IDs and `setup` are requirements for **future** E4 harness adapters, not existing production API claims.
- `references: [{kind:"event", id:...}]` is a source provenance pointer; **only an independently validated producer/source contract can assert the trust of that pointer**. Harness-provided `provenance_authority` is test setup, not a runtime guarantee.
- Time control `at` is a virtual harness control time. Raw `Event.timestamp` is receipt-time and cannot establish real-world ordering across unsynchronized clocks.

Open before semantic E4 conformance: executable reference harness semantics for `setup`/controls, owner adjudication of scoped/alternative gold, exact resource budgets, clock jump/restart recovery, and independent negative variants/holdout. Do not automatically convert this draft into a confirmed benchmark.

## Evaluation tracks and gates

1. **A/B/C — cognitive structure:** count pairwise false episode merges/splits, separate Story edge precision/recall on determinate pairs, and separately count unjustified automatic link/alias resolution; report unknown/abstentions and per-case raw decisions.
2. **D — repair:** check source hashes and derived version history before/after re-encode, with `no_raw_change`, `replay_no_duplicate`, `deny_stale_publication` guards.
3. **U — uncertain questions:** track duplicate uncertainty/Goal creation, correct scoped resolution, refusal compliance, method history and reason for stopping/rearming.
4. **R — scheduler:** event-/time-/condition-trigger activation, one claimed occurrence with replay safety, monotonic checkpoint, bounded preflight and next eligible time. No busy polling.
5. **P — resources and authority:** prohibited network/tool/user actions must never run; metrics for CPU, wall time, context/tokens, user interruption rate and starvation of foreground Goals.

**No scoring leakage:** only `inputs` is passed to the system under test. `gold` is read solely by an independent evaluator after outputs are frozen. A built-in test may validate structure, but passing that test is **not** cognitive conformance. No automatic tuning on this benchmark may be presented as generalization.

## Paired perturbations for v1 (not yet generated)

For selected root cases: punctuation/case changes; EN/RU paraphrases with independent adjudication; duplicate/late Event delivery; identical wordings with distinct Entity IDs; reordered noncausal arrivals; partial Event coverage and budget exhaustion; different source/capability authority; restart at pre/post-claim and publication boundary; resource pressure and multiple competing Goals.

Freeze these **before** comparing candidate algorithms, not after studying failures. Reserve a separately created holdout set for architecture changes. A model-generated paraphrase must be reviewed, not silently copied into the gold labels.

## Current acceptance boundaries

- **Prepared:** 42 root scenario specifications, separated input/gold, static contract validation, explicit underdetermination, refusal, periodic recheck without new Event, no duplicate outcome.
- **Not done:** owner adjudication of every gold root, independent semantic annotation, executable E4 Core adapters, reference schedules/clock model, measured throughput, Raspberry Pi experiments, crash injection, actual Stage 7 model behavior, hidden holdout.
- **Production:** untouched. E1/E2/E3 status and Core Goal/Task permissions do not change.

## Frozen design baseline / read-only observation

- [E4 v0 Freeze Record](Memory_E4_v0_Freeze_Record.md)
- [E4 v0 Runner Contract — L0 Shadow only](Memory_E4_Runner_Contract_v0.md)
- [Frozen content-addressed manifest](Fixtures/memory_e4_frozen_manifest_v0.json)

The `v0` event and oracle JSON files are pinned by exact blob hash. Alternative labels remain bounded and gold remains provisional. L0 observations **cannot** satisfy Story, Goal/Task, SLEEP or recovery checks; unsupported actions are reported, never simulated.

## Pre-freeze technical candidate and development negatives

The [four bounded gold alternatives](Memory_E4_Gold_Adjudication_v0.md), [visible 15-case adversarial suite](Memory_E4_Negative_Variants_v0_Draft.md) and [superseded predecessor candidate manifest](Fixtures/memory_e4_freeze_candidate_manifest_v0.json) remain accessible. The current [frozen design manifest](Fixtures/memory_e4_frozen_manifest_v0.json) fixes source bytes, not conformance or independent gold validation.

## Owner-review questions before freeze

1. Is `Story` an organizational relation with strict separate-episode provenance as described?
2. Should a **known** explicit ticket/case identifier permit a Story link across sessions without extra model reasoning? (proposed yes, provided source scope and identity check)
3. Is `candidate_only` the expected safe response to unproven recurring trouble on the same hardware? (proposed yes)
4. Does user confirmation of a nickname resolve only the intended referent, not physical truth? (proposed yes)
5. May an important unanswered question retain a periodic **cheap** check even without new evidence, while expensive repeated analysis remains gated? (proposed yes)

The exact fixture bytes are now locked under the [freeze record](Memory_E4_v0_Freeze_Record.md). This is a reproducibility freeze, not independent gold adjudication or E4 conformance. Do not infer semantic success from green CI.
