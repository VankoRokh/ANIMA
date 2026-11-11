# ANIMA — Independent E4-A / E4-B Gold Audit v0

**Status:** INITIAL REVIEW COMPLETED; agreed A/B corrections applied to proposed inputs/gold; **corpus FREEZE remains blocked pending full track review**.  
**Reviewed snapshot:** `eb2193e70ca60aead01cbc2e61e12375d77ae3e9`  
**Date:** 2026-11-12.  
**Scope:** 11 root cases (E4-A01…A05, E4-B01…B06), 26 input Events, 23 gold assertions.  
**Sources:** [input fixture](Fixtures/memory_e4_inputs_v0.json), [proposed gold](Fixtures/memory_e4_gold_v0.json), [corpus protocol](Memory_E4_Conformance_Corpus_v0_Draft.md), [E4 architecture](../ROADMAP/Memory_E4_Architecture_Contract_Draft.md).

> The prior GitHub Actions run `43117914991` passed the **static corpus shape** and regression checks on Python 3.12/3.13/3.14. That is not evidence that these semantic gold labels are correct. This audit reviews the frozen *proposal*, does not feed gold into the encoder, and makes **no edits to the fixtures**.

## Review disposition update (2026-11-12)

The owner agreed to hybrid `episode_scope` and typed Story distinctions. A follow-up corpus edit implements the proposed fixes: A01 gets explicit C17 context; A02 same-case Story abstention; A04 typed source Event reference; A05 case-scoped `not_same_case`; B01/B03/B04 report-scoped case relations; B06 abstention. B02's weak candidate allows `insufficient` as an alternative. The findings below remain as the **historical original audit** and are not claims that new data have been independently accepted or tested.

## 1. Verdict

- **3 BLOCK:** `A02`, `A04`, `B06` — current labels assert more than input provenance supports, or use ambiguous evidence semantics.
- **3 REVIEW:** `A01`, `A05`, `B04` — correct answer depends on a missing or under-specified episode/story definition.
- **5 PROVISIONAL:** `A03`, `B01`, `B02`, `B03`, `B05` — viable expected behavior under explicitly stated scope, subject to tightening.

The critical systematic issue is **an episode, a story of the same case, and a broader topic are not interchangeable**. Likewise a reported connection between events is not independently confirmed physical causality.

## 2. Per-case evidence review

| ID | Current gold | Assessment | Required correction or scope |
| --- | --- | --- | --- |
| **A01** | `e1,e2 → same Episode` | **REVIEW** | 82→91°C, same Pi, four minutes apart and same session support a likely single overheating trajectory. But mere temporal adjacency and entity overlap do not prove it; add a common test/incident marker or permit `candidate` rather than mandatory `same`. Do not treat user's measurement as verified sensor truth. |
| **A02** | `different Episodes`, `independent Stories` | **BLOCK** | Different validated physical Entity IDs are a strong negative gate against *single-device episode merge*. They do **not** prove independent Stories; both devices could be part of one wider outage. Change Story gold to **no established shared-case link / insufficient** absent an explicit incident relationship; maintain distinct Episodes. |
| **A03** | `e1,e3 same Episode`, `e2 separate` | **PROVISIONAL** | Loss and restoration of the same router's connection in one short session is a reasonable bounded incident. Cooling Pi event must not be merged. Optionally add `e2,e3 distinct` and forbid inferred causality across topics. |
| **A04** | `episode_pair insufficient`, `no_duplicate_evidence` | **BLOCK** | Two strings contain `reading_id=m17`, but there is **no explicit typed `derived_from` or authenticated source provenance**. Equality of a free-text reading ID does not alone prove a derived projection, while possible duplication must **not** be treated as independent corroboration. Also `type=conversation.user` with `source=projection.ui` is semantically misleading. Supply explicit origin link and revise evidence gold to `same_origin_not_independent`, or label provenance/independence **unknown** and prohibit automatic double-voting. |
| **A05** | `different Episodes`, `independent Stories` | **REVIEW** | User explicitly reports a **new independent** fault and distinct case numbers 41/52; a strong negative gate for one **case-level** story. But a broader recurring-Pi5-overheating Story could legitimately organize both. Specify `Story.kind=case` rather than claim global independence. |
| **B01** | `e1,e2 distinct Episodes`; consecutive Story links | **PROVISIONAL** | Explicit repeated R18 identifier is a good **reported case** scope across four days. Use source/namespace + scoped ticket identity; do not infer independent external ticket verification or confirmed repair from text. Add episode-separation checks `e2,e3`, `e3,e4`. |
| **B02** | `different Episodes`; `candidate_only Story` | **PROVISIONAL** | A one-week gap plus 'again heated up' does not prove the same incident, but can justify a low-authority candidate for a recurring-problem story. No automatic merge or verified causal relationship. |
| **B03** | `different Episodes`; shared Story via T77 | **PROVISIONAL** | Explicit 'continuing T77' is a stronger referential link than lexical similarity alone. Scope T77 to the reporter/project/ticket namespace and mark the Story as organizational/report-based, not externally verified. |
| **B04** | `different Episodes`; one Story after e3 | **REVIEW** | Two distinct physical items within minutes **can** belong to one bounded outage Episode when grouping is at the incident level; alternatively they can be device-local Episodes in one Story. Proposed gold requires device-local segmentation **without an explicit taxonomy**. Define Episode unit / segmentation rules before hard-labeling `distinct`. Third user statement asserts shared case A9 but not physical causation. |
| **B05** | `insufficient Story`, `uncertainty registered` | **PROVISIONAL** | 'Вчера всё исправили' is referentially ambiguous; new session and missing entity support abstention. Further nuance: receipt is Nov 3, 'yesterday' refers to Nov 2 in that message, while initial adapter report is Nov 1. Relative dates are not verified world-time facts; explicit temporal scope is required. |
| **B06** | `unknown_world_order`; `candidate_only Story` | **BLOCK** | Unknown real-world order is appropriate: differing unsynchronized source clocks cannot be normalized from receipt timestamp. But two separate group reports about the same Pi do **not require** a Story candidate without a common incident/case identifier. Gold should allow **no link/insufficient**, and record a candidate as *optional* if low-cost discovery suggests one; must never claim world-time ordering. |

## 3. Two decisions needed before accepting gold

### D1 — What is an Episode's granularity?

Options:

- **incident-level:** any concurrent multi-device event can be one Episode, even if it covers several entities;
- **entity-local/process-level:** a separate Episode per identifiable local trajectory, then one Story groups the overall outage;
- **hybrid policy with explicit `episode_scope`** (recommended): identify the organizing unit (device/process/interaction/incident) and make the **gold's scope** explicit. Other valid segmentations can be recorded as acceptable, but avoid arbitrary automatic splits or merges.

A04 and B04 demonstrate why a single unconditional `same|distinct` label is underspecified without `episode_scope`.

### D2 — What does Story link mean?

At minimum distinguish:

- `same_case_reported` — attributable report/repeated scoped case ID, **not established physical truth**;
- `potentially_same_case` — candidate, uncertainty preserved;
- `not_same_case` — explicit or otherwise verified separate incidents **at case granularity**;
- `insufficient` — no required link and no conclusive negative;
- `same_topic` — optional broader topical grouping, not necessarily the same case.

Proposed split: **Story identity** (belongs to same *case*) vs **typed Story relation** (recurrence/shared subject/part of larger incident). The present `independent` label is dangerously overloaded; `candidate_only` should not be mandatory just for a shared entity.

## 4. Proposed edits, not yet applied

1. **A02:** retain `episode_pair=distinct`, replace `story_pair=independent` with `insufficient_same_case`; no evidence of an overall incident in the input.
2. **A04:** add explicit machine-readable parent source (validated Event link) or change gold to `source_independence=unknown` with prohibition on counting it as *proven independent* evidence. `reading_id` string is not provenance.
3. **B06:** retain `unknown_world_order`, replace mandatory `candidate_only` Story with `insufficient` or a tolerable optional candidate, with no spurious corroboration.
4. **A01:** strengthen shared test/case identifier if `same` is mandatory; alternatively use acceptable set with `same` and abstain/candidate under uncertain origin.
5. **A05:** require `story_scope=case`; an independent case can still share a topical umbrella.
6. **B04:** explicitly decide whether Episodes are incident-level or device-local; judge Story membership separately.
7. **B01/B03:** use typed namespace-scoped case/ticket ID if available; do not treat raw string as universally unique.
8. **A03/B01:** cover remaining pairwise relations (including negative pairs) to avoid scoring a trivial encoder as passing with incomplete assignments.

## 5. Negative variants to add *after owner adjudication*

- A02: different physical devices but a **verified shared outage**; a real negative test for `different Entity → no Story`.
- A04: genuine UI projection with signed/validated `derived_from_event_id`; identical free-text `reading_id` from an **unrelated** source; duplicate projection replay.
- A05: two distinct fault cases under one `recurring_problem` topic, and two accidental duplicate case numbers in different namespaces.
- B01/B03: identical ticket number from two unrelated systems; untrusted quote of another reporter's ticket ID; late contradictory correction to case membership.
- B04: one cross-device incident Episode vs two device-process Episodes in one Story (scope explicitly declared).
- B06: event receipt order opposite **verified occurrence time** and wholly unknown occurrence time; missing/invalid clock-domain mapping.

## 6. Release and verification boundary

**Freeze A/B: BLOCKED** until D1/D2 and three BLOCK labels are adjudicated. Provisional labels are not `VERIFIED`. Static tests can and should remain green while semantic review identifies problematic gold.

No production Core/Memory, scheduling API, Knowledge policy, or source authority was changed. After decisions are approved, update proposed gold & inputs **together**, freeze deterministic manifest/source hash, run an independent gold validation, then add a separately authored holdout. The algorithm under test never receives gold labels.
