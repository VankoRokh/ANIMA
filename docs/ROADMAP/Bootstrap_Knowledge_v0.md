# Bootstrap Knowledge v0 — scoped concept

Status: **concept retained; semantic terminology aligned with [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md). Full write lifecycle remains open.**

## Core principle

Bootstrap Knowledge is curated starting evidence for ANIMA, not a privileged database backdoor and not sacred truth.

A bootstrap item must have an explicit, versioned curated Source/provenance record. There is no provenance-free exception.

Future write-through ingestion must pass through the same system-owned semantic validation/lifecycle as later evidence once DP-08/09/10b/11 are accepted.

## Source and authority

A bootstrap source may be intentionally trusted by system policy, but that authority is assigned by the system, not by model output or by a special `KNOWN` token.

Bootstrap source identity should reference a versioned curated artifact/revision so replay and later correction remain auditable.

Bootstrap evidence may later be:

- independently supported;
- contradicted by new evidence;
- subject to a source-declared correction;
- related to later temporal succession;
- revised/rejected according to future system-owned lifecycle rules.

The exact action/status mapping is still open DP-08/09 and must not be invented in this document.

## Knowledge vs policy

The distinction remains strict:

- **Knowledge** — information ANIMA may retrieve, reason about and later revise;
- **System policy** — enforced rules/permissions that cognition cannot reinterpret away as ordinary facts.

Examples suitable for Knowledge:

```text
physical hardware can overheat
measurements may be wrong
objects may have time-dependent state
ANIMA is an artificial software system
FAST and DEEP are cognitive roles in ANIMA
```

Examples that remain policy/code:

```text
models may not directly mutate durable Knowledge
Hypothesis is not silently promoted to factual Knowledge
safety/execution authority belongs to system-owned policy
```

## Suggested bootstrap groups

### Self/system knowledge

Useful facts about ANIMA and its architecture, while enforcement remains code/policy.

### Basic world knowledge

Small stable facts useful for retrieval/semantic tests. The goal is not to preload an encyclopedia.

### Test-oriented semantic facts

Curated items specifically chosen to exercise support, contradiction, temporal succession, source-declared correction, provenance and retrieval behavior.

These are test/curated facts, not fabricated production autobiography.

## Scale

Grow incrementally rather than loading an arbitrary large set:

```text
~10
→ ~30
→ ~100
→ ~200
```

At each scale measure processing cost, replay/dedup, provenance, retrieval quality/latency, Context size and model behavior.

The final number is not a target by itself.

## Relationship to Stage 7 conformance

Bootstrap data can later contribute controlled semantic scenarios, but the first pre-training corpus must remain independently reviewed and split by semantic root situations.

Do not train on a corpus merely because it exists in bootstrap storage.

## Synthetic memories boundary

Fake autobiographical memories do not belong in production bootstrap Knowledge.

Synthetic history is reserved for explicit test/virtual instances and must remain distinguishable from real ANIMA history/provenance.

## Current implementation boundary

The accepted Stage 7 slice is still read-only/shadow. This document does not authorize direct bootstrap writes into a new semantic lifecycle implementation.

Canonical references:

- [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md);
- [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md);
- [Stage 7 Semantic Conformance v0](../TESTING/Stage7_Conformance_v0.md).

The original detailed bootstrap proposal remains available in Git history.
