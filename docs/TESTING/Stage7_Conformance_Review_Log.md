# Stage 7 Conformance Corpus — Owner Review Log

Status: **Active review log.** This file records owner decisions for the draft root corpus before it is frozen as conformance gold.

Corpus: [Stage7_Conformance_Corpus_v0_Draft.md](Stage7_Conformance_Corpus_v0_Draft.md)

## Review status

| Block | Cases | Status | Decision date |
|---|---:|---|---|
| A — Atomic CONTENT relations | CR-001…CR-016 | **Accepted** | 2026-11-03 |
| B — Temporal CONTENT relations | CR-017…CR-026 | **Accepted with clarifications** | 2026-11-03 |
| C — REVISION / correction | CR-027…CR-034 | **Accepted with clarifications** | 2026-11-03 |
| D — Evidence identity / replay / dependence | CR-035…CR-040 | Pending review | — |
| E — Comparability / sufficiency / capability | CR-041…CR-045 | Pending review | — |
| F — Protocol / boundary / security | CR-046…CR-050 | Pending review | — |

Current progress: **34 / 50 root cases accepted.**

## Accepted Block A invariants

The owner accepted CR-001…CR-016 without semantic changes. In particular:

- exact same proposition in a provably common scope classifies as `SUPPORT`;
- incompatible values/polarity for a single-valued proposition in the same effective scope classify as `CONTRADICTION` without selecting a truth winner;
- compatible distinct values remain `COMPATIBLE_DISTINCT` where cardinality/polarity permits coexistence;
- different canonical entities are `NOT_COMPARABLE(DIFFERENT_ENTITY)` even when value text matches;
- partial wider evidence coverage does not prevent a local pair relation when the grounds required for that pair are present;
- `boolean false` is not silently rewritten as negative proposition polarity;
- source/model confidence, prestige and receipt/creation order do not determine semantic truth.

No accepted Block A case grants Knowledge status, source authority or lifecycle action.

## Accepted Block B invariants

The owner accepted CR-017…CR-026 with two clarifications that are normative for fixture expansion:

- **CR-018:** the quantity predicate is explicitly **single-valued** in addition to being changeable and exactly normalized; different values at ordered instants may then classify as `TEMPORAL_SUCCESSION`.
- **CR-020:** partially known intervals inherit the relevant CR-019 preconditions: same comparison domain, incompatible local states, `single` cardinality and `changeable` temporal behavior. `TEMPORAL_SUCCESSION` is allowed only when the known bounds themselves prove order and disjointness.

Additional accepted temporal invariants:

- `TEMPORAL_SUCCESSION` describes compatible ordered succession of claims, not a proven world-change event, continuous trajectory or exact transition boundary;
- identical state at different disjoint instants is `COMPATIBLE_DISTINCT`, not `SUPPORT`, because temporal scope is part of Claim identity;
- multi-valued compatible claims do not become temporal succession merely because their times differ;
- provably overlapping incompatible single-valued claims are `CONTRADICTION`;
- `Unknown` temporal bounds never become `Unbounded` by default;
- unknown temporal behavior yields `INSUFFICIENT(temporal_behavior)` rather than an assumed changeable predicate;
- richer cross-time inference for registry-declared invariant predicates remains `UNSUPPORTED` in profile `0.1` until a dedicated capability is accepted.

No accepted Block B case infers truth, lifecycle revision or source authority from temporal ordering alone.

## Accepted Block C invariants

The owner accepted CR-027…CR-034 with the following clarifications, normative for fixture expansion:

- **CR-030:** the primary root is deterministic. All relevant supplied structured evidence records explicitly carry `declaration_status=absent`, coverage is `complete_for_declared_scope`, and the result is `REVISION=no_declaration_in_scope` with backend calls = 0. A separate mandatory natural-language variant (`CR-030-M`) may exercise model residual on a complete text fragment that contains no correction declaration.
- **CR-032:** the primary root isolates **correction intent** ambiguity while source attribution is known, so the exact expected result is `REVISION=INSUFFICIENT(correction_intent)`. A separate variant isolates ambiguous source attribution and expects `INSUFFICIENT(source_attribution)`.
- **CR-033:** `UNSUPPORTED` applies specifically when the requested revision question requires interpreting a **reported third-party correction act** (for example Alice reports that Bob corrected A to B). Such evidence must not be reclassified as Alice's own direct `CORRECTION`. This does not mean the report is unsupported for every other possible operation/profile.

Additional accepted revision invariants:

- structured correction declaration and content contradiction may coexist as independent facet results;
- explicit correction can remain known when CONTENT is insufficient, demonstrating that facets do not share one universal resolved/unresolved state;
- truncated evidence cannot justify `no_declaration_in_scope`;
- correction-like language with unresolved intent/attribution must abstain with the precise gap rather than manufacture a declaration;
- retraction without replacement is outside correction v0 and requires an explicit future capability rather than an invented replacement Claim;
- `CORRECTION` never itself selects truth, grants source authority or performs Knowledge supersession.

No accepted Block C case authorizes lifecycle mutation from the relation assessment alone.
