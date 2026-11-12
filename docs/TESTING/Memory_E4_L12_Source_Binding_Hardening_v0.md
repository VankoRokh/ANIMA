# ANIMA — E4 L1.2 Source-Binding Hardening Study

**Status:** PRE-IMPLEMENTATION EXPERIMENT PLAN; not production permission, not a blind holdout.  
**Baseline:** L1.2, `cb8574ecc728df7cd0940d54f611b6fb7d93aa96`; frozen E4 v0 unchanged (57 cases/122 checks), pinned visible challenge unchanged (15 cases/16 checks).

## Two demonstrated or plausible failure classes

**B1 — implicit alias across sessions.** Current L1.2 accepts a previous speaker-intent definition if a later message shares an *anchor* Entity (e.g., Pi5), even when the later message never identifies the referred-to PSU. That ambient shared context proves neither the referent nor persistence of the alias. We must keep provenance as a candidate, but do not select its target across sessions without the target Entity explicitly present in the later source Event.

**B2 — CorrectionTarget source binding.** Current deictic or trial-label proposals can remain useful in a lab-only derived view but do not prove exact origin links. For an explicit proof candidate, require all of: validated raw Event IDs; a prior versioned projection that already groups exactly two earlier Events; correction Event with **two exact typed `kind:event` references** to those sources; no additional/duplicate event refs; strict ordering; same reporting source (user) and session for this bounded laboratory contract; and complete source SHA-256 fingerprints. Even then the verdict is `source_pointer_candidate` and **`production_admission=false`**, since a user can point at a source without making a true claim.

## Predeclared adversarial probes

| Case | Expected safe behavior |
| --- | --- |
| Same label, older session with **shared Pi5 contextual anchor only** | Keep candidate Event ID(s) but **abstain** from target choice |
| Same label, older session, later user Event references **the target Entity itself** | Permit *scoped speaker-intent reuse*; never world-truth confirmation |
| Same label, conflicting definitions or different speaker | No automatic choice |
| Correction with **both exact earlier Event refs** and matching prior projection version | Return source-pointer candidate receipt, no Memory revision/publication |
| Correction missing one ref, duplicates, forged/foreign ref, extra ref, wrong order, wrong version, newer altered source Event, relay source | No source-pointer candidate |
| Source text contradicts target or typed refs are present but not authenticated by Core | No claim of semantic or external truth |
| Reordering/colliding event IDs, or replay with altered raw bytes | Reject or abstain, no silent upgrade |

## Evaluation limits

The target-proof module must not import any gold, Core authority policy or MemoryStore writer. Every receipt identifies exact raw Event IDs and source fingerprints, prior projection version and includes `core_authority_verified=false`, `production_admission=false`, and `memory_store_unchanged=true`. An independent test rehashes the source records and rejects forged claims. The module is **not** connected to L1.2 revision materialization or the SQLite journal.

Run negative tests on separate synthetic copies of *existing* E4 events. Retain frozen original and 15-case challenge byte-identical, and re-run both independent evaluators to detect regressions. Code/fixture authored by same research team: **not independent generalization**.
