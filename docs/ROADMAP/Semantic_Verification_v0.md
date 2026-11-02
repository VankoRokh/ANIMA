# Semantic Verification v0

Status: **pre-Stage 7 design baseline; not yet a production contract**.

This document fixes the agreed principle for handling important semantic uncertainty. It complements `SemanticCandidate v0` and does not start Stage 7 implementation.

## Core principle

When ANIMA receives conflicting, uncertain or weakly supported semantic candidates, especially where the possible consequence is important, the system should not resolve the situation by simple source ranking or model voting.

Instead, sufficiently important uncertainty should be able to create a **persistent verification task** whose purpose is to obtain stronger evidence and resolve the uncertainty.

Canonical flow:

```text
conflicting / uncertain candidates
              ↓
     system significance check
              ↓
   verification needed?
      ├─ no  → normal semantic decision / defer
      └─ yes
              ↓
      persistent verification Task
              ↓
      gather stronger evidence
              ↓
      one logical verification case
              ↓
      bounded FAST / DEEP interpretation if needed
              ↓
      system semantic decision
              ↓
      optional validated response/action
```

## Why this exists

Authority rules are useful, but source ranking alone is insufficient when:

- available sources disagree materially;
- the consequence of being wrong is significant;
- the evidence is stale, indirect or incomplete;
- several plausible interpretations remain;
- a stronger direct measurement is available.

The preferred response is therefore often **active investigation**, not guessing which candidate is correct.

## Example: thermal conflict

Initial candidates may disagree:

```text
user estimate:       temperature ≈ 40 C
DEEP interpretation: temperature ≈ 60 C, normal
FAST interpretation: temperature ≈ 70 C, near critical
internal alarm:      temperature critical
```

Because the subject is safety/reliability relevant and the disagreement is large, ANIMA should create a high-priority verification task instead of selecting a winner.

Possible investigation:

```text
1. read current hardware temperature sensor
2. read throttle / thermal status
3. inspect recent temperature history
4. inspect current CPU load
5. inspect cooling/fan state if available
6. inspect the internal condition that raised the alarm
```

The resulting evidence may be:

```text
sensor temperature: 83.4 C
thermal throttling: true
CPU load: 92%
fan RPM: 0
```

FAST/DEEP may then interpret the *combined verified evidence* and propose a conclusion/response strategy, for example:

```text
conclusion: active overheating
likely cause: cooling failure
proposed response: reduce load and inspect cooling
```

The model does not directly execute the response. Normal system validation, Choice, safety policy and Executor boundaries still apply.

## One logical case, many evidence records

The verification should be represented as one logical case/task, but evidence must remain individually identifiable.

```text
Verification Case
├── original conflicting candidates
├── evidence item A
├── evidence item B
├── evidence item C
├── interpretation/proposal
└── final system decision
```

Do not flatten all evidence into one opaque Event. Provenance must preserve who/what produced each observation, when it was produced, and how it affected the final decision.

## Priority

Verification priority is system-owned. A producer may suggest urgency, but may not assign final priority to itself.

Priority should consider at least:

- possible consequence of being wrong;
- importance of the affected subject/Goal;
- disagreement between evidence;
- uncertainty;
- freshness of evidence;
- availability/cost of stronger verification;
- physical or execution safety implications.

A low-impact preference conflict may be deferred. A possible thermal, power or safety conflict may become an urgent task.

## Relationship to Stage 6

This mechanism should reuse the Stage 6 system substrate rather than create a second investigation agent:

```text
Persistent Task
Goal / purpose
Choice
Executor
Observation
Verification
Unified Trace
Recovery
```

The semantic layer decides that verification is necessary; Stage 6 mechanisms provide the persistent, restart-safe process for carrying it out.

## Learning from resolved cases

The completed verification case is itself valuable experience.

A single case may update the factual result, but should not automatically rewrite a global procedure.

Preferred longer path:

```text
resolved case
   ↓
history / episodic evidence
   ↓
repeated cases or Sleep analysis
   ↓
procedural-rule candidate
   ↓
validation
   ↓
possible durable procedure
```

Example future procedural candidate:

```text
When thermal-model estimates conflict with an internal thermal alarm,
read hardware temperature + throttle status before escalating model reasoning.
```

This keeps strategy refinement evidence-backed rather than letting one unusual incident become a permanent reflex.

## Validation requirements

Before production lock, this mechanism should be tested on at least:

1. low-importance conflicts that should not create urgent work;
2. high-importance conflicts that should create verification tasks;
3. stronger direct evidence that resolves weaker derived claims;
4. verification that remains inconclusive and must `DEFER` rather than guess;
5. restart during evidence collection;
6. duplicate/replay without duplicate side effects;
7. multiple independent evidence items kept under one logical case;
8. bounded FAST/DEEP use after evidence collection;
9. response proposals that still require normal system validation;
10. measurable investigation latency/cost and priority behavior.

## Design rule

> High-significance uncertainty may become an active verification task. ANIMA should prefer obtaining stronger evidence over voting between conflicting candidates when the cost of being wrong justifies investigation.

This is the accepted pre-Stage 7 baseline and may be revised after implementation experiments.
