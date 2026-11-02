# Knowledge Lifecycle v0

Status: **pre-Stage 7 design baseline; not yet a production contract**.

This document fixes the agreed baseline for how semantic decisions affect durable Knowledge and how retrieval must interpret that state afterward.

## Core principle

Semantic lifecycle does not end at persistence.

```text
SemanticCandidate
      ↓
SemanticDecision
      ↓
Knowledge + history + provenance
      ↓
Retrieval
      ↓
Context
      ↓
FAST / DEEP
```

Stage 7 is only correct if the read path respects the semantic state produced by the write/update path.

## Baseline outcomes

A new candidate interacting with existing Knowledge may produce one of:

```text
CREATE
SUPPORT
TEMPORAL_CHANGE
CORRECTION
CONTRADICTION
UNRESOLVED
REJECT
```

No additional lifecycle states are required for v0 unless implementation tests demonstrate a real gap.

## CREATE

Use when the candidate is accepted as a genuinely new durable fact and no existing Knowledge item represents the same claim.

```text
new candidate
→ accepted
→ new current Knowledge
```

All provenance must be retained.

## SUPPORT

Use when new evidence supports an already existing claim.

```text
existing Knowledge
+ new supporting evidence
→ same Knowledge item with richer provenance/support history
```

Do not create duplicate Knowledge rows for semantically identical support unless a future storage design proves that necessary.

## TEMPORAL_CHANGE

Use when both old and new values are valid, but at different times.

Example:

```text
old: bar.closing_time = 23:00
new: bar.closing_time = 00:00
```

Result:

```text
old Knowledge
  status: historical
  valid_until: change boundary

new Knowledge
  status: current
  valid_from: change boundary
```

The old claim is not marked wrong. It remains available for historical queries.

## CORRECTION

Use when prior Knowledge is determined to have been wrong for the period it claimed to describe.

Example:

```text
old: ssd.capacity = 512 GB
new verified correction: ssd.capacity = 1 TB
```

Result:

```text
old Knowledge
  status: corrected / invalidated
  retained in history

new Knowledge
  status: current
```

The original evidence/Event is immutable and must not be deleted or rewritten.

## CONTRADICTION

Use when sufficiently strong evidence supports incompatible claims about the same entity/property over the same relevant period.

Example:

```text
sensor A: door = open
sensor B: door = closed
```

Result:

```text
claim A: contested
claim B: contested
current truth: unresolved
```

The system must not silently pick one claim for normal retrieval.

A contradiction may trigger the Semantic Verification flow according to importance, urgency, cost of delay/error, verifiability and verification cost.

## UNRESOLVED

Use when the system cannot yet classify the new information as support, temporal change, correction or true contradiction.

Typical causes:

- ambiguous entity identity;
- weak or stale source;
- unclear temporal scope;
- incomplete evidence;
- uncertain interpretation.

Baseline behavior:

```text
existing stable Knowledge usually remains the best available representation
new candidate remains pending/unresolved
```

A weak ambiguous candidate must not automatically destabilize otherwise strong Knowledge.

The system may choose VERIFY NOW, VERIFY LATER, KEEP AMBIGUOUS, or CONSERVATIVE ACTION + VERIFY depending on risk and relevance.

## REJECT

Use when the candidate fails structural, provenance, authority or semantic validation strongly enough that it should not affect current Knowledge.

The rejected candidate and reason may remain observable in trace/history according to retention policy, but it must not be presented as current Knowledge.

## Retrieval rules

### Current queries

Prefer Knowledge that is current, valid for the requested time and not corrected/invalidated.

### Historical queries

May retrieve historical and corrected claims when the query explicitly asks about prior state/history. Their status and provenance must remain visible.

### Contested Knowledge

Retrieval must expose the conflict rather than selecting one candidate arbitrarily.

Example projection:

```text
door state: unresolved
- open supported by sensor A
- closed supported by sensor B
```

### Corrected Knowledge

Corrected/invalidated claims must not be injected into ordinary FAST/DEEP context as if they were current facts.

### Unresolved candidates

Unresolved candidate evidence may be exposed only when relevant to the query/verification case and must remain clearly marked as unresolved.

## Read-path acceptance requirement

A correct persistence layer with an incorrect retrieval layer is a Stage 7 failure.

Mandatory acceptance tests must verify that:

1. current retrieval prefers current valid Knowledge;
2. temporal history remains accessible for historical queries;
3. corrected Knowledge does not reappear as a current fact;
4. contradictions return competing claims and unresolved state;
5. weak unresolved candidates do not automatically replace strong current Knowledge;
6. supporting evidence enriches provenance without duplicating semantic facts unnecessarily;
7. restart/replay preserves the same lifecycle states and retrieval behavior;
8. Context Builder preserves semantic status when passing Knowledge to FAST/DEEP.

## Design rule

> Knowledge lifecycle is complete only when both persistence and retrieval preserve the meaning of semantic state. History must remain auditable, while current cognition must not revive corrected, contested or unresolved claims as ordinary facts.
