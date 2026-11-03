# Stage 7 classify_relation/0.1 fixtures

This directory contains canonical conformance fixtures derived from the owner-reviewed
`docs/TESTING/Stage7_Conformance_Corpus_v0.md`.

Layout:

- `block_*/manifest.json` — index of one accepted fixture slice;
- `block_*/CR-XXX/request.json` — canonical typed request, except protocol/parse roots may
  intentionally contain rejected raw JSON text;
- `block_*/CR-XXX/expected.json` — expected semantic Assessment **or**, for protocol roots,
  a harness-level process outcome;
- `block_*/CR-XXX/metadata.json` — execution path, backend-call expectation, expected layer,
  semantic preconditions/invariants, and forbidden conclusions.

Rules:

- fixtures are conformance/evaluation gold, not training data;
- valid semantic `request.json` / Assessment `expected.json` files must conform to
  `docs/SCHEMAS/classify_relation_0_1.schema.json`;
- protocol-invalid roots intentionally demonstrate cases that must be rejected before semantic
  acceptance and therefore are not expected to conform to the renderer schema;
- metadata and process-outcome expectations are harness/test data and are not part of the
  model-facing semantic renderer;
- deterministic and preflight fixtures require `backend_calls_expected = 0`;
- model-residual roots may declare a bounded nonzero backend-call expectation, while already
  deterministic facets remain frozen;
- future generated metamorphic/invalid variants must preserve the root semantics documented
  in the accepted conformance corpus.
