# Stage 7 Conformance Corpus — Owner Review Log

Status: **Complete.** Owner review finished on 2026-11-03.

Accepted corpus: [Stage7_Conformance_Corpus_v0.md](Stage7_Conformance_Corpus_v0.md)  
Historical draft: [Stage7_Conformance_Corpus_v0_Draft.md](Stage7_Conformance_Corpus_v0_Draft.md)

The accepted corpus is now normative. This log preserves the clarifications made during owner review and explains the delta from the draft.

## Review status

| Block | Cases | Status | Decision date |
|---|---:|---|---|
| A — Atomic CONTENT relations | CR-001…CR-016 | **Accepted** | 2026-11-03 |
| B — Temporal CONTENT relations | CR-017…CR-026 | **Accepted with clarifications** | 2026-11-03 |
| C — REVISION / correction | CR-027…CR-034 | **Accepted with clarifications** | 2026-11-03 |
| D — Evidence identity / replay / dependence | CR-035…CR-040 | **Accepted with clarification** | 2026-11-03 |
| E — Comparability / sufficiency / capability | CR-041…CR-045 | **Accepted with clarification** | 2026-11-03 |
| F — Protocol / boundary / security | CR-046…CR-050 | **Accepted with clarifications** | 2026-11-03 |

Final progress: **50 / 50 root cases accepted.**

## Block A — accepted invariants

- exact same proposition in a provably common scope → `SUPPORT`;
- incompatible values/polarity for a single-valued proposition in the same effective scope → `CONTRADICTION` without selecting truth;
- compatible distinct values remain `COMPATIBLE_DISTINCT` where cardinality/polarity permits coexistence;
- different canonical entities → `NOT_COMPARABLE(DIFFERENT_ENTITY)` even when value text matches;
- partial wider evidence coverage does not prevent a local pair relation when required grounds are present;
- boolean `false` is not negative proposition polarity;
- confidence, prestige and receipt/creation order do not determine semantic truth.

## Block B — accepted clarifications

- **CR-018:** exact quantity predicate is explicitly `single` as well as `changeable`.
- **CR-020:** partially known intervals retain the CR-019 preconditions: same domain, incompatible local states, `single` cardinality and `changeable` temporal behavior; known bounds themselves must prove order and disjointness.
- `TEMPORAL_SUCCESSION` is ordered succession, not a proven world-change event, continuous trajectory or exact transition boundary.
- identical state at different disjoint instants is `COMPATIBLE_DISTINCT`, not `SUPPORT`.
- `Unknown` temporal bounds never default to `Unbounded`.
- invariant cross-time contradiction reasoning remains outside profile 0.1 unless a dedicated capability is added.

## Block C — accepted clarifications

- **CR-030:** primary root is deterministic structured `declaration_status=absent` with `complete_for_declared_scope`; natural-language no-declaration is a separate required model-residual variant `CR-030-M`.
- **CR-032:** primary root isolates `INSUFFICIENT(correction_intent)` with known source attribution; ambiguous attribution is a separate variant expecting `INSUFFICIENT(source_attribution)`.
- **CR-033:** `UNSUPPORTED` applies to interpreting a reported third-party correction act in this revision profile; the report must not be recast as the reporter's direct `CORRECTION`.
- `CORRECTION` never itself selects truth, grants authority or performs Knowledge supersession.

## Block D — accepted clarification

- **CR-039:** primary root is exact: semantically equivalent derived and supplied/direct Claims → `CONTENT=SUPPORT`; provenance/dependency remains separate from content relation, and `form=derivation` alone never determines evidence strength.
- replay/aliases do not create independent support;
- shared provenance roots remain dependent;
- independent occurrences remain distinguishable even with identical content/hash;
- direct vs derived form never selects truth by itself.

## Block E — accepted clarification

- **CR-045:** partial context overlap uses explicit unsupported feature `content.partial_context_overlap/1`.
- unresolved identity → `INSUFFICIENT(entity_binding)`, not same/different by mention text;
- unknown cardinality → `INSUFFICIENT(cardinality)`;
- `INSUFFICIENT` means missing prerequisite/information, while `UNSUPPORTED` means the needed semantics are known but outside profile capability.

## Block F — accepted clarifications

- **CR-049:** invalid refs are split by processing stage. Invalid refs in the input Request fail before model dispatch; invalid refs produced by a model fail proposal validation and never reach semantic/lifecycle acceptance.
- **CR-050:** deterministic injection root is retained, and a required model-residual variant **CR-050-M** sends adversarial source text to the LLM while preserving the typed output boundary. Source text cannot grant producer/authority/verification/write/tool/lifecycle rights; extra authority fields are invalid proposals.
- unsupported profile/version is a process/preflight error, not a semantic top-level `UnsupportedRequest`;
- duplicate JSON keys fail before object construction;
- unknown semantic fields in frozen closed records are rejected rather than silently ignored.

## Freeze outcome

The 50 accepted roots and mandatory variants are frozen in [Stage7_Conformance_Corpus_v0.md](Stage7_Conformance_Corpus_v0.md) for `classify_relation/0.1`. They are conformance gold, not training data. Any incompatible semantic change requires a new profile version.
