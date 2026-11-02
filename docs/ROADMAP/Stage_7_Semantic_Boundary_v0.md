# Stage 7 Semantic Boundary v0

Status: **Accepted semantic boundary for pre-training/read-only Stage 7 work. Stage 7 implementation remains Planned.**

Accepted on 2026-11-03 after owner review of the pre-training Stage 7 design proposal and audit results.

This document is the current canonical semantic boundary for the first Stage 7 interface slice. It supersedes conflicting semantic clauses in the earlier provisional Stage 7 design notes while preserving those documents as design history.

## 1. Scope

This boundary stabilizes the concepts required to build and test a **read-only/shadow semantic interface** before production Knowledge write integration or model training.

Accepted now:

- Claim identity and scope;
- Evidence identity and bounded provenance;
- Source vs Producer;
- typed Value v0;
- qualifiers, polarity and predicate cardinality;
- explicit temporal semantics;
- CONTENT and REVISION as independent facets;
- `classify_relation/0.1` as the first versioned operation profile;
- deterministic-first evaluation;
- conformance-first version freeze;
- evidence replay/dependence semantics needed for read-only evaluation.

Still open:

- DP-08: lifecycle actions, source authority and correction rights;
- DP-09: public Knowledge read semantics vs existing storage statuses;
- DP-10b: full descendant re-evaluation/dependency policy after premise revision;
- DP-11: production routing/integration with Stage 6 dispatcher contracts.

No accepted item in this document grants a model direct persistence, Task/Goal, routing, execution or lifecycle authority.

## 2. Layering

The semantic boundary separates four questions that must not collapse into one enum:

1. **Evidence relation** — how supplied claims/evidence relate in a bounded comparison scope.
2. **Evidence sufficiency** — whether the supplied information is enough for a specific facet.
3. **Knowledge state** — what ANIMA currently accepts, disputes, rejects or treats historically.
4. **Lifecycle decision** — what system-owned state transition, if any, is allowed.

A relation can be known while truth remains unresolved. For example, two single-valued claims can be confidently classified as contradictory without deciding which one is true.

## 3. Claim

A `Claim` is an immutable qualified/time-scoped proposition.

Public semantic identity consists of:

```text
subject
+ predicate
+ typed value
+ polarity
+ meaning-bearing qualifiers/context
+ temporal scope
```

The following do **not** belong to Claim semantic identity:

```text
Source
Evidence occurrence
Producer
confidence
Knowledge status
support count
storage row ID
```

Changing value, polarity, a meaning-bearing qualifier or temporal scope creates a new semantic Claim/revision. Internal storage may factor or intern shared atomic components as long as the public semantics remain identical.

## 4. EntityRef and PredicateRef

### EntityRef

An entity reference is either:

- a system-resolved canonical entity binding with revision/version context; or
- an explicitly unresolved mention tied to source evidence.

Equal names do not prove equal identity. Unresolved does not mean different.

### PredicateRef

A predicate reference identifies a registry-owned meaning/version. The registry defines at least:

- expected Value type;
- cardinality;
- allowed/required qualifiers;
- unit semantics when relevant;
- temporal behavior needed by deterministic comparison;
- comparison mode.

Changing predicate meaning requires an explicit semantic revision; matching strings alone do not prove matching semantics.

## 5. typed Value v0

The first semantic core supports only atomic typed values:

```text
string
symbol
boolean
integer
decimal
quantity
entity
```

Rules:

- integer/decimal semantics are exact; float approximation is not the canonical representation;
- `quantity = exact decimal + registered unit`;
- unit normalization/conversion is deterministic code;
- `symbol` is used for registry/controlled vocabulary values;
- `entity` is an EntityRef-valued atom;
- unknown/missing extraction is not represented by an invented literal;
- `boolean false` and negative polarity are not silently treated as equivalent unless predicate semantics explicitly define an equivalence.

The first comparison mode is `exact` only.

Not in v0 unless enabled by a separate capability/version:

- arbitrary nested objects;
- fuzzy similarity;
- implicit synonymy;
- approximate/distribution values;
- general n-ary logic;
- recursive/model-generated rules.

## 6. Qualifiers, polarity and cardinality

### Qualifiers

Qualifiers are registry-defined typed context that changes proposition meaning. They are not a free metadata dump.

A complete empty qualifier set differs from an unknown/partial qualifier set. Missing qualifier data never means universal context by default.

### Polarity

Polarity is explicit:

```text
positive
negative
```

Unknown is not a polarity.

### Cardinality

Predicate cardinality v0:

```text
single
multi
unknown
```

`single` means at most one positive value in the same effective entity/context/time scope. It does not assert that a value exists.

Consequences:

- multi-valued positive A and positive B may coexist;
- the same atom with opposite polarity conflicts in the same scope;
- single-valued positive A and positive B with `A != B` conflict in the same scope;
- two different negative atoms can be compatible.

## 7. Evidence, Source and Producer

### Evidence

Evidence is an identifiable occurrence/record that grounds a claim or an interpretation act. Evidence is not the Claim itself and is not truth by existence.

Evidence preserves:

- stable occurrence/record identity;
- versioned immutable content/locator identity;
- claim associations;
- evidence form/stance;
- SourceRef or derivation premises;
- ProducerRef for the interpretation/record;
- relevant temporal markers;
- bounded provenance/lineage references.

Two independent sensors may support one semantic Claim with two different Evidence occurrences. Re-reading or redelivering the same immutable occurrence does not create new independent support.

### Source

`Source` is the origin of the information/observation/statement, such as a person, sensor, document, system tool observation or versioned curated bootstrap artifact.

Source authority is system-owned and is **not** a universal ranking such as user > sensor > DEEP > FAST.

### Producer

`Producer` is the component/method that created a particular interpretation or record. A parser/FAST/DEEP that extracts a Claim from a user's message is the Producer; the user/message remains the Source.

Producer identity does not grant source authority.

## 8. Observation, Report, Hypothesis and Derived claim

These are orthogonal evidence/epistemic facets, not alternative world states that replace Claim.

### Observation

A registered observation/measurement from a source adapter. A statement saying "I observed X" is still a Report unless the ingress source is actually registered as the observer/measurement channel.

### Assertion / Report

A source reports a proposition. The existence of the report proves that the statement occurred, not that its content is true.

### Hypothesis

A claim explicitly marked as hypothetical. It may carry basis references or explicitly have none. A hypothesis never silently becomes accepted factual Knowledge.

### Derived claim

A claim produced from premises by a recorded method/rule/model. Provenance must preserve premise refs and method identity. `derived` is not automatically weaker or stronger than `direct`; reliability depends on source, method, proof/verification and lineage.

## 9. Evidence identity and dependence — DP-10a

Accepted for the read-only prototype:

- Evidence has stable occurrence/version identity separate from Claim equality;
- replay/redelivery of one occurrence is not new independent support;
- different EvidenceRefs can remain dependent when they share a provenance root;
- a chain such as source report → summary → LLM extraction may create multiple records but not multiple independent witnesses;
- support accounting must use lineage/dependence, not raw EvidenceRef count;
- derived evidence keeps premise/method provenance;
- no unconditional `DIRECT > DERIVED` rule is allowed.

Full policy for cascading descendant re-evaluation after premise revision remains open DP-10b.

## 10. Time semantics

The following temporal concepts are distinct:

### observed_at

When the source actually observed/measured the referenced event/state, if known.

### asserted_at

When a source made the report/assertion, if known.

### received_at

When ANIMA first received the occurrence. This is system/ingress-owned.

### created_at

When ANIMA created a specific internal record/interpretation. This is system/producer-owned.

None of these automatically defines world validity.

No global invariant such as `observed_at <= asserted_at <= received_at <= created_at` is assumed across independent clocks. Clock domains require explicit mapping/normalization before exact comparison.

### World-valid temporal scope

```text
TemporalScope = UnknownScope | Instant | Interval
```

For an interval:

```text
from  = Known | Unknown | Unbounded
until = Known | Unknown | Unbounded
```

Accepted interval convention:

```text
[valid_from, valid_until)
```

Rules:

- `Unknown` means the boundary is not known;
- `Unknown` never defaults to infinity;
- `Unbounded` requires explicit semantic grounds;
- equal known interval bounds are invalid/empty; a point is represented by `Instant`;
- partial intervals are allowed, but only conclusions logically implied by known bounds may be drawn;
- two point observations at different times do not establish continuous validity between them or an exact transition boundary.

## 11. Relation taxonomy

`classify_relation/0.1` separates `CONTENT` from `REVISION`.

### CONTENT results

#### SUPPORT

Same normalized proposition/polarity in a provably common scope. It does not mean confirmed Knowledge.

#### CONTRADICTION

Claims are incompatible in a common entity/predicate/context/time comparison scope. It does not choose a winner.

#### COMPATIBLE_DISTINCT

Claims are comparable and semantically compatible, but do not support the same proposition. Typical examples include distinct members of a multi-valued predicate.

#### TEMPORAL_SUCCESSION

Claims describe a compatible ordered succession of locally incompatible states where temporal/context/cardinality preconditions are known and the predicate permits change.

`TEMPORAL_SUCCESSION` does **not** mean:

- a proven world-change event;
- truth of both claims;
- continuous history between observations;
- a known exact transition boundary.

The legacy label `TEMPORAL_CHANGE` remains only in historical documents/audits where it described the earlier baseline.

#### NOT_COMPARABLE

Claims are proven outside the common atomic comparison domain, such as different canonical entity, different predicate meaning or disjoint context.

Unresolved identity/context is not `NOT_COMPARABLE`; it is insufficient information.

#### INSUFFICIENT

The operation supports the requested question but required evidence, binding, temporal scope or semantics are missing/unclear.

#### UNSUPPORTED

The requested feature/semantics is known but not implemented by this profile/capability.

Protocol/backend failures are not semantic `INSUFFICIENT` or `UNSUPPORTED` results.

### REVISION results

#### CORRECTION

A bounded source fragment explicitly declares a correction and the correction target is identifiable.

`CORRECTION` means **source-declared correction act**, not:

- proof that the old Claim was false;
- permission to revise Knowledge;
- automatic lifecycle supersession.

A result can simultaneously be:

```text
CONTENT = CONTRADICTION
REVISION = CORRECTION
```

or, for example:

```text
CONTENT = INSUFFICIENT(temporal_scope)
REVISION = CORRECTION
```

Partial outcomes are valid.

## 12. No universal RESOLVED/UNRESOLVED axis

The old audit v0.2 coupling of relation and resolution is not part of the accepted contract.

There is no universal semantic `RESOLVED/UNRESOLVED` result in `classify_relation/0.1`.

Each facet returns its own typed result such as relation, insufficient, unsupported, not-comparable or not-requested. Knowledge state and lifecycle action remain separate system-owned contracts.

## 13. `classify_relation/0.1`

Purpose: classify the bounded relation of **exactly two supplied Claims** using a bounded Evidence slice.

It does not:

- extract new entities/predicates;
- perform unrestricted coreference resolution;
- select the true/winning Claim;
- choose a lifecycle action;
- write Memory/Knowledge;
- assign source authority;
- execute tools/actions.

### Canonical request semantics

The request contains at least:

```text
profile = classify_relation/0.1
requested aspects = CONTENT and/or REVISION
required feature set
predicate definitions needed by the pair
exactly two Claim views
bounded Evidence views
coverage/completeness metadata
system-owned scope comparison facts
```

Resource bounds for the first experimental renderer are profile limits, not ontology:

```text
claims: exactly 2
evidence: 1..8
predicate definitions: 0..2
qualifiers per claim: bounded, initial target <= 8
text fragment: bounded, initial target <= 4096 Unicode characters
```

### Result semantics

```text
Assessment
├── content: ContentResult
└── revision: RevisionResult
```

Each facet can independently return a positive classification, insufficiency, unsupported feature or not-requested where applicable.

Evidence references in results must point only to supplied evidence and mean "grounds considered for this facet", not "system-verified truth".

## 14. Deterministic-first rule

If a result is exactly computable from typed structured data, the LLM must not be invoked.

Examples suitable for deterministic evaluation include:

- exact normalized support in a known common scope;
- single-valued incompatible positive values in the same scope;
- same-atom positive/negative contradiction;
- multi-valued compatible distinct membership;
- proven different entity/predicate/context;
- interval order/overlap where clocks and bounds are already normalized;
- structured registered correction declarations;
- capability/preflight failures.

A partial deterministic result is preserved. A model may only process the unresolved requested facet and may not overwrite a system-computed facet.

## 15. Model-facing boundary

The model may be given only the bounded semantic information required by the operation. It must not receive authority-bearing implementation details merely as answer hints.

Do not expose as semantic vocabulary unless specifically required by another profile:

- storage row IDs / SQL layout;
- persistence commands;
- accepted/challenged Knowledge status as model-owned output;
- routing thresholds;
- model size/quantization/sampling settings;
- credentials/paths;
- unrestricted provenance graph;
- system priority/authority ranking;
- Task/Goal/execution mutation commands.

The model may propose an interpretation; the system validates structure, references, type compatibility, scope, capability and authority boundaries.

## 16. Versioning and freeze policy — DP-12

The following are versioned independently:

- semantic schema/meaning;
- operation profile;
- predicate registry revisions;
- projection renderer;
- constrained decoder grammar/schema;
- model adapter/LoRA.

`classify_relation/0.1` is frozen only after owner-reviewed conformance fixtures validate the semantics and deterministic baseline.

Any incompatible semantic change requires a new profile version such as `0.2`; historical benchmark results keep their original contract.

No floating `latest` semantic profile is used in reproducible tests.

## 17. Conformance before model training

Before implementation is considered ready for model evaluation:

- review at least 30 semantic root fixtures; target 40–50 for the first corpus;
- include SUPPORT, CONTRADICTION, COMPATIBLE_DISTINCT, TEMPORAL_SUCCESSION, CORRECTION, insufficiency, not-comparable, unsupported, unknown/unbounded, replay/dependent evidence, partial coverage and protocol failures;
- include metamorphic transformations such as field/evidence order and alias renaming;
- include meaning-changing transformations for cardinality, polarity, validity, correction target and fragment completeness;
- all deterministic-decidable cases must pass with model backend call count = 0;
- source text injection must remain data and must not grant authority;
- semantic accuracy, abstention/error and evidence attribution are measured separately from JSON/shape validity.

No arbitrary model-accuracy threshold is accepted before the real semantic residual is measured.

Training sequence:

```text
accepted semantic boundary
→ reviewed conformance corpus
→ deterministic baseline
→ constrained renderer / vanilla model evaluation
→ measure real semantic residual
→ only then decide whether LoRA/SFT is justified
```

The current audit corpus is regression/history, not the untouched future training/evaluation set.

## 18. Open decisions after this boundary

### DP-08 — lifecycle actions / authority

Open. A relation/correction must never directly perform Knowledge mutation. Exact action mapping and source correction rights require separate owner review.

### DP-09 — Knowledge read semantics

Open. Existing production statuses must not be replaced by documentation-only enums. Retrieval projection for accepted/pending/rejected, temporal applicability and disputes/revisions needs a separate contract.

### DP-10b — dependency re-evaluation

Open. The read-only boundary fixes Evidence identity/dependence, but not the full algorithm for cascading or selective re-evaluation when a premise is revised.

### DP-11 — Stage 6 integration

Open. The first implementation should be an isolated read-only/shadow capability. Production dispatcher/routing integration requires a separate decision and must not bypass current Stage 6 proposal/candidate guards.

## 19. Relationship to earlier Stage 7 documents

The following files remain useful design history and scoped concepts:

- `Semantic_Candidate_v0.md`;
- `Semantic_Temporal_Conflict_v0.md`;
- `Knowledge_Lifecycle_v0.md`;
- `Semantic_Verification_v0.md`;
- `Bootstrap_Knowledge_v0.md`;
- `Dynamic_Task_Arbitration_Concept.md`;
- `Emergency_Response_Mode_Concept.md`.

Where they conflict with this accepted boundary, **this document wins for the pre-training/read-only Stage 7 interface slice**.

Historical TV reports, Stage 5/6 specs and old audit labels are not rewritten retroactively.

## 20. Implementation boundary

This document authorizes documentation and conformance work only. It does not claim that the new semantic interface is implemented or production-proven.

The first implementation slice should remain read-only/shadow until a later owner decision explicitly accepts DP-08/09/10b/11 integration semantics.
