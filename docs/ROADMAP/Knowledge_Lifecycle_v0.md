# Knowledge Lifecycle v0 — historical compatibility note

Status: **not a current accepted lifecycle state machine.** Current semantic boundary: [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md).

The original document proposed how semantic outcomes might affect durable Knowledge and retrieval. Its core principle remains valid:

> write/update semantics and read/retrieval semantics must agree; history and provenance must remain auditable.

However, owner review on 2026-11-03 explicitly separated evidence relation, evidence sufficiency, Knowledge state and lifecycle decision. The original list:

```text
CREATE
SUPPORT
TEMPORAL_CHANGE
CORRECTION
CONTRADICTION
UNRESOLVED
REJECT
```

must **not** be treated as one production enum.

## Accepted separation

### Relation / evidence assessment

The current read-only relation profile can describe:

```text
SUPPORT
CONTRADICTION
COMPATIBLE_DISTINCT
TEMPORAL_SUCCESSION
CORRECTION declaration
INSUFFICIENT
NOT_COMPARABLE
UNSUPPORTED
```

These results do not mutate Knowledge.

### Knowledge state

Public read semantics and their exact mapping to the existing implementation statuses:

```text
provisional
confirmed
challenged
superseded
rejected
```

remain **open DP-09**. Documentation must not invent a second production state machine by renaming these statuses to `current/historical/corrected/contested` without an explicit mapping.

### Lifecycle action

The exact accepted system-owned action vocabulary, source authority policy and correction rights remain **open DP-08**.

The design proposal discussed actions such as:

```text
CREATE
ATTACH_SUPPORT
OPEN_CHALLENGE
APPLY_REVISION
DEFER
REJECT
NO_OP
```

but these are not accepted production API until DP-08 is reviewed.

### Dependency re-evaluation

Evidence identity/replay semantics are accepted under DP-10a, but full descendant re-evaluation after a premise correction remains **open DP-10b**.

## Read-path requirements retained

Regardless of the eventual storage mapping, Stage 7 must preserve these requirements:

- corrected/historical evidence must not silently reappear as an unconditional current fact;
- contested/disputed information must remain distinguishable from accepted information;
- temporal applicability must be respected for the query scope;
- source/provenance history must survive revision;
- weak new evidence must not overwrite stronger accepted state merely because it is newer or model-produced;
- restart/replay must preserve the same semantic effects;
- Context Builder must not erase semantic status when projecting information to FAST/DEEP.

## Current implementation boundary

The first Stage 7 interface slice is read-only/shadow. `classify_relation/0.1` may classify supplied Claims/Evidence but cannot CREATE, challenge, revise, supersede or reject durable Knowledge.

Write-through lifecycle integration requires later acceptance of DP-08, DP-09, DP-10b and DP-11.

Canonical references:

- [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md);
- [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md);
- [Stage 7 Semantic Conformance v0](../TESTING/Stage7_Conformance_v0.md).

The original detailed lifecycle proposal remains available in Git history.
