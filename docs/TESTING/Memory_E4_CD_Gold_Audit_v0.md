# ANIMA — E4-C/D Independent Gold Audit v0

**Status:** initial independent audit retained; **audit corrections now applied to proposed C/D fixtures**, not frozen and not yet E4 runtime-verified.  
**Reviewed base:** `eb2193e70ca60aead01cbc2e61e12375d77ae3e9` (existing C/D cases unchanged by A/B corrections).  
**Scope:** 11 root cases: six C and five D.  
**Reference:** [E4 corpus](Memory_E4_Conformance_Corpus_v0_Draft.md), [Architecture](../ROADMAP/Memory_E4_Architecture_Contract_Draft.md), [Stage 7 boundary](../ROADMAP/Stage_7_Semantic_Boundary_v0.md).

## Correction disposition (2026-11-12)

Revisions: C01 no forced distinct Episodes; C03 source-backed alias reuse; C04 scoped negative alias; C05 explicit affected/unaffected dependent links; C06 distinct physical supply IDs; D01 versioned pre-correction projection; D02/D03 typed sensor payload/replay; D04 unsynchronized sensor clock; D05 stale derived snapshot publication. No raw source mutation or Knowledge admission.

**Below is the historical original audit**, preserved for traceability. Labels `BLOCK/REVIEW` refer to the *prior fixture revision*; they are not a claim that the revised fixtures have passed independent semantic acceptance.

## Findings

| Case | Verdict | Analysis / proposed correction |
| --- | --- | --- |
| **C01** | **BLOCK** | E1/E2/E3 occur within five minutes and same session; required `story_pair=linked_distinct_episodes` presupposes an **unproven Episode split**. Keep scope-specific alias confirmation; require only same reported referent/case, or explicitly add episode boundary before demanding linked distinct episodes. |
| **C02** | **REVIEW** | User reports an unspecified broken adapter. The named entity may remain unresolved; registering an informational question is sensible, but only Core can decide whether it is significant enough to open Goal. No global alias. |
| **C03** | **BLOCK** | Setup pre-installs verified `PSU → psu` with `source_ref=fixture_precondition` rather than a real provenance-backed record. Replace with a prior source Event and constrained alias registry version, or explicitly state this is trusted initialized fixture state. Measure **repeat inference cost** and zero additional DEEP calls. |
| **C04** | **PROVISIONAL** | Two adapter types with distinct Entity IDs correctly discourage a same-device Episode merge. Limit `rejected` to this contextual pairing, not the general word. |
| **C05** | **BLOCK** | `revision=recheck_dependent_links` presupposes dependent Episode/Story links, absent from `setup`. Add versioned prior derived links and their dependency IDs, verify only affected links are invalidated; raw unaffected. |
| **C06** | **REVIEW** | Event references designate a *notebook and Pi*, not their power supplies. If the oracle requires distinct PSU identities, provide typed refs for the **two physical supplies**. Shared abbreviation is not physical identity. |
| **D01** | **PROVISIONAL** | Separate explicit tests A/B and corrective user message can justify resegmentation in an organizational projection, not physical verification. Add source-hash/version/dependency checks and ensure rollback does not erase raw evidence. |
| **D02** | **PROVISIONAL** | Same Event ID replay should produce one effect; consider using `type=device.temperature` for sensor source and checking identical payload hashes. |
| **D03** | **PROVISIONAL** | Conflicting payload under same Event ID must be rejected, leaving canonical record intact; ensure the attempted conflicting value is also auditable, not silently adopted. |
| **D04** | **BLOCK** | `source=sensor.pi5` but `type=conversation.user`, and sensor message itself claims unsynchronized recording. Clarify actual producer, received-at vs observed-at, and clock mapping; keep `unknown_world_order` absent trusted clock proof. |
| **D05** | **BLOCK** | `source_current_version` is ambiguous: raw Events are immutable. Express versioning of a **derived projection or source snapshot**, include source IDs/hashes and publish preconditions, then test stale publication is rejected. |

## Required corrections for C/D before freeze

1. Reconcile `Story` vs `Episode` in C01; do **not** turn identification of a user nickname into mandatory episode splitting.
2. Make alias/Entity identity **scope-and-provenance-aware** in C03/C04/C06; no global alias from one utterance.
3. Provide explicit versioned dependent links for C05; ensure correction triggers bounded re-evaluation, not rewrite.
4. Represent valid sensor/projection provenance and separate received time from claimed observation time for D04.
5. Version derived snapshots and detect stale publication without claiming raw event mutation for D05.
6. Add negative counterexamples: two real power supplies both called PSU, unsupported corrective report, version changes without actual source change, stale snapshot after restart.

## Gate

**E4-C/D freeze: BLOCKED** on four concrete missing-input/over-strong-gold cases (C01, C03, C05, D04, D05) plus review qualifications. The algorithm must not see gold. Static `pytest` PASS cannot close semantic gaps. No production changes authorized.
