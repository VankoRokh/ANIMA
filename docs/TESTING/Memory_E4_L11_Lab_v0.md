# ANIMA — E4 L1.1 Conservative Revision Lab v0

**Status:** experimental, opt-in, no production Memory writes; not E4 conformance.  
**Motivation:** [Four measured L1 problems and counterexamples](Memory_E4_L11_Failure_Research_v0.md).  
**Code:** [L1.1 association lab](../../labs/exp009/e4_l11_association.py), [independent L1.1 evaluator](../../labs/exp009/e4_l11_evaluator.py), [differential comparison](../../labs/exp009/e4_l11_compare.py).

## Boundaries

- **Derived Episode revision:** only a source-user explicit later correction of two distinguishable named trials that were already merged and backed by a valid previous projection creates a *temporary revised derived view*. Original L0 Episode assignments remain unchanged in the trace. No durable memory migration and no physical-world truth claim.
- **Aliases:** store raw surface and bounded grammatical canonical form. A speaker's explicit source Event determines identity **in scope**, not a universal synonym. No LLM and no model authority.
- **Story:** same reported incident reference within source/namespace is a provisional organizational link; trusted distinct ticket namespaces permit a scoped negative relation. Unknown/untrusted sources do not silently become authoritative.
- **Evaluator:** separate process reads **closed raw trace** and frozen, unchanged JSON. Checks reported revision's source Event IDs, prior projection revision and later correction, but cannot prove physical truth. L1 unchanged and measured on same commit.
- **Negative counterexamples:** same trial repeated; untrusted separation report; no versioned prior; different words without shared case ID; untrusted repeated ticket ID; ambiguous project namespace without trusted disjoint registry; forged revision or alias canonicalization.

## Run

```bash
mkdir -p e4-l11-results
python -m labs.exp009.e4_l0_observation --level L1.1 --suite positive --output e4-l11-results/positive_raw.json
python -m labs.exp009.e4_l11_evaluator --suite positive --trace e4-l11-results/positive_raw.json --output e4-l11-results/positive_evaluation.json --print-summary
```

For head-to-head comparison, also run legacy L1 and independent evaluator from [E4 Evaluator v0](Memory_E4_Independent_Evaluator_v0.md) and then `python -m labs.exp009.e4_l11_compare --old OLD.json --new NEW.json --output DIFF.json`.

**Scoring interpretation:** a PASS for a derived Episode view is a **lab-only proxy**; it does not satisfy durable E4 revision, crash-safe SLEEP, or Goal/Task execution. 99 forbidden obligations are NOT_SUPPORTED absent independent effects instrumentation. The negative suite is visible development data; no blind holdout.
