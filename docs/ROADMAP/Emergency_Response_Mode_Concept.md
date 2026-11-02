# Emergency Response Mode — concept

Status: **future safety/reliability concept; not part of Stage 7 implementation baseline**.

This document records the agreed concept of a future emergency response mode inspired by an organism's acute stress/adrenaline response. The biological analogy is descriptive only; the implementation must remain explicit, bounded and auditable.

## Core principle

When ANIMA faces a high-consequence situation under uncertainty, it may need to act before it has enough evidence for a confident semantic conclusion.

In that case the preferred first response is not to guess which hypothesis is true, but to choose a fast, reversible action that reduces the worst plausible risk and preserves the ability to diagnose the real cause afterward.

Canonical idea:

```text
high-risk uncertainty
        ↓
fast risk classification
        ↓
minimal safe response
        ↓
stabilise / reduce resource use / stop risky work
        ↓
collect evidence
        ↓
normal verification and diagnosis
        ↓
restore / adapt / escalate
```

Example:

```text
possible overheating + conflicting evidence
        ↓
stop or throttle expensive inference/workloads
enter low-load diagnostic state
preserve logs and current evidence
read hardware telemetry
        ↓
resolve actual cause
```

The emergency action may later prove unnecessary. That is acceptable when the action was intentionally selected to be safe, bounded and reversible under asymmetric risk.

## Important separation

Emergency behavior must not turn uncertainty into false Knowledge.

It is valid to have:

```text
Knowledge state: unresolved thermal condition
Action state: reduce load because possible thermal damage is costly
```

The system may act conservatively without claiming that the feared hypothesis is already confirmed.

## Selection priorities

A future emergency response should prefer actions that are:

1. fast to decide;
2. low-risk across several plausible hypotheses;
3. reversible where possible;
4. bounded in duration/scope;
5. protective of identity, persistent state and evidence;
6. minimally destructive to current Tasks/Goals;
7. compatible with later diagnosis and recovery.

Examples of suitable responses may include:

- pause/throttle nonessential high-load computation;
- stop an action whose continuation could increase damage;
- switch to a lower-resource operating profile;
- prioritise telemetry/diagnostic collection;
- checkpoint persistent work before deeper shutdown;
- isolate a failing peripheral or subsystem when supported by explicit safety policy.

Irreversible or destructive actions should require a substantially stronger threshold and separate safety rules.

## Relationship to Semantic Verification

This concept complements `Semantic_Verification_v0.md`.

Normal path:

```text
uncertainty → verify → resolve → act
```

Emergency path when delay itself is risky:

```text
uncertainty + high consequence + urgency
        ↓
conservative stabilising action
        ↓
verification continues
        ↓
semantic resolution
        ↓
normal response/recovery
```

Emergency response therefore changes the order of **action vs diagnosis**, not the authority rules for Knowledge.

## Potential future internal-state relationship

The mode may later use future acute state variables analogous to stress/adrenaline, but Internal State must remain a bounded influence rather than an unchecked owner of actions.

A future implementation may temporarily change system priorities such as:

- resource allocation;
- Task urgency;
- DEEP availability/cost tolerance;
- preference for reversible conservative actions;
- diagnostic priority;
- tolerance for postponing nonessential work.

The mode must not be a hidden LLM personality or uncontrolled prompt state.

## Failure modes to prevent

A future design must explicitly prevent:

- permanent emergency mode due to one stale alarm;
- repeated oscillation between emergency/normal states;
- emergency action silently becoming confirmed Knowledge;
- uncontrolled shutdown or destructive action from weak evidence;
- loss of logs/evidence needed to diagnose the incident;
- starvation of recovery/verification work;
- a model self-declaring an emergency and gaining additional authority.

## Useful principles that may affect current design now

Although the full mode is deferred, several principles can already be used in Stage 7 design:

1. **Knowledge uncertainty and action policy are separate.**
2. **High consequence + urgency may justify conservative action before semantic certainty.**
3. **Verification priority should include the cost of delay.**
4. **Emergency actions should produce explicit evidence/trace and remain recoverable.**
5. **The system, not FAST/DEEP, owns emergency activation and final action authority.**
6. **A resolved incident should become evidence for later procedural refinement, but one case must not automatically become a permanent global rule.**

## Future validation

Before production use, the emergency mechanism should be tested against at least:

- true positive emergencies;
- false alarms;
- stale/conflicting sensors;
- unavailable verification source;
- rapidly worsening conditions;
- emergency action that is safe but unnecessary;
- restart during emergency handling;
- oscillation/hysteresis scenarios;
- recovery to normal mode;
- preservation of evidence and persistent Tasks;
- attempts by FAST/DEEP to overstate urgency;
- comparison of damage/risk with and without the emergency path.

## Design rule

> Under urgent high-consequence uncertainty, ANIMA may temporarily optimise for fast, reversible risk reduction rather than perfect diagnosis. Stabilise first when delay is dangerous; then verify, explain and recover without rewriting uncertainty as fact.
