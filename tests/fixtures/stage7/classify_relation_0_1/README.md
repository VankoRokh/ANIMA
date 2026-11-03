# Stage 7 classify_relation/0.1 fixtures

This directory contains canonical conformance fixtures derived from the owner-reviewed
`docs/TESTING/Stage7_Conformance_Corpus_v0.md`.

Layout:

- `block_a/manifest.json` — index of the current fixture slice;
- `block_a/CR-XXX/request.json` — canonical typed profile request;
- `block_a/CR-XXX/expected.json` — expected semantic Assessment;
- `block_a/CR-XXX/metadata.json` — execution path, backend-call expectation,
  semantic preconditions/invariants, and forbidden conclusions.

Rules:

- fixtures are conformance/evaluation gold, not training data;
- `request.json` and `expected.json` must conform to
  `docs/SCHEMAS/classify_relation_0_1.schema.json`;
- metadata is harness/test metadata and is not part of the model-facing semantic renderer;
- deterministic fixtures require `backend_calls_expected = 0`;
- future generated metamorphic/invalid variants must preserve the root semantics documented
  in the accepted conformance corpus.
