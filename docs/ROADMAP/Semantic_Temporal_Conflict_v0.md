# Semantic Temporal Conflict v0 — historical compatibility note

Status: **superseded as the current semantic contract by [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md).**

The original document established an important principle that remains accepted:

a different value does not automatically invalidate an older value. ANIMA must distinguish content incompatibility, temporal succession, source-declared correction, missing scope and entity/context mismatch while preserving source history.

The detailed original proposal is preserved in Git history. The current terminology and time model were revised during owner review on 2026-11-03.

## Current accepted temporal model

Separate:

```text
observed_at  — when the source observed/measured the event/state
asserted_at  — when the source made the assertion/report
received_at  — when ANIMA first received the occurrence
created_at   — when an internal record/interpretation was created
validity     — world-valid scope of the Claim
```

None of the first four timestamps automatically establishes Claim validity.

World-valid scope is:

```text
UnknownScope | Instant | Interval
```

Each interval boundary is:

```text
Known | Unknown | Unbounded
```

Accepted interval convention:

```text
[valid_from, valid_until)
```

`Unknown` is not `Unbounded`; missing time never defaults to infinity or `now`.

Two point observations at different times do not establish a continuous interval or exact transition boundary between them.

## Current relation terminology

### TEMPORAL_SUCCESSION

The legacy model-facing term `TEMPORAL_CHANGE` is replaced by `TEMPORAL_SUCCESSION` in the accepted Stage 7 slice.

It means supplied Claims describe an ordered, compatible succession of locally incompatible states under known temporal/context/cardinality preconditions.

It does **not** prove:

- a world-change event;
- truth of both Claims;
- continuous history between observations;
- an exact change boundary.

### CORRECTION

`CORRECTION` now means a bounded source fragment explicitly declares a correction and the target is identifiable.

It does **not** mean:

- the old Claim has been proven false;
- the new Claim has been accepted as truth;
- Knowledge should automatically be revised.

A pair may therefore have both:

```text
CONTENT = CONTRADICTION
REVISION = CORRECTION
```

### CONTRADICTION

Content incompatibility can be established without deciding which Claim is true or whether accepted Knowledge should change.

### COMPATIBLE_DISTINCT

Comparable Claims that can coexist but do not support the same proposition use `COMPATIBLE_DISTINCT`, not `NOT_COMPARABLE`.

### INSUFFICIENT / NOT_COMPARABLE / UNSUPPORTED

These are distinct:

- `INSUFFICIENT`: supported question, missing/unclear required information;
- `NOT_COMPARABLE`: proven outside the common atomic comparison domain;
- `UNSUPPORTED`: required semantics/capability is not implemented by the profile.

There is no universal `RESOLVED/UNRESOLVED` axis in the new contract.

## Lifecycle boundary

Relation classification is not a lifecycle command. Accepted actions, source authority/correction rights and Knowledge read-state mapping remain open DP-08/09/10b/11.

Use the current canonical documents:

- [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md);
- [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md);
- [Stage 7 Semantic Conformance v0](../TESTING/Stage7_Conformance_v0.md).
