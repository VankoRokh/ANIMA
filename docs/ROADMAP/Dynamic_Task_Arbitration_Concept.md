# Dynamic Task Arbitration & Interest — concept

Status: **future autonomy/personality concept; only a minimal scheduling subset is relevant to Stage 7**.

This document records the agreed direction for dynamic task ordering without making curiosity/interest part of the immediate Stage 7 implementation.

## Core principle

ANIMA's task queue must not be a static FIFO or a fixed numeric-priority list. Task order may change when the situation changes.

Conceptually:

```text
available Tasks
    ↓
re-evaluate when meaningful conditions change
    ↓
consider safety / urgency / importance / delay cost / Goals / resources
    ↓
choose or continue current Task
```

The system must be able to move a newly urgent verification task ahead of previously queued work, while also avoiding constant reordering and starvation.

## Immediate Stage 7 subset

Only the following ideas are considered necessary for current semantic-verification design:

1. verification Tasks may receive different system-owned priorities;
2. task order may be recomputed after meaningful events;
3. an urgent or high-consequence verification may pre-empt lower-value work;
4. an already running Task should have continuity/inertia and should not be interrupted for a trivial score difference;
5. deferred verification must remain persistent and must not be forgotten;
6. waiting time/starvation must be observable so permanently postponed work can eventually be reconsidered;
7. emergency/safety policy remains above interest-driven exploration.

This does **not** require implementing a general autonomous task scheduler or personality-driven curiosity during Stage 7.

## Meaningful re-evaluation points

Task ordering should not be recomputed continuously. Useful triggers include:

- a new high-significance Event;
- a new verification Task;
- a Goal status/priority change;
- new evidence that changes urgency or expected value;
- completion/checkpoint of the current Task;
- resource availability changing materially;
- deadline/cost-of-delay change;
- entry into or recovery from a future Emergency Response Mode.

This reduces scheduler oscillation and unnecessary context switching.

## Factors for future task arbitration

Potential factors include:

- safety / possible harm;
- urgency;
- importance;
- cost of delay or error;
- relation to active Goals;
- expected information gain;
- verification/action cost;
- available compute/energy/time;
- current Internal State;
- age/waiting time;
- interruption/switching cost;
- future personal interest / curiosity.

No fixed weighted formula is accepted yet. Initial scheduling should prefer explicit deterministic rules and measured behavior over decorative scoring.

## Interest / curiosity — future concept

Future ANIMA may develop task-specific interest that affects what it chooses to investigate when higher-authority obligations do not determine the answer.

Interest should be treated as a bounded factor, not as a superior authority.

A future interest signal may depend on:

- novelty;
- unresolved questions;
- expected information gain;
- relation to previously interesting topics;
- recurrence of unexplained events;
- personal history;
- decreasing novelty from repetition.

Example:

```text
Task A: routine cleanup
Task B: investigate an unfamiliar sensor

No safety issue, no urgent Goal, resources available.
High novelty + high information gain may legitimately move Task B ahead of Task A.
```

This is intended to create differentiated exploratory behavior over time, not to override safety, user/system obligations, or important Goals.

## Potential personality relationship

A future personality-like individuality may emerge partly from accumulated history influencing what ANIMA finds worth investigating.

Two instances with the same models, hardware and safety rules could eventually order optional tasks differently because their histories and learned interests differ.

This is preferred over a large static prompt such as `personality=curious`.

However, this remains a research direction. We have not yet decided whether interest should be:

- an Internal State variable;
- a computed property of a Task;
- a learned preference/history model;
- or a combination of these.

Do not add a new `interest` state variable until experiments justify its semantics and bounded influence.

## Safety and authority ordering

Interest must never be allowed to overtake higher-authority requirements simply because a task is more attractive.

Conceptual ordering:

```text
safety / emergency obligations
        >
explicit high-authority Goals and urgent Tasks
        >
time-sensitive normal work
        >
optional useful work
        >
interest-driven exploration
```

Within the same authority/safety band, interest may become a meaningful tie-breaker or bounded modifier.

## Anti-oscillation and anti-starvation

A future scheduler must explicitly prevent:

- switching Tasks repeatedly for small priority changes;
- abandoning useful work every time something novel appears;
- permanent starvation of old low-priority Tasks;
- interest loops that repeatedly select similar rewarding/novel work;
- priority inflation by FAST/DEEP;
- task reordering that loses persistence/recovery guarantees.

Possible future mechanisms include hysteresis, minimum commitment windows/checkpoints, ageing, bounded pre-emption and explicit re-evaluation triggers.

## Observability

Task selection should be explainable.

Example projection:

```text
TASK SELECTION

Selected: verify thermal state
Reasons:
+ high safety consequence
+ high urgency
+ verification source available

Deferred: investigate unknown sensor
Reasons:
+ high novelty
+ useful information gain
- no urgency
- current safety task dominates
```

Interest and Internal State should be visible as bounded contributions, not hidden reasons.

## Validation before broader autonomy

Before a personality/interest mechanism can influence real task scheduling, tests should include:

1. urgent Task correctly pre-empts optional work;
2. trivial new Tasks do not interrupt stable work;
3. deferred Tasks survive restart;
4. old Tasks are not starved indefinitely;
5. interest changes ordering only where higher-authority factors permit it;
6. repeated novelty does not produce pathological loops;
7. emergency/safety always dominates curiosity;
8. task-choice trace explains the ordering;
9. two histories can legitimately produce different optional-task choices;
10. performance cost of re-ranking remains bounded.

## Design rule

> ANIMA should eventually be able to choose not only what must be done, but what is worth doing next when multiple admissible tasks compete. Safety, obligations and urgency remain authoritative; personal interest may later shape optional exploration within those boundaries.

For Stage 7, implement only the scheduling behavior required to support persistent semantic verification and urgent/deferred reordering. Keep personality-driven interest as a documented future experiment.
