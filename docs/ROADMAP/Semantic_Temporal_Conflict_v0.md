# Semantic Temporal Conflict v0

Status: **pre-Stage 7 design baseline; not yet a proven production contract**.

This document fixes the first minimal rules for distinguishing a true semantic contradiction from a temporal change or correction. It complements `Semantic_Candidate_v0.md` and `Semantic_Verification_v0.md`.

## Core principle

A new value that differs from existing Knowledge must not automatically invalidate the old value.

Before deciding that two claims conflict, ANIMA must first ask whether they describe:

- the same entity;
- the same predicate/meaning;
- the same relevant time interval;
- the same context/qualifiers.

Only then may the difference be classified.

## Minimal time model v0

The initial temporal model distinguishes:

- `observed_at` — when ANIMA received/observed the evidence;
- `valid_from` — when the claim became true, if known;
- `valid_until` — when the claim stopped being true, if known.

`observed_at` must not be silently treated as `valid_from`.

Unknown temporal bounds remain unknown; the system must not invent dates.

## Four classification outcomes

### `TEMPORAL_CHANGE`

Both old and new values may be true, but at different times.

Example:

```text
old: bar.closing_time = 23:00
new: bar.closing_time = 00:00
valid_from(new) = 2026-11-02
```

Expected interpretation:

```text
old valid_until = change boundary
new valid_from  = change boundary
```

Old history remains valid for its historical interval.

### `CORRECTION`

The previous representation was wrong for the interval in which it claimed to be true.

Typical evidence:

- explicit source statement such as "I was wrong" / "correction";
- stronger direct evidence showing the old claim was mistaken;
- a stable property whose apparent change is implausible without entity replacement or prior error.

The original Event/evidence is never deleted; the semantic interpretation is marked as corrected/invalidated.

### `CONTRADICTION`

Two sufficiently strong claims disagree about the same entity, predicate, context and overlapping time interval.

Example:

```text
20:00 sensor_A: door = open
20:00 sensor_B: door = closed
```

Neither claim should be silently selected as truth merely because one producer is FAST/DEEP or because one was processed later.

The conflict may trigger normal verification policy.

### `UNRESOLVED`

Available evidence is insufficient to distinguish temporal change, correction, entity mismatch or true contradiction.

`UNRESOLVED` is a valid system state and must not be converted into a guessed fact for database cleanliness.

It can later lead to:

- `VERIFY NOW`;
- `VERIFY LATER`;
- `CONSERVATIVE ACTION + VERIFY`;
- `KEEP AMBIGUOUS`.

## Classification cues v0

The system should consider at least four simple questions.

### 1. Same entity?

Before comparing values, verify that the claims refer to the same canonical entity.

An apparent capacity change from 512 GB to 1 TB may actually mean two different SSDs or incorrect entity resolution.

### 2. Explicit correction signal?

Statements such as:

```text
"I was wrong"
"that earlier value was incorrect"
"it was always 1 TB"
```

strongly support `CORRECTION` rather than temporal change.

### 3. Explicit change boundary?

Statements such as:

```text
"from Monday"
"since 2026-11-02"
"now"
"after replacement"
```

support `TEMPORAL_CHANGE` when the property can legitimately change.

### 4. Can the property naturally change?

Common time-varying properties:

```text
temperature
location
battery charge
online/offline
opening hours
preferences
current task/job
```

Typically stable properties:

```text
serial number
hardware model
factory capacity of the same physical device
date of birth
fixed-version file hash
```

A surprising change in a stable property should raise suspicion of correction, entity replacement/mismatch or bad evidence rather than be accepted as an ordinary temporal update.

## Historical preservation

No classification deletes the raw source history.

The semantic layer may change which Knowledge item is current/valid, but the system must preserve:

```text
what was believed
why it was believed
which evidence supported it
when it was considered valid
what later changed or challenged it
```

This allows ANIMA to distinguish:

```text
world changed
```

from:

```text
ANIMA's previous understanding was wrong
```

## Important distinction

A claim may stop being the current truth in two fundamentally different ways:

```text
SUPERSEDED BY CHANGE
```

The old claim was historically valid but later ceased to be current.

```text
INVALIDATED BY CORRECTION
```

The old semantic interpretation was wrong for the interval it claimed.

These outcomes must not collapse into one generic "updated" status.

## Relationship to verification

When classification is uncertain or evidence remains in real conflict, use the normal verification policy instead of guessing.

Conceptual flow:

```text
new value differs
      ↓
same entity/context/time?
      ↓
TEMPORAL_CHANGE / CORRECTION / CONTRADICTION / UNRESOLVED
      ↓
if needed: verification policy
      ↓
VERIFY NOW / VERIFY LATER /
CONSERVATIVE ACTION + VERIFY / KEEP AMBIGUOUS
```

## Validation cases required before production lock

At minimum test:

1. clear temporal succession;
2. explicit correction;
3. simultaneous conflicting sensors;
4. ambiguous entity identity;
5. stable property with incompatible new value;
6. retroactive correction of a derived claim;
7. late discovery where `observed_at != valid_from`;
8. unknown validity boundary without invented timestamp;
9. overlapping validity intervals;
10. restart/replay without duplicate semantic transitions.

## Design rule

> A different value is not automatically a contradiction. First determine whether the world changed, the previous understanding was wrong, strong evidence truly conflicts, or the system simply does not yet know. Preserve history in every case.
