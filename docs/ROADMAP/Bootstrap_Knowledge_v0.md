# Bootstrap Knowledge v0

Status: **pre-Stage 7 design baseline; not yet a production contract**.

## Core principle

Bootstrap Knowledge is the curated starting knowledge given to ANIMA before it accumulates enough real experience of its own. It must enter through the same semantic lifecycle as later knowledge instead of bypassing validation and persistence rules.

Canonical flow:

```text
bootstrap/system-curated source
        ↓
SemanticCandidate
        ↓
SemanticLifecycleEngine
        ↓
SemanticDecision
        ↓
Knowledge + provenance/history
```

Bootstrap input is therefore a special source class, not a privileged database backdoor.

## Authority

Bootstrap Knowledge may begin with strong source authority because it is explicitly curated by the developer/system setup, but it is not immutable or infallible.

It may later be:

- supported by new evidence;
- superseded by temporal change;
- corrected when the original curated fact was wrong;
- challenged by conflicting strong evidence;
- retained historically when no longer current.

The original bootstrap source must remain traceable in provenance.

## Knowledge vs system policy

A strict distinction is required:

- **Knowledge** = information ANIMA may know, reason about, retrieve and revise;
- **System policy** = rules ANIMA must obey and that do not become ordinary semantic claims.

Examples suitable for Knowledge:

```text
physical hardware can overheat
measurements may be wrong
objects may change state over time
ANIMA is an artificial software system
FAST and DEEP are cognitive roles in ANIMA
```

Examples that belong to system policy instead:

```text
HYPOTHESIS must not be silently promoted to confirmed Knowledge
FAST/DEEP may not directly mutate persistent Knowledge
safety policy overrides optional interest-driven work
```

A policy must not be implemented merely as a retrievable fact that cognition can reinterpret away.

## Suggested bootstrap groups

### 1. Self/system knowledge

Basic facts about ANIMA and its architecture that are useful to cognition, while implementation-enforced boundaries remain policy/code.

Examples:

```text
ANIMA is this system
FAST is a cognitive role
DEEP is a cognitive role
Memory persists independently of LLM model replacement
```

### 2. Basic world knowledge

Small, stable, useful facts sufficient to exercise semantic reasoning and retrieval. The goal is not to preload a miniature encyclopedia.

Examples:

```text
physical objects may change state
temperature is time-dependent
hardware can fail
files can be modified
measurements can contain error
```

### 3. Test-oriented semantic facts

Curated facts chosen specifically to exercise lifecycle behavior: entities, relations, temporal changes, corrections, contradictions and support.

These remain real bootstrap inputs for the test instance but must not be fabricated autobiographical events of production ANIMA.

## Loading strategy

Bootstrap scale should grow incrementally instead of loading an arbitrary large set immediately.

Suggested progression:

```text
~10 items
→ ~30
→ ~100
→ ~200
```

At each scale measure at least:

- candidate processing cost;
- duplicate/support behavior;
- Entity resolution;
- provenance preservation;
- retrieval quality and latency;
- Context Builder size/selection;
- effects on FAST/DEEP behavior;
- restart/replay idempotency;
- conflict/temporal lifecycle behavior.

The final number is not a target by itself. Scale is increased only while the added corpus provides useful coverage.

## Relationship to testing

Bootstrap Knowledge should double as a controlled Stage 7 corpus.

Examples:

```text
bootstrap: device_X.capacity = 512 GB
later correction candidate: device_X.capacity = 1 TB
```

```text
bootstrap: bar.closing_time = 23:00
later temporal update: bar.closing_time = 00:00 from T2
```

```text
bootstrap: relation A connected_to B
later independent evidence supports the same relation
```

This lets Stage 7 validate the full path from ingestion through retrieval rather than testing persistence in isolation.

## Synthetic memories boundary

Fake autobiographical memories must not be placed into production bootstrap Knowledge.

Synthetic history belongs only to explicitly marked test/virtual instances and must remain distinguishable from real ANIMA history.

## Validation requirements

Before production lock, verify that bootstrap data:

1. enters through the normal SemanticCandidate/SemanticDecision path;
2. retains explicit `bootstrap/system-curated` provenance;
3. can be supported, corrected, challenged and superseded normally;
4. survives restart/replay without duplicate semantic effects;
5. is retrieved according to current/historical/contested/corrected status;
6. does not bypass system policy or create a second source of truth;
7. scales from small to larger corpora with measured latency/resource impact;
8. remains separate from synthetic autobiographical test history.

## Design rule

> Bootstrap Knowledge is trusted starting evidence, not sacred truth. It must use the same semantic lifecycle as later knowledge, while system policy remains outside ordinary Knowledge and is enforced by system-owned code/rules.
