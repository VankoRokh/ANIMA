# ANIMA — E4 L1.2 Scoped Identity and CorrectionTarget Contract v0

**Status:** RESEARCH DESIGN / NOT APPROVED FOR PRODUCTION.  
**Basis:** [Pre-L2 independent-minded architecture review](Memory_E4_PreL2_Architecture_Review_v0.md) and [15-case challenge results](Memory_E4_L11_Challenge_Results_v0.md).  
**Frozen inputs:** E4 v0 (57 cases, 122 checks), open development challenge (15 cases, 16 checks); neither may be relabeled to improve a score.

## Separations of authority

1. A raw Event is evidence that a source *said* something; it does not independently prove its real-world truth.
2. A typed identifier is `(source, namespace, kind, token)`. `ticket T77` and `case T77` are **not identical** without a typed bridge. A string collision must return `insufficient`. Known distinct **trusted** ticket namespaces justify `not_same_case_reported`, not a universal truth claim. An unverified relay cannot assert user-scoped continuity.
3. A user definition of an alias carries `(surface, entity_id, source_event_id, session_id, anchors)`. More than one competing referent in the same scope is a real conflict; an unanchored mention must abstain. A later definition is not a global overwrite. A uniquely anchored reference may select a candidate without deleting the others. Raw label and grammatical form are retained.
4. A derived Episode revision requires an auditable `CorrectionTarget`: target projection/version, exact prior Event IDs, correction Event ID, linkage method, source authority, scope and negative evidence. If the target comes only from deictic discourse («это были»), classify it `bounded_deictic_lab_only`. It can support a *temporary* research view when unique and uncontradicted, but may not authorize a production revision.
5. Source Event and L0 Shadow baseline are **immutable**. L1.2 is opt-in and records old L1.1 outcomes for comparison; the SQLite revision-journal experiment is not automatically connected to L1.2, so false semantic bindings cannot silently become durable.

## Typed Story rule

Recognize the limited explicit lexicon `тикет/ticket` → `ticket`; `случай/case` → `case`; `авария/инцидент/событие` → `incident`. Parse the marker from **source text**, not from gold. Comparisons require matching kind and source-scoped namespace; cross-kind same-token returns `insufficient`. Preserve independently source-backed joint-incident reports when neither earlier Event supplies a marker. Any extension of this lexicon needs its own negative probes.

## Alias policy

Collect source-backed definitions before resolving later mentions, while respecting original temporal order. For each mention, compare **all eligible definitions**; do not choose the last. A current explicit Entity anchor can filter candidates. If there are zero candidates → `insufficient`; multiple *distinct target entities* with no unique anchor → `insufficient` with an explicit ambiguity reason; exactly one admissible target → `scoped_alias_reuse` with provenance and zero LLM/DEEP calls. Definitions are never automatically interpreted as reuse statements.

Normalization uses a bounded candidate grammar (feminine instrumental adjective(s) + noun), preserving original surface forms. It is not a universal Russian morphological parser. Source and authority must remain attached to each cached candidate.

## CorrectionTarget policy

Accept only a prior projection of exact original IDs and version with L0 proof the pair was merged; later correction from the source user in the same session; distinctive prior trial labels; sufficient disjointness to bind *that* pair; and an actual corrective statement. Two qualified binding modes are permitted **only in the lab**:
- `explicit_trial_labels_lab_only`: correction names both unique trial labels.
- `bounded_deictic_lab_only`: correction refers deictically («это были»), prior view has exactly two unambiguous local antecedents, and no other plausible same-context targets intervene. This is weaker than an explicit Event pointer and must remain unapproved for durable publication.

A mere shared Entity/session/temporal window and phrases such as «коллега проводил два испытания» are not qualified bindings. When the criteria fail, preserve original L0 assignments and emit a rejected/ambiguous `CorrectionTarget` record with source Event. No default replacement of the persisted projection head.

## Evaluation and gates

- New level **L1.2** available independently of unchanged L0/L1/L1.1; legacy original episodes remain readable.
- Same sealed **57 frozen cases + 15 predeclared challenges**, with *separate* denominators and per-case statuses. No change to either pinned input or gold, and no training/overfitting claim.
- Independent post-hoc L1.2 evaluator is allowed to open gold **only after** verifying the raw trace; reject unbacked aliases, forged event links, false kind/namespace/source authority and unsupported production publication claims.
- Add new non-frozen adversarial tests for mixed identifier kinds, repeated untrusted relay IDs, ambiguous and anchored aliases, unrelated third-party correction, forged target refs and normalization collisions.
- No production migration, Core Goal/Task admission, SLEEP publication, extra hardware actions, L2 autonomy or global Knowledge promotion. The 99 existing forbidden obligations remain `NOT_SUPPORTED` without an independent Core effect ledger.

**Expected interpretation:** reducing errors on known cases is a useful engineering check, but **not independent generalization** and not E4 production acceptance. A genuine unseen external holdout, real source binding and crash/authority tests remain future gates.
