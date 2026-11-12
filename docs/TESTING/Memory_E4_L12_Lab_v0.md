# ANIMA — E4 L1.2 Scoped Association Laboratory v0

**Status:** EXPERIMENTAL / OPT-IN; **NOT** a production Memory implementation or E4 conformance.  
**Design:** [L1.2 scoped contract](Memory_E4_L12_Contract_v0.md).  
**Baseline:** [L1.1 evaluation results](Memory_E4_L11_Evaluation_Results_v0.md) and [new challenge failures](Memory_E4_L11_Challenge_Results_v0.md).  
**Lab:** [L1.2 association module](../../labs/exp009/e4_l12_association.py).  
**Independent post-hoc evaluators:** [57-case frozen evaluation](../../labs/exp009/e4_l12_evaluator.py), [15-case visible challenge](../../labs/exp009/e4_l12_challenge_evaluator.py).  
**Source-only challenge adapter:** [pinned-input runner](../../labs/exp009/e4_l12_challenge_runner.py).  
**Tests:** [L1.2 adversarial checks](../../tests/test_memory_e4_l12.py).

## What changed from L1.1

- Distinguishes **typed reported identifiers**, e.g. `ticket T77` != `case T77`. A user report of an incident is not a verified external fact.
- Preserves **competing scoped alias definitions** instead of silently choosing the last target. A current grounded Entity reference can select one; otherwise it abstains and exposes candidate Event IDs.
- Stores `CorrectionTarget` with target projection, prior revision, exact Event ID set, later correction Event, binding method, reason and `production_admission=false`. An irrelevant later statement cannot modify the derived view merely because it shares a device and a few correction words.
- Extends bounded two-word Russian adjective/noun normalization to **one-to-three adjective** forms while preserving raw strings and source evidence. It does not infer global synonyms.
- Keeps original L0 Shadow decisions and existing L1.1 available as separate references; unchanged frozen E4 v0 and 15-case open challenge are scored after sealed raw traces.

## Run

```bash
mkdir -p e4-l12-results
python -m labs.exp009.e4_l12_association --suite positive --output e4-l12-results/positive_raw.json
python -m labs.exp009.e4_l12_evaluator --suite positive \
  --trace e4-l12-results/positive_raw.json --output e4-l12-results/positive_eval.json --print-summary

python -m labs.exp009.e4_l12_challenge_runner --output e4-l12-results/challenge_raw.json
python -m labs.exp009.e4_l12_challenge_evaluator \
  --trace e4-l12-results/challenge_raw.json \
  --output e4-l12-results/challenge_eval.json --print-summary
```

**Evaluation interpretation:** L1.2 is not allowed to publish Memory, Knowledge or any external effects. Its bound `CorrectionTarget` may support a temporary research view, but deictic reference is a heuristic, not independently authenticated Event targeting. A green CI means deterministic laboratory checks and integrity gates; visible developer-authored gold cannot certify broad generalization. The remaining 99 forbidden E4 obligations are outside this evaluation.
