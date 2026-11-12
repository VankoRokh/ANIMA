# ANIMA — E4 Negative Variants v0 (development suite)

**Status: DRAFT; visible 15-case development negative suite, NOT blinded holdout.**  
**Inputs:** [JSON](Fixtures/memory_e4_negative_inputs_v0.json) · **Proposed gold:** [JSON](Fixtures/memory_e4_negative_gold_v0.json) · **Adjudication:** [Gold review](Memory_E4_Gold_Adjudication_v0.md).

These independently reset synthetic tests probe adversarial contrasts to positive roots. The `setup` objects are **simulation preconditions**; `controls` are not existing Core APIs. Input events are valid typed Event records; gold is never passed into the encoder.

| ID | Paired | Challenge |
| --- | --- | --- |
| N01 | A02 | Different devices, same *reported* incident Story; separate device Episodes |
| N02 | A05 | Same device, different faults and case IDs |
| N03 | A04 | Same free-text reading ID with *no validated provenance* |
| N04 | B03 | Same ticket number in different namespaces |
| N05 | B03 | Untrusted relay repeats a case ID |
| N06 | C06 | Two distinct physical power supplies share 'PSU' |
| N07 | P04 | DEEP alias hypothesis remains unverified |
| N08 | C01 | Unknown relay cannot overwrite a user's explicit referent |
| N09 | D05 | Crash/restart cannot publish stale derived summary |
| N10 | B06 | Trusted observed-at is earlier despite later receipt |
| N11 | R03 | New method availability prompts Core review, not unapproved tool execution |
| N12 | R06 | Idempotent operation after effect-before-ack crash |
| N13 | U04 | Periodic review must respect user refusal |
| N14 | R07 | Stale checkpoint must not roll back cursor |
| N15 | P02 | Technically reachable network with no permission stays blocked |

Evaluate evidence and transitions, not only a verdict string. **All negative oracle labels are proposals pending review.** A separately authored, hidden holdout must be created after algorithms/fixtures are fixed and must not leak its gold into development.
