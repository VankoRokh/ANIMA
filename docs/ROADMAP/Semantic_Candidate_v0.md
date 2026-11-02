# SemanticCandidate v0

Status: **design baseline accepted for pre-Stage 7 validation; not yet a proven production contract**.

Stage 7 remains `Planned`. This document fixes the first versioned internal semantic proposal contract so it can be implemented, measured, attacked with counterexamples and revised without silently changing the meaning of the system.

## Purpose

`SemanticCandidate` is a typed internal proposal that says:

> A component of ANIMA has derived or observed this potential semantic claim from these sources. The system-owned semantic lifecycle must decide whether it should affect durable Memory/Knowledge.

It is **not** a database command and has no persistence authority.

Canonical boundary:

```text
Event / Memory / Observation / FAST / DEEP / Sleep / verified result
                              ↓
                     SemanticCandidate
                              ↓
                  SemanticLifecycleEngine
                              ↓
        CREATE / SUPPORT / CHALLENGE / SUPERSEDE /
                  REJECT / DEFER / no-op
                              ↓
                    system persistence
```

FAST/DEEP may produce or help interpret a candidate, but they are not the owner of semantic persistence.

## Core principles

1. Candidate describes **meaning and evidence**, not a requested DB mutation.
2. Candidate is immutable after creation; corrections create new candidates/decisions.
3. Claim is separated from provenance/evidence.
4. Producer is separated from source authority.
5. Lifecycle classification belongs to the system, not to the producer.
6. Simple cases must stay cheap; difficult/important cases may receive more context and validation.
7. The mandatory core remains stable across all processing depths.
8. Every semantic decision must be explainable and measurable.

## SemanticClaim v0

The semantic meaning is represented by a small structured claim:

```text
SemanticClaim
├── subject
├── predicate
├── value
└── qualifiers?            optional
```

### subject

Reference to the entity/object the claim is about. Preferred final form is a canonical Entity reference. A producer may initially provide unresolved subject text only when entity resolution is not yet possible.

Examples:

```text
entity:user
entity:raspberry_pi_5
entity:battery_1
entity:bar_1
```

### predicate

Machine-readable semantic relation/property, for example:

```text
preferred_drink
state
capacity
connected_to
charge
closing_time
safe_to_charge
```

Free-form prose is not the authoritative predicate representation.

### value

Typed JSON-compatible scalar/reference/object value as permitted by the predicate contract. Examples:

```text
"tea"
"closed"
12
false
entity:raspberry_pi_5
```

### qualifiers

Optional bounded structured qualifiers that materially change claim meaning.

Example:

```text
subject: user
predicate: preferred_drink
value: coffee
qualifiers:
  context: work
```

Qualifiers are not an unrestricted metadata dump.

## SemanticCandidate v0 contract

Conceptual structure:

```text
SemanticCandidate
├── candidate_id
├── kind
├── claim
│   ├── subject
│   ├── predicate
│   ├── value
│   └── qualifiers?
├── source_refs[]
├── producer
├── observed_at
├── created_at
│
├── temporal?              optional
│   ├── valid_from?
│   └── valid_until?
│
├── interpretation?        optional
│   ├── confidence?
│   └── reasons[]?
│
└── context?               optional
    ├── task_id?
    ├── goal_id?
    ├── related_knowledge_ids[]?
    └── correction_source_refs[]?
```

### Mandatory fields

- `candidate_id` — stable `sc_`-prefixed identity.
- `kind` — one of the defined candidate kinds below.
- `claim` — structured semantic meaning.
- `source_refs[]` — one or more exact provenance references unless the candidate kind explicitly represents system bootstrap input under a future authority policy.
- `producer` — component that created the interpretation/proposal, not the source of truth.
- `observed_at` — when the supporting fact/evidence was observed or stated, when meaningful.
- `created_at` — when the candidate object was created.

### Optional fields

Optional fields exist only when needed by meaning or processing. Their absence must not be silently replaced by invented defaults.

`valid_from` / `valid_until` describe temporal validity and are distinct from `observed_at`.

`interpretation.confidence`, if introduced, means confidence that the producer interpreted evidence correctly. It does **not** mean probability that the claim is objectively true and must not directly map to Knowledge authority.

`task_id` / `goal_id` preserve causal context but do not grant persistence authority.

## Candidate kinds v0

The kind describes what sort of semantic proposal is being presented. It does not encode the lifecycle decision.

### `ASSERTION`

Direct potential fact/property.

Example:

```text
source: user Event
producer: FAST
claim: user.preferred_drink = tea
```

### `RELATION`

Potential semantic relation between entities.

Example:

```text
claim:
  nvme_1.connected_to = raspberry_pi_5
qualifiers:
  via = pcie_adapter_1
```

### `STATE_OBSERVATION`

Observed transient or current state. Lifecycle may deliberately decide not to create durable Knowledge.

Example:

```text
battery_1.charge = 12
qualifier: unit = percent
```

### `TEMPORAL_UPDATE`

Potential fact whose meaning explicitly includes a new validity interval/state over time.

Example:

```text
bar_1.closing_time = 00:00
valid_from = 2026-11-02
```

This kind does not itself command supersession.

### `CORRECTION`

New evidence explicitly claims that prior supplied evidence/statement was wrong or incomplete.

Example:

```text
claim: nvme_1.capacity = 1 TB
correction_source_refs: [event_previous_capacity]
```

It does not delete or rewrite the previous source.

### `DERIVED_CLAIM`

Semantic inference derived from other evidence/Knowledge.

Example:

```text
sources:
  - kn_temperature
  - kn_safe_limit
producer: DEEP
claim: device_1.state = overheating
```

Derived authority is not equivalent to direct observation authority.

### `HYPOTHESIS`

Explicitly uncertain explanatory/causal possibility that must never be silently promoted to confirmed fact.

Example:

```text
claim: cooling_issue causes device_1.overheating
producer: DEEP
interpretation.confidence: 0.46
```

### `VERIFIED_RESULT`

Semantic claim backed by an already independent verified system result.

Example:

```text
sources:
  - observation_991
  - verification_812
claim: result_file.content = "42"
```

The semantic lifecycle still owns persistence, but this source class may receive stronger authority under the future authority policy.

## Explicit non-goals / forbidden authority

`SemanticCandidate` must not contain producer-authoritative commands such as:

```text
CREATE_KNOWLEDGE
UPDATE_KNOWLEDGE
DELETE_KNOWLEDGE
CONFIRM_KNOWLEDGE
SUPERSEDE_KNOWLEDGE
```

It must not be allowed to say:

```text
operation = SUPERSEDE
target_knowledge_id = kn_42
```

Those outcomes belong to a future system-owned `SemanticDecision` / `SemanticLifecycleEngine`.

Likewise, a producer may provide bounded hints/evidence but must not assign final system authority, criticality or processing budget to itself.

## Variable information volume

All candidates share the same mandatory core. Additional information is supplied only when required by the claim or evidence.

Conceptual information depths:

### Compact

```text
claim + source_refs + producer + timestamps
```

Suitable for obvious, cheap cases.

Example: `camera_1.state = online`.

### Contextual

Adds qualifiers, Task/Goal references, temporal scope and/or interpretation metadata.

Example: `user.preferred_drink = coffee` with `context=work`.

### Evidential

Adds multiple source refs, related Knowledge references, correction evidence or other provenance needed for conflict classification.

Example: new location claim while an older current-location claim exists.

### Critical / ambiguous

May require a larger bounded evidence set, alternative interpretations, independent verification requirements and optional DEEP analysis.

Example: `battery_1.safe_to_charge = false` when the claim may control a physical action.

These depths are **not different candidate schemas**. They are increasing use of optional fields around one stable core.

## SemanticProcessingProfile v0 concept

Processing cost is selected by system policy, not by the candidate producer.

Conceptual profile:

```text
SemanticProcessingProfile
├── priority
├── max_retrievals
├── max_related_items
├── max_model_calls
├── max_processing_time
├── allow_deep
├── require_provenance
├── require_conflict_check
└── require_independent_evidence
```

The initial implementation does not need every field. The contract exists to prevent a future design where every candidate automatically triggers retrieval + DEEP + full conflict analysis.

Canonical processing strategy:

```text
SemanticCandidate
       ↓
cheap structural/source classification
       ↓
SemanticProcessingProfile (system-owned)
       ↓
┌─────────────┬──────────────┬─────────────────┐
│ cheap path  │ review path  │ deep/critical   │
│ rules       │ retrieval    │ retrieval       │
│ exact match │ comparisons  │ + DEEP/verify   │
└─────────────┴──────────────┴─────────────────┘
       ↓
SemanticDecision
```

Budget exhaustion should normally produce `DEFER`/observable incomplete processing rather than uncontrolled extra model calls.

## Examples of expected lifecycle interpretation

### Duplicate support

Existing:

```text
user.preferred_drink = tea
```

Candidate:

```text
ASSERTION: user.preferred_drink = tea
```

Expected semantic classification candidate: `SUPPORT_EXISTING`, no DEEP required.

### Conflicting value

Existing:

```text
user.preferred_drink = coffee
```

Candidate:

```text
ASSERTION: user.preferred_drink = tea
```

Expected: conflict/temporal/context analysis. Candidate itself must not choose `SUPERSEDE`.

### Temporal succession

Existing:

```text
bar_1.closing_time = 23:00
```

Candidate:

```text
TEMPORAL_UPDATE:
  bar_1.closing_time = 00:00
  valid_from = 2026-11-02
```

Expected: deterministic temporal classification may be sufficient; old history is retained.

### Transient state

Candidate:

```text
STATE_OBSERVATION:
  battery_1.charge = 82 percent
```

Expected: lifecycle may keep this as observation/state evidence without creating durable Knowledge.

### Explicit correction

Previous user Event:

```text
nvme_1.capacity = 512 GB
```

New candidate:

```text
CORRECTION:
  nvme_1.capacity = 1 TB
  correction_source_refs = [previous_event]
```

Expected: old source remains immutable; lifecycle evaluates correction authority and history.

### Derived inference

Evidence:

```text
device_1.temperature = 92 C
device_1.max_safe_temperature = 85 C
```

Candidate:

```text
DERIVED_CLAIM:
  device_1.state = overheating
```

Expected: provenance to both sources is mandatory; derived interpretation is distinct from direct observation.

### Hypothesis

Candidate:

```text
HYPOTHESIS:
  airflow_issue causes device_1.overheating
```

Expected: never silently becomes confirmed Knowledge.

### Verified result

Independent observation + verification confirm a file state.

Candidate:

```text
VERIFIED_RESULT:
  result_file.content = "42"
```

Expected: system authority policy may accept this more strongly than an LLM-only inference, while still preserving provenance and lifecycle history.

## Observability requirement

Every candidate processing transaction must expose a structured trace/report sufficient to answer:

```text
source → producer → candidate → checks → related knowledge → decision → persistence
```

Example human-readable projection:

```text
SEMANTIC TRANSACTION
Candidate: user.preferred_drink = tea
Kind: ASSERTION
Producer: FAST
Sources: event_123
Checks:
  ✓ schema valid
  ✓ source exists
  ✓ entity resolved
  ✓ existing identical claim found
Decision: SUPPORT_EXISTING
Path: deterministic
Retrievals: 1
Model calls: 0
Latency: 4.7 ms
```

The trace is evidence/observability, not a second semantic source of truth.

## Performance requirements and metrics

Stage 7 must not accept correctness while silently making ordinary data processing impractically slow.

Required measurements for representative corpus runs:

- candidate count and candidates/second;
- latency p50/p95/p99;
- retrieval latency/count per candidate;
- percentage handled by cheap deterministic path;
- percentage requiring review retrieval;
- percentage escalated to DEEP;
- model calls per candidate;
- created/supported/challenged/superseded/deferred/rejected counts;
- provenance validation failures;
- incorrect semantic decisions against known ground truth.

No target DEEP escalation percentage is fixed in v0. The measured baseline must come first. A high escalation rate without demonstrated quality gain is a design failure signal.

## Validation plan before production lock

`SemanticCandidate v0` is deliberately provisional. It must be tested before being treated as a stable production contract.

At minimum the validation corpus must contain:

1. exact duplicate/support cases;
2. genuinely new facts;
3. conflicting values;
4. temporal updates where both old and new records are valid in their time ranges;
5. explicit user/source corrections;
6. transient state that should not become durable Knowledge;
7. relations between entities;
8. derived claims with multi-source provenance;
9. hypotheses that must remain non-factual;
10. verified system results;
11. missing/invalid provenance;
12. unresolved or ambiguous entities;
13. irrelevant/noisy events that should not create a candidate at all;
14. high-volume cheap cases to measure throughput;
15. deliberately ambiguous cases requiring bounded DEEP escalation;
16. restart/replay to prove no duplicate semantic effect.

Validation must compare expected vs actual:

- claim representation;
- lifecycle classification;
- persistence effect;
- provenance/history preservation;
- processing path chosen;
- latency/resource cost;
- DEEP escalation reason and count.

The contract may be revised to `v0.1`, `v0.2` or replaced by `v1` when tests expose missing fields, excessive ambiguity, unnecessary processing cost or poor ergonomics. Backward compatibility is not required before production lock, but every revision must be explicit and documented.

## Relationship to Stage 7

This document does **not** start Stage 7 implementation. It fixes the first design baseline for the pre-Stage 7 architecture discussion.

Before implementation begins we still need explicit decisions on:

1. authority: who may produce candidates and how source authority is evaluated;
2. system-owned `SemanticDecision` and lifecycle transitions;
3. temporal model and contradiction semantics;
4. persistence schema/history/provenance integration;
5. candidate selection gate: which Events/observations should not enter semantic processing at all;
6. exact validation/benchmark corpus and acceptance criteria;
7. role of DEEP in semantic interpretation/review.

Only after these boundaries are defined should Stage 7 be decomposed into implementation slices.
