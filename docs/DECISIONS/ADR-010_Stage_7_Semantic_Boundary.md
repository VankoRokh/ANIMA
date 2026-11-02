# ADR-010 — Stage 7 Semantic Boundary v0

**Accepted.** 2026-11-03.

## Context

Pre-Stage 7 research and the FAST/DEEP audit exposed three coupled problems:

1. earlier semantic design mixed proposition meaning, evidence provenance, source authority, model producer identity and lifecycle effects;
2. audit v0.2 coupled relation labels to a universal `RESOLVED/UNRESOLVED` axis even though relation classification and truth/lifecycle resolution are independent questions;
3. model-facing work risked becoming tied to temporary Python/storage/prompt details before the semantic boundary was stable enough for constrained generation or future LoRA/SFT.

The project therefore needs a small, versioned semantic contract that survives model replacement and renderer changes while keeping system authority outside the model.

## Decision

Adopt [Stage 7 Semantic Boundary v0](../ROADMAP/Stage_7_Semantic_Boundary_v0.md) as the canonical semantic boundary for the first **read-only/shadow pre-training Stage 7 interface slice**.

Accepted owner decisions:

- **DP-01:** public `Claim` is an immutable qualified/time-scoped proposition; Knowledge status/source/producer do not define Claim identity.
- **DP-02:** `CORRECTION` means a source-declared correction act, not established falsity or an automatic lifecycle revision. The earlier `TEMPORAL_CHANGE` model-facing label is replaced by **`TEMPORAL_SUCCESSION`**, which means compatible ordered succession of claims, not a proven world-change event or exact transition boundary.
- **DP-03:** add **`COMPATIBLE_DISTINCT`** for comparable claims that can coexist but do not support the same proposition.
- **DP-04:** Value v0 is restricted to atomic `string | symbol | boolean | integer | decimal | quantity | entity`; exact comparison only, with deterministic numeric/unit normalization.
- **DP-05:** distinguish `observed_at`, `asserted_at`, `received_at` and `created_at`; unknown timestamps never default to `now`, and independent clock domains require explicit mapping/normalization.
- **DP-06:** temporal scope is `UnknownScope | Instant | Interval`; interval convention is `[from, until)`, each boundary is `Known | Unknown | Unbounded`, and `Unknown != Unbounded`.
- **DP-07:** `CONTENT` and `REVISION` are independent facet results. Partial outcomes are valid. The new semantic contract has no universal `RESOLVED/UNRESOLVED` axis.
- **DP-10a:** Evidence identity is occurrence/version identity separate from Claim equality; replay does not add independent support; shared provenance roots remain dependent; no unconditional `DIRECT > DERIVED` rule.
- **DP-12:** semantic meaning, operation profile, renderer/grammar and model adapter are versioned independently. Conformance and deterministic-first evaluation precede model training.

The first operation profile is `classify_relation/0.1`, which compares exactly two supplied Claims and bounded Evidence without selecting truth, mutating Knowledge or choosing lifecycle actions.

## Open decisions

This ADR does **not** accept:

- **DP-08:** final lifecycle action vocabulary, authority policy and correction rights;
- **DP-09:** mapping of public read semantics to existing Knowledge storage statuses;
- **DP-10b:** complete descendant/dependency re-evaluation policy after premise revision;
- **DP-11:** production routing/dispatcher integration with Stage 6 contracts.

The first implementation must therefore remain read-only/shadow unless a later ADR explicitly accepts these boundaries.

## Consequences

### Positive

- semantic meaning is separated from transport, persistence and model implementation;
- Claim and Evidence identities no longer collapse into one object;
- contradiction can be known without selecting a truth winner;
- correction declaration and content contradiction can coexist;
- temporal uncertainty cannot silently become infinite validity or receipt-order truth;
- deterministic cases can bypass LLM inference entirely;
- future training targets can be generated from a stable semantic profile rather than temporary prompt/service fields;
- legacy audits remain reproducible because their old labels are not rewritten retroactively.

### Cost

- earlier provisional Stage 7 documents require explicit compatibility notes or updates;
- the Work-proposed JSON schema must be regenerated/reviewed against the accepted naming/time decisions before it becomes an implementation contract;
- lifecycle/write integration remains deliberately incomplete until DP-08/09/10b/11 are reviewed;
- a new independent conformance corpus is required before LoRA/SFT.

## Rejected shortcuts

- treating model confidence or model role as truth authority;
- encoding Knowledge mutation commands in model output;
- using one global source ranking as semantic truth;
- interpreting missing temporal bounds as unbounded;
- using `NOT_COMPARABLE` for comparable multi-valued claims;
- keeping `TEMPORAL_CHANGE` in the new model-facing profile despite its stronger world-change implication;
- training on the current audit corpus before the contract and independent splits are stable.

## Validation gate

Before the first model-facing implementation is considered stable:

1. owner-review a 30+ fixture conformance corpus, target 40–50;
2. require 100% conformance on deterministic-decidable reviewed fixtures;
3. verify deterministic cases invoke no model backend;
4. test replay/dependent evidence, unknown/unbounded time, partial coverage, adversarial source text and metamorphic permutations;
5. measure the remaining semantic model residual;
6. compare constrained vanilla inference before deciding on LoRA/SFT.

Stage 7 remains `Planned`; this ADR accepts a semantic boundary, not completed implementation.
