# SemanticCandidate v0 — historical compatibility note

Status: **superseded as the current semantic contract by [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md).**

The original pre-Stage 7 design in this file introduced several principles that remain important:

- a model/interpreter may propose semantic meaning but does not own persistence;
- semantic content must remain separate from provenance;
- Producer is not Source authority;
- system-owned validation/lifecycle decides durable effects;
- bounded processing and observable traces are required.

The detailed original v0 contract is preserved in Git history. It is no longer the current model-facing taxonomy because owner review on 2026-11-03 accepted a smaller orthogonal semantic core.

## What changed

The former `SemanticCandidate.kind` list mixed several independent axes:

```text
ASSERTION
RELATION
STATE_OBSERVATION
TEMPORAL_UPDATE
CORRECTION
DERIVED_CLAIM
HYPOTHESIS
VERIFIED_RESULT
```

These are **not** eight equivalent world-state kinds in the accepted boundary.

Current semantics use:

- one immutable qualified/time-scoped `Claim`;
- separate Evidence identity/provenance;
- separate evidence form/stance such as Observation, Report, Hypothesis and Derived claim;
- separate CONTENT/REVISION assessments;
- separate system-owned Knowledge state and lifecycle decisions.

`CORRECTION` in the current model-facing relation profile means a **source-declared correction act**, not permission to supersede Knowledge.

The former `TEMPORAL_CHANGE` model-facing name is replaced by `TEMPORAL_SUCCESSION` for the accepted Stage 7 slice. Historical audit/docs results retain their original label.

## Current canonical boundary

Use:

- [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md);
- [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md);
- [Stage 7 Semantic Conformance v0](../TESTING/Stage7_Conformance_v0.md).

## Authority rule retained

No model-facing semantic object may directly issue authoritative persistence commands such as:

```text
CREATE_KNOWLEDGE
UPDATE_KNOWLEDGE
DELETE_KNOWLEDGE
CONFIRM_KNOWLEDGE
SUPERSEDE_KNOWLEDGE
```

The first implementation authorized by the accepted boundary is read-only/shadow. DP-08/09/10b/11 remain open before write-through lifecycle integration.
