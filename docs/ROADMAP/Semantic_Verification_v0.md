# Semantic Verification v0 — scoped concept

Status: **concept retained; terminology aligned with [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md). Production lifecycle integration remains open.**

## Core principle

Important semantic uncertainty should not be resolved by source-count voting, model-role preference or model confidence alone.

When the cost of being wrong justifies it, ANIMA may create or schedule a persistent verification task that seeks stronger evidence through the existing Stage 6 Task/Goal/Choice/Executor/Observation/Verification substrate.

This is a system-owned decision. A FAST/DEEP output may suggest uncertainty or an interpretation, but does not assign final verification priority or mutate Knowledge.

## Evidence roles

The accepted Stage 7 boundary distinguishes evidence form and provenance explicitly:

- **Observation** — registered measurement/observation from a source adapter;
- **Report** — a source states a proposition; the report act is evidence that the statement occurred, not proof of its content;
- **Hypothesis** — explicitly speculative interpretation;
- **Derived claim** — conclusion produced from recorded premises/method.

Model estimates are therefore **derived/hypothetical interpretations unless backed by registered observations**. They must not be presented beside hardware measurements as if all were equivalent observations.

## Example: thermal conflict

Possible initial evidence:

```text
user report: estimated temperature around 40 C
FAST derived hypothesis: likely near 70 C
DEEP derived hypothesis: likely around 60 C
registered internal alarm observation: thermal condition critical
```

These are not four equal measurements.

If the situation is important, the system can create a verification task such as:

```text
1. obtain registered hardware temperature observation
2. obtain throttle/thermal status observation
3. inspect recent temperature observations
4. inspect CPU load observation
5. inspect fan/cooling observation if available
```

A resulting evidence slice might contain independently identifiable observations:

```text
temperature sensor = 83.4 C
thermal throttling = true
CPU load = 92%
fan RPM = 0
```

FAST/DEEP may then interpret that bounded evidence and propose a conclusion/response. Normal system validation, Choice, safety policy and Executor boundaries remain authoritative.

## One logical case, multiple Evidence identities

A verification case can group many records without flattening them into one opaque event:

```text
Verification Case
├── original claims/evidence
├── Evidence A
├── Evidence B
├── Evidence C
├── derived interpretation/proposal
└── eventual system decision
```

Evidence identity/dependence follows accepted DP-10a:

- replay of one occurrence is not new independent support;
- different EvidenceRefs can share one provenance root;
- independent measurements remain distinct even when their semantic Claim is equal.

## Time and provenance

Verification records must preserve the relevant distinction between:

```text
observed_at
asserted_at
received_at
created_at
Claim validity
```

A later receipt does not make evidence a later world state. Unknown time is not silently replaced with `now`.

## Relationship to `classify_relation/0.1`

Relation assessment and verification are separate contracts.

For example:

```text
CONTENT = CONTRADICTION
```

can be known while the system still has insufficient authority/evidence to choose a truth winner. A later lifecycle policy may decide whether that contradiction warrants immediate verification, deferred verification or no new task.

`classify_relation/0.1` itself does not create verification Tasks.

## Priority

Future verification priority should remain system-owned and may consider:

- consequence of error;
- Goal relevance;
- evidence disagreement;
- freshness and provenance;
- availability/cost of stronger evidence;
- execution/physical safety.

Exact arbitration remains outside the first read-only Stage 7 slice.

## Validation requirements

Future lifecycle integration should test at least:

1. low-impact conflicts that do not create urgent work;
2. high-impact conflicts that do;
3. stronger registered observations against weaker derived hypotheses;
4. inconclusive verification that defers rather than guesses;
5. restart during evidence collection;
6. replay without duplicate side effects;
7. multiple evidence identities under one case;
8. bounded FAST/DEEP interpretation after evidence collection;
9. response proposals still requiring normal validation;
10. measurable investigation cost and latency.

Canonical semantics and open integration boundaries:

- [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md);
- [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md).
